# MCP → Tableau 连接自动桥接 技术规格书

> 版本：v1.0 | 状态：已实现 | 日期：2026-04-24 | 关联 PRD：无（内部基础设施）

---

## 1. 概述

### 1.1 目的

解决 `mcp_servers`（MCP 统一配置管理）与 `tableau_connections`（Tableau 资产同步）两套数据源之间的断裂问题。用户在「系统设置 → MCP 配置」页面添加 Tableau MCP 后，「Tableau 资产浏览」页面应自动获取资产数据，无需手动在两处重复配置连接信息。

### 1.2 范围

| 包含 | 不包含 |
|------|--------|
| `mcp_servers` → `tableau_connections` 的单向自动桥接 | `tableau_connections` → `mcp_servers` 反向同步 |
| 新增连接的自动创建（按 `name` 去重） | 已有连接的自动更新（凭据变更后需手动处理） |
| PAT 凭据加密后写入 `token_encrypted` | MCP 配置页面 UI 变更 |
| 桥接后自动启用资产同步（`auto_sync_enabled=True`） | 桥接状态的前端可视化 |

### 1.3 关联文档

| 文档 | 路径 | 关系 |
|------|------|------|
| MCP 统一配置管理 | docs/specs/spec-mcp-configs.md | 上游：定义 `mcp_servers` 表结构 |
| Tableau MCP V1 | docs/specs/07-tableau-mcp-v1-spec.md | 依赖：定义 `tableau_connections` 表结构和同步机制 |
| 数据模型总览 | docs/specs/03-data-model-overview.md | 参考：表命名和 ER 关系 |

---

## 2. 背景

### 2.1 问题描述

平台存在两套独立的 Tableau 连接配置路径：

```
路径 A（MCP 配置管理）：
  用户在「系统设置 → MCP 配置」页面添加 Tableau Server
  → 写入 mcp_servers 表（type='tableau'）
  → 用于 MCP 直连查询（Agent 对话、NLQ 等）

路径 B（Tableau 资产同步）：
  scheduled_sync_all Beat 任务（每 60 秒）
  → 读取 tableau_connections 表中 auto_sync_enabled=True 的记录
  → 调用 Tableau REST API 拉取资产
  → 写入 tableau_assets 表
  → 前端「Tableau 资产浏览」页面展示
```

两条路径没有交叉点。用户通过路径 A 配置了 Tableau MCP 后，路径 B 的 `tableau_connections` 表仍为空，导致资产同步任务无连接可用，**「Tableau 资产浏览」页面始终显示为空**。

### 2.2 解决思路

在 `scheduled_sync_all` 任务起始处插入一个桥接步骤：每次调度时先扫描 `mcp_servers`，将活跃的 Tableau 类型记录自动同步到 `tableau_connections`，再执行正常的资产同步流程。

---

## 3. 方案设计

### 3.1 桥接流程

```
scheduled_sync_all（Celery Beat，每 60 秒）
  │
  ├─ Step 1：_bridge_mcp_to_connections()
  │    ├─ 查询 mcp_servers WHERE type='tableau' AND is_active=True
  │    ├─ 遍历每条记录：
  │    │    ├─ 提取 credentials JSONB 中的连接凭据
  │    │    ├─ 用 Fernet 加密 pat_value → token_encrypted
  │    │    └─ 调用 ensure_connection_from_mcp() 按 name 去重 upsert
  │    └─ 跳过无 pat_value 的记录（记录 warning 日志）
  │
  └─ Step 2：正常资产同步流程（遍历 tableau_connections，触发 sync）
```

### 3.2 字段映射

从 `mcp_servers.credentials` JSONB 到 `tableau_connections` 列的映射关系：

| `mcp_servers` 字段 | `tableau_connections` 列 | 转换 |
|-------------------|--------------------------|------|
| `credentials.tableau_server` | `server_url` | 直接映射；fallback 到 `mcp_servers.server_url` |
| `credentials.site_name` | `site` | 直接映射 |
| `credentials.pat_name` | `token_name` | 直接映射 |
| `credentials.pat_value` | `token_encrypted` | Fernet 加密后存储 |
| `mcp_servers.name` | `name` | 直接映射（用于去重判断） |
| `mcp_servers.server_url` | `mcp_server_url` | 直接映射 |
| —（硬编码） | `api_version` | `"3.21"` |
| —（硬编码） | `connection_type` | `"mcp"` |
| —（硬编码） | `is_active` | `True` |
| —（硬编码） | `auto_sync_enabled` | `True` |
| —（硬编码） | `mcp_direct_enabled` | `True` |
| —（硬编码） | `owner_id` | `1`（默认管理员） |

### 3.3 去重策略

- **去重键**：`tableau_connections.name`（与 `mcp_servers.name` 匹配）
- **行为**：若已存在同名记录，返回现有记录，不更新任何字段
- **含义**：桥接只负责"首次创建"。后续凭据变更需通过其他途径处理

### 3.4 错误处理

| 场景 | 处理方式 |
|------|---------|
| `mcp_servers` 查询失败 | 记录 warning 日志，跳过桥接步骤，正常同步流程不受影响 |
| 单条记录无 `pat_value` | 记录 warning 日志，跳过该记录，继续处理下一条 |
| Fernet 加密失败 | 记录 warning 日志，跳过该记录 |
| `ensure_connection_from_mcp` 数据库写入失败 | 由调用方捕获异常，不影响其他记录 |

---

## 4. 代码实现示例

### 4.1 `_bridge_mcp_to_connections()` — 桥接主函数

**文件**：`backend/services/tasks/tableau_tasks.py`

在 `scheduled_sync_all()` 函数开头调用。

```python
import logging
from app.core.database import SessionLocal
from services.mcp.models import McpServer
from services.tableau.models import TableauDatabase

logger = logging.getLogger(__name__)


def _bridge_mcp_to_connections():
    """扫描活跃 Tableau MCP 配置，自动桥接到 tableau_connections 表。"""
    db = SessionLocal()
    try:
        mcp_servers = (
            db.query(McpServer)
            .filter(McpServer.type == "tableau", McpServer.is_active == True)
            .all()
        )
        if not mcp_servers:
            return

        tableau_db = TableauDatabase()
        for mcp in mcp_servers:
            creds = mcp.credentials or {}
            pat_value = creds.get("pat_value", "")
            if not pat_value:
                logger.warning(
                    "Bridge: mcp_server '%s' (id=%d) has no pat_value, skipping",
                    mcp.name, mcp.id,
                )
                continue

            try:
                from app.core.crypto import get_tableau_crypto
                fernet = get_tableau_crypto()
                token_encrypted = fernet.encrypt(pat_value.encode()).decode()

                tableau_db.ensure_connection_from_mcp(
                    db,
                    name=mcp.name,
                    server_url=creds.get("tableau_server") or mcp.server_url,
                    site=creds.get("site_name", ""),
                    token_name=creds.get("pat_name", ""),
                    token_encrypted=token_encrypted,
                    mcp_server_url=mcp.server_url,
                )
            except Exception as e:
                logger.warning(
                    "Bridge: failed to bridge mcp_server '%s' (id=%d): %s",
                    mcp.name, mcp.id, e,
                )
    except Exception as e:
        logger.warning("Bridge: _bridge_mcp_to_connections failed: %s", e)
    finally:
        db.close()
```

**调用位置**（`scheduled_sync_all` 函数开头）：

```python
@celery_app.task
def scheduled_sync_all():
    _bridge_mcp_to_connections()   # Step 1: 桥接
    # Step 2: 正常同步流程（遍历 tableau_connections）...
```

### 4.2 `ensure_connection_from_mcp()` — 去重 upsert

**文件**：`backend/services/tableau/models.py`，`TableauDatabase` 类新增方法。

```python
def ensure_connection_from_mcp(
    self,
    db,
    *,
    name: str,
    server_url: str,
    site: str,
    token_name: str,
    token_encrypted: str,
    mcp_server_url: str,
) -> "TableauConnection":
    """按 name 去重：存在则返回现有记录，不存在则创建。

    返回值：TableauConnection 实例（已提交到 DB）。
    """
    existing = (
        db.query(TableauConnection)
        .filter(TableauConnection.name == name)
        .first()
    )
    if existing:
        logger.info(
            "Bridge: tableau_connection '%s' already exists (id=%d), skipping",
            name, existing.id,
        )
        return existing

    conn = TableauConnection(
        name=name,
        server_url=server_url,
        site=site,
        token_name=token_name,
        token_encrypted=token_encrypted,
        mcp_server_url=mcp_server_url,
        api_version="3.21",
        connection_type="mcp",
        is_active=True,
        auto_sync_enabled=True,
        mcp_direct_enabled=True,
        owner_id=1,
    )
    db.add(conn)
    db.commit()
    db.refresh(conn)
    logger.info(
        "Bridge: created tableau_connection '%s' (id=%d) from mcp_server",
        name, conn.id,
    )
    return conn
```

> **约束**：
> - 函数签名使用 keyword-only 参数（`*,`），禁止位置传参，防止字段顺序混淆
> - 去重逻辑只按 `name` 匹配，不按 `server_url`。同名不同 URL 视为同一连接
> - 已存在时**不更新任何字段**（只创建不更新），返回现有记录
> - `owner_id=1` 为硬编码管理员 ID（见开放问题 #2）

---

## 5. 涉及文件

### 5.1 变更文件

| 文件 | 变更内容 |
|------|---------|
| `backend/services/tasks/tableau_tasks.py` | 新增 `_bridge_mcp_to_connections()` 函数；在 `scheduled_sync_all()` 开头调用 |
| `backend/services/tableau/models.py` | `TableauDatabase` 类新增 `ensure_connection_from_mcp()` 方法 |

### 5.2 依赖文件（未变更）

| 文件 | 依赖关系 |
|------|---------|
| `backend/services/mcp/models.py` | 读取 `McpServer` ORM 模型 |
| `backend/app/core/crypto.py` | 调用 `get_tableau_crypto()` 获取 Fernet 实例 |
| `backend/app/core/database.py` | 调用 `SessionLocal()` 管理 Session 生命周期 |

### 5.3 迁移说明

无需数据库迁移。本次变更仅涉及对已有表（`mcp_servers`、`tableau_connections`）的数据读写操作，未修改表结构。

---

## 6. 安全

### 5.1 凭据处理

- PAT 明文（`credentials.pat_value`）仅在桥接函数内存中短暂存在
- 写入 `tableau_connections.token_encrypted` 前通过 Fernet 对称加密
- 加密密钥由 `app.core.crypto` 统一管理，与现有 Tableau 连接创建流程共用同一套加密体系

### 5.2 权限

- 桥接函数运行在 Celery Worker 进程内，不经过 HTTP 认证层
- 创建的连接 `owner_id` 默认为 `1`（系统管理员），与手动创建连接的权限模型一致

---

## 7. 测试与验证

### 6.1 验证步骤

| # | 步骤 | 预期结果 |
|---|------|---------|
| 1 | 在「MCP 配置」页面添加一个 Tableau 类型的 MCP Server，填入有效 PAT 凭据，启用 | `mcp_servers` 表新增一条 `type='tableau', is_active=True` 的记录 |
| 2 | 等待 60 秒（或手动触发 `scheduled_sync_all`） | `tableau_connections` 表自动出现同名记录，`auto_sync_enabled=True` |
| 3 | 再次等待下一个同步周期 | 同步任务使用桥接创建的连接拉取 Tableau 资产，`tableau_assets` 表有数据 |
| 4 | 访问「Tableau 资产浏览」页面 | 页面正常展示资产列表，不再为空 |
| 5 | 重复触发 `scheduled_sync_all` | 不会重复创建连接（去重逻辑生效） |
| 6 | MCP Server 的 `pat_value` 为空 | 该记录被跳过，日志记录 warning，其他记录正常处理 |
| 7 | MCP Server 的 `is_active=False` | 该记录不参与桥接 |

### 6.2 日志确认

桥接成功时日志输出：
```
INFO  Bridge: created tableau_connection '<name>' (id=<id>) from mcp_server id=<mcp_id>
```

桥接跳过时日志输出：
```
WARNING  Bridge: mcp_server '<name>' has no pat_value, skipping
```

---

## 8. 开放问题

| # | 问题 | 状态 |
|---|------|------|
| 1 | MCP 侧凭据更新后，桥接创建的 `tableau_connections` 记录是否需要自动同步更新？当前实现为"只创建不更新"。 | 待评估 |
| 2 | `owner_id` 硬编码为 `1` 是否需要改为从 MCP Server 记录中继承创建者？ | 待评估 |
| 3 | 是否需要在前端「Tableau 连接」页面标记哪些连接是桥接自动创建的（`connection_type='mcp'`）？ | 待评估 |

# SPEC：MCP 统一配置管理

- **状态**：已实施（v1.1 — 2026-04-24 补充 credentials 列）
- **创建**：2026-04-17
- **执行者**：coder
- **背景**：Tableau MCP URL 仅能通过环境变量配置；用户将陆续接入 StarRocks、MySQL MCP，需要可管理的统一界面

---

## 变更日志

| 日期 | 版本 | 变更 |
|------|------|------|
| 2026-04-17 | v1.0 | 初版 |
| 2026-04-24 | v1.1 | 补充 credentials JSONB 列（实际已在 20260417_010000 迁移中实现）；补充 test-draft 端点；补充 parse 端点；标记 type 默认值修正为 `'tableau'` |

---

## 非目标

- 不做 MCP 协议级健康检查（只做 HTTP 可达性探测）
- 不改 `tableau_connections` 表上连接级别的 `mcp_server_url` 字段
- 不做批量导入/导出

---

## 一、数据模型

### 表：`mcp_servers`

```sql
id          INTEGER      PRIMARY KEY
name        VARCHAR(128) NOT NULL UNIQUE
type        VARCHAR(32)  NOT NULL DEFAULT 'tableau'  -- tableau|starrocks
server_url  VARCHAR(512) NOT NULL
description TEXT         NULL
is_active   BOOLEAN      NOT NULL DEFAULT false
credentials JSONB        NULL     -- v1.1 新增：存储认证凭据（见下方 schema）
created_at  DATETIME     NOT NULL DEFAULT now()
updated_at  DATETIME     NOT NULL DEFAULT now()
```

#### credentials JSONB Schema

按 `type` 字段区分存储格式：

**type=tableau**：
```json
{
  "tableau_server": "https://online.tableau.com",
  "site_name": "my_site",
  "pat_name": "my-pat",
  "pat_value": "UaN/B5UUSF+dw/+WGwrD6w==:LrWI0..."
}
```

**type=starrocks**：
```json
{
  "host": "localhost",
  "port": "9030",
  "user": "root",
  "password": "xxx",
  "database": "my_db"
}
```

> ⚠️ **安全待办**：当前 credentials 以 JSONB 明文存储。应将敏感字段（`pat_value`、`password`）加密存储，复用 `TABLEAU_ENCRYPTION_KEY`。已登记为 P4 安全修复项。

索引：
- `UNIQUE INDEX ix_mcp_servers_name (name)`
- `INDEX ix_mcp_servers_type_active (type, is_active)`  ← Tableau fallback 查询加速

### SQLAlchemy Model

新建文件：`backend/services/mcp/__init__.py`（空文件）
新建文件：`backend/services/mcp/models.py`

```python
from sqlalchemy import Column, Integer, String, Boolean, DateTime, Text
from app.core.database import Base, sa_func, sa_text

class McpServer(Base):
    __tablename__ = "mcp_servers"

    id          = Column(Integer, primary_key=True)
    name        = Column(String(128), nullable=False, unique=True)
    type        = Column(String(32), nullable=False, server_default=sa_text("'custom'"))
    server_url  = Column(String(512), nullable=False)
    description = Column(Text, nullable=True)
    is_active   = Column(Boolean, nullable=False, default=False, server_default=sa_text("false"))
    created_at  = Column(DateTime, nullable=False, server_default=sa_func.now())
    updated_at  = Column(DateTime, nullable=False, server_default=sa_func.now(),
                         onupdate=sa_func.now())

    def to_dict(self):
        return {
            "id":          self.id,
            "name":        self.name,
            "type":        self.type,
            "server_url":  self.server_url,
            "description": self.description,
            "is_active":   self.is_active,
            "created_at":  self.created_at.isoformat() if self.created_at else None,
            "updated_at":  self.updated_at.isoformat() if self.updated_at else None,
        }
```

### Alembic 迁移

新建文件：`backend/alembic/versions/20260417_000000_create_mcp_servers.py`

```python
revision = '20260417_000000'
down_revision = '20260416_020000'   # ← 当前 HEAD，已确认

import sqlalchemy as sa
from alembic import op

def upgrade():
    op.create_table(
        'mcp_servers',
        sa.Column('id',          sa.Integer(),     primary_key=True),
        sa.Column('name',        sa.String(128),   nullable=False),
        sa.Column('type',        sa.String(32),    nullable=False, server_default='custom'),
        sa.Column('server_url',  sa.String(512),   nullable=False),
        sa.Column('description', sa.Text(),        nullable=True),
        sa.Column('is_active',   sa.Boolean(),     nullable=False, server_default='false'),
        sa.Column('created_at',  sa.DateTime(),    nullable=False, server_default=sa.func.now()),
        sa.Column('updated_at',  sa.DateTime(),    nullable=False, server_default=sa.func.now()),
    )
    op.create_index('ix_mcp_servers_name', 'mcp_servers', ['name'], unique=True)
    op.create_index('ix_mcp_servers_type_active', 'mcp_servers', ['type', 'is_active'])

def downgrade():
    op.drop_table('mcp_servers')
```

迁移前需确认 `McpServer` 已被 `alembic/env.py` 的 `target_metadata` 感知（检查 env.py 是否有统一 model import 入口，若有则在其中加 `from services.mcp.models import McpServer`）。

---

## 二、后端 API

新建文件：`backend/app/api/mcp_configs.py`

### Pydantic Schemas

```python
MCP_TYPE_VALUES = {"tableau", "starrocks", "mysql", "custom"}

class McpServerCreateRequest(BaseModel):
    name:        str
    type:        str        # 校验：in MCP_TYPE_VALUES
    server_url:  str        # 校验：startswith http
    description: Optional[str] = None
    is_active:   bool = True

class McpServerUpdateRequest(BaseModel):
    name:        Optional[str] = None
    type:        Optional[str] = None
    server_url:  Optional[str] = None
    description: Optional[str] = None
    is_active:   Optional[bool] = None
```

### 端点规格

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/mcp-configs/parse` | AI 解析粘贴文本，返回结构化字段 |
| GET | `/api/mcp-configs` | 列表，按 created_at DESC |
| POST | `/api/mcp-configs` | 新建，name 重复返回 409；body 含 credentials |
| PUT | `/api/mcp-configs/{id}` | 部分更新，id 不存在返回 404 |
| DELETE | `/api/mcp-configs/{id}` | 删除，id 不存在返回 404 |
| POST | `/api/mcp-configs/test-draft` | 保存前连通测试（传 server_url，不需要先保存） |
| POST | `/api/mcp-configs/{id}/test` | 已保存配置的连通测试 |

所有端点：`get_current_admin(request)` 鉴权（与 `llm.py` 保持一致，不用 Depends(get_db)）。

### 连通测试实现

```python
@router.post("/{id}/test")
async def test_mcp_server(id: int, request: Request):
    get_current_admin(request)
    db = SessionLocal()
    try:
        record = db.query(McpServer).filter(McpServer.id == id).first()
        if not record:
            raise HTTPException(status_code=404, detail="MCP server not found")
        url = record.server_url
    finally:
        db.close()

    import time as _time
    import httpx as _httpx
    start = _time.monotonic()
    try:
        async with _httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(url)
        latency_ms = int((_time.monotonic() - start) * 1000)
        return {"status": "online", "latency_ms": latency_ms, "http_status": resp.status_code}
    except (_httpx.ConnectError, _httpx.TimeoutException) as e:
        latency_ms = int((_time.monotonic() - start) * 1000)
        return {"status": "offline", "latency_ms": latency_ms, "error": type(e).__name__}
```

### 路由注册

修改 `backend/app/main.py`，在 llm router 注册行之后添加：

```python
from app.api import mcp_configs
app.include_router(mcp_configs.router, prefix="/api/mcp-configs", tags=["MCP 配置管理"])
```

---

## 三、Tableau MCP Client 适配

**文件：** `backend/services/common/settings.py`

修改 `get_tableau_mcp_server_url()` 函数：

1. 移除 `@lru_cache` 装饰器
2. 函数内部 DB 查询优先，异常时静默 fallback

```python
# 移除 @lru_cache
def get_tableau_mcp_server_url() -> str:
    """
    获取 Tableau MCP Server URL。
    优先级：DB(type=tableau, is_active=True) > 环境变量 > 默认值
    DB 查询失败时静默 fallback（迁移未完成等情况）。
    """
    try:
        from app.core.database import SessionLocal
        from services.mcp.models import McpServer
        db = SessionLocal()
        try:
            record = (
                db.query(McpServer)
                .filter(McpServer.type == "tableau", McpServer.is_active == True)
                .order_by(McpServer.created_at.asc())
                .first()
            )
            if record:
                return record.server_url
        finally:
            db.close()
    except Exception:
        pass
    return os.environ.get("TABLEAU_MCP_SERVER_URL", "http://localhost:3927/tableau-mcp")
```

`clear_tableau_mcp_cache()` 函数：移除 `get_tableau_mcp_server_url.cache_clear()` 调用（函数已无缓存），保留 timeout 和 protocol 的 cache_clear。

---

## 四、前端路由与菜单

### router/config.tsx

新增 lazy import（在 LLMConfigsPage 行附近）：
```typescript
const McpConfigsPage = lazy(() => import('../pages/admin/mcp-configs/page'));
```

新增路由（在 `llm-configs` 路由块之后）：
```typescript
{
  path: 'mcp-configs',
  element: (
    <ProtectedRoute adminOnly>
      <McpConfigsPage />
    </ProtectedRoute>
  ),
},
```

### config/menu.ts

在 `key: 'llm'` 菜单项之后插入：
```typescript
{
  key: 'mcp-configs',
  label: 'MCP 配置',
  icon: 'ri-plug-line',
  path: '/system/mcp-configs',
},
```

---

## 五、前端页面

新建文件：`frontend/src/pages/admin/mcp-configs/page.tsx`

参考 `llm-configs/page.tsx` 整体结构（列表视图 + 内嵌表单切换，无弹窗）。

### 类型 Badge 规格

```typescript
const TYPE_META = {
  tableau:    { icon: 'ri-bar-chart-2-line', cls: 'bg-blue-100 text-blue-700',   label: 'Tableau' },
  starrocks:  { icon: 'ri-database-2-line',  cls: 'bg-orange-100 text-orange-700', label: 'StarRocks' },
  mysql:      { icon: 'ri-database-line',    cls: 'bg-cyan-100 text-cyan-700',   label: 'MySQL' },
  custom:     { icon: 'ri-plug-line',        cls: 'bg-slate-100 text-slate-600', label: '自定义' },
};
```

### 列表字段

| 列 | 渲染 |
|----|------|
| 类型 | `TypeBadge` 组件（icon + label） |
| 名称 | `name` 纯文本 |
| Server URL | `font-mono text-xs`，超 50 字符截断，完整 URL 放 `title` tooltip |
| 状态 | `is_active` toggle，点击直接调 PUT 即时更新 |
| 操作 | 编辑 / 测试（显示 latency 或错误）/ 删除（ConfirmModal） |

### 表单字段

| 字段 | 类型 | 规则 |
|------|------|------|
| name | text | 必填 |
| type | select | 四种类型，选项见 TYPE_META |
| server_url | text | 必填；placeholder 按 type 自动切换（见下） |
| description | textarea | 可选 |
| is_active | toggle switch | 默认 true |

**server_url placeholder 按 type：**

| type | placeholder |
|------|-------------|
| tableau | `http://localhost:3927/tableau-mcp` |
| starrocks | `http://localhost:3928/starrocks-mcp` |
| mysql | `http://localhost:3929/mysql-mcp` |
| custom | `http://your-mcp-server/path` |

表单底部：「测试连接」按钮（编辑态调 `POST /api/mcp-configs/{id}/test`；新建态提示先保存）+ 「保存」按钮。

### 从 LLM 配置页清理

修改 `frontend/src/pages/admin/llm-configs/page.tsx`，删除：
- `mcpStatus`、`mcpTesting`、`mcpTestResult` state 声明
- `useEffect` 中的 `/api/tableau/mcp-status` 调用块
- `handleTestMcp` 函数
- Tableau MCP 集成 `<section>` JSX 节点（含 `StatusBadge` 组件）

---

## 六、实施顺序

```
Step 1（并行）
  A. 新建 services/mcp/__init__.py + models.py
  B. 新建 alembic migration 文件

Step 2（依赖 A）
  C. 检查 alembic/env.py，确保 McpServer 被 import
  D. 执行 alembic upgrade head，确认表建成

Step 3（依赖 A，中）
  E. 新建 backend/app/api/mcp_configs.py

Step 4（依赖 E）
  F. 修改 main.py 注册路由

Step 5（依赖 A，低）
  G. 修改 settings.py（DB 优先查询）

Step 6（并行，与后端无依赖，中）
  H. 新建 frontend/src/pages/admin/mcp-configs/page.tsx
  I. 修改 router/config.tsx + menu.ts

Step 7（依赖 H）
  K. 修改 llm-configs/page.tsx 删除 MCP 卡片
```

---

## 七、验收标准

### 后端

```bash
# 登录取 cookie
curl -c /tmp/c.txt -X POST http://localhost:8000/api/auth/login \
  -H "Content-Type: application/json" -d '{"username":"admin","password":"admin123"}'

# 新建
curl -b /tmp/c.txt -X POST http://localhost:8000/api/mcp-configs \
  -H "Content-Type: application/json" \
  -d '{"name":"Tableau Dev","type":"tableau","server_url":"http://localhost:3927/tableau-mcp","is_active":true}'
# 期望：含 id 的 JSON

# 列表
curl -b /tmp/c.txt http://localhost:8000/api/mcp-configs
# 期望：包含新建记录

# 连通测试
curl -b /tmp/c.txt -X POST http://localhost:8000/api/mcp-configs/1/test
# 期望：{"status":"online"|"offline","latency_ms":...}

# name 重复 → 409
curl -b /tmp/c.txt -X POST http://localhost:8000/api/mcp-configs \
  -H "Content-Type: application/json" \
  -d '{"name":"Tableau Dev","type":"tableau","server_url":"http://x","is_active":true}'
# 期望：409
```

### Tableau MCP Client 适配

```bash
# DB 中有 type=tableau is_active=true 记录时：
curl -b /tmp/c.txt http://localhost:8000/api/tableau/mcp-status
# 期望：url 字段 = DB 中的 server_url，而非环境变量值

# 将记录 is_active 改为 false 后：
curl -b /tmp/c.txt http://localhost:8000/api/tableau/mcp-status
# 期望：url 字段回退为 TABLEAU_MCP_SERVER_URL 环境变量或默认值
```

### 前端

- [ ] `/system/mcp-configs` 可访问，无 404
- [ ] 侧边栏「MCP 配置」菜单项可见，点击跳转正确
- [ ] `/system/llm-configs` 页面不再显示 Tableau MCP 卡片
- [ ] 创建 tableau 类型记录 → 蓝色图标 badge
- [ ] Toggle `is_active` → 即时更新，无需刷新
- [ ] TypeScript 编译零报错

---

## 风险

| 风险 | 缓解 |
|------|------|
| `get_tableau_mcp_server_url` 无缓存后性能影响 | `mcp_client.py` 实例级缓存覆盖，不会每次工具调用触发 DB 查询 |
| alembic down_revision 链断裂 | `down_revision = '20260416_020000'` 已确认为当前 HEAD |
| DB 查询在 settings.py 引入启动时序问题 | `try/except Exception: pass` 静默 fallback，迁移未完成也不会崩溃 |
| 前端删除 MCP 卡片遗漏 state | TypeScript 编译会暴露悬空引用，CI 可检测 |

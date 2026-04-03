# API 约定规范

> 版本：v1.0 | 状态：已完成 | 日期：2026-04-04

---

## 1. 概述

本文档定义木兰 BI 平台所有 API 端点必须遵循的约定，包括认证、分页、命名、响应格式和安全策略。所有新模块开发**必须**遵循本规范。

---

## 2. 基础路径与版本策略

### 2.1 当前方案
所有 API 统一使用 `/api/{module}/...` 路径，无版本前缀。

### 2.2 路由注册总览

| 路由模块 | 前缀 | 标签 |
|---------|------|------|
| `ddl` | `/api/ddl` | DDL 检查 |
| `rules` | `/api/rules` | 规则配置 |
| `logs` | `/api/logs` | 日志 |
| `requirements` | `/api/requirements` | 需求管理 |
| `auth` | `/api/auth` | 认证 |
| `users` | `/api/users` | 用户管理 |
| `groups` | `/api/groups` | 用户组管理 |
| `permissions` | `/api/permissions` | 权限配置 |
| `activity` | `/api/activity` | 访问日志 |
| `datasources` | `/api/datasources` | 数据源管理 |
| `tableau` | `/api/tableau` | Tableau 管理 |
| `health_scan` | `/api/governance/health` | 数仓健康检查 |
| `llm` | `/api/llm` | LLM 管理 |
| `tasks` | `/api/tasks` | 任务管理 |
| `sm_datasources` | `/api/semantic-maintenance` | 语义维护 |
| `sm_fields` | `/api/semantic-maintenance` | 语义维护 |
| `sm_review` | `/api/semantic-maintenance` | 语义维护 |
| `sm_sync` | `/api/semantic-maintenance` | 语义维护 |
| `sm_publish` | `/api/semantic-maintenance` | 语义维护 |

顶层端点：`GET /`（欢迎页）、`GET /health`（健康检查）。

源文件：`backend/app/main.py`

### 2.3 未来版本迁移路径

当需要引入破坏性变更时，迁移至 `/api/v1/...`：
1. 新建 `v1/` 子路由模块
2. 旧路径保留 6 个月，返回 `Deprecation` Header
3. 前端逐步切换

---

## 3. 认证机制

### 3.1 Session/Cookie 认证

| 项目 | 值 |
|------|-----|
| Token 类型 | JWT (HS256) |
| 存储位置 | HTTP-Only Cookie `session` |
| 签名密钥 | `SESSION_SECRET` 环境变量 |
| 有效期 | 7 天 |
| Cookie 标志 | `HttpOnly=true`, `SameSite=Lax`, `Secure=SECURE_COOKIES` |

Token Payload：
```json
{
  "sub": 1,
  "username": "admin",
  "role": "admin",
  "exp": 1743724800
}
```

### 3.2 依赖注入守卫

源文件：`backend/app/core/dependencies.py`

| 守卫函数 | 适用场景 | 行为 |
|---------|---------|------|
| `get_current_user(request, db)` | 所有需认证端点 | 从 `session` Cookie 提取 JWT → 解码 → 验证用户存在且 `is_active=True` → 返回 `{id, username, role}`。失败抛 401 |
| `get_current_admin(request, db)` | 管理员专属端点 | 调用 `get_current_user` + 断言 `role=="admin"`。失败抛 403 |
| `require_roles(request, allowed_roles, db)` | 角色受限端点 | 调用 `get_current_user` + 断言 `role in allowed_roles`。失败抛 403 |

### 3.3 资源所有权验证 (IDOR 防护)

对于属主隔离的资源（数据源、Tableau 连接），在守卫之后额外验证：

```python
# 模式：非 admin 只能访问自己的资源
if user["role"] != "admin":
    resource = db.query(Model).filter_by(id=resource_id, owner_id=user["id"]).first()
    if not resource:
        raise HTTPException(403, "Access denied")
```

---

## 4. 请求/响应约定

### 4.1 Content-Type

| 方向 | 格式 |
|------|------|
| 请求 | `application/json`（文件上传除外） |
| 响应 | `application/json`（文件下载、HTML 报告除外） |

### 4.2 标准分页

**请求参数：**

| 参数 | 类型 | 默认值 | 最大值 | 说明 |
|------|------|--------|--------|------|
| `page` | int | 1 | - | 页码（从 1 开始） |
| `page_size` | int | 20 | 100 | 每页条数 |

> 部分端点默认 `page_size=50`（如 Tableau assets），但最大值统一为 100。

**响应格式：**
```json
{
  "items": [{ "id": 1, "name": "..." }],
  "total": 100,
  "page": 1,
  "page_size": 20,
  "pages": 5
}
```

### 4.3 日期格式

| 场景 | 格式 | 示例 |
|------|------|------|
| JSON 响应 | `YYYY-MM-DD HH:MM:SS` (字符串) | `"2026-04-04 14:30:00"` |
| URL 查询参数 | ISO 8601 | `?after=2026-04-01T00:00:00Z` |
| 数据库存储 | `TIMESTAMP WITHOUT TIME ZONE` | PostgreSQL 原生 |

实现方式：各 Model 的 `to_dict()` 方法使用 `.strftime("%Y-%m-%d %H:%M:%S")`。

### 4.4 成功响应

| 操作类型 | HTTP 状态码 | 响应体 |
|---------|------------|--------|
| 列表查询 | 200 | 分页包络 |
| 单资源查询 | 200 | 资源对象 |
| 创建 | 200 | 创建后的资源对象 |
| 更新 | 200 | 更新后的资源对象 |
| 删除 | 200 | `{"message": "...", "success": true}` |
| 触发动作 | 200 | 动作结果对象 |

> 注：当前代码统一使用 200（非 201/204），保持一致即可。

### 4.5 错误响应

参见 [01-error-codes-standard.md](01-error-codes-standard.md)。格式：
```json
{
  "error_code": "MODULE_NNN",
  "message": "描述",
  "detail": {}
}
```

---

## 5. CORS 配置

| 项目 | 值 |
|------|-----|
| 配置来源 | `ALLOWED_ORIGINS` 环境变量（逗号分隔） |
| 默认值 | `http://localhost:5173,http://localhost:3002,http://localhost:3003` |
| `allow_credentials` | `true`（Cookie 认证必需） |
| `allow_methods` | `["*"]` |
| `allow_headers` | `["*"]` |

---

## 6. 角色与权限矩阵

### 6.1 四级角色

| 角色 | 代码 | 说明 |
|------|------|------|
| 超级管理员 | `admin` | 全局最高权限 |
| 数据管理员 | `data_admin` | 数据源、扫描、Tableau 连接管理 |
| 分析师 | `analyst` | 浏览报表、使用 AI 功能 |
| 普通用户 | `user` | 基础 DDL 验证 |

### 6.2 全模块权限矩阵

| 操作 | admin | data_admin | analyst | user |
|------|:-----:|:----------:|:-------:|:----:|
| **用户管理** |
| 用户 CRUD | Y | - | - | - |
| 用户组 CRUD | Y | - | - | - |
| 权限配置 | Y | - | - | - |
| **数据源** |
| 数据源 CRUD | Y | Y(own) | - | - |
| 连接测试 | Y | Y(own) | - | - |
| **DDL** |
| DDL 验证 | Y | Y | Y | Y |
| 规则 CRUD | Y | Y | - | - |
| **Tableau** |
| 连接 CRUD | Y | Y | - | - |
| 触发同步 | Y | Y | - | - |
| 资产浏览/搜索 | Y | Y | Y | - |
| AI 解读 | Y | Y | Y | - |
| 健康评分查看 | Y | Y | Y | - |
| **语义治理** |
| 语义 CRUD | Y | Y | - | - |
| AI 语义生成 | Y | Y | - | - |
| 提交审核 | Y | Y | - | - |
| 审批/驳回 | Y | reviewer | - | - |
| 发布到 Tableau | Y | - | - | - |
| 回滚 | Y | - | - | - |
| **LLM** |
| LLM 配置 CRUD | Y | - | - | - |
| 资产 AI 摘要 | Y | Y | Y | - |
| **健康扫描** |
| 触发扫描 | Y | Y | - | - |
| 查看扫描结果 | Y | Y | Y | - |
| **系统管理** |
| 活动日志查看 | Y | - | - | - |
| 任务管理 | Y | - | - | - |

---

## 7. 命名约定

### 7.1 URL 路径
- **风格**：kebab-case（`/api/semantic-maintenance/datasources`）
- **集合**：复数名词（`/connections`, `/assets`）
- **单资源**：`/{collection}/{id}`
- **动作**：`POST /{collection}/{id}/{verb}`（如 `/test`, `/sync`, `/explain`）

### 7.2 请求/响应字段
- **风格**：snake_case
- **布尔字段**：`is_*` 前缀（`is_active`, `is_deleted`）
- **时间戳**：`*_at` 后缀（`created_at`, `synced_at`）
- **外键**：`*_id` 后缀（`connection_id`, `owner_id`）
- **JSONB 文本**：`*_json` 后缀（`tags_json`, `diff_json`）
- **加密字段**：`*_encrypted` 后缀（`password_encrypted`, `token_encrypted`）

---

## 8. 安全约定

### 8.1 加密密钥隔离

| 密钥 | 用途 | 算法 |
|------|------|------|
| `SESSION_SECRET` | JWT 签名 | HS256 |
| `DATASOURCE_ENCRYPTION_KEY` | 数据源密码加密 | Fernet (AES-128-CBC) |
| `TABLEAU_ENCRYPTION_KEY` | Tableau PAT 加密 | Fernet |
| `LLM_ENCRYPTION_KEY` | LLM API Key 加密 | Fernet |

> 四把密钥**必须**不同，**必须**为 32 字节强随机值。

### 8.2 安全红线
- 密码/密钥**不得**出现在日志或 API 响应中
- LLM 调用仅发送资产名称/描述，**不得**发送实际数据值
- LLM 返回内容需 HTML 转义后再渲染
- 所有 SQL 使用参数化查询，禁止字符串拼接

### 8.3 频率限制
- 注册：同一 IP 60 秒内最多 5 次
- 其他端点：当前无全局限制，按需在 Spec 中定义

---

## 9. 端点统计

| 模块 | 端点数 | 状态 |
|------|--------|------|
| Auth | 5 | 已实现 |
| Users | ~4 | 已实现 |
| Groups | ~4 | 已实现 |
| Permissions | ~3 | 已实现 |
| Activity | ~2 | 已实现 |
| DataSources | 6 | 已实现 |
| DDL | ~4 | 已实现 |
| Rules | ~7 | 已实现 |
| Tableau | 18 | 已实现 |
| LLM | 5 | 已实现 |
| Health Scan | 6 | 已实现 |
| Semantic Maintenance | ~20 | 已实现 |
| Tasks | ~2 | 已实现 |
| Logs | ~3 | 已实现 |
| Requirements | ~5 | 已实现 |
| **合计** | **~94** | |

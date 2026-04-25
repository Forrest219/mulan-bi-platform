# 平台设置（Platform Settings）技术规格书

> 版本：v0.1 | 状态：草稿 | 日期：2026-04-24 | 关联需求：用户要求 Logo 全局可配置

---

## 1. 概述

### 1.1 目的

将平台 Logo、平台名称等全局配置从硬编码 `frontend/src/config.ts` 迁移至数据库存储，并通过管理后台 UI 实时修改，实现"一次配置、全局生效、不改代码不重启"的企业级规范。

### 1.2 范围

- **包含**：平台基础设置（Logo URL、平台名称、平台副标题）存储与读取；管理后台 UI；前端全局 Context
- **不包含**：Favicon 个性化（后期扩展）、多主题/多租户、LDAP/SSO 集成

### 1.3 关联文档

| 文档 | 路径 | 关系 |
|------|------|------|
| Spec 18 菜单重构 | docs/specs/18-menu-restructure-spec.md | 复用 AppSidebar 组件 |
| Auth RBAC Spec | docs/specs/04-auth-rbac-spec.md | 复用 admin 角色校验 |
| API 规范 | docs/specs/02-api-conventions.md | 复用统一响应格式 |

---

## 2. 数据模型

### 2.1 表定义

#### `platform_settings`

| 列名 | 类型 | 约束 | 说明 |
|------|------|------|------|
| id | INTEGER | PK, AUTO | 主键（固定为 1，单行记录） |
| platform_name | VARCHAR(128) | NOT NULL, DEFAULT '木兰 BI 平台' | 平台显示名称 |
| platform_subtitle | VARCHAR(256) | DEFAULT '数据建模与治理平台' | 平台副标题 |
| logo_url | VARCHAR(512) | NOT NULL | Logo 图片 URL |
| favicon_url | VARCHAR(512) | NULLABLE | Favicon URL（预留） |
| created_at | TIMESTAMP | NOT NULL, DEFAULT NOW | 创建时间 |
| updated_at | TIMESTAMP | NOT NULL, DEFAULT NOW | 更新时间 |

**说明**：本表设计为单行记录（id=1），通过 `GET` 全量返回、`PUT` 全量更新，不做列表 CRUD。

### 2.2 Alembic 迁移

- 生成命令：`cd backend && alembic revision --autogenerate -m "add platform_settings"`
- 迁移文件放入 `backend/alembic/versions/`
- 种子数据：迁移自动插入 id=1 的默认记录（Logo URL 复用原硬编码值）

### 2.3 索引策略

| 表 | 索引名 | 列 | 类型 | 用途 |
|----|--------|-----|------|------|
| platform_settings | pk_platform_settings | id | BTREE | 主键 |
| platform_settings | uq_platform_settings_id | id | BTREE | 确保 id=1 唯一性 |

---

## 3. API 设计

### 3.1 端点总览

| 方法 | 路径 | 说明 | 认证 | 角色 |
|------|------|------|------|------|
| GET | /api/platform-settings/ | 获取平台设置 | 需要 | 任意登录用户 |
| PUT | /api/platform-settings/ | 更新平台设置 | 需要 | admin |

### 3.2 请求/响应 Schema

#### `GET /api/platform-settings`

**响应 (200)：**

```json
{
  "id": 1,
  "platform_name": "木兰 BI 平台",
  "platform_subtitle": "数据建模与治理平台",
  "logo_url": "https://public.readdy.ai/ai/img_res/d9bf8fa2-dfff-4c50-98cf-7b635309e7d6.png",
  "favicon_url": null,
  "created_at": "2026-04-24T00:00:00Z",
  "updated_at": "2026-04-24T00:00:00Z"
}
```

**错误响应 (404)：** 记录不存在

```json
{
  "error_code": "PLT_001",
  "message": "平台设置记录不存在",
  "detail": {}
}
```

#### `PUT /api/platform-settings`

**请求：**

```json
{
  "platform_name": "木兰 BI 平台",
  "platform_subtitle": "数据建模与治理平台",
  "logo_url": "https://example.com/logo.png",
  "favicon_url": null
}
```

**校验规则：**
- `logo_url`：必填，有效 HTTP(S) URL，最大 512 字符
- `platform_name`：必填，1-128 字符
- `platform_subtitle`：可选，最大 256 字符

**响应 (200)：** 返回更新后的完整记录（同 GET 格式）

**错误响应 (400)：** 校验失败

```json
{
  "error_code": "PLT_002",
  "message": "logo_url 必须是有效的 HTTP(S) URL",
  "detail": { "field": "logo_url" }
}
```

---

## 4. 业务逻辑

### 4.1 初始化逻辑

- 应用启动时，若 `platform_settings` 表无记录，自动插入 id=1 的默认记录
- 默认值：平台名称="木兰 BI 平台"、副标题="数据建模与治理平台"、Logo URL 复用 `config.ts` 原有值

### 4.2 读取逻辑

- `GET` 时直接查 `WHERE id=1`，记录不存在返回 404
- 不做缓存，首次读取后由前端 Context 持有

### 4.3 写入逻辑

- `PUT` 时强制 `id=1` 更新，不允许创建新记录
- `updated_at` 由数据库 `ON UPDATE` 自动维护
- 写入后返回完整新记录

---

## 5. 错误码

| 错误码 | HTTP | 说明 | 触发条件 |
|--------|------|------|---------|
| PLT_001 | 404 | 平台设置记录不存在 | GET 时无 id=1 记录 |
| PLT_002 | 400 | 字段校验失败 | logo_url 非 URL 或 platform_name 超长 |

---

## 6. 安全

### 6.1 角色权限矩阵

| 操作 | admin | data_admin | analyst | user |
|------|-------|-----------|---------|------|
| 查看设置 | Y | Y | Y | Y |
| 修改设置 | Y | N | N | N |

### 6.2 URL 安全

- `logo_url` 和 `favicon_url` 仅接受 `http://` 和 `https://` 开头
- 前端渲染 `<img src={logo_url}>` 时浏览器自带 XSS 防护，无需额外转义

---

## 7. 前端架构

### 7.1 全局 Context

- 文件：`frontend/src/context/PlatformSettingsContext.tsx`
- 内容：存储 `logo_url`、`platform_name`、`platform_subtitle`
- 初始化：App 启动时调用 `GET /api/platform-settings`，请求完成后设置 Context
- 加载态：`PlatformSettingsContext` 提供 `isLoading` 状态，Context 未加载完前 Sidebar 显示默认 LOGO_URL

### 7.2 组件更新路径

```
PlatformSettingsContext.logo_url
    ├── AppSidebar.tsx  → 显示 Logo + 平台名称
    ├── AppHeader.tsx   → （已移除 Logo，忽略）
    ├── LoginForm       → 显示 Logo + 平台名称（登录页）
    └── PlatformSettingsPage → 读取/修改 Settings
```

### 7.3 平台设置页面

- 路径：`/system/platform-settings`（属于"平台"域）
- 入口：侧边栏"平台 → 平台设置"（仅 admin 可见）
- 功能：表单展示当前设置，修改后即时预览，提交调用 PUT

---

## 8. 集成点

### 8.1 上游依赖

| 模块 | 接口 | 用途 |
|------|------|------|
| AuthService | 验证 session cookie | 接口认证 |
| User Model | 获取当前用户 role | admin 权限校验 |

### 8.2 下游消费者

| 模块 | 消费方式 | 说明 |
|------|---------|------|
| AppSidebar | 直接读取 Context | 渲染 Logo |
| LoginForm | 直接读取 Context | 渲染 Logo |
| PlatformSettingsPage | 调用 API | 读写设置 |

---

## 9. 时序图

```mermaid
sequenceDiagram
    participant U as User
    participant F as Frontend
    participant B as Backend
    participant DB as Database

    rect rgb(240, 248, 255)
        Note over F,B: 首次加载（App 初始化）
        F->>B: GET /api/platform-settings
        B->>DB: SELECT WHERE id=1
        DB-->>B: settings row
        B-->>F: { logo_url, platform_name, ... }
        F->>F: 设置 PlatformSettingsContext
    end

    rect rgb(255, 248, 240)
        Note over U,F,B: Admin 修改设置
        U->>F: 填写表单 → PUT
        F->>B: PUT /api/platform-settings
        B->>DB: UPDATE platform_settings SET ...
        DB-->>B: updated row
        B-->>F: 200 OK + new settings
        F->>F: 更新 Context → 自动触发 Sidebar 重渲染
    end
```

---

## 10. 测试策略

### 10.1 关键场景

| # | 场景 | 预期 | 优先级 |
|---|------|------|--------|
| 1 | 未登录用户 GET /api/platform-settings | 返回 401 | P0 |
| 2 | 普通用户 PUT /api/platform-settings | 返回 403 | P0 |
| 3 | Admin PUT 合法 logo_url | 返回 200，新设置入库 | P0 |
| 4 | PUT 无效 URL | 返回 400 + PLT_002 | P1 |
| 5 | 前端 Context 未加载完时 Sidebar 不报错 | 显示默认 LOGO_URL | P1 |

### 10.2 验收标准

- [ ] `GET /api/platform-settings` 返回 200 及正确 JSON
- [ ] `PUT /api/platform-settings`（admin）返回 200 并更新数据库
- [ ] `PUT /api/platform-settings`（非 admin）返回 403
- [ ] 前端 `PlatformSettingsContext` 在 App 启动时自动加载
- [ ] 修改 logo_url 后，Sidebar、登录页同步显示新 Logo
- [ ] Alembic 迁移可正常执行，种子数据正确插入

### 10.3 Mock 与测试约束

- **`PlatformSettingsService.get_or_initialize`**：首次调用时若记录不存在会自动创建。测试时需确保 DB 干净或用 `id=1` 固定记录
- **`put_settings`**：强制 `id=1`，不允许其他 id。测试时请勿依赖 autoincrement 行为

---

## 11. 开发交付约束

### 11.1 架构约束

- PlatformSettings Model 放在 `backend/services/platform_settings/models.py`（新服务目录）
- Service 放在 `backend/services/platform_settings/service.py`
- API 路由注册到 `backend/app/api/__init__.py` 的 router
- 前端 Context 放在 `frontend/src/context/PlatformSettingsContext.tsx`
- 不得在 PlatformSettingsContext 外单独存储 logo 相关 state

### 11.2 强制检查清单

- [ ] 后端 `python3 -m py_compile` 无语法错误
- [ ] 后端 `pytest tests/services/platform_settings/` 全部通过（如有测试）
- [ ] 前端 `npm run type-check` 无类型错误
- [ ] 前端 `npm run lint` 无 lint 错误
- [ ] 前端 `npm run build` 构建成功
- [ ] Alembic 迁移可执行：`alembic upgrade head`
- [ ] 手动验证：PUT 新 logo_url 后刷新页面，Sidebar 显示新 Logo

### 11.3 验证命令

```bash
# 后端语法检查
cd backend && python3 -m py_compile $(find services/platform_settings -name "*.py")

# 后端测试（如有）
cd backend && pytest tests/services/platform_settings/ -v

# 前端检查
cd frontend && npm run type-check && npm run lint && npm run build
```

### 11.4 正确/错误示范

```python
# ✗ 错误 — 硬编码 logo
logo = "https://example.com/logo.png"

# ✓ 正确 — 从 Context 读取
logo = usePlatformSettings().logo_url
```

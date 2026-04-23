# Spec 14: 用户问数界面 — Connected Apps JWT 用户模拟 + 内建问数前端

| 版本 | 日期 | 状态 | 依赖 Spec |
|------|------|------|----------|
| v1.0 | 2026-04-21 | Draft | Spec 13（MCP V2 直连）、Spec 22（多站点 MCP + 多 LLM）、Spec 04（Auth RBAC）、Spec 08（LLM 层）|

---

## 目录

1. [需求理解](#1-需求理解)
2. [非目标范围](#2-非目标范围)
3. [架构总览](#3-架构总览)
4. [Connected Apps JWT 方案](#4-connected-apps-jwt-方案)
5. [后端 API 设计](#5-后端-api-设计)
6. [前端模块设计](#6-前端模块设计)
7. [问数链路时序图](#7-问数链路时序图)
8. [数据库变更](#8-数据库变更)
9. [任务拆分](#9-任务拆分)
10. [验收标准](#10-验收标准)
11. [测试计划](#11-测试计划)
12. [风险与约束](#12-风险与约束)

---

## 1. 需求理解

### 1.1 核心问题

当前 Tableau MCP 使用运维 PAT（个人访问令牌）执行所有查询，导致 RLS 失效——所有用户等同以运维账号身份查看全量数据。这既是安全问题，也是产品不可用的根本原因：普通 BI 用户无法在数据隔离保真的前提下问数。

### 1.2 解决方案摘要

两个并行工程交付：

**A. RLS 修复**：Tableau Connected Apps JWT 用户模拟，每次查询用当前登录用户的 AD 用户名签发短效 JWT，Tableau 以该用户身份执行查询，RLS 完整生效。

**B. 问数入口**：Mulan 内建"问数"前端模块，独立路由 `/query`，对普通 BI 用户呈现干净聊天界面，不暴露任何运维功能。

### 1.3 已确认前提条件

- Tableau Server 2025.3.4，原生支持 Connected Apps，无降级风险
- Mulan 与 Tableau 共用 AD/LDAP，`auth_users.username` = Tableau 用户名，无需映射表
- 不部署外部 Open WebUI，前端在 Mulan 内部自建
- RLS 保真为硬性约束，任何场景禁止 fallback 到运维 PAT

---

## 2. 非目标范围

| 排除项 | 说明 |
|--------|------|
| 图表渲染 | 查询结果以数据表格返回，不在 Mulan 内渲染 Tableau 图表 |
| 查询历史 UI | MVP 不建查询日志管理页面，日志写入后端表即可 |
| 跨数据源联合查询 | 单次问数只查一个 Tableau 数据源 |
| 普通用户权限修改 | 用户不能自行选择或绑定 Tableau 身份 |
| 写操作 | 只读查询，不写入 Tableau（写操作属于 Spec 26 范畴） |
| Tableau 资产浏览/管理 | 问数模块不包含 Tableau 资产列表、健康扫描等运维功能 |
| 多租户 / SaaS | 项目级 Non-Goal |

---

## 3. 架构总览

### 3.1 新增模块与现有系统关系

```
┌──────────────────────────────────────────────────────────────────────┐
│                         Mulan 前端                                    │
│                                                                      │
│  现有（AppShellLayout + 侧边栏）          新增（QueryLayout）         │
│  ┌────────────────────────────┐          ┌─────────────────────┐     │
│  │ /dev /governance /assets  │          │  /query             │     │
│  │ /analytics /system        │          │  QueryPage          │     │
│  │ 面向运维和数据工程师       │          │  QueryChatPanel     │     │
│  └────────────────────────────┘          │  QueryMessageList   │     │
│                                          │  QueryInputBar      │     │
│                                          └────────┬────────────┘     │
└───────────────────────────────────────────────────┼──────────────────┘
                                                    │ POST /api/query/ask (SSE)
                                                    │ GET  /api/query/datasources
                                                    │ POST /api/query/sessions
┌───────────────────────────────────────────────────┼──────────────────┐
│                         Mulan 后端                 │                  │
│                                                    v                  │
│  ┌──────────────────┐    ┌────────────────────────────────────────┐  │
│  │ 现有路由层        │    │  新增：backend/app/api/query.py        │  │
│  │ search.py        │    │  HTTP/SSE 层，调用 query_service        │  │
│  │ ask_data.py      │    └──────────────────┬─────────────────────┘  │
│  │ tableau_mcp.py   │                       │                        │
│  └──────────────────┘                       v                        │
│                              ┌──────────────────────────────────┐    │
│                              │ 新增：backend/services/query/    │    │
│                              │ service.py  — 问数业务编排        │    │
│                              │ jwt_service.py — JWT 签发         │    │
│                              │ session_store.py — 对话 Session   │    │
│                              └──────┬────────────────┬───────────┘    │
│                                     │                │               │
│                       ┌─────────────┘                └──────────┐    │
│                       v                                         v    │
│  ┌─────────────────────────────┐      ┌────────────────────────────┐ │
│  │ services/tableau/           │      │ services/llm/service.py    │ │
│  │ mcp_client.py               │      │ (现有，purpose="query")     │ │
│  │ + JWT header 注入（新增）   │      └────────────────────────────┘ │
│  └──────────────┬──────────────┘                                     │
│                 │ MCP Streamable-HTTP + JWT                          │
└─────────────────┼────────────────────────────────────────────────────┘
                  v
    ┌─────────────────────────────┐
    │  @tableau/mcp-server        │
    │  接收 JWT → 转发给 Tableau  │
    │  Server → RLS 以用户身份生效│
    └─────────────────────────────┘
```

### 3.2 模块边界规则

| 模块 | 职责边界 | 禁止事项 |
|------|---------|---------|
| `backend/app/api/query.py` | HTTP 参数校验、身份提取、调用 `query_service` | 不直接调用 MCP Client、不签发 JWT |
| `backend/services/query/service.py` | 问数业务编排：意图解析 → JWT签发 → MCP 查询 → LLM 摘要 | 不依赖 FastAPI Request 对象 |
| `backend/services/query/jwt_service.py` | Connected Apps JWT 生成，持有密钥引用 | 不直接调用 MCP，不持有 DB Session |
| `backend/services/tableau/mcp_client.py` | 注入 JWT header 执行 MCP 查询（现有文件改造） | 不签发 JWT，不做 LLM 调用 |
| `frontend/src/pages/query/` | 问数页面，布局和 UI 组件 | 不直接调用 Tableau API，不挂载运维路由 |

---

## 4. Connected Apps JWT 方案

### 4.1 Tableau Connected Apps 机制

Tableau Connected Apps 是官方支持的服务端用户模拟方案（Server 2021.4+）。Mulan 以 Connected App 的 Client ID + 密钥对签发标准 JWT，Header 携带该 JWT 调用 MCP Server，MCP Server 将 JWT 转发给 Tableau Server 做身份验证，Tableau 以 JWT `sub` 字段（用户名）执行查询，RLS 完整生效。

### 4.2 JWT 结构

签名算法确认为 **HS256**（Tableau Connected Apps 官方仅支持 HMAC SHA-256，不支持 RS256）。

```
Header:
{
  "alg": "HS256",
  "typ": "JWT",
  "kid": "<connected_app_client_id>"      // 必填，Tableau 用于查找验证密钥
}

Payload:
{
  "iss": "<connected_app_client_id>",     // 发行方 = Client ID（必填）
  "sub": "<ad_username>",                // 目标用户的 Tableau/AD 用户名（核心，必填）
  "aud": "tableau",                      // 固定值（必填）
  "exp": <now + 600>,                    // 有效期最长 10 分钟，必须按需签发，不可复用（必填）
  "jti": "<uuid4>",                      // 唯一 ID，防重放（必填）
  "scp": ["tableau:datasources:read",    // 问数场景固定 scope（必填）
           "tableau:datasources:query"]
}
```

**scp 字段说明**：问数场景固定使用 `["tableau:datasources:read", "tableau:datasources:query"]`，数组格式。删除旧草稿中的 `tableau:views:read` 和 `tableau:content:read`（不适用于问数场景）。

**必填字段**：`iss`、`sub`、`aud`、`exp`、`jti`、`scp`，六字段缺一不可。

### 4.3 签发流程

```
谁签：Mulan 后端 jwt_service.py，在用户发起每次问数请求时签发
何时签：query_service.ask() 调用 MCP 前，每次查询独立签发，不复用
有效期：600 秒（10 分钟），覆盖单次查询最长耗时，到期自动失效
```

签发时序：

```
1. query.py API 层从 session cookie 提取当前用户（get_current_user）
2. 提取 current_user["username"]（即 AD 用户名）
3. 调用 jwt_service.issue(username=ad_username, connection_id=conn_id)
4. jwt_service 从 connected_app_secrets 表读取该连接的密钥（Fernet 解密）
5. 用 PyJWT 签发，返回 token 字符串
6. query_service 将 token 注入 MCP 请求 header
```

### 4.4 密钥存储方案

新增数据库表 `query_connected_app_secrets`（详见第 8 节）。

存储字段：`connection_id`（关联 Tableau 连接）、`client_id`（Connected App Client ID）、`secret_encrypted`（Fernet 加密的 Secret Value）、`is_active`。

加密使用现有 `get_tableau_crypto()` 工厂函数（环境变量 `TABLEAU_ENCRYPTION_KEY`），与 Tableau PAT 存储机制完全一致，复用已有密钥管理方案。

管理员通过 `POST /api/query/admin/connected-app-secrets` 配置，普通用户无权访问。

### 4.5 Token 刷新策略

Connected Apps JWT 设计为短效一次性令牌，不需要 refresh 机制：
- 每次问数请求独立签发新 JWT（`jti` 唯一，防重放）
- 10 分钟有效期：即使 MCP 查询超时（设 30s），JWT 有足够余量
- 用户长对话追问时，每条消息各自签发新 JWT，不跨请求复用

### 4.6 失败场景处理

| 失败场景 | Tableau 错误 | Mulan 处理 | 用户提示 |
|---------|-------------|-----------|---------|
| AD 账号在 Tableau 不存在 | 401/404 + "user not found" | 写入 `query_error_events` 告警表；返回错误 | "您的账号尚未完成 Tableau 身份绑定，请联系管理员" |
| 数据权限拒绝（RLS 过滤后空数据 or 403） | 403 Forbidden | 不 fallback，直接返回 | "您暂无该数据的访问权限，如需申请请联系 BI 团队" |
| JWT 过期（查询耗时 >10 分钟极端情况） | 401 Unauthorized | 自动重签 JWT 重试一次 | 透明（用户无感知）|
| Connected App 密钥未配置 | N/A | `jwt_service` 返回配置错误 | "问数服务尚未完成配置，请联系管理员" |
| MCP Server 不可达 | 连接超时 | 同现有 NLQ_006 映射逻辑 | "Tableau 查询服务暂时不可用，请稍后重试" |

**禁止行为**：任何场景下禁止 fallback 到运维 PAT，禁止将 JWT 签发错误暴露给前端（技术堆栈信息不外露）。

**告警机制**：Tableau 返回"用户不存在/身份无效"时，写入 `query_error_events` 表（`error_type='identity_not_found'`）；管理员面板通过 `GET /api/query/admin/error-events` 查看告警用户列表（AC-07-1/07-2 验收需求）。

---

## 5. 后端 API 设计

### 5.1 新增 Endpoints 概览

| Method | Path | 描述 | 权限 |
|--------|------|------|------|
| POST | `/api/query/ask` | 问数主接口（SSE 流式返回） | 登录用户 |
| GET | `/api/query/datasources` | 获取可用数据源列表（供前端选择器） | 登录用户 |
| POST | `/api/query/sessions` | 创建问数 Session（对话隔离） | 登录用户 |
| GET | `/api/query/sessions/{session_id}/messages` | 获取 Session 消息历史 | 登录用户（仅自己） |
| POST | `/api/query/admin/connected-app-secrets` | 配置 Connected App 密钥 | admin |
| GET | `/api/query/admin/connected-app-secrets` | 查看已配置密钥（不返回明文） | admin |
| DELETE | `/api/query/admin/connected-app-secrets/{id}` | 删除密钥配置 | admin |
| GET | `/api/query/admin/error-events` | 问数异常用户告警列表 | admin |

### 5.2 POST /api/query/ask

**Request Body**

```json
{
  "question": "上个月华东区的销售额是多少",
  "session_id": "uuid4",           // 可选；不传则每次独立对话
  "connection_id": 1               // 可选；不传则自动选第一个 active 连接
}
```

**Response**：`text/event-stream`，严格遵循现有 ask_data.py 的 SSE event 格式：

```
data: {"type":"metadata","sources_count":1,"top_sources":["销售数据源"]}\n\n
data: {"type":"token","content":"根据"}\n\n
data: {"type":"token","content":"查询结果"}\n\n
data: {"type":"done","answer":"...(完整摘要)...","trace_id":"uuid","data_table":[...]}\n\n
```

错误 event（不中断 SSE，以 error event 结束）：

```
data: {"type":"error","code":"QUERY_001","message":"您的账号尚未完成身份绑定"}\n\n
```

**错误码**（前缀 `QUERY_`，遵循 Spec 01 约定）：

| 错误码 | 含义 |
|--------|------|
| QUERY_001 | Tableau 身份未绑定（用户不存在） |
| QUERY_002 | 数据权限拒绝 |
| QUERY_003 | MCP 服务不可用 |
| QUERY_004 | Connected App 密钥未配置 |
| QUERY_005 | 问数 Session 不存在或无权访问 |

**Request 校验**：
- `question`：非空字符串，长度 1~1000
- `session_id`：有效 UUID 格式（如提供）
- `connection_id`：正整数（如提供）

**后端处理流程**（query.py 路由层）：

```
1. get_current_user() — 从 session cookie 提取用户，获取 username
2. 校验 request body
3. 调用 query_service.ask(username, question, session_id, connection_id)
4. 以 StreamingResponse 返回 SSE generator
```

### 5.3 GET /api/query/datasources

**Response**

```json
{
  "items": [
    {
      "connection_id": 1,
      "datasource_luid": "abc123",
      "name": "销售数据源",
      "site": "default"
    }
  ]
}
```

**数据源选择策略（已确认）**：采用用户手动选择。该接口用当前登录用户的 JWT 调用 Tableau API，仅返回该用户在 Tableau Server 上有权限访问的数据源，非全量数据源列表。前端必须显示数据源选择器（`QueryDataSourceSelector`），不做静默自动选择。

### 5.4 POST /api/query/sessions

**Request**

```json
{
  "title": "华东区销售分析"   // 可选，默认取首条消息前20字
}
```

**Response**

```json
{
  "session_id": "uuid4",
  "created_at": "2026-04-21T10:00:00Z"
}
```

### 5.5 GET /api/query/sessions/{session_id}/messages

**Response**

```json
{
  "session_id": "uuid4",
  "messages": [
    {
      "id": 1,
      "role": "user",
      "content": "上个月华东区的销售额是多少",
      "created_at": "2026-04-21T10:00:01Z"
    },
    {
      "id": 2,
      "role": "assistant",
      "content": "根据查询结果...",
      "data_table": [...],
      "created_at": "2026-04-21T10:00:05Z"
    }
  ]
}
```

鉴权：`session_id` 归属必须为当前用户，否则返回 403 + QUERY_005。

### 5.6 POST /api/query/admin/connected-app-secrets

**Request**

```json
{
  "connection_id": 1,
  "client_id": "my-connected-app-client-id",
  "secret_value": "raw-secret-value-from-tableau"
}
```

`secret_value` 在服务层 Fernet 加密后存储，接口不返回明文。

**Response**

```json
{
  "id": 1,
  "connection_id": 1,
  "client_id": "my-connected-app-client-id",
  "is_active": true,
  "created_at": "2026-04-21T10:00:00Z"
}
```

---

## 6. 前端模块设计

### 6.1 路由规划

问数模块挂载到独立布局，与 AppShellLayout（运维侧边栏）完全隔离：

```typescript
// frontend/src/router/config.tsx 新增

const QueryPage = lazy(() => import('../pages/query/page'));

// 在现有路由数组中新增（与 HomeLayout 块平级，不嵌套在 AppShellLayout 内）
{
  element: (
    <ProtectedRoute>       // 仅要求登录，无特定权限
      <QueryLayout />      // 新增：无侧边栏的全屏布局
    </ProtectedRoute>
  ),
  children: [
    { path: '/query', element: <QueryPage /> },
    { path: '/query/:sessionId', element: <QueryPage /> },
  ],
},
```

`QueryLayout` 不包含 AppSidebar，不包含运维导航。普通 BI 用户只拿到 `/query` 地址，无法通过 URL 访问 `/dev`、`/governance`、`/system` 等路由（后端 API 层各自有权限守卫）。

### 6.2 核心组件树

```
QueryLayout                          // frontend/src/components/layout/QueryLayout.tsx
  ├── QueryHeader                    // 顶栏：Logo + 用户头像 + 退出（无运维菜单）
  └── QueryPage                      // frontend/src/pages/query/page.tsx
        ├── QuerySessionSidebar      // 左侧：对话历史列表（可折叠）
        │     └── QuerySessionItem   // 单条 Session 条目
        ├── QueryChatPanel           // 中间主区：当前对话
        │     ├── QueryMessageList   // 消息流滚动列表
        │     │     ├── UserMessage  // 用户气泡
        │     │     └── AssistantMessage // AI 回复（含 DataTable 子组件）
        │     └── QueryInputBar      // 底部输入框
        └── QueryDataSourceSelector  // 右上角数据源下拉（可选，默认隐藏）
```

**组件职责划分**：

| 组件 | 文件 | 职责 |
|------|------|------|
| `QueryLayout` | `components/layout/QueryLayout.tsx` | 纯布局，无业务状态 |
| `QueryHeader` | `components/layout/QueryHeader.tsx` | 纯 UI，只接收用户信息 props |
| `QueryPage` | `pages/query/page.tsx` | 页面容器，组合 hooks，不含业务逻辑 |
| `QueryChatPanel` | `pages/query/components/QueryChatPanel.tsx` | 布局分区组件 |
| `QueryMessageList` | `pages/query/components/QueryMessageList.tsx` | 纯 UI，渲染 messages 数组 |
| `QueryInputBar` | `pages/query/components/QueryInputBar.tsx` | 纯 UI，受控输入 + 发送按钮 |
| `AssistantMessage` | `pages/query/components/AssistantMessage.tsx` | 渲染 AI 回复 + DataTable |
| `DataTable` | `components/feature/DataTable.tsx` | 通用数据表格（可复用于其他模块） |

### 6.3 关键状态管理

业务状态下沉到自定义 hooks，页面组件不持有业务 state：

```typescript
// frontend/src/pages/query/hooks/useQuerySession.ts
// 职责：Session 生命周期、消息列表、追问上下文

interface QueryMessage {
  id: string;
  role: 'user' | 'assistant';
  content: string;
  dataTable?: Record<string, unknown>[];
  isStreaming?: boolean;
  errorCode?: string;
}

interface UseQuerySessionReturn {
  messages: QueryMessage[];
  isLoading: boolean;
  sessionId: string | null;
  send: (question: string) => Promise<void>;
  createSession: () => Promise<void>;
  clearSession: () => void;
}
```

```typescript
// frontend/src/pages/query/hooks/useQueryDatasources.ts
// 职责：数据源列表加载、当前选中数据源

interface UseQueryDatasourcesReturn {
  datasources: QueryDatasource[];
  selectedConnectionId: number | null;
  setSelectedConnectionId: (id: number) => void;
}
```

**SSE 处理**：复用现有 `frontend/src/hooks/useStreamingChat.ts` 的模式（ask_data.py 已有完整实现参考），在 `useQuerySession.send()` 中通过 `EventSource` 或 `fetch` + `ReadableStream` 消费 SSE event，逐 token 更新 `messages` 状态。

**对话上下文**：`session_id` 随每次请求发送给后端，后端 `query_service` 在生成 LLM prompt 时从 `query_messages` 表读取最近 N 条历史，拼接为多轮对话上下文（不在前端存储原始 SQL 或 VizQL，只存用户可读消息）。

### 6.4 页面 UX 要点

- 全屏布局，无侧边栏压缩空间，对话区居中最大宽度 `max-w-3xl`
- 输入框固定底部，消息区滚动
- Streaming token 逐字显示（伪流式，与现有 ask_data 一致）
- 数据表格内联展示在 AI 回复气泡内，超过 10 行显示"展开"
- 无数据权限时，以黄色 Warning 样式展示错误提示，不显示技术信息

---

## 7. 问数链路时序图

### 7.1 完整链路（从用户输入到结果返回）

```
用户浏览器                 Mulan 前端              Mulan 后端              Tableau MCP Server   Tableau Server
     │                       │                       │                           │                    │
     │ 输入问题 + 点击发送    │                       │                           │                    │
     │──────────────────────>│                       │                           │                    │
     │                       │ POST /api/query/ask   │                           │                    │
     │                       │ {question, session_id}│                           │                    │
     │                       │──────────────────────>│                           │                    │
     │                       │                       │ 1. get_current_user()     │                    │
     │                       │                       │    提取 username (AD账号) │                    │
     │                       │                       │                           │                    │
     │                       │                       │ 2. 读取 connected_app_    │                    │
     │                       │                       │    secrets（Fernet解密）  │                    │
     │                       │                       │                           │                    │
     │                       │                       │ 3. jwt_service.issue()   │                    │
     │                       │                       │    签发 JWT               │                    │
     │                       │                       │    sub=<ad_username>      │                    │
     │                       │                       │    exp=now+600            │                    │
     │                       │                       │    jti=<uuid>             │                    │
     │                       │                       │                           │                    │
     │                       │                       │ 4. nlq_service 意图分类   │                    │
     │                       │                       │    + 数据源路由            │                    │
     │                       │                       │    + 字段准备              │                    │
     │                       │                       │                           │                    │
     │                       │                       │ 5. mcp_client.query()     │                    │
     │                       │                       │    Header:                │                    │
     │                       │                       │    Authorization: Bearer <JWT>                 │
     │                       │                       │──────────────────────────>│                    │
     │                       │                       │                           │ 6. 转发请求 + JWT  │
     │                       │                       │                           │───────────────────>│
     │                       │                       │                           │                    │ 7. 验证 JWT
     │                       │                       │                           │                    │    (kid → client_id)
     │                       │                       │                           │                    │    以 sub 用户身份
     │                       │                       │                           │                    │    执行 VizQL 查询
     │                       │                       │                           │                    │    RLS 生效
     │                       │                       │                           │<───────────────────│
     │                       │                       │<──────────────────────────│ 8. 返回查询结果    │
     │                       │                       │                           │                    │
     │                       │                       │ 9. llm_service.complete() │                    │
     │                       │                       │    purpose="query"         │                    │
     │                       │                       │    生成自然语言摘要         │                    │
     │                       │                       │                           │                    │
     │                       │                       │ 10. 写入 query_messages 表│                    │
     │                       │                       │     写入审计日志           │                    │
     │                       │                       │                           │                    │
     │                       │<──────────────────────│ SSE events (token by token)                   │
     │ 逐字显示回复 + 数据表格 │                       │                           │                    │
     │<──────────────────────│                       │                           │                    │
```

### 7.2 JWT 签发在链路中的位置

JWT 在步骤 3 签发，在步骤 5 注入 MCP 请求 header。`mcp_client.py` 接收 `jwt_token` 参数（字符串），自身不持有 Connected App 密钥，密钥只存在于 `jwt_service.py` 的调用栈中。

### 7.3 身份验证失败分支

```
步骤 6/7 Tableau 返回 401（用户不存在）：
  MCP Server → mcp_client 收到 error
  → query_service 识别错误类型为 identity_not_found
  → 写入 query_error_events 告警表
  → 不重试，不 fallback
  → SSE 返回 {"type":"error","code":"QUERY_001","message":"..."}
```

---

## 8. 数据库变更

### 8.1 新增表：`query_connected_app_secrets`

Connected App 密钥配置表，每个 Tableau 连接最多一条 active 记录。

```sql
CREATE TABLE query_connected_app_secrets (
    id               SERIAL PRIMARY KEY,
    connection_id    INTEGER NOT NULL REFERENCES tableau_connections(id) ON DELETE CASCADE,
    client_id        VARCHAR(256) NOT NULL,         -- Tableau Connected App Client ID
    secret_encrypted TEXT NOT NULL,                -- Fernet 加密的 Secret Value
    is_active        BOOLEAN NOT NULL DEFAULT TRUE,
    created_by       INTEGER REFERENCES auth_users(id),
    created_at       TIMESTAMP NOT NULL DEFAULT now(),
    updated_at       TIMESTAMP
);

CREATE UNIQUE INDEX uq_connected_app_active
    ON query_connected_app_secrets(connection_id)
    WHERE is_active = TRUE;

CREATE INDEX idx_connected_app_connection
    ON query_connected_app_secrets(connection_id);
```

### 8.2 新增表：`query_sessions`

用户问数对话 Session，支持多轮对话上下文追踪。

```sql
CREATE TABLE query_sessions (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id     INTEGER NOT NULL REFERENCES auth_users(id),
    title       VARCHAR(128),
    created_at  TIMESTAMP NOT NULL DEFAULT now(),
    updated_at  TIMESTAMP,
    is_active   BOOLEAN NOT NULL DEFAULT TRUE
);

CREATE INDEX idx_query_sessions_user ON query_sessions(user_id, created_at DESC);
```

### 8.3 新增表：`query_messages`

对话消息记录，支持多轮追问上下文读取。

```sql
CREATE TABLE query_messages (
    id              SERIAL PRIMARY KEY,
    session_id      UUID NOT NULL REFERENCES query_sessions(id) ON DELETE CASCADE,
    role            VARCHAR(16) NOT NULL CHECK (role IN ('user', 'assistant')),
    content         TEXT NOT NULL,                  -- 消息文本
    data_table      JSONB,                          -- assistant 回复时的结构化数据
    connection_id   INTEGER REFERENCES tableau_connections(id),
    datasource_luid VARCHAR(256),                  -- 查询命中的数据源 LUID
    query_context   JSONB,                         -- 预留 P2：追问上下文（与 Spec 22 C7 对齐）
    created_at      TIMESTAMP NOT NULL DEFAULT now()
);

CREATE INDEX idx_query_messages_session ON query_messages(session_id, created_at);
```

### 8.4 新增表：`query_error_events`

Tableau 身份问题告警表，管理员监控用。

```sql
CREATE TABLE query_error_events (
    id           SERIAL PRIMARY KEY,
    user_id      INTEGER REFERENCES auth_users(id),
    username     VARCHAR(64) NOT NULL,              -- 冗余存储，防止用户删除后丢失
    error_type   VARCHAR(64) NOT NULL,              -- 'identity_not_found' | 'permission_denied'
    connection_id INTEGER REFERENCES tableau_connections(id),
    raw_error    TEXT,                              -- Tableau 原始错误信息（脱敏后存储）
    resolved     BOOLEAN NOT NULL DEFAULT FALSE,
    created_at   TIMESTAMP NOT NULL DEFAULT now()
);

CREATE INDEX idx_query_error_events_unresolved
    ON query_error_events(resolved, created_at DESC)
    WHERE resolved = FALSE;
```

### 8.5 Alembic 迁移说明

新建迁移脚本：`backend/alembic/versions/add_query_interface_tables.py`

迁移要点：
- 4 张表全部新建，无修改现有表，零破坏性
- `gen_random_uuid()` 需要 PostgreSQL `pgcrypto` 扩展（现有库应已开启，迁移脚本中加 `CREATE EXTENSION IF NOT EXISTS pgcrypto`）
- 无需数据回填
- 回滚（downgrade）直接 `DROP TABLE`，顺序：`query_messages` → `query_sessions` → `query_error_events` → `query_connected_app_secrets`

---

## 9. 任务拆分

### 任务优先级说明

- **P0**：RLS 修复核心链路，必须在普通用户上线前完成
- **P1**：前端问数模块，普通用户可用的最小 MVP
- **P2**：体验增强，可后续迭代

---

### T-01：Connected App 密钥存储 + JWT 签发服务（P0）

**涉及文件（新增）**：
- `backend/services/query/__init__.py`
- `backend/services/query/jwt_service.py`
- `backend/alembic/versions/add_query_interface_tables.py`

**涉及文件（现有，不修改结构）**：
- `backend/app/core/crypto.py`（复用 `get_tableau_crypto()`）

**实现要点**：
- `ConnectedAppSecretsDatabase`：CRUD，读取时自动 Fernet 解密
- `JWTService.issue(username, connection_id) -> str`：签发符合 Tableau Connected Apps 规范的 JWT（PyJWT HS256，kid/iss/sub/exp/jti/aud/scp 完整）
- 依赖注入：`JWTService` 不持有全局单例，由 `query_service` 实例化调用

**验收标准**：
- `jwt_service.issue("test_user", conn_id=1)` 返回合法 JWT，PyJWT decode 可验证字段完整性
- `kid` 字段与 `client_id` 一致
- 相同参数两次调用，`jti` 不同（不复用）
- `sub` 字段精确等于传入的 `username`

---

### T-02：问数业务服务层（P0）

**涉及文件（新增）**：
- `backend/services/query/service.py`

**涉及文件（现有，不修改接口）**：
- `backend/services/tableau/mcp_client.py`（新增 `jwt_token` 参数注入，详见 T-03）
- `backend/services/llm/service.py`（新增 `purpose="query"` 调用，无签名变更）

**实现要点**：
`QueryService.ask(username, question, session_id, connection_id)` 编排流程：
1. 调用 `jwt_service.issue(username, connection_id)` 获取 JWT
2. 调用现有 `nlq_service` 做意图分类和字段准备（复用现有 `classify_intent`、`route_datasource`）
3. 调用 `mcp_client.query_datasource(..., jwt_token=token)` 执行 MCP 查询
4. 异常分支：识别 Tableau 401/identity_not_found，写入 `query_error_events`，抛出 `QueryError`
5. 调用 `llm_service.complete_for_semantic(purpose="query")` 生成自然语言摘要
6. 写入 `query_messages` 表

**验收标准**：
- 后端日志中每次查询可确认 JWT `sub` 字段等于当前 AD 用户名
- 同一请求中 JWT 签发和 MCP 查询耗时 < 200ms（纯签发时间）
- Tableau 返回 401 时，`query_error_events` 新增一条记录，不触发 fallback

---

### T-03：mcp_client.py 注入 JWT Header（P0）

**涉及文件（现有，改造）**：
- `backend/services/tableau/mcp_client.py`

**改造范围（最小改动）**：
- `TableauMCPClient.query_datasource()` 新增可选参数 `jwt_token: Optional[str] = None`
- 当 `jwt_token` 有值时，MCP 请求 Header 中添加 `Authorization: Bearer <jwt_token>`，覆盖现有的 PAT-based token header
- 当 `jwt_token` 为 None 时，行为完全不变（向后兼容，现有运维问数链路不受影响）

**并发修改风险**：此文件同时被 Spec 22（per-site session 映射）改造，两个改动必须在同一 PR 中合并，或明确串行顺序（Spec 22 先，本 Spec T-03 后）。

**验收标准**：
- 传入 `jwt_token` 时，Wireshark 或日志可确认 HTTP Header 携带该值
- 不传 `jwt_token` 时，现有 PAT header 不变，运维问数链路回归测试通过

---

### T-04：后端 API 路由层（P0）

**涉及文件（新增）**：
- `backend/app/api/query.py`

**涉及文件（现有，修改）**：
- `backend/app/main.py`（注册新路由 `app.include_router(query.router, prefix="/api/query")`）

**实现要点**：
- `POST /api/query/ask`：SSE StreamingResponse，调用 `query_service.ask()`，SSE event 格式对齐现有 ask_data.py 协议
- `GET /api/query/datasources`：调用现有 `TableauConnectionDatabase` 获取 active 连接，返回数据源列表
- `POST /api/query/sessions`、`GET /api/query/sessions/{id}/messages`：CRUD 调用 `query_service` session 管理方法
- 管理员接口 4 个：`require_role("admin")` 依赖注入（复用现有 `get_current_user` + role 校验模式）

**验收标准**：
- `POST /api/query/ask` SSE 响应格式通过前端 EventSource 解析（与 ask_data.py 格式完全一致）
- 普通用户访问管理员接口返回 403
- 未登录用户访问任意接口返回 401

---

### T-05：Alembic 数据库迁移（P0）

**涉及文件（新增）**：
- `backend/alembic/versions/add_query_interface_tables.py`

**实现要点**：
- `upgrade()`：按依赖顺序建 4 张表 + 索引（`query_connected_app_secrets` → `query_sessions` → `query_messages` → `query_error_events`）
- `downgrade()`：反序 DROP
- 迁移脚本首行加 `op.execute("CREATE EXTENSION IF NOT EXISTS pgcrypto")`

**验收标准**：
- `alembic upgrade head` 在空库执行成功，无报错
- `alembic downgrade -1` 后 4 张表均已删除
- `alembic upgrade head` 二次执行幂等（无报错）

---

### T-06：前端问数路由 + 布局（P1）

**涉及文件（新增）**：
- `frontend/src/components/layout/QueryLayout.tsx`
- `frontend/src/components/layout/QueryHeader.tsx`
- `frontend/src/pages/query/page.tsx`

**涉及文件（现有，改造）**：
- `frontend/src/router/config.tsx`（新增 `/query` 和 `/query/:sessionId` 路由）

**实现要点**：
- `QueryLayout`：无侧边栏，全屏，flex-column
- `QueryHeader`：Logo（可点击跳回 `/`）+ 用户名 + 退出按钮，不含任何运维导航
- `/query` 挂载在独立 layout 下（不嵌套在 AppShellLayout 内）
- `ProtectedRoute` 只校验登录态，无特定 permission 要求

**验收标准**：
- 访问 `/query` 不出现 AppSidebar
- 未登录访问 `/query` 重定向到 `/login`
- 访问 `/dev/ddl-validator` 等管理路由，QueryHeader 不出现

---

### T-07：前端问数核心组件（P1）

**涉及文件（新增）**：
- `frontend/src/pages/query/components/QueryChatPanel.tsx`
- `frontend/src/pages/query/components/QueryMessageList.tsx`
- `frontend/src/pages/query/components/QueryInputBar.tsx`
- `frontend/src/pages/query/components/AssistantMessage.tsx`
- `frontend/src/pages/query/components/QuerySessionSidebar.tsx`
- `frontend/src/components/feature/DataTable.tsx`（通用，可复用）

**实现要点**：
- `QueryMessageList`：纯展示，接收 `messages: QueryMessage[]` prop，自动滚动到底部
- `QueryInputBar`：受控 textarea（支持 Shift+Enter 换行，Enter 发送），禁用态（isLoading 时）
- `AssistantMessage`：Streaming 时显示光标动画，`dataTable` 有值时渲染内联表格
- `DataTable`：超过 10 行显示「展开」按钮，表格支持横向滚动

**验收标准**：
- 发送消息后 InputBar 禁用，SSE 完成后恢复
- dataTable 数据正确渲染，中文列名不截断
- 错误消息（QUERY_001/002）以 Warning 样式展示，不显示 error code 原文

---

### T-08：前端问数 Hooks（P1）

**涉及文件（新增）**：
- `frontend/src/pages/query/hooks/useQuerySession.ts`
- `frontend/src/pages/query/hooks/useQueryDatasources.ts`
- `frontend/src/api/query.ts`（API 调用层）

**实现要点**：
- `useQuerySession.send(question)` 内部用 `fetch` + `ReadableStream` 消费 SSE（对齐现有 ask_data 前端实现）
- SSE `token` event 实时 append 到当前 assistant message 的 `content`
- SSE `done` event 时更新 `dataTable`，标记 `isStreaming=false`
- SSE `error` event 时设置 `errorCode`，触发错误展示
- `useQueryDatasources`：页面挂载时自动调用 `GET /api/query/datasources`，默认选第一个

**验收标准**：
- Streaming token 可见逐字出现，P90 首 token < 8 秒
- 网络中断时，错误提示出现在对话流中（不是全页报错）
- 切换 Session 时消息列表正确切换

---

### T-09：管理员配置 Connected App 密钥 UI（P1）

**涉及文件（新增或改造）**：
- `frontend/src/pages/system/mcp-configs/page.tsx`（在现有 MCP 配置页新增 Connected App 密钥配置区块，而非新建独立页）

**实现要点**：
- 在现有 `McpConfigsPage` 中，对每个 Tableau 连接新增「Connected App 配置」折叠面板
- 输入字段：Client ID、Secret Value（password input，不回显）
- 保存后显示「已配置」状态，不显示 secret 内容
- 管理员 only（非 admin 不渲染该区块）

**验收标准**：
- 配置保存后，调用 `POST /api/query/ask` 不再报 QUERY_004
- 非管理员登录，Connected App 配置区块不可见

---

### T-10：告警事件管理员查看（P1）

**涉及文件（新增或改造）**：
- `frontend/src/pages/admin/user-management/page.tsx` 或独立 tab（具体位置由 UI 评审确认）

**实现要点**：
- `GET /api/query/admin/error-events` 返回未解决身份告警列表
- 列显示：用户名、错误类型、首次发生时间、状态（未处理/已处理）
- 管理员可标记为「已处理」（`PATCH /api/query/admin/error-events/{id}/resolve`）

**验收标准**：
- AC-07-1：用户首次问数身份失败后，admin 在告警列表看到该用户
- AC-07-2：管理员可在列表中标记处理，状态更新持久化

---

## 10. 验收标准

对应 PRD 第六节，按 US 编号列出完整验收条件：

**US-01 / AC-01**

- AC-01-1：用户在 `/query` 页面输入自然语言，P90 首 SSE token < 8 秒（不含 MCP 查询时间）
- AC-01-2：SSE `done` event 包含 `answer`（自然语言摘要）和 `data_table`（结构化数据）
- AC-01-3：后端日志（`query_messages` 表 + Python 日志）可确认查询使用了目标用户 JWT，`sub` 字段与 AD 用户名一致

**US-02 / AC-02（RLS 验收，必须用真实 Tableau 账号测试）**

- AC-02-1：账号 A（仅华东区权限）问"全国销售额"，返回数据仅含华东区
- AC-02-2：运维账号问同一问题，返回全国数据（两次结果不同，证明 RLS 生效）
- AC-02-3：账号 B（仅华北区权限）问同一问题，返回数据仅含华北区

**US-03 / AC-03**

- AC-03-1：同一 Session 追问"按月份拆分"，LLM prompt 中包含前一轮对话上下文
- AC-03-2：追问请求的 JWT `sub` 字段与首次问数 JWT 一致（同一用户，不漂移）

**US-04 / AC-04**

- AC-04-1：查询无权数据，前端显示"您暂无该数据的访问权限，如需申请请联系 BI 团队"，不显示 HTTP 状态码或堆栈
- AC-04-2：Tableau 端账号不存在，前端显示"您的账号尚未完成 Tableau 身份绑定，请联系管理员"

**US-05 / AC-05**

- AC-05-1：进入 `/query` 后，页面不出现"连接管理"、"资产同步"、"用户管理"等运维导航元素
- AC-05-2：`/query` 路由不嵌套在 AppShellLayout 内，AppSidebar DOM 节点不存在

**US-06 / AC-06**

- AC-06-1：用户登录 Mulan 后直接访问 `/query` 问数，系统自动以其 AD 用户名签发 JWT，无需任何额外配置步骤
- AC-06-2：`query_messages` 表中 `datasource_luid` 字段有值（问数链路完整走通）

**US-07 / AC-07**

- AC-07-1：模拟 Tableau 返回 identity_not_found，`query_error_events` 表新增记录
- AC-07-2：管理员访问 `/api/query/admin/error-events`，可看到该用户条目

---

## 11. 测试计划

### 11.1 单元测试

| 测试目标 | 测试文件 | 测试内容 |
|---------|---------|---------|
| `JWTService.issue()` | `backend/tests/unit/test_query_jwt_service.py` | JWT 字段完整性（kid/iss/sub/exp/jti）、jti 唯一性、过期时间 ±5s、密钥不存在时抛 QueryError |
| `ConnectedAppSecretsDatabase` | `backend/tests/unit/test_query_secrets_db.py` | 加密存储、解密读取、唯一 active 约束 |
| `QueryService.ask()` mock 测试 | `backend/tests/unit/test_query_service.py` | mock mcp_client 返回正常数据；mock 返回 401 触发 error_event 写入；mock 返回数据后 LLM 摘要生成 |
| `mcp_client.query_datasource()` JWT 注入 | `backend/tests/unit/test_mcp_client_jwt.py` | 传 jwt_token 时 header 正确；不传时 header 不变 |

### 11.2 集成测试

| 测试目标 | 环境要求 | 内容 |
|---------|---------|------|
| RLS 保真验证 | Tableau Server 2025.3.4 测试账号 A/B | 按 AC-02 三条逐一验证，人工记录截图 |
| SSE 链路端到端 | 本地开发环境 + mock Tableau | 从前端发送问题到收到 done event 全链路走通 |
| JWT 过期重试 | 单元测试 mock | 伪造过期 JWT，确认自动重签逻辑 |
| 告警写入 | 本地 PostgreSQL | Tableau mock 返回 401，确认 query_error_events 记录写入 |

### 11.3 回归测试

以下现有功能不得因本次改动受影响：

- 现有 `POST /api/ask-data` 接口（ask_data.py）行为不变
- 现有 `POST /api/search/query` 接口（search.py）行为不变
- `TableauMCPClient` 不传 jwt_token 时（运维场景）行为完全不变
- 现有路由 `/dev`、`/governance`、`/system` 等访问正常

### 11.4 性能基线

在 200 并发用户场景下（PRD P2 指标）：
- JWT 签发耗时 < 10ms（纯 PyJWT HS256，无 I/O）
- `query_connected_app_secrets` 读取走 `connection_id` 索引，< 5ms
- 签发频率：每用户每次问数一个 JWT，不存在 Token 池压力

---

## 12. 风险与约束

### 12.1 技术风险

| 风险 | 严重程度 | 概率 | 缓解措施 |
|------|---------|------|---------|
| AD 账号已在 Mulan 存在，但 Tableau Server 未完成同步（新员工入职延迟） | 高（用户完全无法问数） | 中 | 提供清晰用户提示 + 管理员告警；上线前与 IT 确认 AD→Tableau 同步周期 |
| JWT `scp` 字段与 Tableau Connected Apps 要求的 scope 不匹配 | 高（所有用户问数失败） | 低 | 开发前查阅 Tableau 2025.3.4 Connected Apps 文档确认 scope 枚举值；集成测试必须在真实 Server 上跑通后才能上线 |
| Tableau Connected Apps 密钥轮换后遗忘更新 Mulan 配置 | 高（问数服务中断） | 低 | 管理员界面展示密钥最后更新时间；未来可增加定期健康检查（本 Spec P2） |
| 高并发场景 JWT 签发 + MCP 调用的端到端延迟超出 8 秒 P90 指标 | 中 | 低 | JWT 签发无 I/O，瓶颈在 MCP/LLM；现有 ask_data.py 已验证链路，延迟基线可参考 |
| `mcp_client.py` 与 Spec 22 并发改造冲突 | 中（合并冲突） | 高 | 明确串行合并顺序：Spec 22 per-site session 改造先合并，本 Spec T-03 JWT 注入后合并；两个改动在同一文件，绝对不允许并行开发 |

### 12.2 安全约束（不可违反）

1. **密钥不出服务端**：Connected App Secret 只存在于 PostgreSQL（Fernet 加密）和 `jwt_service` 调用栈。API 响应不返回 secret 明文，日志不打印 secret。
2. **JWT 不下发客户端**：JWT 只在 Mulan 后端内部传递（service → mcp_client），不通过 API 暴露给前端或用户。
3. **禁止 PAT fallback**：`QueryService.ask()` 中任何错误分支均不降级为运维 PAT。代码 review 必须包含此检查项。
4. **JWT 最长有效期 10 分钟**：`exp = now + 600`，不得配置为更长时间。
5. **Session 隔离**：`GET /api/query/sessions/{id}/messages` 必须校验 session 归属用户，防止横向越权读取他人对话。

### 12.3 并发修改互斥声明

以下文件在本 Spec 开发期间，禁止其他 Spec 的 coder 同时修改：

| 文件 | 互斥原因 |
|------|---------|
| `backend/services/tableau/mcp_client.py` | T-03 改造 + Spec 22 per-site session 改造同时涉及此文件，必须串行 |
| `frontend/src/router/config.tsx` | T-06 新增 `/query` 路由，与任何其他路由改动串行合并 |
| `backend/app/main.py` | T-04 注册新路由，避免合并冲突 |

### 12.4 P0 开发启动前必须人工确认的决策点

以下 3 个问题**必须在编码开始前明确**，否则会导致返工：

**[P0-D1] Connected App scope 枚举值（已确认）**：签名算法为 HS256，`scp` 字段数组格式，问数场景固定为 `["tableau:datasources:read", "tableau:datasources:query"]`。exp 最长 10 分钟，必须按需签发，不可复用。必填字段：`iss`、`sub`、`aud`、`exp`、`jti`、`scp`。详见第 4.2 节。

**[P0-D2] 默认数据源策略（已确认）**：用户手动选择数据源。`GET /api/query/datasources` 用当前用户 JWT 调用 Tableau API，仅返回该用户有权限的数据源。`QueryDataSourceSelector` 组件必须显示，不做静默自动选择。详见第 5.3 节。

**[P0-D3] 问数权限设计（已确认）**：仅登录即可访问 `POST /api/query/ask`，不新增独立 `query` permission。所有已认证用户均可使用。`Auth` 模块的 `ALL_PERMISSIONS` 和 `ROLE_DEFAULT_PERMISSIONS` 不做修改。后续如需细粒度控制再扩展。详见第 5.1 节权限列。

---

*文档结束。下一步：P0-D1/D2/D3 确认后，任务 T-01 → T-05 可并行开工（T-03 与 Spec 22 串行）；T-06 → T-10 在 T-04 API 上线后开工。*

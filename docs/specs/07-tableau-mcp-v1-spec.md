# Tableau MCP V1 集成技术规格书

| 版本 | 日期 | 状态 |
|------|------|------|
| v1.0 | 2026-04-03 | Draft |
| v1.1 | 2026-04-06 | Draft |

---

## 目录

1. [概述](#1-概述)
2. [数据模型](#2-数据模型)
3. [API 设计](#3-api-设计)
4. [业务逻辑](#4-业务逻辑)
5. [错误码](#5-错误码)
6. [安全](#6-安全)
7. [集成点](#7-集成点)
8. [时序图](#8-时序图)
9. [测试策略](#9-测试策略)
10. [开放问题](#10-开放问题)

---

## 1. 概述

### 1.1 背景

Mulan BI Platform 需要与 Tableau Server/Cloud 深度集成，实现 BI 资产的自动发现、元数据同步、健康度评分和 AI 增强解读。本模块通过 Tableau REST API 和 TSC（tableauserverclient）两种模式连接 Tableau，将工作簿、视图、仪表板、数据源等资产元数据同步至本地 PostgreSQL，并在此基础上提供健康评分、AI 摘要和深度解读能力。

### 1.2 设计目标

- **双模式连接**：支持 MCP（原生 REST API）和 TSC（tableauserverclient 库）两种连接方式
- **全量资产同步**：自动发现并同步 workbooks、views、dashboards、datasources 及其关联关系
- **增量 UPSERT**：基于 `(connection_id, tableau_id)` 唯一键的幂等同步，支持软删除
- **定时调度**：Celery Beat 每 60 秒轮询，按连接配置的同步间隔触发异步同步任务
- **健康度治理**：7 因子加权评分体系，量化资产元数据质量
- **AI 增强**：LLM 驱动的资产解读和字段语义标注

### 1.3 模块边界

```
┌─────────────────────────────────────────────────────┐
│                    Frontend (React)                   │
│          Tableau 资产管理页面 / 健康看板                │
└──────────────────────┬──────────────────────────────┘
                       │ HTTP /api/tableau/*
┌──────────────────────▼──────────────────────────────┐
│              FastAPI Router (tableau.py)              │
│         连接管理 │ 资产浏览 │ 健康评分 │ AI 解读       │
└──────┬───────────┬──────────┬───────────┬───────────┘
       │           │          │           │
┌──────▼──┐ ┌──────▼──┐ ┌────▼────┐ ┌────▼────┐
│ Models  │ │  Sync   │ │ Health  │ │  LLM    │
│ (ORM)   │ │ Service │ │ Engine  │ │ Service │
└─────────┘ └────┬────┘ └─────────┘ └─────────┘
                 │
        ┌────────▼────────┐
        │ Tableau Server   │
        │ REST API / TSC   │
        └─────────────────┘
```

---

## 2. 数据模型

### 2.1 ER 关系图

```
┌─────────────────────────┐
│  tableau_connections     │
│─────────────────────────│
│  id (PK)                │
│  name                   │
│  server_url             │
│  site                   │
│  api_version            │
│  connection_type        │──── 'mcp' | 'tsc'
│  token_name             │
│  token_encrypted        │──── Fernet 加密
│  owner_id               │
│  is_active              │
│  auto_sync_enabled      │
│  sync_interval_hours    │
│  sync_status            │──── 'idle' | 'running' | 'failed'
│  last_sync_at           │
│  last_sync_duration_sec │
│  last_test_at           │
│  last_test_success      │
│  last_test_message      │
│  created_at             │
│  updated_at             │
└──────────┬──────────────┘
           │ 1:N
           │
┌──────────▼──────────────┐       ┌──────────────────────────┐
│  tableau_assets          │       │  tableau_sync_logs        │
│──────────────────────────│       │───────────────────────────│
│  id (PK)                 │       │  id (PK)                  │
│  connection_id (FK)      │       │  connection_id (FK)       │
│  asset_type              │       │  trigger_type             │
│  tableau_id              │       │  started_at               │
│  name                    │       │  finished_at              │
│  project_name            │       │  status                   │
│  description             │       │  workbooks_synced         │
│  owner_name              │       │  views_synced             │
│  thumbnail_url           │       │  dashboards_synced        │
│  content_url             │       │  datasources_synced       │
│  raw_metadata (JSONB)    │       │  assets_deleted           │
│  is_deleted              │       │  error_message            │
│  synced_at               │       │  details (JSONB)          │
│  parent_workbook_id      │       └───────────────────────────┘
│  parent_workbook_name    │
│  tags (JSONB)            │
│  sheet_type              │
│  created_on_server       │
│  updated_on_server       │
│  view_count              │
│  ai_summary              │
│  ai_summary_generated_at │
│  ai_summary_error        │
│  ai_explain              │
│  ai_explain_at           │
│  health_score            │
│  health_details (JSONB)  │
│  field_count             │
│  is_certified            │
└──────┬──────┬────────────┘
       │      │
       │ 1:N  │ 1:N
       │      │
┌──────▼──────────────────┐  ┌──────▼────────────────────────┐
│ tableau_asset_datasources│  │ tableau_datasource_fields      │
│─────────────────────────│  │────────────────────────────────│
│ id (PK)                 │  │ id (PK)                        │
│ asset_id (FK)           │  │ asset_id (FK)                  │
│ datasource_name         │  │ datasource_luid                │
│ datasource_type         │  │ field_name                     │
└─────────────────────────┘  │ field_caption                  │
                             │ data_type                      │
                             │ role                           │
                             │ description                    │
                             │ formula                        │
                             │ aggregation                    │
                             │ is_calculated                  │
                             │ metadata_json (JSONB)          │
                             │ fetched_at                     │
                             │ ai_caption                     │
                             │ ai_description                 │
                             │ ai_role                        │
                             │ ai_confidence                  │
                             │ ai_annotated_at                │
                             └─────────────┬──────────────────┘
                                           │ 1:1 (Spec 12)
                                           │ (field_registry_id → id)
                                           ▼
                             ┌──────────────────────────────────────────┐
                             │  tableau_field_semantics (Spec 12)         │
                             │───────────────────────────────────────────│
                             │  id (PK)                                  │
                             │  field_registry_id (FK) ────────────────▶│ ← 表边界：Spec 07 写入 asset_id/field_name
                             │  connection_id (FK)                        │   Spec 12 负责 sensitivity_level / canonical_name
                             │  sensitivity_level  │──── low / medium /    │
                             │                    │       high / confidential │
                             │  canonical_name                              │
                             │  semantic_tags (JSONB)                       │
                             │  annotated_at                                │
                             │  annotated_by                                │
                             └──────────────────────────────────────────┘
```

> **表边界说明（Spec 07 ↔ Spec 12）**
> - `tableau_datasource_fields`：由 Spec 07 同步流程写入（字段元数据来自 Tableau Metadata API）
> - `tableau_field_semantics`：由 Spec 12 语义维护流程管理，`field_registry_id` 指向 `tableau_datasource_fields.id`
> - 两个表通过 `(field_registry_id, connection_id)` 关联，不直接外键约束（跨模块解耦）

### 2.2 表定义详情

#### 2.2.1 tableau_connections

Tableau Server/Cloud 的 PAT 认证连接配置。

| 字段 | 类型 | 约束 | 说明 |
|------|------|------|------|
| id | Integer | PK, auto | 主键 |
| name | String(128) | NOT NULL | 连接显示名称 |
| server_url | String(512) | NOT NULL | Tableau Server URL |
| site | String(128) | NOT NULL | Site Content URL |
| api_version | String(16) | DEFAULT '3.21' | REST API 版本 |
| connection_type | String(16) | NOT NULL, DEFAULT 'mcp' | 连接模式：'mcp' (REST) 或 'tsc' (库) |
| token_name | String(256) | NOT NULL | PAT Token 名称 |
| token_encrypted | String(512) | NOT NULL | PAT Token 密文（Fernet 加密） |
| owner_id | Integer | NOT NULL | 创建者用户 ID |
| is_active | Boolean | DEFAULT true | 是否启用 |
| auto_sync_enabled | Boolean | DEFAULT false | 是否自动同步 |
| sync_interval_hours | Integer | DEFAULT 24 | 自动同步间隔（小时） |
| last_test_at | DateTime | nullable | 最近一次测试时间 |
| last_test_success | Boolean | nullable | 最近一次测试结果 |
| last_test_message | Text | nullable | 最近一次测试消息 |
| last_sync_at | DateTime | nullable | 最近一次同步完成时间 |
| last_sync_duration_sec | Integer | nullable | 最近同步耗时（秒） |
| sync_status | String(16) | DEFAULT 'idle' | 同步状态：idle / running / failed |
| created_at | DateTime | NOT NULL, server_default | 创建时间 |
| updated_at | DateTime | onupdate | 最后更新时间 |

**关系**：`assets` -> TableauAsset (1:N, cascade delete-orphan)

#### 2.2.2 tableau_assets

同步到本地的 Tableau 资产元数据（workbook / view / dashboard / datasource）。

| 字段 | 类型 | 约束 | 说明 |
|------|------|------|------|
| id | Integer | PK, auto | 本地主键 |
| connection_id | Integer | FK -> tableau_connections.id, CASCADE | 所属连接 |
| asset_type | String(32) | NOT NULL | 资产类型：workbook / view / dashboard / datasource |
| tableau_id | String(256) | NOT NULL | Tableau Server 上的原始 ID |
| name | String(256) | NOT NULL | 资产名称 |
| project_name | String(256) | nullable | 所属项目名称 |
| description | Text | nullable | 描述信息 |
| owner_name | String(128) | nullable | 所有者名称 |
| thumbnail_url | String(512) | nullable | 缩略图 URL |
| content_url | String(512) | nullable | 访问 URL 路径 |
| raw_metadata | JSONB | nullable | 原始元数据快照 |
| is_deleted | Boolean | DEFAULT false | 软删除标记 |
| synced_at | DateTime | NOT NULL, server_default | 最后同步时间 |
| parent_workbook_id | String(256) | nullable | 父工作簿 Tableau ID（view/dashboard） |
| parent_workbook_name | String(256) | nullable | 父工作簿名称 |
| tags | JSONB | nullable | 标签数组 |
| sheet_type | String(32) | nullable | 工作表类型 |
| created_on_server | DateTime | nullable | 在 Tableau Server 上的创建时间 |
| updated_on_server | DateTime | nullable | 在 Tableau Server 上的更新时间 |
| view_count | Integer | nullable | 浏览次数 |
| ai_summary | Text | nullable | AI 生成的摘要 |
| ai_summary_generated_at | DateTime | nullable | 摘要生成时间 |
| ai_summary_error | Text | nullable | 摘要生成错误信息 |
| ai_explain | Text | nullable | AI 深度解读 |
| ai_explain_at | DateTime | nullable | 深度解读生成时间 |
| health_score | Float | nullable | 健康评分 (0-100) |
| health_details | JSONB | nullable | 健康评分明细 |
| field_count | Integer | nullable | 字段数量 |
| is_certified | Boolean | nullable | 是否已认证（datasource） |

**API 类型契约**：
- `tags` 是 JSONB 数组字段，对外响应必须统一为 `string[] | null`，不得返回逗号拼接字符串。
- 前端不得对 `tags` 直接调用字符串方法（如 `.split()`），必须按数组渲染；兼容历史数据时应先做运行时归一化。

**唯一约束**：`(connection_id, tableau_id)` -> `uq_asset_conn_tid`

**索引**：
- `ix_asset_conn_deleted_type` -> `(connection_id, is_deleted, asset_type)`
- `ix_asset_conn_parent` -> `(connection_id, parent_workbook_id)`

**关系**：
- `connection` -> TableauConnection (N:1)
- `datasources` -> TableauAssetDatasource (1:N, cascade delete-orphan)

#### 2.2.3 tableau_asset_datasources

资产与数据源的多对多关联表。记录 workbook 使用了哪些数据源。

| 字段 | 类型 | 约束 | 说明 |
|------|------|------|------|
| id | Integer | PK, auto | 主键 |
| asset_id | Integer | FK -> tableau_assets.id, CASCADE | 所属资产 |
| datasource_name | String(256) | NOT NULL | 数据源名称 |
| datasource_type | String(64) | nullable | 数据源类型 |

**唯一约束**：`(asset_id, datasource_name)` -> `uq_asset_ds_name`

#### 2.2.4 tableau_sync_logs

同步执行历史记录，每次同步（手动或调度）生成一条日志。

| 字段 | 类型 | 约束 | 说明 |
|------|------|------|------|
| id | Integer | PK, auto | 主键 |
| connection_id | Integer | FK -> tableau_connections.id, CASCADE | 所属连接 |
| trigger_type | String(16) | NOT NULL | 触发方式：'manual' / 'scheduled' |
| started_at | DateTime | NOT NULL, server_default | 开始时间 |
| finished_at | DateTime | nullable | 结束时间 |
| status | String(16) | NOT NULL, DEFAULT 'running' | 状态：running / success / partial / failed |
| workbooks_synced | Integer | DEFAULT 0 | 同步的工作簿数 |
| views_synced | Integer | DEFAULT 0 | 同步的视图数 |
| dashboards_synced | Integer | DEFAULT 0 | 同步的仪表板数 |
| datasources_synced | Integer | DEFAULT 0 | 同步的数据源数 |
| assets_deleted | Integer | DEFAULT 0 | 软删除的资产数 |
| error_message | Text | nullable | 错误信息 |
| details | JSONB | nullable | 扩展详情 |

**索引**：`ix_synclog_conn_started` -> `(connection_id, started_at)`

#### 2.2.5 tableau_datasource_fields

数据源的字段级元数据缓存，支持 AI 语义标注。

| 字段 | 类型 | 约束 | 说明 |
|------|------|------|------|
| id | Integer | PK, auto | 主键 |
| asset_id | Integer | FK -> tableau_assets.id, CASCADE | 所属资产 |
| datasource_luid | String(256) | NOT NULL | 数据源 LUID |
| field_name | String(256) | NOT NULL | 字段原始名称 |
| field_caption | String(256) | nullable | 字段显示名（Tableau 中配置） |
| data_type | String(64) | nullable | 数据类型 |
| role | String(32) | nullable | 角色：dimension / measure |
| description | Text | nullable | 字段描述 |
| formula | Text | nullable | 计算字段公式 |
| aggregation | String(32) | nullable | 默认聚合方式 |
| is_calculated | Boolean | DEFAULT false | 是否为计算字段 |
| metadata_json | JSONB | nullable | 原始元数据 JSON |
| fetched_at | DateTime | NOT NULL, server_default | 拉取时间 |
| ai_caption | String(256) | nullable | AI 生成的中文名 |
| ai_description | Text | nullable | AI 生成的描述 |
| ai_role | String(32) | nullable | AI 判定的角色 |
| ai_confidence | Float | nullable | AI 标注置信度 (0-1) |
| ai_annotated_at | DateTime | nullable | AI 标注时间 |

**索引**：`ix_dsfield_asset_luid` -> `(asset_id, datasource_luid)`

---

## 3. API 设计

**基础路径**：`/api/tableau`

**认证**：所有接口需 Session/Cookie 认证。标注 `[admin/data_admin]` 的接口需要 admin 或 data_admin 角色。

### 3.1 连接管理

#### 3.1.1 获取连接列表

```
GET /connections
```

**权限**：已登录用户。admin 可见所有连接，非 admin 仅可见自己创建的连接。

**请求参数**：

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| include_inactive | bool | 否 | 是否包含已停用连接，默认 false |

**响应 200**：

```json
{
  "connections": [
    {
      "id": 1,
      "name": "Production Tableau",
      "server_url": "https://tableau.example.com",
      "site": "default",
      "api_version": "3.21",
      "connection_type": "mcp",
      "token_name": "mulan-pat",
      "owner_id": 1,
      "is_active": true,
      "auto_sync_enabled": true,
      "sync_interval_hours": 24,
      "last_test_at": "2026-04-03 10:00:00",
      "last_test_success": true,
      "last_test_message": "REST API 连接成功 (site_id=xxx)",
      "last_sync_at": "2026-04-03 09:00:00",
      "last_sync_duration_sec": 45,
      "sync_status": "idle",
      "next_sync_at": "2026-04-04 09:00:00",
      "created_at": "2026-04-01 12:00:00",
      "updated_at": "2026-04-03 10:00:00"
    }
  ],
  "total": 1
}
```

#### 3.1.2 创建连接

```
POST /connections
```

**权限**：`[admin/data_admin]`

**请求体**：

```json
{
  "name": "Production Tableau",
  "server_url": "https://tableau.example.com",
  "site": "default",
  "api_version": "3.21",
  "connection_type": "mcp",
  "token_name": "mulan-pat",
  "token_value": "plaintext-pat-token"
}
```

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| name | string | 是 | 连接名称 |
| server_url | string | 是 | Tableau Server URL |
| site | string | 是 | Site Content URL |
| api_version | string | 否 | REST API 版本，默认 "3.21" |
| connection_type | string | 否 | 'mcp' 或 'tsc'，默认 'mcp' |
| token_name | string | 是 | PAT Token 名称 |
| token_value | string | 是 | PAT Token 值（明文，服务端加密存储） |

**响应 200**：

```json
{
  "connection": { /* 连接对象，同 3.1.1 */ },
  "message": "连接创建成功"
}
```

**错误**：
- 400：`connection_type 必须为 'mcp' 或 'tsc'`

#### 3.1.3 更新连接

```
PUT /connections/{conn_id}
```

**权限**：`[admin/data_admin]`，且必须是连接所有者或 admin。

**请求体**（全部字段可选）：

```json
{
  "name": "Updated Name",
  "server_url": "https://new-url.com",
  "site": "new-site",
  "api_version": "3.22",
  "connection_type": "tsc",
  "token_name": "new-pat-name",
  "token_value": "new-pat-secret",
  "is_active": true,
  "auto_sync_enabled": true,
  "sync_interval_hours": 12
}
```

**响应 200**：

```json
{ "message": "连接更新成功" }
```

**说明**：
- `token_value` 非空时，同时更新 `token_name` 和加密后的 `token_encrypted`
- `token_value` 为空字符串时，不更新 token 相关字段

#### 3.1.4 删除连接

```
DELETE /connections/{conn_id}
```

**权限**：`[admin/data_admin]`，且必须是连接所有者或 admin。

**响应 200**：

```json
{ "message": "连接已删除" }
```

**说明**：级联删除关联的 assets、sync_logs、datasource_fields。

#### 3.1.5 测试连接

```
POST /connections/{conn_id}/test
```

**权限**：`[admin/data_admin]`，且必须是连接所有者或 admin。

**响应 200**：

```json
{
  "success": true,
  "message": "REST API 连接成功 (site_id=xxx)"
}
```

**测试逻辑**：
- MCP 模式：直接调用 REST API `/auth/signin`，成功后 `/auth/signout`
- TSC 模式：通过 `tableauserverclient` 库 `sign_in()` 并获取 `server_info`
- 测试结果保存至 `last_test_at` / `last_test_success` / `last_test_message`

**错误场景**：
- Token 解密失败（密钥变更）
- 连接超时
- 认证失败（PAT 过期/无效）

### 3.2 同步管理

#### 3.2.1 触发手动同步

```
POST /connections/{conn_id}/sync
```

**权限**：`[admin/data_admin]`

**响应 200**：

```json
{
  "task_id": "celery-task-uuid",
  "message": "同步任务已提交",
  "status": "pending"
}
```

**说明**：
- 如果当前 `sync_status == "running"`，返回 `{"message": "同步正在进行中", "status": "running"}`
- 同步通过 Celery 异步执行，返回 `task_id` 供前端轮询

#### 3.2.2 获取同步状态

```
GET /connections/{conn_id}/sync-status
```

**权限**：已登录用户，需有连接访问权。

**响应 200**：

```json
{
  "status": "idle",
  "last_sync_at": "2026-04-03 09:00:00",
  "last_sync_duration_sec": 45,
  "auto_sync_enabled": true,
  "sync_interval_hours": 24,
  "next_sync_at": "2026-04-04 09:00:00"
}
```

#### 3.2.3 获取同步日志列表

```
GET /connections/{conn_id}/sync-logs
```

**权限**：已登录用户，需有连接访问权。

**请求参数**：

| 参数 | 类型 | 必填 | 默认 | 说明 |
|------|------|------|------|------|
| page | int | 否 | 1 | 页码 (>=1) |
| page_size | int | 否 | 20 | 每页条数 (1-100) |

**响应 200**：

```json
{
  "logs": [
    {
      "id": 1,
      "connection_id": 1,
      "trigger_type": "manual",
      "started_at": "2026-04-03 09:00:00",
      "finished_at": "2026-04-03 09:00:45",
      "status": "success",
      "workbooks_synced": 10,
      "views_synced": 35,
      "dashboards_synced": 8,
      "datasources_synced": 5,
      "assets_deleted": 2,
      "error_message": null,
      "duration_sec": 45
    }
  ],
  "total": 15,
  "page": 1,
  "page_size": 20,
  "pages": 1
}
```

#### 3.2.4 获取同步日志详情

```
GET /connections/{conn_id}/sync-logs/{log_id}
```

**权限**：已登录用户，需有连接访问权。

**响应 200**：同步日志对象（同上）。

**错误**：404 - 日志不存在或不属于该连接。

### 3.3 资产浏览

#### 3.3.1 获取资产列表

```
GET /assets
```

**权限**：已登录用户，需有连接访问权。

**请求参数**：

| 参数 | 类型 | 必填 | 默认 | 说明 |
|------|------|------|------|------|
| connection_id | int | 是 | - | 连接 ID |
| asset_type | string | 否 | null | 过滤类型：workbook / view / dashboard / datasource |
| page | int | 否 | 1 | 页码 (>=1) |
| page_size | int | 否 | 50 | 每页条数 (1-100) |

**响应 200**：

```json
{
  "assets": [ /* 资产对象数组 */ ],
  "total": 58,
  "page": 1,
  "page_size": 50,
  "pages": 2
}
```

#### 3.3.2 搜索资产

```
GET /assets/search
```

**权限**：已登录用户。

**请求参数**：

| 参数 | 类型 | 必填 | 默认 | 说明 |
|------|------|------|------|------|
| q | string | 是 (min 1 字符) | - | 搜索关键词（匹配 name / project_name / owner_name） |
| connection_id | int | 否 | null | 限定连接 |
| asset_type | string | 否 | null | 限定类型 |
| page | int | 否 | 1 | 页码 |
| page_size | int | 否 | 50 | 每页条数 |

**搜索策略**：基于 `ILIKE` 模糊匹配 name、project_name、owner_name 三个字段。

> **🛑 P0 安全修复：强制多租户隔离（IDOR 防护）**
>
> 如果当前用户**非 admin** 且请求中**未指定 `connection_id`**：
> ```sql
> WHERE connection_id IN (
>     SELECT id FROM tableau_connections
>     WHERE owner_id = :current_user_id
> )
> ```
> 即：自动将搜索范围限定为当前用户自己创建的连接。
>
> 禁止出现 `SELECT * FROM tableau_assets WHERE ...` 不带 connection_id 过滤的查询。
> 该约束同样适用于 `GET /assets`（3.3.1）接口。

#### 3.3.3 获取资产详情

```
GET /assets/{asset_id}
```

**权限**：已登录用户，需有资产所属连接的访问权。

**响应 200**：

```json
{
  "id": 1,
  "connection_id": 1,
  "asset_type": "workbook",
  "tableau_id": "abc-123",
  "name": "Sales Dashboard",
  "project_name": "Finance",
  "description": "Monthly sales overview",
  "owner_name": "John",
  "datasources": [
    { "id": 1, "asset_id": 1, "datasource_name": "Sales DB", "datasource_type": "sqlserver" }
  ],
  "server_url": "https://tableau.example.com",
  "health_score": 75.0,
  "ai_summary": "...",
  "ai_explain": "..."
}
```

**说明**：详情接口额外返回 `datasources` 数组和 `server_url`（用于构建跳转链接）。

#### 3.3.4 获取子资产（workbook 下属 view/dashboard）

```
GET /assets/{asset_id}/children
```

**响应 200**：

```json
{ "children": [ /* 资产对象数组 */ ] }
```

**说明**：仅对 `asset_type == "workbook"` 的资产返回子级。其他类型返回空数组。

#### 3.3.5 获取父资产

```
GET /assets/{asset_id}/parent
```

**响应 200**：

```json
{ "parent": { /* workbook 资产对象 */ } }
```

**说明**：返回 view/dashboard 的父 workbook。无父级时返回 `null`。

#### 3.3.6 获取项目树

```
GET /projects
```

**请求参数**：

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| connection_id | int | 是 | 连接 ID |

**响应 200**：

```json
{
  "projects": [
    {
      "name": "Finance",
      "children": {
        "workbook": { "type": "workbook", "count": 5 },
        "view": { "type": "view", "count": 12 }
      }
    }
  ]
}
```

### 3.4 健康评分

#### 3.4.1 获取资产健康评分

```
GET /assets/{asset_id}/health
```

**权限**：已登录用户，需有连接访问权。

**响应 200**：

```json
{
  "score": 75.0,
  "level": "good",
  "checks": [
    {
      "key": "has_description",
      "label": "有描述信息",
      "weight": 20,
      "passed": true,
      "detail": "已填写描述"
    },
    {
      "key": "has_owner",
      "label": "有所有者",
      "weight": 15,
      "passed": true,
      "detail": "所有者: John"
    }
  ]
}
```

**说明**：计算结果会缓存到 `tableau_assets.health_score` 和 `health_details`。

#### 3.4.2 连接级健康总览

```
GET /connections/{conn_id}/health-overview
```

**权限**：已登录用户，需有连接访问权。

**响应 200**：

```json
{
  "connection_id": 1,
  "connection_name": "Production Tableau",
  "total_assets": 58,
  "avg_score": 62.3,
  "avg_level": "good",
  "level_distribution": {
    "excellent": 10,
    "good": 25,
    "warning": 15,
    "poor": 8
  },
  "top_issues": [
    { "check": "has_description", "count": 23 },
    { "check": "fields_have_captions", "count": 18 }
  ],
  "assets": [
    { "asset_id": 1, "name": "Report A", "asset_type": "workbook", "score": 35.0, "level": "poor" }
  ]
}
```

**说明**：
- 遍历连接下所有资产，逐一计算健康评分并更新缓存
- `assets` 数组按 score 升序排列（最差的排前面）
- `top_issues` 取失败次数最多的前 5 项检查

### 3.5 AI 功能

#### 3.5.1 资产深度解读

```
POST /assets/{asset_id}/explain
```

**权限**：已登录用户，需有连接访问权。

**请求体**：

```json
{ "refresh": false }
```

**响应 200**：

```json
{
  "explain": "该工作簿是财务部门的月度销售分析报表...",
  "cached": true,
  "generated_at": "2026-04-03 10:00:00",
  "field_semantics": [
    {
      "field": "sales_amount",
      "caption": "销售金额",
      "role": "measure",
      "data_type": "REAL",
      "meaning": "订单的实际成交金额"
    }
  ]
}
```

**缓存策略**：
- 1 小时内不重新生成（除非 `refresh: true`）
- 缓存存储在 `ai_explain` / `ai_explain_at` 字段

**LLM Prompt 输入**：
- 资产名称、类型、项目、描述、所有者
- 父工作簿信息
- 关联数据源列表
- 字段元数据（名称、caption、类型、角色、公式、描述）

**错误场景**：
- LLM 服务未配置（ImportError）
- 生成超时或 API 失败

### 3.6 完整端点汇总

| # | 方法 | 路径 | 权限 | 说明 |
|---|------|------|------|------|
| 1 | GET | /connections | 登录用户 | 获取连接列表 |
| 2 | POST | /connections | admin/data_admin | 创建连接 |
| 3 | PUT | /connections/{conn_id} | admin/data_admin + 所有者 | 更新连接 |
| 4 | DELETE | /connections/{conn_id} | admin/data_admin + 所有者 | 删除连接 |
| 5 | POST | /connections/{conn_id}/test | admin/data_admin + 所有者 | 测试连接 |
| 6 | POST | /connections/{conn_id}/sync | admin/data_admin | 触发手动同步 |
| 7 | GET | /connections/{conn_id}/sync-status | 登录用户 | 获取同步状态 |
| 8 | GET | /connections/{conn_id}/sync-logs | 登录用户 | 获取同步日志列表 |
| 9 | GET | /connections/{conn_id}/sync-logs/{log_id} | 登录用户 | 获取同步日志详情 |
| 10 | GET | /connections/{conn_id}/health-overview | 登录用户 | 连接级健康总览 |
| 11 | GET | /assets | 登录用户 | 获取资产列表（分页） |
| 12 | GET | /assets/search | 登录用户 | 搜索资产 |
| 13 | GET | /assets/{asset_id} | 登录用户 | 获取资产详情 |
| 14 | GET | /assets/{asset_id}/children | 登录用户 | 获取子资产 |
| 15 | GET | /assets/{asset_id}/parent | 登录用户 | 获取父资产 |
| 16 | GET | /assets/{asset_id}/health | 登录用户 | 获取资产健康评分 |
| 17 | POST | /assets/{asset_id}/explain | 登录用户 | AI 深度解读 |
| 18 | GET | /projects | 登录用户 | 获取项目树 |

---

## 4. 业务逻辑

### 4.1 同步引擎

#### 4.1.1 双模式架构

系统支持两种同步模式，由 `connection_type` 字段决定：

| 模式 | 实现类 | 依赖 | 适用场景 |
|------|--------|------|---------|
| mcp | `TableauRestSyncService` | `requests` | 无需安装 TSC 库；适用于 Tableau Cloud 和受限环境 |
| tsc | `TableauSyncService` | `tableauserverclient` | 需要 TSC 库；适用于 Tableau Server |

#### 4.1.2 同步流程

1. **认证**：使用解密后的 PAT 调用 `/auth/signin`（MCP）或 `server.sign_in()`（TSC）
2. **拉取工作簿**：分页获取所有 workbooks，同时拉取每个 workbook 的关联数据源
3. **拉取视图**：分页获取所有 views，根据 `sheetType` 区分 view 和 dashboard，关联父 workbook
4. **拉取数据源**：分页获取所有独立 datasources
5. **拉取字段级元数据**（⚠️ P0 修复，Spec 12 边界）：对每个 datasource 资产调用 Tableau Metadata API 或 REST API，解析字段元数据（`field_name`、`data_type`、`role`、`description`、`formula`），批量写入 `tableau_datasource_fields` 表
6. **UPSERT**：基于 `(connection_id, tableau_id)` 唯一键执行 INSERT OR UPDATE
7. **软删除**：将本次未出现在同步结果中的资产标记为 `is_deleted = true`
8. **日志记录**：更新 sync_log 的计数和状态

> **⚠️ 字段元数据同步说明（Spec 12 边界）**
> - 数据源字段是 Spec 12 语义标注和 Spec 14 NL-to-Query 的上游依赖
> - 字段元数据必须在本步骤完整拉取，否则健康度评分因子 4（`fields_have_captions`）无法生效
> - Tableau Metadata API：推荐使用 GraphQL endpoint `/api/metadata/graphql`；fallback 至 REST `/api/{version}/datasources/{datasource_luid}/fields`
> - 每个数据源的字段应做 UPSERT（按 `asset_id + field_name` 唯一键），支持增量同步
> - 字段表 `tableau_datasource_fields` 写入后方可被 Spec 12 的 `TableauFieldSemantics` 关联标注

#### 4.1.3 UPSERT 逻辑

```python
# 伪代码
existing = SELECT * FROM tableau_assets
           WHERE connection_id = ? AND tableau_id = ?

if existing:
    UPDATE existing SET name=?, description=?, ..., synced_at=NOW(), is_deleted=false
else:
    INSERT INTO tableau_assets (connection_id, tableau_id, name, ...)
```

**关键点**：
- 已软删除的资产在再次同步时会恢复（`is_deleted = false`）
- `synced_at` 每次同步都更新

#### 4.1.4 分页拉取（MCP REST 模式）

```
GET /api/{version}/sites/{site_id}/workbooks?pageSize=100&pageNumber=1
```

- 默认 `pageSize = 100`
- 通过响应中的 `pagination.pageNumber` / `pagination.totalPages` 判断是否继续翻页
- 支持多种响应格式（嵌套 dict 或直接数组）

#### 4.1.5 同步状态机

```
idle ──[触发同步]──> running ──[成功]──> idle
                       │
                       ├──[部分失败]──> idle (status=partial)
                       │
                       └──[全部失败]──> failed
```

同步日志 status 取值：
- `running`：同步进行中
- `success`：全部成功
- `partial`：部分成功（有错误但同步了部分资产）
- `failed`：全部失败（无资产同步成功）

### 4.2 Celery 调度

#### 4.2.1 任务定义

| 任务 | 函数 | 调度方式 | 说明 |
|------|------|---------|------|
| `sync_connection_task` | 单连接同步 | 手动触发 / Beat 间接调用 | bind=True, max_retries=2, retry_delay=30s |
| `scheduled_sync_all` | 全连接轮询 | Celery Beat 每 60 秒 | 检查所有活跃连接，到期则触发 sync_connection_task |

#### 4.2.2 调度逻辑

```python
# scheduled_sync_all 伪代码
for conn in get_all_active_connections():
    if not conn.auto_sync_enabled:
        continue
    if conn.last_sync_at and (now - conn.last_sync_at) < timedelta(hours=conn.sync_interval_hours):
        continue
    sync_connection_task.delay(conn.id)
```

#### 4.2.3 重试机制

- `sync_connection_task` 最多重试 2 次，间隔 30 秒
- 如果连接已在 `running` 状态，跳过本次任务
- 达到最大重试次数后，设置连接状态为 `failed`

### 4.3 健康评分引擎

健康评分算法（7 因子定义、权重、特殊计算规则、健康等级划分）统一定义于 [健康评分规格书 Spec 10](10-tableau-health-scoring-spec.md)，本文档不再重复。

本模块的职责是：
1. 调用 `HealthScoringEngine.compute_asset_health(asset, datasources, fields)` 获取评分结果
2. 将计算结果缓存至 `tableau_assets.health_score` 和 `health_details`
3. 通过 `GET /assets/{asset_id}/health` 和 `GET /connections/{conn_id}/health-overview` 接口暴露评分数据

#### 4.3.4 返回结构

```json
{
  "score": 75.0,
  "level": "good",
  "checks": [
    {
      "key": "has_description",
      "label": "有描述信息",
      "weight": 20,
      "passed": true,
      "detail": "已填写描述"
    }
  ]
}
```

### 4.4 AI 功能

#### 4.4.1 深度解读 (Explain)

**触发条件**：用户调用 `POST /assets/{asset_id}/explain`

**输入上下文**：
- 资产基本信息（名称、类型、项目、描述、所有者）
- 父工作簿名称
- 关联数据源列表
- 字段元数据（field_name, caption, data_type, role, formula, description）

**Prompt 模板**：使用 `services.llm.prompts.ASSET_EXPLAIN_TEMPLATE`，System 角色："你是一个专业的 BI 报表解读专家。"

**缓存**：
- 结果存储在 `ai_explain` 字段
- 1 小时缓存有效期
- `refresh=true` 强制重新生成

#### 4.4.2 字段语义标注

**存储**：`tableau_datasource_fields` 表的 `ai_caption` / `ai_description` / `ai_role` / `ai_confidence` 字段

**更新方式**：通过 `TableauDatabase.update_field_annotation()` 方法

---

## 5. 错误码

本模块错误码定义详见 [统一错误码标准 §5.5 TAB](01-error-codes-standard.md#55-tab---tableau-mcp-集成)。

以下为本模块**常见触发场景**快速参考（HTTP 状态码以 Spec 01 为准）：

| 错误码 | 常见触发场景 |
|--------|-------------|
| TAB_001 | 按 ID 查询连接未找到（conn_id 不存在） |
| TAB_002 | 非所有者且无共享权限尝试访问连接 |
| TAB_003 | PAT Token 无效或已过期 |
| TAB_004 | 网络不通或 Tableau Server 宕机 |
| TAB_005 | 同步任务已在运行，重复触发 |
| TAB_006 | 请求的工作簿/视图/数据源在 Tableau 中未找到 |
| TAB_007 | Tableau REST API 调用返回错误（同步失败） |
| TAB_008 | 提供了不支持的 connection_type 值 |
| TAB_009 | 通过 MCP 协议查询 Tableau 数据失败 |
| TAB_010 | 按 ID 查询同步日志未找到 |

---

## 6. 安全

### 6.1 认证与授权

| 安全层 | 实现 |
|--------|------|
| API 认证 | Session/Cookie (HTTP Only)，由 `get_current_user()` 统一校验 |
| 角色控制 | `require_roles()` 限制 admin/data_admin 角色 |
| 资源隔离 | `verify_connection_access()` 确保非 admin 用户只能访问自己创建的连接（防 IDOR） |
| 资产权限 | 通过 `asset.connection_id` -> 连接所有权间接控制 |

### 6.2 凭证加密

- **算法**：Fernet 对称加密（AES-128-CBC + HMAC-SHA256）
- **密钥**：环境变量 `TABLEAU_ENCRYPTION_KEY`
- **加密对象**：PAT Token 明文值 (`token_value`)
- **存储**：加密后的密文存储在 `token_encrypted` 字段
- **解密时机**：仅在测试连接和执行同步时解密

```python
# 加密流程
from services.common.crypto import CryptoHelper

crypto = CryptoHelper(os.environ["TABLEAU_ENCRYPTION_KEY"])
encrypted = crypto.encrypt(token_value)   # 存入 DB
decrypted = crypto.decrypt(encrypted)     # 使用时解密
```

### 6.3 API 响应安全

- `to_dict()` 方法不暴露 `token_encrypted` 字段
- 连接列表仅返回 `token_name`，不返回 token 密文或明文
- `tableau_assets.tags` 对外响应保持 JSON 数组语义，禁止在后端 `json.dumps()` 后让前端按字符串解析

### 6.4 传输安全

- Tableau Server 连接使用 HTTPS
- REST API 调用设置超时限制（认证 20s，数据请求 30s，signout 5s）

### 6.5 发布日志授权边界

语义发布、重试、回滚接口必须同时验证请求连接与目标发布日志/语义对象属于同一连接，并且该连接对当前用户可访问。

禁止模式：
```python
verify_connection_access(req.connection_id, user, db)
log = get_publish_log(req.log_id)  # ❌ 未限定 connection_id
rollback(log.connection_id, log.object_id)
```

必须模式：
```python
log = get_publish_log(req.log_id, connection_id=req.connection_id)
if not log:
    raise HTTPException(status_code=404, detail="发布日志不存在")
verify_connection_access(log.connection_id, user, db)
```

所有按 `log_id`、`asset_id`、`field_id`、`ds_id` 触发副作用的接口，都必须在数据库查询层绑定父级 `connection_id`。传入的 `connection_id` 只能作为查询谓词，不得只作为前置权限校验凭据。

---

## 7. 集成点

### 7.1 LLM 服务

| 项目 | 说明 |
|------|------|
| 模块 | `services.llm.service.LLMService` |
| 调用点 | `POST /assets/{asset_id}/explain` |
| Prompt 模板 | `services.llm.prompts.ASSET_EXPLAIN_TEMPLATE` |
| System 角色 | "你是一个专业的 BI 报表解读专家。" |
| 超时 | 30 秒 |
| 错误处理 | ImportError -> "LLM 服务未配置"；其他异常 -> "生成失败: {error}" |

### 7.2 Celery

| 项目 | 说明 |
|------|------|
| Broker | 由 `services.tasks` 中的 `celery_app` 配置 |
| Beat 调度 | `scheduled_sync_all`，每 60 秒执行一次 |
| 异步任务 | `sync_connection_task`，max_retries=2, retry_delay=30s |
| 结果存储 | 同步结果直接写入 PostgreSQL（sync_logs + connection status） |

### 7.3 数据库

| 项目 | 说明 |
|------|------|
| ORM | SQLAlchemy 2.x |
| 数据库 | PostgreSQL 16 |
| Session 管理 | **API 层**：FastAPI `Depends(get_db)` 注入（请求级生命周期，自动 commit/rollback）；**Celery 任务层**：上下文管理器 `with get_db_context() as db:`（任务级生命周期） |
| 迁移 | Alembic 管理 DDL |
| JSONB | 原生 PostgreSQL JSONB 类型（tags, raw_metadata, health_details, details, metadata_json） |

> **⚠️ Session 管理约束（P1）**
>
> 现有代码中每次 DB 操作创建新 session 并 `expire_all()` 的模式，在高并发（Celery 多 worker + FastAPI 多 worker）场景下存在连接池耗尽风险。统一规范：
>
> 1. **API 层**（FastAPI 路由 / 依赖服务）：使用 `get_db()` 依赖注入，由框架管理 session 生命周期（begin → commit → close）
> 2. **Celery 异步任务层**：使用 `with get_db_context() as db:` 上下文管理器，不自行创建 session
> 3. **禁止**：在异步任务中调用 `db.session.close()` 或 `expire_all()`，由上下文管理器统一清理

### 7.4 Tableau Server

| 项目 | 说明 |
|------|------|
| 认证方式 | Personal Access Token (PAT) |
| REST API 版本 | 默认 3.21 |
| TSC 库版本 | tableauserverclient (可选) |
| 资源拉取 | 分页（pageSize=100），自动翻页 |
| 数据类型 | workbooks, views (含 dashboards), datasources |
| 辅助请求 | workbook datasources（每个 workbook 独立请求） |

---

## 8. 时序图

### 8.1 手动同步流程

```
用户           Frontend        API (tableau.py)     Celery Worker      Tableau Server     PostgreSQL
 │               │                  │                    │                   │                │
 │──触发同步────>│                  │                    │                   │                │
 │               │──POST /sync────>│                    │                   │                │
 │               │                  │──verify_access────>│                   │                │
 │               │                  │<──────ok──────────│                   │                │
 │               │                  │──check sync_status│                   │                │
 │               │                  │                    │                   │              read
 │               │                  │<──status=idle─────│                   │                │
 │               │                  │──task.delay()────>│                   │                │
 │               │<──task_id───────│                    │                   │                │
 │<──显示进度────│                  │                    │                   │                │
 │               │                  │                    │──decrypt token──>│                │
 │               │                  │                    │<──token──────────│                │
 │               │                  │                    │──set running────>│                │
 │               │                  │                    │──create sync_log>│                │
 │               │                  │                    │──REST signin───>│                │
 │               │                  │                    │<──auth_token────│                │
 │               │                  │                    │──GET workbooks──>│                │
 │               │                  │                    │<──workbooks─────│                │
 │               │                  │                    │──GET views──────>│                │
 │               │                  │                    │<──views──────────│                │
 │               │                  │                    │──GET datasources>│                │
 │               │                  │                    │<──datasources───│                │
 │               │                  │                    │──signout────────>│                │
 │               │                  │                    │──upsert assets──────────────────>│
 │               │                  │                    │──mark deleted───────────────────>│
 │               │                  │                    │──finish sync_log────────────────>│
 │               │                  │                    │──set idle───────────────────────>│
 │               │                  │                    │                   │                │
```

### 8.2 健康评分流程

```
用户           API (tableau.py)        Health Engine         PostgreSQL
 │                  │                      │                     │
 │──GET health────>│                      │                     │
 │                  │──get asset──────────────────────────────>│
 │                  │<──asset──────────────────────────────────│
 │                  │──get datasources───────────────────────>│
 │                  │<──datasources────────────────────────────│
 │                  │──get fields────────────────────────────>│
 │                  │<──fields──────────────────────────────────│
 │                  │──compute_asset_health()                  │
 │                  │              │                            │
 │                  │              │──check has_description     │
 │                  │              │──check has_owner           │
 │                  │              │──check has_datasource_link │
 │                  │              │──check fields_have_captions│
 │                  │              │──check is_certified        │
 │                  │              │──check naming_convention   │
 │                  │              │──check not_stale           │
 │                  │              │                            │
 │                  │<──{score, level, checks}                 │
 │                  │──update_asset_health────────────────────>│
 │<──{score, level, checks}                                    │
```

### 8.3 Celery Beat 调度流程

```
Celery Beat (每60s)          scheduled_sync_all          PostgreSQL         sync_connection_task
       │                           │                        │                      │
       │──trigger──────────────>│                        │                      │
       │                           │──get_all_connections──>│                      │
       │                           │<──connections──────────│                      │
       │                           │                        │                      │
       │                           │──for each conn:        │                      │
       │                           │  auto_sync_enabled?    │                      │
       │                           │  interval elapsed?     │                      │
       │                           │                        │                      │
       │                           │──task.delay(conn_id)──────────────────────>│
       │                           │──task.delay(conn_id2)─────────────────────>│
       │                           │                        │                      │
       │                           │                        │    (各 task 独立执行同步)
```

---

## 9. 测试策略

### 9.1 单元测试

| 测试对象 | 测试内容 | Mock 范围 |
|---------|---------|----------|
| `compute_asset_health()` | 7 个检查因子的独立验证，边界条件（空字段、无数据源、过期资产） | 无需 mock |
| `get_health_level()` | 80/60/40 边界值测试 | 无需 mock |
| `_test_connection_rest()` | REST 认证成功/失败/超时/网络错误 | mock `requests.post` |
| `CreateConnectionRequest` | Pydantic 模型校验（必填、默认值、类型） | 无需 mock |
| `TableauDatabase` CRUD | create/get/update/delete connection/asset 的正确性 | mock 或使用测试数据库 |

### 9.2 集成测试

| 测试场景 | 前置条件 | 验证点 |
|---------|---------|--------|
| 连接创建 -> 测试 -> 同步 | 可达的 Tableau Server + 有效 PAT | 连接健康状态更新；资产数据入库 |
| UPSERT 幂等性 | 已有同步数据 | 二次同步后数据不重复，is_deleted 正确恢复 |
| 软删除 | Tableau 上删除资产后同步 | 本地 is_deleted=true，后续查询不返回 |
| 权限隔离 | 两个 data_admin 用户 | 用户 A 无法访问用户 B 的连接 |
| 发布日志 IDOR | 用户 A 拥有连接 A，用户 B 拥有连接 B，B 有发布日志 L | 用户 A 使用 `connection_id=A` + `log_id=L` 调用 retry/rollback 必须 403/404 |
| tags 契约 | 资产 tags 为 JSON 数组 | API 返回数组；前端资产详情不报错且逐个渲染标签 |
| 加密密钥轮换 | 变更 TABLEAU_ENCRYPTION_KEY | 旧连接测试返回解密失败提示 |

### 9.3 性能测试

| 场景 | 目标 |
|------|------|
| 大规模同步 | 500+ 资产的同步在 5 分钟内完成 |
| 健康总览计算 | 500 资产的 health-overview 在 10 秒内返回 |
| 资产搜索 | ILIKE 搜索在 10000 条记录下 < 500ms |

### 9.4 测试数据

建议创建 fixtures：
- 1 个 Tableau 连接配置
- 10 个 workbook + 30 个 view + 5 个 dashboard + 5 个 datasource
- 每个 workbook 关联 1-3 个数据源
- 部分资产缺少 description/owner 用于健康评分测试

---

## 10. 开放问题

| # | 问题 | 影响 | 优先级 | 状态 | 修复说明 |
|---|------|------|--------|------|---------|
| 1 | `TableauDatabase` 每次操作创建新 Session 并 `expire_all()`，高并发下可能有性能问题 | 性能 | P1 | ✅ 已约束 | §7.3 明确 API 层用 `Depends(get_db)`、Celery 层用 `get_db_context()` |
| 2 | 同步服务中 `sync_service.py:145` 引用了旧路径 `from src.tableau.models`，生产环境可能报错 | 功能 | P0 | 🔴 待修复 | 需修正为 `from services.tableau.models` |
| 3 | `health-overview` 对所有资产逐一计算健康评分，资产量大时响应缓慢 | 性能 | P2 | 🟡 待优化 | 考虑使用缓存的 `health_score` 字段，仅重新计算过期或无缓存的资产 |
| 4 | 搜索接口使用 `ILIKE` 模糊匹配，未限制非 admin 用户跨连接搜索（IDOR） | 安全 | P0 | ✅ 已约束 | §3.3.2 增加强制 tenant isolation，非 admin 不带 connection_id 时自动限定为自己创建的连接 |
| 5 | MCP REST 模式的分页解析器对多种响应格式做了兼容处理，但缺少 XML 响应的处理 | 兼容性 | P2 | 🟡 待确认 | Tableau REST API 默认返回 JSON（需要 Accept: application/json header），但部分旧版本可能返回 XML |
| 6 | `tags` 字段在同步时使用 `json.dumps()` 写入，但 JSONB 列类型可直接接受 Python list | 代码质量 | P3 | 🟡 可优化 | 统一为直接传入 list，移除不必要的 `json.dumps()` |
| 7 | 缺少字段级元数据的自动拉取（`tableau_datasource_fields` 依赖外部填入） | 功能 | P0 | ✅ 已修复 | §4.1.2 同步流程增加 Step 5：调用 Tableau Metadata API 拉取字段元数据并写入 `tableau_datasource_fields` |
| 8 | AI 解读的缓存策略为固定 1 小时，无法根据资产变更动态失效 | 功能 | P3 | 🟡 可优化 | 考虑在 synced_at 更新时清除 ai_explain 缓存 |
| 9 | Celery Beat 任务 `scheduled_sync_all` 无防重入机制 | 可靠性 | P2 | 🟡 待优化 | 如果前一次 scheduled_sync_all 执行超过 60 秒，可能产生重叠执行 |
| 10 | 缺少 WebSocket/SSE 推送，前端只能轮询同步状态 | 用户体验 | P3 | 🟡 V2 规划 | 考虑在 V2 中引入实时推送 |

---

## 11. 开发交付约束

> 通用约束见 `.claude/rules/dev-constraints.md`（自动加载），以下为本模块特有约束。

### 11.1 强制检查清单

- [ ] **import 路径**：所有 `from src.tableau` → `from services.tableau`
- [ ] **IDOR 防护**：`/tableau/assets/:id` 详情接口必须加 `connection_id` 过滤
- [ ] **Session 隔离**：API 层用 `Depends(get_db)`，Celery 层用 `get_db_context()`
- [ ] **Field Metadata 同步**：sync_pipeline 必须包含 Step 4（field_metadata sync）
- [ ] **重试退避**：连接失败使用指数退避 + jitter（非固定间隔）
- [ ] **Token 上限**：单次 LLM 调用 ≤ 8192 tokens（tiktoken cl100k_base）

### 11.2 正确/错误示范

```python
# ✗ 错误 — src.tableau 不存在
from src.tableau.models import TableauConnection

# ✓ 正确
from services.tableau.models import TableauConnection
```

```python
# ✓ 正确 — services/ 层无 FastAPI 依赖
# services/tableau/sync_service.py
from services.tableau.models import TableauConnection
from app.core.database import get_db_context
import httpx

class TableauSyncService:
    def sync_workbooks(self, connection_id: str):
        db = get_db_context()  # Celery 兼容
```

### 11.3 验证命令

```bash
ruff check backend/services/tableau/ --output-format=github
# F821（undefined name）或 F401（unused import）必须修复
```

---

*文档结束*

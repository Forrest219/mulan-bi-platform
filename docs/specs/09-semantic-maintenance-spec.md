# Mulan Tableau 语义治理模块实施规格书 v0.1

- 日期：2026-04-01
- 定位：在现有 Tableau 模块**完全不改动**的前提下，新增语义治理能力
- 原则：读取与回写职责分离，sync_service 保持纯采集职责

---

## 1. 模块架构

```
tableau/                          # 现有模块（不动）
├── sync_service.py               # ✅ 纯读取采集
├── models.py                     # ✅ 已有资产模型
└── ...

semantic_maintenance/             # 🆕 语义维护子模块
├── __init__.py
├── models.py                     # 语义表模型
├── database.py                   # 语义数据库管理
├── service.py                    # 语义业务逻辑
├── field_sync.py                 # 字段级同步（REST Metadata API）
└── publish_service.py            # 回写发布服务

backend/app/api/
├── tableau/                      # 现有路由（不动）
│   ├── connections.py
│   ├── assets.py
│   └── fields.py
└── semantic_maintenance/        # 🆕 语义维护 API 路由
    ├── datasources.py           # 数据源语义
    ├── fields.py                # 字段语义
    ├── review.py                # 审核流转
    ├── publish.py               # 发布管理
    └── versions.py              # 版本历史
```

---

## 2. 数据模型

### 2.1 表：`tableau_datasource_semantics`

数据源级语义主信息表。

| 字段 | 类型 | 说明 |
|------|------|------|
| id | Integer, PK | 主键 |
| connection_id | Integer, FK | 关联 TableauConnection |
| tableau_datasource_id | String(256) | Tableau 原始数据源 ID |
| semantic_name | String(256) | 英文语义名 |
| semantic_name_zh | String(256) | 中文语义名 |
| semantic_description | Text | 语义描述 |
| business_definition | Text | 业务定义 |
| usage_scenarios | Text | 使用场景说明 |
| owner | String(128) | 责任人 |
| steward | String(128) | 数据管家 |
| sensitivity_level | String(16) | low / medium / high / confidential |
| tags_json | Text | JSON 标签数组 |
| status | String(32) | draft / ai_generated / reviewed / approved / published |
| source | String(16) | sync / manual / ai / imported |
| current_version | Integer, default=1 | 当前版本号 |
| published_to_tableau | Boolean, default=False | 是否已发布到 Tableau |
| published_at | DateTime | 最近发布时间 |
| created_by | Integer, FK | 创建人用户 ID |
| updated_by | Integer, FK | 更新人用户 ID |
| created_at | DateTime | 创建时间 |
| updated_at | DateTime | 更新时间 |

**索引：**
- `uq_ds_semantic_conn_ds` = UniqueConstraint(connection_id, tableau_datasource_id)
- `ix_ds_semantic_status` = Index(status)
- `ix_ds_semantic_conn_id` = Index(connection_id)

---

### 2.2 表：`tableau_field_semantics`

字段语义版本表。

| 字段 | 类型 | 说明 |
|------|------|------|
| id | Integer, PK | 主键 |
| field_registry_id | Integer, FK | 关联 tableau_datasource_fields.id |
| connection_id | Integer, FK | 关联 TableauConnection |
| tableau_field_id | String(256) | Tableau 原始字段 ID |
| semantic_name | String(256) | 英文语义名 |
| semantic_name_zh | String(256) | 中文语义名 |
| semantic_definition | Text | 语义定义 |
| metric_definition | Text | 指标口径（如适用） |
| dimension_definition | Text | 维度解释（如适用） |
| unit | String(64) | 单位 |
| enum_desc_json | Text | 枚举值说明 JSON |
| tags_json | Text | JSON 标签数组 |
| synonyms_json | Text | JSON 同义词数组 |
| sensitivity_level | String(16) | low / medium / high / confidential |
| is_core_field | Boolean, default=False | 是否为核心字段 |
| ai_confidence | Float | AI 置信度 0~1 |
| status | String(32) | draft / ai_generated / reviewed / approved / published |
| source | String(16) | sync / manual / ai / imported |
| version | Integer, default=1 | 版本号 |
| published_to_tableau | Boolean, default=False | 是否已发布到 Tableau |
| published_at | DateTime | 最近发布时间 |
| created_by | Integer, FK | 创建人用户 ID |
| updated_by | Integer, FK | 更新人用户 ID |
| created_at | DateTime | 创建时间 |
| updated_at | DateTime | 更新时间 |

**索引：**
- `uq_field_semantic_conn_fid` = UniqueConstraint(connection_id, tableau_field_id)
- `ix_field_semantic_status` = Index(status)
- `ix_field_semantic_reg_id` = Index(field_registry_id)

---

### 2.3 表：`tableau_publish_log`

发布回写日志表。

| 字段 | 类型 | 说明 |
|------|------|------|
| id | Integer, PK | 主键 |
| connection_id | Integer, FK | 关联 TableauConnection |
| object_type | String(32) | datasource / field |
| object_id | Integer | 语义记录 ID |
| tableau_object_id | String(256) | Tableau 侧对象 ID |
| target_system | String(32) | tableau（当前仅支持 Tableau） |
| publish_payload_json | Text | 发布的完整 payload JSON |
| diff_json | Text | 变更差异 JSON |
| status | String(16) | pending / success / failed / rolled_back |
| response_summary | Text | 回写响应摘要 |
| operator | Integer, FK | 操作人用户 ID |
| created_at | DateTime | 创建时间 |

**索引：**
- `ix_publish_log_conn_status` = Index(connection_id, status)
- `ix_publish_log_object` = Index(object_type, object_id)

---

### 2.4 表：`tableau_field_semantic_versions`

字段语义历史版本表（轻量快照）。

| 字段 | 类型 | 说明 |
|------|------|------|
| id | Integer, PK | 主键 |
| field_semantic_id | Integer, FK | 关联 tableau_field_semantics.id |
| version | Integer | 版本号 |
| snapshot_json | Text | 该版本的完整快照 JSON |
| changed_by | Integer, FK | 变更人用户 ID |
| change_reason | Text | 变更原因 |
| created_at | DateTime | 创建时间 |

---

## 3. 服务层规格

### 3.1 SemanticMaintenanceDatabase

单例数据库管理类，继承现有 `TableauDatabase` 的线程安全模式。

**核心方法：**

```
# 数据源语义
create_datasource_semantics() → TableauDatasourceSemantics
get_datasource_semantics(conn_id, tableau_ds_id) → TableauDatasourceSemantics
upsert_datasource_semantics() → TableauDatasourceSemantics
list_datasource_semantics(conn_id, status=None, page=1, page_size=50) → (list, total)

# 字段语义
create_field_semantics() → TableauFieldSemantics
get_field_semantics(field_registry_id) → TableauFieldSemantics
upsert_field_semantics() → TableauFieldSemantics
list_field_semantics(conn_id, ds_id=None, status=None, page=1, page_size=50) → (list, total)
get_field_semantic_history(field_semantic_id) → list[TableauFieldSemanticVersions]

# 发布日志
create_publish_log() → TableauPublishLog
update_publish_log_status(log_id, status, response_summary=None)
list_publish_logs(conn_id, object_type=None, status=None, page=1, page_size=50) → (list, total)

# 状态流转
transition_datasource_status(ds_id, new_status, user_id, reason=None) → bool
transition_field_status(field_id, new_status, user_id, reason=None) → bool
```

---

### 3.2 SemanticMaintenanceService

语义业务逻辑层，**不依赖 sync_service**，独立运行。

#### 3.2.1 状态机

```
datasource_semantics / field_semantics 共用同一状态机：

draft ──→ ai_generated ──→ reviewed ──→ approved ──→ published
  ↑          │                  │
  └──────────┴── rejected ───────┘
```

**流转规则：**
- `draft → ai_generated`：调用 AI 生成语义草稿后自动转换
- `ai_generated → reviewed`：人工提交审核
- `reviewed → approved`：审核人点击通过
- `reviewed → rejected`：审核人驳回，返回 draft
- `approved → published`：发布服务确认回写成功
- `published → draft`：回滚后降级

#### 3.2.2 AI 语义生成

**输入：**
- 字段名（field_name）
- 数据类型（data_type）
- 角色（dimension / measure）
- 公式（formula）
- 示例值（enum_desc）
- 父数据源业务含义

**输出（AI 建议）：**
- semantic_name_zh（中文名）
- semantic_definition（语义定义）
- metric_definition / dimension_definition（口径/解释）
- unit（单位）
- synonyms_json（同义词）
- sensitivity_level（敏感级别）
- ai_confidence（置信度 0~1）
- tags_json（标签建议）

**原则：** AI 输出只作为 `ai_generated` 态建议，不自动流转到 reviewed。

#### 3.2.3 版本管理

每次 `upsert` 语义时：
1. 递增 `version`
2. 将旧版本完整快照写入 `tableau_field_semantic_versions`
3. `change_reason` 记录变更摘要

`rollback_to_version(version_id)`：从快照恢复并创建新版本。

---

### 3.3 FieldSyncService

字段级元数据同步服务，使用 **REST Metadata API**（非 TSC）。

#### 3.3.1 同步范围

文档 §4.1 字段级建议：

```
tableau_datasource_id / field_name / field_caption
field_role / data_type / formula / calculation
raw_description / is_hidden / example_values
semantic_hash（变更检测）synced_at
```

#### 3.3.2 API 端点

使用 Tableau REST API：
```
GET /api/{version}/sites/{site-id}/datasources/{datasource-id}/fields
```

#### 3.3.3 变更检测

每个字段计算 `semantic_hash = md5(field_name + data_type + formula)`，与上次同步结果对比，只更新变化的字段。

---

### 3.4 PublishService

回写发布服务，职责与 sync_service 完全对称（读取↔回写）。

#### 3.4.1 可回写字段白名单

文档 §7.2 建议只允许：

| Tableau 字段 | Mulan 语义字段 |
|---|---|
| description | semantic_description |
| caption | semantic_name_zh |
| isCertified | (通过 REST API 设置) |

**禁止自动回写：**
- 高敏感字段（sensitivity_level = confidential）
- 复杂业务口径（metric_definition 等内部字段）
- 标签、同义词等 Mulan 专属内容

#### 3.4.2 Diff 预览

发布前必须展示：

```
Tableau 当前值：
  description: "原始描述"

Mulan 待发布值：
  description: "业务语义描述"

差异摘要：description 已修改
影响范围：数据源 [xxx]，字段 [yyy]
发布人：[当前用户]
```

#### 3.4.3 回写 API

使用 Tableau REST API：
```
PUT /api/{version}/datasources/{datasource-id}
PUT /api/{version}/databases/{database-id}/tables/{table-id}/columns/{column-id}
```

#### 3.4.4 重试机制

- 回写失败自动重试 3 次，间隔 5s / 30s / 60s
- 重试仍失败状态标记为 `failed`，记录 `response_summary`
- 支持人工触发重试

---

## 4. API 路由规格

### 4.1 数据源语义

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | /api/semantic-maintenance/datasources | 列表（支持 status 过滤） |
| GET | /api/semantic-maintenance/datasources/{id} | 详情 |
| PUT | /api/semantic-maintenance/datasources/{id} | 更新语义（手动） |
| POST | /api/semantic-maintenance/datasources/{id}/generate-ai | AI 生成语义 |
| POST | /api/semantic-maintenance/datasources/{id}/submit-review | 提交审核 |
| POST | /api/semantic-maintenance/datasources/{id}/approve | 审核通过 |
| POST | /api/semantic-maintenance/datasources/{id}/reject | 审核驳回 |

### 4.2 字段语义

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | /api/semantic-maintenance/fields | 列表（支持 ds_id / status 过滤） |
| GET | /api/semantic-maintenance/fields/{id} | 详情 |
| PUT | /api/semantic-maintenance/fields/{id} | 更新语义（手动） |
| POST | /api/semantic-maintenance/fields/{id}/generate-ai | AI 生成语义 |
| POST | /api/semantic-maintenance/fields/{id}/submit-review | 提交审核 |
| POST | /api/semantic-maintenance/fields/{id}/approve | 审核通过 |
| POST | /api/semantic-maintenance/fields/{id}/reject | 审核驳回 |
| GET | /api/semantic-maintenance/fields/{id}/versions | 版本历史 |
| POST | /api/semantic-maintenance/fields/{id}/rollback/{version_id} | 回滚到指定版本 |

### 4.3 字段同步

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | /api/semantic-maintenance/connections/{conn_id}/sync-fields | 触发字段级同步 |
| GET | /api/semantic-maintenance/connections/{conn_id}/sync-fields/status | 同步状态 |

### 4.4 发布管理

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | /api/semantic-maintenance/publish/logs | 发布日志列表 |
| POST | /api/semantic-maintenance/publish/diff | 预览 Diff |
| POST | /api/semantic-maintenance/publish/datasource | 发布数据源语义 |
| POST | /api/semantic-maintenance/publish/fields | 批量发布字段语义 |
| POST | /api/semantic-maintenance/publish/retry/{log_id} | 重试失败发布 |
| POST | /api/semantic-maintenance/publish/rollback/{log_id} | 回滚发布 |

---

## 5. 安全与权限

### 5.1 状态流转权限

| 动作 | 允许角色 |
|------|---------|
| generate-ai | editor / admin |
| submit-review | editor / admin |
| approve / reject | reviewer / admin |
| publish | publisher / admin |
| rollback | admin |

### 5.2 敏感级别权限

- `confidential` 级别字段：只有 admin 可查看完整信息
- `high` 级别字段：需要 reviewer 及以上角色

---

## 6. 数据库迁移策略

使用 SQLite ALTER TABLE，通过 `SemanticMaintenanceDatabase._ensure_columns()` 实现：

```python
# 新增表（CREATE TABLE IF NOT EXISTS）
tableau_datasource_semantics
tableau_field_semantics
tableau_field_semantic_versions
tableau_publish_log

# 新增列（ALTER TABLE ADD COLUMN IF NOT EXISTS）
# 复用现有 tableau_connections / tableau_assets / tableau_datasource_fields 的FK关系
```

---

## 7. 实施顺序

### 第一批（核心闭环）
1. `semantic_maintenance/models.py` — 新增 4 张语义表
2. `semantic_maintenance/database.py` — 数据库管理
3. `semantic_maintenance/service.py` — 语义 CRUD + 状态机 + 版本管理
4. `backend/app/api/semantic_maintenance/` — API 路由接入

### 第二批（字段级同步）
5. `semantic_maintenance/field_sync.py` — 字段级同步服务
6. 字段同步 API 路由

### 第三批（发布回写）
7. `semantic_maintenance/publish_service.py` — 回写服务
8. Diff 预览 API
9. 发布日志 API

---

## 8. 不纳入本模块的内容

- AI 模型接入（依赖 llm/ 模块的能力）
- 前端页面（前端项目自行实现）
- 多 BI 平台抽象（未来扩展方向）
- 跨数据源口径统一（未来扩展方向）

---

## 9. 验收标准

- [ ] 现有 `sync_service.py` 零改动
- [ ] 现有 `models.py` 零改动
- [ ] 语义状态流转可正常运作（draft → published 完整链路）
- [ ] AI 生成语义不自动发布，必须人工审核
- [ ] 版本历史可查、可回滚
- [ ] 发布前 Diff 预览展示 Tableau 当前值 vs Mulan 待发布值
- [ ] 回写日志完整记录
- [ ] 高敏感字段禁止自动回写

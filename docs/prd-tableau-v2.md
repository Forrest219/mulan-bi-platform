# Tableau 模块 PRD v2.0 — 智能 BI 资产中心

> **文档版本**: v2.0
> **日期**: 2026-04-01
> **状态**: 设计评审中
> **关联文档**: `prd-tableau-mcp.md` (v1.2), `prd-llm-layer.md` (v0.1)
> **关联项目**: mulan-bi-platform, semantic-center

---

## 一、背景与目标

### 1.1 现状（Phase 1 已完成）

Phase 1 已交付的 Tableau 模块具备以下能力:

- **连接管理**: PAT 认证、支持 MCP/TSC 双模式、Fernet 加密存储 Token、多 Server/Site
- **资产同步**: 基于 tableauserverclient 同步 workbook/view/dashboard/datasource 四类资产
- **资产浏览**: 列表/卡片视图、项目树、类型筛选、关键词搜索
- **资产详情**: 基本信息展示 + 数据源关联表
- **AI 摘要**: 基于 `ASSET_SUMMARY_TEMPLATE` 调用 LLM 生成 100 字摘要（仅使用名称/项目/描述/所有者）

### 1.2 已识别问题

| 编号 | 问题 | 影响 |
|------|------|------|
| G1 | 同步仅获取最小元数据（无缩略图、view 无 owner/description） | 资产信息不完整 |
| G2 | view 未关联到父 workbook，缺少层级关系 | 无法展示报表结构 |
| G3 | AI 摘要仅用名称/描述，不接触实际数据和字段语义 | 解读浅层无价值 |
| G4 | 无定时同步、无同步日志 | 运维不透明 |
| G5 | 无法连接 Tableau 实际数据（仅浏览元数据） | 无法回答数据问题 |
| G6 | 无语义层——无业务术语解析、无字段级理解 | AI 无法做深度解读 |

### 1.3 升级目标

通过四个方向的升级，将 Tableau 模块从 **"资产目录浏览器"** 升级为 **"智能 BI 资产中心"**:

| 方向 | 一句话描述 | 核心价值 |
|------|-----------|---------|
| D1 深度 AI 解读 | 用字段语义 + 数据源元数据生成专业报表解读 | 让业务人员秒懂报表 |
| D2 Tableau MCP 直连 | 调用 Tableau MCP 工具实现实时数据查询 | 用自然语言查 Tableau 数据 |
| D3 资产治理增强 | 定时同步 + 同步日志 + 元数据健康度评分 | 资产可信可管 |
| D4 语义层融合 | 将 semantic-center 的术语库/Schema/RAG 嵌入 mulan | 让 AI 理解业务语言 |

### 1.4 非目标（v2.0 不做）

| 不做项 | 说明 |
|--------|------|
| Tableau Pulse Metrics 集成 | 依赖 Tableau Cloud，当前环境为 Tableau Server |
| 向量数据库（Milvus）引入 | 用 SQLite FTS5 满足当前规模 |
| 多语言支持 | 当前仅中文 |
| 报表自动生成/推荐 | 超出 v2.0 范围 |
| 用户级个性化推荐 | 超出 v2.0 范围 |

---

## 二、用户故事

| 角色 | 故事 | 阶段 |
|------|------|------|
| 业务分析师 | 我想在资产详情页看到详细的报表解读，包括关键指标含义、分析维度、适用场景 | 2a |
| 业务分析师 | 我想用自然语言问 "各区域销售额多少"，直接在 Mulan 里得到数据结果 | 2b |
| 业务分析师 | 我想查看报表的预览截图，不用打开 Tableau | 2b |
| BI 中心管理员 | 我想看到同步历史日志，知道每次同步了多少资产、是否有失败 | 2a |
| BI 中心管理员 | 我想配置定时同步，不需要每天手动点 | 2a |
| BI 中心管理员 | 我想看到每个资产的元数据健康度评分，快速定位质量差的资产 | 2b |
| 数据工程师 | 我想看到数据源的完整字段列表（字段名/中文名/类型/角色/公式） | 2b |
| 数据工程师 | 我想管理业务术语库，让 AI 理解 "收入" 等业务概念 | 2c |
| 数据工程师 | 我想用 AI 自动为缺少描述的字段生成标注建议 | 2c |
| 平台管理员 | 我想从 Tableau 数据源自动生成语义 Schema，减少手工维护 | 2c |

---

## 三、分阶段规划

### 3.0 阶段总览

```
Phase 2a (2~3 周)         Phase 2b (2~3 周)         Phase 2c (2~3 周)
───────────────────       ───────────────────       ───────────────────
- 同步增强 (D3)           - MCP 直连 (D2)           - 语义层融合 (D4)
- 深度 AI 解读 (D1)       - NL-to-Query (D2)        - RAG 知识问答 (D4)
- 同步日志 (D3)           - 资产健康度 (D3)          - AI 字段标注 (D4)
- 资产层级 (G2)           - 视图截图 (D2)            - 查询路由 (D4)
- 定时同步 (D3)           - 数据源字段元数据 (D2)     - 术语管理 (D4)
```

### 3.1 Phase 2a — 基础增强（P0）

**目标**: 补齐元数据短板，让 AI 解读从 "100 字摘要" 升级到 "专业报表解读"

| 功能项 | 优先级 | 方向 | 解决问题 |
|--------|--------|------|---------|
| 同步增强: 获取完整元数据（view 关联 workbook、server 时间戳） | P0 | D3 | G1, G2 |
| 资产层级关系: view/dashboard -> workbook 关联 | P0 | D3 | G2 |
| 深度 AI 解读: 使用增强版 Prompt + 数据源字段元数据 | P0 | D1 | G3 |
| 同步日志表 + API + 前端页面 | P0 | D3 | G4 |
| 定时同步（后台任务） | P1 | D3 | G4 |

### 3.2 Phase 2b — MCP 直连与治理（P1）

**目标**: 打通 Tableau 实际数据通道，支持自然语言查数据

| 功能项 | 优先级 | 方向 | 解决问题 |
|--------|--------|------|---------|
| 数据源元数据获取 (get-datasource-metadata) | P0 | D2 | G5 |
| 数据源查询 (query-datasource) | P0 | D2 | G5 |
| 自然语言转 VizQL JSON (NL-to-Query) | P1 | D2 | G5 |
| 视图截图获取 (get-view-image) | P1 | D2 | — |
| 资产健康度评分 | P1 | D3 | G1 |
| 过期资产检测 | P2 | D3 | — |

### 3.3 Phase 2c — 语义层融合（P1~P2）

**目标**: 将 semantic-center 核心能力嵌入 mulan，实现智能问答

| 功能项 | 优先级 | 方向 | 解决问题 |
|--------|--------|------|---------|
| 语义 Schema 自动生成（从 Tableau 元数据） | P1 | D4 | G6 |
| 业务术语知识库（glossary 导入/管理） | P1 | D4 | G6 |
| 查询路由（数据查询 vs 知识问答） | P1 | D4 | G6 |
| RAG 知识问答 | P2 | D4 | G6 |
| AI 辅助字段标注 | P2 | D4 | G6 |

---

## 四、数据模型变更

### 4.1 现有表变更

#### TableauAsset 新增字段

| 字段 | 类型 | 说明 | 阶段 |
|------|------|------|------|
| `parent_workbook_id` | VARCHAR(256) | 父工作簿的 tableau_id（view/dashboard 用） | 2a |
| `parent_workbook_name` | VARCHAR(256) | 父工作簿名称（冗余，方便查询） | 2a |
| `tags` | TEXT | JSON 数组，如 `["利润分析","季度报告"]` | 2a |
| `sheet_type` | VARCHAR(32) | 原始 sheet 类型 | 2a |
| `created_on_server` | DATETIME | Tableau 上的创建时间 | 2a |
| `updated_on_server` | DATETIME | Tableau 上的更新时间 | 2a |
| `view_count` | INTEGER | 使用次数/查看次数 | 2a |
| `ai_explain` | TEXT | 深度 AI 解读（替代短摘要） | 2a |
| `ai_explain_at` | DATETIME | 解读生成时间 | 2a |
| `health_score` | FLOAT | 元数据健康度评分 0~100 | 2b |
| `health_details` | TEXT | JSON，各项检查结果 | 2b |
| `field_count` | INTEGER | 字段数量（数据源类型） | 2b |
| `is_certified` | BOOLEAN | 是否已认证（数据源类型） | 2b |

#### TableauConnection 新增字段

| 字段 | 类型 | 说明 | 阶段 |
|------|------|------|------|
| `last_sync_duration_sec` | INTEGER | 上次同步耗时（秒） | 2a |
| `sync_status` | VARCHAR(16) | idle / running / failed | 2a |

### 4.2 新增表

#### tableau_sync_logs — 同步日志表（Phase 2a）

| 字段 | 类型 | 说明 |
|------|------|------|
| id | INTEGER PK | 主键 |
| connection_id | INTEGER FK | 关联连接 |
| trigger_type | VARCHAR(16) | `manual` / `scheduled` |
| started_at | DATETIME | 同步开始时间 |
| finished_at | DATETIME | 同步结束时间 |
| status | VARCHAR(16) | `running` / `success` / `partial` / `failed` |
| workbooks_synced | INTEGER | 同步工作簿数 |
| views_synced | INTEGER | 同步视图数 |
| dashboards_synced | INTEGER | 同步仪表盘数 |
| datasources_synced | INTEGER | 同步数据源数 |
| assets_deleted | INTEGER | 软删除资产数 |
| error_message | TEXT | 错误信息 |
| details | TEXT | JSON，每个资产类型的详细结果 |

#### tableau_datasource_fields — 数据源字段缓存表（Phase 2b）

| 字段 | 类型 | 说明 |
|------|------|------|
| id | INTEGER PK | 主键 |
| asset_id | INTEGER FK | 关联 datasource 类型资产 |
| datasource_luid | VARCHAR(256) | Tableau 数据源 LUID |
| field_name | VARCHAR(256) | 字段名 |
| field_caption | VARCHAR(256) | 中文显示名 |
| data_type | VARCHAR(64) | 数据类型 |
| role | VARCHAR(32) | `dimension` / `measure` |
| description | TEXT | 描述 |
| formula | TEXT | 计算字段公式 |
| aggregation | VARCHAR(32) | 聚合方式 |
| is_calculated | BOOLEAN | 是否计算字段 |
| metadata_json | TEXT | 完整原始元数据 |
| fetched_at | DATETIME | 获取时间 |
| ai_caption | VARCHAR(256) | AI 建议的中文名 |
| ai_description | TEXT | AI 建议的描述 |
| ai_role | VARCHAR(32) | AI 建议的角色 |
| ai_confidence | FLOAT | AI 标注置信度 |
| ai_annotated_at | DATETIME | AI 标注时间 |

#### semantic_schemas — 语义 Schema 表（Phase 2c）

| 字段 | 类型 | 说明 |
|------|------|------|
| id | INTEGER PK | 主键 |
| datasource_id | INTEGER FK | 关联 datasource 类型资产 |
| schema_yaml | TEXT | YAML 格式的语义 Schema |
| version | INTEGER | 版本号 |
| auto_generated | BOOLEAN | 是否自动生成 |
| created_at | DATETIME | 创建时间 |
| updated_at | DATETIME | 更新时间 |

#### semantic_glossary — 业务术语表（Phase 2c）

| 字段 | 类型 | 说明 |
|------|------|------|
| id | INTEGER PK | 主键 |
| term | VARCHAR(128) | 术语名称 |
| canonical_term | VARCHAR(128) | 标准术语 |
| synonyms | TEXT | JSON 数组，同义词 |
| definition | TEXT | 定义 |
| formula | TEXT | 计算公式 |
| category | VARCHAR(64) | 分类（revenue/user/product...） |
| source | VARCHAR(64) | 来源（manual/imported/ai_suggested） |
| created_at | DATETIME | 创建时间 |
| updated_at | DATETIME | 更新时间 |

---

## 五、API 设计

> 所有 API 需登录态。管理类操作需 `admin` 或 `data_admin` 角色。

### 5.1 Phase 2a — 同步增强 & AI 解读

#### 同步日志

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/tableau/connections/{conn_id}/sync-logs?page=&page_size=` | 同步日志列表（分页） |
| GET | `/api/tableau/connections/{conn_id}/sync-logs/{log_id}` | 同步日志详情 |

**SyncLog 响应结构**:
```json
{
  "id": 1,
  "connection_id": 1,
  "trigger_type": "manual",
  "started_at": "2026-04-01 10:00:00",
  "finished_at": "2026-04-01 10:02:15",
  "status": "success",
  "workbooks_synced": 3,
  "views_synced": 12,
  "dashboards_synced": 2,
  "datasources_synced": 2,
  "assets_deleted": 1,
  "error_message": null,
  "duration_sec": 135
}
```

#### 定时同步

| 方法 | 路径 | 说明 |
|------|------|------|
| PUT | `/api/tableau/connections/{conn_id}` | 更新 `auto_sync_enabled` + `sync_interval_hours` |
| GET | `/api/tableau/connections/{conn_id}/sync-status` | 当前同步状态 + 下次同步时间 |

#### 深度 AI 解读

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/tableau/assets/{asset_id}/explain` | 生成/获取深度解读 |

**请求 Body**: `{ "refresh": false }`

**响应**:
```json
{
  "explain": "## 报表概述\n这是一份...",
  "field_semantics": [
    { "field": "Sales", "caption": "销售额", "role": "measure", "meaning": "..." }
  ],
  "cached": true,
  "generated_at": "2026-04-01 10:00:00"
}
```

**内部流程**:
1. 获取资产基本信息（名称/项目/描述/所有者）
2. 获取关联数据源的字段元数据（从缓存表或实时调用 MCP `get-datasource-metadata`）
3. 查询语义术语表匹配业务术语（Phase 2c 可用后）
4. 组装增强版 Prompt
5. 调用 LLM 生成深度解读

#### 资产层级

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/tableau/assets/{asset_id}/children` | workbook 下属的 view/dashboard |
| GET | `/api/tableau/assets/{asset_id}/parent` | view/dashboard 的父 workbook |

### 5.2 Phase 2b — MCP 直连

#### 数据源元数据

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/tableau/datasources/{asset_id}/metadata` | 数据源字段元数据（缓存优先） |

**响应**:
```json
{
  "datasource_luid": "xxx",
  "fields": [
    {
      "name": "Sales",
      "caption": "销售额",
      "data_type": "REAL",
      "role": "MEASURE",
      "description": "...",
      "formula": null,
      "is_calculated": false
    }
  ],
  "cached": true,
  "fetched_at": "2026-04-01 10:00:00"
}
```

#### 数据查询

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/tableau/datasources/{asset_id}/query` | 自然语言数据查询 |

**请求 Body**:
```json
{
  "question": "各区域销售额是多少？",
  "limit": 100
}
```

**响应**:
```json
{
  "query_json": { "fields": [...], "filters": [...] },
  "data": [{ "Region": "华东", "SUM(Sales)": 120000 }],
  "explanation": "按区域维度汇总了销售额（SUM）",
  "fields_used": ["Region", "Sales"],
  "execution_time_ms": 230
}
```

**内部流程**:
1. 获取数据源字段元数据（缓存）
2. 加载语义 Schema + 术语表（如有）
3. LLM 将自然语言转为 `query-datasource` 的 JSON 参数
4. 调用 MCP `query-datasource` 执行查询
5. 格式化结果返回

#### 视图截图

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/tableau/views/{asset_id}/image?width=800&height=600` | 视图截图（PNG） |

#### 资产健康度

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/tableau/assets/{asset_id}/health` | 单个资产健康度 |
| GET | `/api/tableau/connections/{conn_id}/health-overview` | 连接级健康度总览 |

**单个资产健康度响应**:
```json
{
  "score": 65,
  "level": "warning",
  "checks": [
    { "item": "has_description", "pass": false, "weight": 20 },
    { "item": "has_owner", "pass": true, "weight": 15 },
    { "item": "has_datasource_link", "pass": true, "weight": 15 },
    { "item": "fields_have_captions", "pass": false, "weight": 20 },
    { "item": "is_certified", "pass": false, "weight": 10 },
    { "item": "naming_convention", "pass": true, "weight": 10 },
    { "item": "not_stale", "pass": true, "weight": 10 }
  ]
}
```

**健康度评分规则**:

| 检查项 | 权重 | 说明 |
|--------|------|------|
| has_description | 20 | 资产有描述 |
| has_owner | 15 | 资产有所有者 |
| has_datasource_link | 15 | 有关联数据源 |
| fields_have_captions | 20 | 数据源字段有中文 caption（仅 datasource 类型） |
| is_certified | 10 | 数据源已认证（仅 datasource 类型） |
| naming_convention | 10 | 命名符合规范 |
| not_stale | 10 | 非过期资产（Tableau 更新时间在 90 天内） |

**level 分级**: excellent(>=80) / good(>=60) / warning(>=40) / poor(<40)

**连接级总览响应**:
```json
{
  "total_assets": 20,
  "avg_score": 58,
  "distribution": { "excellent": 3, "good": 5, "warning": 8, "poor": 4 },
  "top_issues": [
    { "issue": "缺少描述", "count": 12 },
    { "issue": "字段无 caption", "count": 8 }
  ]
}
```

### 5.3 Phase 2c — 语义层

#### 语义 Schema 管理

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/semantic/schemas/generate` | 从 Tableau 数据源自动生成 Schema |
| GET | `/api/semantic/schemas?datasource_id=` | Schema 列表 |
| GET | `/api/semantic/schemas/{schema_id}` | Schema 详情 |
| PUT | `/api/semantic/schemas/{schema_id}` | 手动编辑 Schema |

#### 业务术语管理

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/semantic/glossary?category=&search=` | 术语列表（搜索/分类筛选） |
| POST | `/api/semantic/glossary` | 创建术语 |
| PUT | `/api/semantic/glossary/{term_id}` | 编辑术语 |
| DELETE | `/api/semantic/glossary/{term_id}` | 删除术语 |
| POST | `/api/semantic/glossary/import` | YAML 批量导入 |

#### 智能问答

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/semantic/ask` | 智能问答（自动路由） |

**请求 Body**:
```json
{
  "question": "各区域销售额是多少？",
  "datasource_id": 1,
  "context": "connection"
}
```

**响应**:
```json
{
  "query_type": "data",
  "answer": "各区域销售额如下...",
  "data": [...],
  "sources": ["数据查询"],
  "confidence": 0.9
}
```

#### AI 字段标注

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/semantic/annotate/fields` | 对数据源字段生成 AI 标注建议 |
| POST | `/api/semantic/annotate/fields/{field_id}/apply` | 确认并保存标注 |

---

## 六、前端页面变更

### 6.1 现有页面增强

#### 资产浏览页 `/tableau/assets` (Phase 2a)

- 每张资产卡片新增**健康度指示器**（绿/黄/红圆点）
- 新增**层级导航**: 点击 workbook 可展开下属 view/dashboard
- 新增**最近同步状态**指示（成功/失败/进行中）

#### 资产详情页 `/tableau/assets/:id` (Phase 2a + 2b)

- **"AI 解读" Tab 升级**: 从 100 字摘要升级为深度解读面板
  - 报表概述（2~3 段）
  - 关键指标列表（含业务含义）
  - 维度说明
  - 数据关注点
  - 适用场景建议
  - "重新生成" 按钮
- **新增 "字段元数据" Tab**: 数据源字段表格（字段名/中文名/类型/角色/描述/公式），仅 datasource 类型显示
- **新增 "健康度" Tab**: 各项检查结果 + 评分 + 整改建议
- **新增**: 视图截图预览（view/dashboard 类型资产）
- **新增**: 父工作簿/子视图面包屑导航

#### 连接管理页 `/tableau/connections` (Phase 2a)

- 每张连接卡片新增**同步状态**标签（idle/running/failed）
- 新增**"查看日志"** 按钮，跳转同步日志页

### 6.2 新增页面

#### 同步日志页 `/tableau/connections/:id/sync-logs` (Phase 2a)

- 同步历史表格: 时间、触发方式、状态、各类资产数量、耗时
- 点击展开查看详细日志
- 状态颜色标识: 成功=绿、部分失败=黄、失败=红

#### 数据查询页 `/tableau/query` (Phase 2b)

- 选择数据源（下拉选择已同步的 datasource 类型资产）
- 自然语言输入框
- 查询结果表格展示
- 查询解释面板（"我帮你查了..."）
- 字段元数据侧边栏（可折叠）

#### 资产健康度总览页 `/tableau/health` (Phase 2b)

- 连接级汇总卡片: 平均分、分布饼图
- 问题排行榜: 最常见的元数据问题
- 资产列表（按健康度排序），点击跳转详情

#### 术语管理页 `/admin/glossary` (Phase 2c)

- 术语列表: 搜索/分类筛选
- 新增/编辑术语表单
- YAML 批量导入
- AI 建议标记（source = ai_suggested 高亮显示）

#### 语义 Schema 管理页 `/admin/semantic-schemas` (Phase 2c)

- 按数据源列出已有 Schema
- "自动生成" 按钮
- YAML 编辑器
- 字段列表预览

---

## 七、Prompt 模板设计

### 7.1 深度解读模板（Phase 2a）

基于现有 `ASSET_EXPLAIN_TEMPLATE` 扩展:

```
你是一个 BI 报表解读专家。请根据以下报表信息，用通俗易懂的语言向业务用户解释这个报表。

## 报表基本信息
名称：{name}
类型：{asset_type}
项目：{project_name}
描述：{description}
所有者：{owner_name}

## 所属工作簿
{parent_workbook_info}

## 关联数据源
{datasources}

## 数据源字段元数据
{field_metadata}

## 业务术语参考
{glossary_context}

请提供以下内容:
1. **报表概述**: 用 2~3 句话说明这个报表的核心用途
2. **关键指标**: 列出报表涉及的主要指标，并用业务语言解释其含义
3. **维度说明**: 说明报表的主要分析维度
4. **数据关注点**: 指出使用此报表时需要注意的要点
5. **适用场景**: 建议在什么场景下使用此报表

要求:
- 面向非技术业务人员
- 使用中文
- 如果字段元数据中有计算字段公式，要解释其业务含义而非技术实现
```

### 7.2 NL-to-Query 模板（Phase 2b）

```
你是一个 Tableau 数据查询专家。请将用户的自然语言问题转换为 Tableau VizQL 查询 JSON。

## 可用数据源
数据源 LUID: {datasource_luid}
数据源名称: {datasource_name}

## 可用字段
{fields_with_types}

## 业务术语映射
{term_mappings}

## 业务规则
{business_rules}

## 用户问题
{question}

请生成符合以下格式的 JSON:
{{
  "fields": [
    {{"fieldCaption": "字段显示名", "function": "SUM"}},
    {{"fieldCaption": "维度字段"}}
  ],
  "filters": []
}}

规则:
- 度量字段必须指定 function (SUM/AVG/COUNT/COUNTD/MIN/MAX 等)
- 维度字段不需要 function
- 如需排序，添加 sortDirection ("ASC"/"DESC") 和 sortPriority
- 如需限制条数，使用 TOP 类型 filter
- 仅输出 JSON，不要其他内容
```

---

## 八、技术方案要点

### 8.1 同步增强方案（Phase 2a）

**View 关联 Workbook**: TSC 的 `view` 对象包含 `workbook_id` 属性。同步 view 时:
1. 记录 `parent_workbook_id = view.workbook_id`
2. 通过已同步的 workbook 资产反查 `parent_workbook_name`

**同步日志**: 在 `sync_all_assets()` 方法的开始和结束分别写入日志记录。使用 try/except 按资产类型记录成功/失败数量。

**定时同步**: 使用 FastAPI 的 `BackgroundTasks` + `asyncio` 定时器实现（不引入 APScheduler 等重依赖）。应用启动时检查所有 `auto_sync_enabled=True` 的连接并注册定时任务。

### 8.2 MCP 桥接方案（Phase 2b）

后端封装 Tableau MCP 调用为内部服务类:

```python
class TableauMCPClient:
    """Tableau MCP 工具调用客户端"""
    def get_datasource_metadata(self, datasource_luid: str) -> dict
    def query_datasource(self, datasource_luid: str, query: dict) -> dict
    def get_view_image(self, view_id: str, width=800, height=600) -> bytes
    def get_view_data(self, view_id: str) -> str  # CSV
    def search_content(self, terms: str, content_types: list) -> dict
```

MCP 工具通过 Tableau REST API 认证，复用已有连接的 PAT Token。

### 8.3 语义层嵌入方案（Phase 2c）

从 semantic-center 提取核心模块，作为 `src/semantic/` 包嵌入 mulan:

| semantic-center 原模块 | mulan 新模块 | 变化 |
|------------------------|-------------|------|
| `api/query_router.py` | `src/semantic/query_router.py` | 直接复用，动态加载关键词 |
| `api/glossary_search.py` | `src/semantic/glossary_service.py` | 数据源从 YAML 改为 SQLite |
| `knowledge/rag_pipeline.py` | `src/semantic/rag_service.py` | LLM 调用改用 mulan 的 LLMService |
| `annotations/ai_assisted.py` | `src/semantic/annotator.py` | LLM 调用改用 mulan 的 LLMService |
| `api/semantic_center.py` | **不嵌入** | Milvus 向量检索暂不引入 |
| `config/schemas.yaml` | DB 存储 | 改为 `semantic_schemas` 表 |
| `config/glossary.yaml` | DB 存储 | 改为 `semantic_glossary` 表 |

**关键决策**: 不引入 Milvus 依赖。Phase 2c 使用 SQLite FTS5 做术语/字段的模糊搜索。

### 8.4 Schema 自动生成流程（Phase 2c）

```
Tableau datasource (asset)
    │
    ▼
调用 get-datasource-metadata (MCP)
    │
    ▼
获取字段列表: name, dataType, role, description, formula...
    │
    ▼
LLM 辅助: 为缺失 caption/description 的字段生成建议
    │
    ▼
组装为 semantic schema YAML (兼容 semantic-center 格式)
    │
    ▼
存入 semantic_schemas 表
```

---

## 九、文件变更清单

### 后端

| 文件 | 变更类型 | 阶段 | 说明 |
|------|---------|------|------|
| `src/tableau/models.py` | 修改 | 2a | 新增 SyncLog、DatasourceField 模型，Asset 新字段 |
| `src/tableau/sync_service.py` | 修改 | 2a | 增强同步逻辑、写入同步日志、view-workbook 关联 |
| `backend/app/api/tableau.py` | 修改 | 2a+2b | 新增同步日志/AI解读/健康度/查询 API |
| `src/llm/prompts.py` | 修改 | 2a | 扩展解读模板，新增 NL-to-Query 模板 |
| `src/llm/service.py` | 修改 | 2a | 新增 `generate_asset_explain()` 方法 |
| `src/tableau/mcp_client.py` | **新增** | 2b | Tableau MCP 工具调用客户端 |
| `src/tableau/health.py` | **新增** | 2b | 资产健康度评分引擎 |
| `src/semantic/__init__.py` | **新增** | 2c | 语义层模块初始化 |
| `src/semantic/query_router.py` | **新增** | 2c | 查询路由（从 semantic-center 适配） |
| `src/semantic/glossary_service.py` | **新增** | 2c | 术语管理服务（SQLite 存储） |
| `src/semantic/rag_service.py` | **新增** | 2c | RAG 知识问答（从 semantic-center 适配） |
| `src/semantic/annotator.py` | **新增** | 2c | AI 字段标注（从 semantic-center 适配） |
| `src/semantic/schema_generator.py` | **新增** | 2c | 语义 Schema 自动生成 |
| `backend/app/api/semantic.py` | **新增** | 2c | 语义层 API 路由 |

### 前端

| 文件 | 变更类型 | 阶段 | 说明 |
|------|---------|------|------|
| `frontend/src/api/tableau.ts` | 修改 | 2a+2b | 新增类型定义和 API 函数 |
| `frontend/src/pages/tableau/asset-detail/page.tsx` | 修改 | 2a+2b | 升级 AI Tab、新增字段/健康度/截图 Tab |
| `frontend/src/pages/tableau/assets/page.tsx` | 修改 | 2a | 健康度指示器、层级导航 |
| `frontend/src/pages/tableau/sync-logs/page.tsx` | **新增** | 2a | 同步日志页 |
| `frontend/src/pages/tableau/query/page.tsx` | **新增** | 2b | 数据查询页 |
| `frontend/src/pages/tableau/health/page.tsx` | **新增** | 2b | 健康度总览页 |
| `frontend/src/pages/admin/glossary/page.tsx` | **新增** | 2c | 术语管理页 |
| `frontend/src/pages/admin/semantic-schemas/page.tsx` | **新增** | 2c | Schema 管理页 |
| `frontend/src/api/semantic.ts` | **新增** | 2c | 语义层 API 调用 |
| `frontend/src/router/config.tsx` | 修改 | 2a~2c | 注册新路由 |

---

## 十、验收标准

### Phase 2a 验收

| # | 验收项 | 验证方法 |
|---|--------|---------|
| A1 | 同步后 view/dashboard 有 parent_workbook_id | 查数据库确认 view 资产的 parent_workbook_id 非空 |
| A2 | 同步日志有记录 | 手动触发同步后，GET sync-logs 返回最新日志 |
| A3 | AI 深度解读包含字段语义 | 对含数据源关联的 workbook 调用 explain，结果包含"关键指标"和"维度说明" |
| A4 | 定时同步可配置并执行 | 开启 auto_sync，等待一个周期后确认有新 sync log |
| A5 | 资产详情页展示层级导航 | 打开 view 详情，能看到父 workbook 面包屑 |

### Phase 2b 验收

| # | 验收项 | 验证方法 |
|---|--------|---------|
| B1 | 可获取数据源字段元数据 | GET datasources/{id}/metadata 返回字段列表 |
| B2 | 自然语言查询返回数据 | POST query，输入"各区域销售额"，返回结果 |
| B3 | 视图截图可获取 | GET views/{id}/image 返回 PNG 图片 |
| B4 | 健康度评分可计算 | GET health 返回 score 和 checks 数组 |
| B5 | 健康度总览页可用 | 打开 /tableau/health 显示连接级汇总 |

### Phase 2c 验收

| # | 验收项 | 验证方法 |
|---|--------|---------|
| C1 | 可自动生成语义 Schema | POST schemas/generate 返回 YAML |
| C2 | 术语 CRUD 可用 | 创建/编辑/删除术语正常 |
| C3 | 术语 YAML 导入可用 | 导入 semantic-center 的 glossary.yaml，术语入库 |
| C4 | 查询路由正确分类 | "销售额是什么" → knowledge，"各区域销售额" → data |
| C5 | 知识问答可用 | 问"日耗收入和账单收入有什么区别"，返回术语对比 |
| C6 | AI 字段标注可用 | 对数据源触发标注，返回字段 caption/description 建议 |

---

## 十一、风险与依赖

| 风险 | 影响 | 缓解措施 |
|------|------|---------|
| Tableau MCP Server 不可用 | D2 全部功能受阻 | 优雅降级，MCP 不可用时仅展示缓存元数据 |
| Tableau Server 不支持部分 API | get-view-image 可能需要特定版本 | 功能检测 + 版本判断，不支持时隐藏 UI |
| LLM 调用延迟 > 10s | AI 解读/查询响应慢 | 异步生成 + 缓存，首次生成后缓存结果 |
| 字段元数据量大（>200 字段） | Prompt 超长 | 按相关性截取 top-N 字段，或分批处理 |
| SQLite 并发写入 | 定时同步与手动同步冲突 | 同步加锁（sync_status 状态机），同时只允许一次同步 |

---

## 十二、与现有模块的关系

| 已有能力 | 如何复用/整合 |
|----------|--------------|
| 数据源管理（Phase 2） | 复用加密存储模式、连接测试模式 |
| 用户认证 | 直接复用 Session/Cookie 体系 |
| 权限系统 | 新增 `semantic` 权限 key，`data_admin` + `analyst` 默认拥有 |
| DDL 检查 | Tableau 数据源字段元数据 → 可关联 DDL 规范检查结果 |
| LLM 能力层 | 深度解读/NL-to-Query/AI标注 全部通过 LLMService 调用 |
| semantic-center | 核心模块嵌入为 `src/semantic/`，YAML 配置迁移为 DB 存储 |

# 数据质量监控模块实现笔记 (Spec 15 v1.1)

> 基于 PRD 规格 v1.1，修复 P0 级阻塞后的完整实现记录。

---

## 修复清单

### 核心服务函数

| 函数名 | 所在文件 | 说明 |
|--------|---------|------|
| `QualityDatabase.create_rule()` | `services/governance/database.py` | 规则创建，含重复检测 |
| `QualityDatabase.get_enabled_rules()` | `services/governance/database.py` | 获取所有启用规则 |
| `QualityDatabase.append_score()` | `services/governance/database.py` | **Append-Only 追加评分（不 UPSERT）** |
| `QualityDatabase.get_score_trend()` | `services/governance/database.py` | 按日期聚合趋势查询 |
| `QualityDatabase.get_dashboard_summary()` | `services/governance/database.py` | 看板汇总统计 |
| `QualitySQLEngine.generate_sql()` | `services/governance/engine.py` | 跨方言 SQL 生成（SQLAlchemy Core） |
| `validate_custom_sql()` | `services/governance/engine.py` | 自定义 SQL 安全校验（辅助防护线） |
| `check_scan_row_limit()` | `services/governance/engine.py` | max_scan_rows 熔断检查 |
| `calculate_quality_score()` | `services/governance/scorer.py` | 三输入源整合评分 |
| `execute_quality_rules_task()` | `services/tasks/quality_tasks.py` | Celery 异步规则执行任务 |
| `cleanup_old_quality_results()` | `services/tasks/quality_tasks.py` | 90 天数据清理（Celery Beat 每日） |

### API 端点（13 个，全部对齐 PRD §4）

| Method | Path | Auth | 说明 |
|--------|------|------|------|
| POST | `/api/governance/quality/rules` | admin/data_admin | 创建质量规则 |
| GET | `/api/governance/quality/rules` | 已认证 | 规则列表（支持筛选） |
| GET | `/api/governance/quality/rules/{id}` | 已认证 | 规则详情 |
| PUT | `/api/governance/quality/rules/{id}` | admin/data_admin | 更新规则 |
| DELETE | `/api/governance/quality/rules/{id}` | admin/data_admin | 删除规则 |
| PUT | `/api/governance/quality/rules/{id}/toggle` | admin/data_admin | 启用/禁用规则 |
| POST | `/api/governance/quality/execute` | admin/data_admin | 手动触发检测 |
| POST | `/api/governance/quality/execute/rule/{id}` | admin/data_admin | 执行单条规则 |
| GET | `/api/governance/quality/results` | 已认证 | 检测结果列表 |
| GET | `/api/governance/quality/results/latest` | 已认证 | 各规则最新结果 |
| GET | `/api/governance/quality/scores` | 已认证 | 质量评分查询 |
| GET | `/api/governance/quality/scores/trend` | 已认证 | 评分趋势（近 30 天） |
| GET | `/api/governance/quality/dashboard` | 已认证 | 质量看板数据 |

---

## 对比校验表

| 功能点 | PRD 定义 | 实际实现状态 | 是否对齐 |
|--------|---------|-------------|---------|
| **bi_quality_scores 写入模式** | Append-Only（每次 INSERT，不 UPSERT） | `QualityDatabase.append_score()` 直接 INSERT，无 UPSERT | ✅ |
| **评分趋势查询** | 按 calculated_at 聚合近 N 天每日最新评分 | `get_score_trend()` 使用 `func.date(calculated_at).label("date")` + GROUP BY | ✅ |
| **SQL 方言约束** | 禁止硬编码原生 SQL，必须用 SQL Builder 适配方言 | `QualitySQLEngine.generate_sql()` 全程使用 SQLAlchemy Core，无硬编码字符串 | ✅ |
| **freshness 跨方言** | PostgreSQL/MySQL/SQL Server 各有专用函数 | `_freshness_sql()` 根据 `_dialect_name` 选择 `EXTRACT(EPOCH)` / `TIMESTAMPDIFF` / `DATEDIFF` | ✅ |
| **强制只读连接** | 检测连接强制 Read-Only，黑名单为辅助 | `_get_target_connection()` 中 PostgreSQL 传 `default_transaction_read_only=true`，MySQL/SQL Server 同样只读账号 | ✅ |
| **黑名单关键字** | 禁止 INSERT/UPDATE/DELETE/DROP/COPY 等 15 个关键字 | `FORBIDDEN_KEYWORDS` 列表包含全部禁止词，`validate_custom_sql()` 检测 | ✅ |
| **max_scan_rows 熔断** | 超过阈值记录警告并跳过执行 | `check_scan_row_limit()` 在 `execute_quality_rules_task()` 中执行前调用 | ✅ |
| **bi_quality_results 数据保留** | 默认 90 天，PostgreSQL 月分区 | `cleanup_old_quality_results()` Celery Beat 每日执行 DELETE with cutoff | ✅ |
| **三输入源评分整合** | 规则检测(50%) + 健康扫描(30%) + DDL合规(20%) | `calculate_quality_score()` 硬编码 `RULE_SCORE_WEIGHT=0.50` 等常量 | ✅ |
| **五维度评分** | 完整性(30%)/一致性(25%)/唯一性(20%)/时效性(15%)/格式规范(10%) | `DIMENSION_WEIGHTS` 字典硬编码，与 PRD §5.2 完全一致 | ✅ |
| **严重级别加权** | HIGH=3.0 / MEDIUM=2.0 / LOW=1.0 | `SEVERITY_WEIGHTS` 字典，与 PRD §5.3 一致 | ✅ |
| **数据源连接校验** | datasource_id 对应数据源存在且 `is_active=true` | 所有写操作 API 均调用 `DataSourceDatabase.get()` 验证 | ✅ |
| **自定义 SQL 限制** | 仅 SELECT，黑名单双重防护，read-only 连接强制 | `validate_custom_sql()` + `_get_target_connection()` 只读账号 + `default_transaction_read_only=true` | ✅ |
| **GOV_001~GOV_011 错误码** | PRD §7 定义 11 个错误码 | API 响应中返回 `"GOV_XXX"` 字符串，与 PRD §7 描述一致 | ✅ |
| **分区键** | executed_at（结果表）/ calculated_at（评分表） | 两表的分区键列均正确标注在注释中，迁移脚本有说明 | ✅ |

---

## 关键实现决策

### 1. Append-Only bi_quality_scores
PRD §2.1 和 §10.1 明确要求：评分快照每次计算后 **INSERT 新记录**，不做 UPSERT。实现通过 `append_score()` 直接 INSERT 实现，`get_latest_scores()` 通过子查询取每组最新 ID。

### 2. SQL 方言抽象
`QualitySQLEngine` 使用 SQLAlchemy Core 的 `func.count()`, `column()`, `table()` 等抽象 API，`_compile()` 动态传入目标 dialect 实现跨数据库兼容。

### 3. 强制只读连接
`_get_target_connection()` 构建连接 URL 时，对 PostgreSQL 额外传递 `default_transaction_read_only=true` 参数，并在连接建立后执行 `SET default_transaction_read_only = ON`，形成数据库层面的强制约束。

### 4. max_scan_rows 熔断
`_estimate_row_count()` 在执行前通过 `pg_class`（PostgreSQL）、`information_schema`（MySQL）等系统表预估行数，超过 `threshold.max_scan_rows` 时跳过执行并记录警告日志（GOV_007 降级为警告），不阻塞 Celery 任务流。

---

## 新增文件清单

| 文件路径 | 说明 |
|---------|------|
| `backend/services/governance/__init__.py` | 包初始化 |
| `backend/services/governance/models.py` | QualityRule / QualityResult / QualityScore 模型 |
| `backend/services/governance/database.py` | 数据库访问层（CRUD + 评分查询） |
| `backend/services/governance/engine.py` | SQL 生成引擎（跨方言 + 安全校验） |
| `backend/services/governance/scorer.py` | 评分计算器（维度评分 + 综合评分） |
| `backend/services/tasks/quality_tasks.py` | Celery 任务（规则执行 + 清理） |
| `backend/app/api/governance/__init__.py` | API 子包初始化 |
| `backend/app/api/governance/quality.py` | FastAPI 路由（13 个端点） |
| `backend/alembic/versions/add_quality_governance_tables.py` | 数据库迁移脚本 |

---

## 修改文件清单

| 文件路径 | 修改内容 |
|---------|---------|
| `backend/app/main.py` | 注册 `/api/governance/quality` 路由 |
| `backend/app/core/database.py` | `init_db()` 中导入 Quality* 模型 |
| `backend/services/tasks/__init__.py` | Celery Beat 增加 `quality-cleanup-old-results` 调度 |
| `docs/specs/15-data-governance-quality-spec.md` | v1.0 → v1.1，修复 5 个 P0/P1 级问题 |

---

## ⚠️ 技术冲突警报

**无。** 所有 PRD 设计与实现不存在无法逾越的底层技术冲突。以下为已识别但均已解决的细节：

1. **PostgreSQL 分区语法**：Alembic 迁移中分区语法（`PARTITION BY RANGE`）在 `CREATE TABLE ... PARTITION OF` 语句中手动处理，迁移脚本中有明确 NOTE 说明，Celery 清理任务通过 `DELETE WHERE executed_at < cutoff` 兜底。

2. **ClickHouse dialect**：环境中的 SQLAlchemy 不含 `clickhouse` 方言包，`QualitySQLEngine._dialect_name` 将 clickhouse 映射为 postgresql dialect 降级兼容，MySQL/SQL Server 等其他主流 DB 均完整支持。

3. **custom_sql 跨方言执行**：用户自定义 SQL 无法跨方言保证安全执行，PRD §8.2 约束 custom_sql 在强制只读连接（数据库层面约束）+ 黑名单双重防护下执行。

---

# 知识库模块实现笔记

## 概述

按 `docs/specs/17-knowledge-base-spec.md`（v1.0）实现知识库与 RAG 增强模块。

---

## 实现的文件

### 服务层（`backend/services/knowledge_base/`）

| 文件 | 类/函数 | 说明 |
|------|---------|------|
| `models.py` | `KbGlossary`, `KbSchema`, `KbDocument`, `KbEmbedding` | SQLAlchemy 模型（HNSW 索引，VECTOR 无硬编码维度） |
| `models.py` | `KbGlossaryDatabase` | 术语 CRUD + `match_by_term` 精确匹配 |
| `models.py` | `KbDocumentDatabase` | 文档 CRUD + `update_embedding_meta` |
| `models.py` | `KbEmbeddingDatabase` | 向量 upsert/batch_upsert + `search_by_vector`（余弦相似度，HNSW） |
| `glossary_service.py` | `GlossaryService` | 术语服务：精确匹配/模糊搜索/CRUD |
| `document_service.py` | `DocumentService` | 文档服务：CRUD + 滑动窗口分块 + 嵌入 |
| `embedding_service.py` | `EmbeddingService` | 向量服务：生成/批量生成/检索 |
| `rag_service.py` | `RAGService` | RAG 服务：动态 Token 预算（3000-200-上下文-800）|
| `__init__.py` | 模块导出 | 统一导出所有模型和服务 |

### API 层（`backend/app/api/`）

| 文件 | 端点 | 说明 |
|------|------|------|
| `knowledge_base.py` | `GET /api/kb/glossary` | 术语列表 |
| | `POST /api/kb/glossary` | 创建术语 |
| | `GET /api/kb/glossary/{id}` | 术语详情 |
| | `PUT /api/kb/glossary/{id}` | 更新术语 |
| | `DELETE /api/kb/glossary/{id}` | 删除术语（软删除）|
| | `GET /api/kb/documents` | 文档列表 |
| | `POST /api/kb/documents` | 创建文档 |
| | `POST /api/kb/documents/{id}/embed` | 文档向量化 |
| | `DELETE /api/kb/documents/{id}` | 删除文档 |
| | `GET /api/kb/search` | 知识检索（术语+向量混合）|
| | `POST /api/kb/rag/enrich` | RAG 上下文增强 |

### 迁移（`backend/alembic/versions/`）

| 文件 | 内容 |
|------|------|
| `add_knowledge_base_tables.py` | 创建 `kb_glossary`, `kb_schemas`, `kb_documents`, `kb_embeddings` 四张表；创建 HNSW 向量索引 `ix_emb_hnsw`（m=16, ef_construction=200）|

### 依赖更新

| 文件 | 变更 |
|------|------|
| `app/main.py` | 注册 `knowledge_base.router` at `/api/kb` |
| `app/core/database.py` | 导入 KB 模型（`KbGlossary`, `KbSchema`, `KbDocument`, `KbEmbedding`）|
| `alembic/env.py` | 导入 KB 模型供迁移使用 |
| `services/llm/service.py` | 新增 `generate_embedding()` 方法 |

---

## PRD 修订点实现确认

| PRD 条款 | 修订内容 | 实现状态 |
|----------|---------|---------|
| §2.2 | SSOT 原则标注（`kb_glossary` 是唯一术语入口）| ✅ 已添加注释 |
| §2.5 | IVFFlat → HNSW（m=16, ef_construction=200）| ✅ 迁移脚本使用 `USING hnsw` |
| §2.5 | `VECTOR(1536)` → `VECTOR`（解除硬编码维度）| ✅ JSONB 存储，无维度约束 |
| §6.2 | 动态 Token 预算公式：`3000 - 200 - 上下文 - 800` | ✅ `RAGService._calc_rag_budget()` |
| §12 | OI-01 "已解决（动态维度）"，OI-02 "已采用 HNSW" | ✅ 迁移脚本已实现 |

---

# NL-to-Query 流水线实现笔记（PRD §14）

## 新增 / 修改文件清单

| 文件路径 | 操作 |
|---------|------|
| `services/common/redis_cache.py` | **新增** — Redis 缓存封装（NLQ 路由防抖） |
| `services/llm/service.py` | **修改** — 新增 `complete_with_temp()` 方法（temperature 参数覆盖） |
| `services/llm/prompts.py` | **修改** — 新增 `ONE_PASS_NL_TO_QUERY_TEMPLATE` 和 `ONE_PASS_RETRY_TEMPLATE` |
| `services/llm/nlq_service.py` | **新增** — NL-to-Query 流水线核心服务 |
| `app/api/search.py` | **新增** — NL 搜索 API（`POST /api/search/query` 等） |
| `app/main.py` | **修改** — 注册 `search.router` at `/api/search` |

---

## 核心函数对照

| 函数 / 类 | 说明 | PRD 章节 |
|---------|------|---------|
| `one_pass_llm()` | One-Pass LLM 调用（temperature=0.1 硬编码，带反馈重试） | §5.1 |
| `validate_one_pass_output()` | JSON Schema 校验（intent/enum/function 全部枚举） | §5.4 |
| `_retry_with_feedback()` | 带报错信息的 JSON 重试 | §5.4 |
| `classify_intent()` | 意图分类规则快速路径（关键词匹配） | §3.3 |
| `route_datasource()` | 多数据源路由算法（调用 get_datasource_fields_cached） | §7.1 |
| `get_datasource_fields_cached()` | 带 Redis 缓存的字段查询（TTL=1h，防 N+1 风暴） | §7.1 |
| `calculate_routing_score()` | 路由评分公式（0.50×完备度 + 0.25×新鲜度 + 0.10×字段数 + 0.15×频次） | §7.3 |
| `resolve_fields()` | 字段解析（精确/同义词/语义/模糊匹配） | §4 |
| `format_response()` | 结果格式化（number/table/text） | §8 |
| `complete_with_temp()` | LLM 调用（temperature 参数覆盖，不继承全局 0.7） | §5.1 |

---

## 对比校验表

| 功能点 | PRD 定义 | 实际实现状态 | 是否对齐 |
|--------|----------|--------------|---------|
| LLM temperature | 硬编码 temperature = 0.1 | `one_pass_llm()` 内两次 `complete_with_temp(..., temperature=0.1)` | ✅ |
| JSON 校验失败重试 | 带报错信息反馈的重试（最多1次） | `_retry_with_feedback()` 将 `error_details` 追加到 Prompt 末尾后重试 | ✅ |
| 路由性能防抖 | `get_datasource_fields` 命中 Redis 缓存（field_caption 列表，1小时 TTL） | `get_datasource_fields_cached()` 先查 Redis，未命中查 DB 并回填 | ✅ |
| API 前缀 | `/api/search` | `app.include_router(search.router, prefix="/api/search")` | ✅ |
| 端点 POST /query | POST /api/search/query | `@router.post("/query")` → `/api/search/query` | ✅ |
| 端点 GET /suggestions | GET /api/search/suggestions | `@router.get("/suggestions")` → `/api/search/suggestions` | ✅ |
| 端点 GET /history | GET /api/search/history | `@router.get("/history")` → `/api/search/history` | ✅ |
| JSON Schema intent.enum | aggregate\|filter\|ranking\|trend\|comparison | `ONE_PASS_OUTPUT_SCHEMA` 完全一致 | ✅ |
| function enum | SUM/AVG/MEDIAN/COUNT/COUNTD/MIN/MAX + 时间粒度 | `ONE_PASS_OUTPUT_SCHEMA` 包含全部枚举值 | ✅ |
| MIN_ROUTING_SCORE | 0.3 | `MIN_ROUTING_SCORE = 0.3` | ✅ |
| 路由评分公式 | 0.50×字段完备度 + 0.25×新鲜度 + 0.10×字段数得分 + 0.15×频次得分 | `calculate_routing_score()` 完全按 PRD §7.3 公式实现 | ✅ |
| 规则快速路径 | 关键词命中时跳过 LLM | `classify_intent()` 在 One-Pass 前执行，命中返回 `IntentResult(source="rule")` | ✅ |
| 置信度阈值 | confidence < 0.5 → NLQ_002 | `one_pass_llm()` 返回后检查，低于 0.5 抛出 `NLQ_002` | ✅ |
| 权限要求 | analyst+ | `_require_role(user, "analyst")` 在所有端点执行 | ✅ |
| Prompt 模板 | 意图分类 + 查询构建合并为单次输出 | `ONE_PASS_NL_TO_QUERY_TEMPLATE` 输出 `{intent, confidence, vizql_json}` | ✅ |

---

## NL-to-Query PRD 对比校验表（Spec 14 v1.0）

| 功能点 | PRD 定义 | 实际实现状态 | 是否对齐 |
|--------|----------|--------------|---------|
| API 前缀 | `/api/search` | `app.include_router(search.router, prefix="/api/search")` | ✅ |
| 端点 POST /query | POST /api/search/query | `@router.post("/query")` → `/api/search/query` | ✅ |
| 端点 GET /suggestions | GET /api/search/suggestions | `@router.get("/suggestions")` → `/api/search/suggestions` | ✅ |
| 端点 GET /history | GET /api/search/history | `@router.get("/history")` → `/api/search/history` | ✅ |
| LLM temperature | 硬编码 temperature=0.1 | `complete_with_temp(..., temperature=0.1)` 硬编码 | ✅ |
| JSON 校验失败重试 | 带报错信息反馈的重试（最多1次） | `_retry_with_feedback()` 将 `error_details` 追加到 Prompt 末尾后重试 | ✅ |
| intent 枚举 | aggregate\|filter\|ranking\|trend\|comparison | `ONE_PASS_OUTPUT_SCHEMA` 完全一致 | ✅ |
| function 枚举 | SUM/AVG/COUNT/COUNTD/MIN/MAX/MEDIAN + 时间粒度 | `ONE_PASS_OUTPUT_SCHEMA` 包含全部枚举值 | ✅ |
| filter.field 嵌套 | `{"fieldCaption": "..."}` 对象，不是字符串 | `validate_one_pass_output` 检查 `isinstance(f["field"], dict)` | ✅ |
| DATE filter 必填字段 | periodType + dateRangeType | `validate_one_pass_output` 检查 DATE filter 必填字段 | ✅ |
| QUANTITATIVE RANGE | min + max | `validate_one_pass_output` 检查 RANGE 须同时有 min/max | ✅ |
| 路由性能防抖 | `get_datasource_fields` 命中 Redis 缓存（1小时 TTL） | `get_datasource_fields_cached()` 先查 Redis，未命中查 DB 并回填 | ✅ |
| MIN_ROUTING_SCORE | 0.3 | `MIN_ROUTING_SCORE = 0.3` | ✅ |
| 路由评分公式 | 0.50×字段完备度 + 0.25×新鲜度 + 0.10×字段数得分 + 0.15×频次得分 | `calculate_routing_score()` 完全按 PRD §7.3 公式实现 | ✅ |
| 规则快速路径 | 关键词命中时跳过 LLM | `classify_intent()` 在 One-Pass 前执行，命中返回 `IntentResult(source="rule")` | ✅ |
| 置信度阈值 | confidence < 0.5 → NLQ_002 | `one_pass_llm()` 返回后检查，低于 0.5 抛出 `NLQ_002` | ✅ |
| 权限要求 | analyst+ | `_require_role(user, "analyst")` 在所有端点执行 | ✅ |
| Prompt 模板 | 意图分类 + 查询构建合并为单次输出 | `ONE_PASS_NL_TO_QUERY_TEMPLATE` 输出 `{intent, confidence, vizql_json}` | ✅ |
| MCP 工具名 | `query-datasource` | `TableauMCPClient._build_jsonrpc_request()` method=query-datasource | ✅ |
| MCP env 注入 | TABLEAU_SERVER_URL/SITE/PAT_NAME/PAT_VALUE | `TableauMCPClient._decrypt_pat()` → `get_tableau_crypto().decrypt()` | ✅ |
| MCP Session 复用 | 禁止每次 new Session | `TableauMCPClient` 单例 + `requests.Session()` 连接池 | ✅ |
| MCP 重试策略 | 5xx 重试 1 次（间隔 1s），4xx 不重试 | `_send_jsonrpc()` 实现：attempt < 2 时 5xx 重试 | ✅ |
| NLQ_006/007/009 错误码 | §5.5.5 错误映射 | `TableauMCPError` → `NLQError` 映射表 | ✅ |
| MCP 响应格式（Stage 3） | `{"fields": [{fieldCaption, dataType}], "rows": [[...]]}` | `execute_query()` 返回格式一致 | ✅ |
| API 响应 number 格式 | `data: {value, label, unit, formatted}` | `search.py` 阶段4：从 MCP rows 提取标量，传标量给 `format_response` | ✅ |
| API 响应 table 格式 | `data: {columns: [{Name, label, type}], rows: [{col1: v1, col2: v2}]}` | `search.py` 阶段4：MCP rows 数组→对象数组，columns.name=fieldCaption | ✅ |
| Stage 3 → 4 数据转换 | MCP `rows: [[...]]` → format_response 兼容格式 | `search.py` 阶段4边界做转换，不破坏 format_response | ✅（修复前有bug）|
| options.limit | 默认 1000 | `options.get("limit", 1000)` | ✅ |
| options.timeout | 默认 30 | `options.get("timeout", 30)` | ✅ |
| options.response_type | auto/number/table/text | `response_type = options.get("response_type", "auto")` | ✅ |
| execution_time_ms | 实际耗时 | `time.time()` 计时，保留到毫秒 | ✅ |

**本次修复（Phase 2）的 2 个关键 bug**：

| bug | PRD 定义 | 修复前 | 修复后 |
|-----|----------|--------|--------|
| `format_response` number 值提取 | `value: 345678.0` | `value: [345678.0]`（从 `[[345678.0]]` 提取错误） | 阶段4边界提取 `mcp_rows[0][0]` 作为标量传入 |
| `format_response` table 列名推断 | `columns[].Name = fieldCaption` | `columns[].name` 从 row values 推断（错误迭代行值） | 直接从 `mcp_fields[i].fieldCaption` 构建 columns |

---

## Golden Dataset（测试资产）

| 文件 | 说明 |
|------|------|
| `backend/tests/fixtures/nlq_golden_dataset.py` | 21 组 Golden Case（新增 Case 21 模糊匹配），覆盖 aggregate/filter/ranking/trend/comparison 五种意图 |
| `backend/tests/test_nlq_pipeline.py` | Stage 1/3/4 校验 + 模糊匹配专项（TestFuzzyMatchingFieldBridge）|
| `backend/tests/fixtures/__init__.py` | fixtures 包初始化文件 |

**测试结果**：319 passed (21 cases × 15 base assertions + 4 fuzzy matching 专项断言)

**Stage 3 实现（§5.5.7）**：

| 约束 | 实现位置 | 状态 |
|------|---------|------|
| 约束 A | `mcp_client._decrypt_pat()` → `get_tableau_crypto().decrypt(token_encrypted)` 注入 `TABLEAU_SERVER_URL/SITE/PAT_NAME/PAT_VALUE` 到 MCP 请求 env 参数 | ✅ 已实现 |
| 约束 B | `TableauMCPClient` 单例 + `requests.Session()` 连接池（pool_maxsize=20），`_get_shared_session()` 全局复用 | ✅ 已实现 |
| 约束 C | `execute_query()` 在 `nlq_service.py` 中调用，vizql_json 由 Stage 1 生成，resolved_fields 由 Stage 2 校验 | ✅ 已实现 |
| Stage 3 placeholder 替换 | `search.py` 阶段3：`execute_query(ds_luid, vizql_json, limit, timeout)` 替代 `{"rows":[]}` | ✅ 已实现 |
| MCP Client 文件 | `services/tableau/mcp_client.py` | ✅ 新增 |
| execute_query 函数 | `services/llm/nlq_service.py` | ✅ 新增 |

**§10.1/10.2/10.3 实现（Phase 5）**：

| PRD 条款 | 实现内容 | 文件 | 状态 |
|---------|---------|------|------|
| §10.1 审计日志 | `NlqQueryLog` 模型（JSONB/vizql_json，仅结构不记结果）| `services/llm/models.py` | ✅ |
| §10.1 审计日志 | `log_nlq_query()` fire-and-forget 写入 | `services/llm/models.py` | ✅ |
| §10.1 审计日志 | endpoint `finally` 块调用 `log_nlq_query()` | `app/api/search.py` | ✅ 已完成（修复前缺失） |
| §10.1 审计日志 | Alembic 迁移 `nlq_query_logs` 表 | `alembic/versions/add_nlq_query_logs.py` | ✅ 新增 |
| §10.2 限速 | Redis 滑动窗口（ZREMRANGEBYSCORE/ZADD/ZCARD，20次/分钟）| `services/common/redis_cache.py` | ✅ |
| §10.2 限速 | `check_rate_limit(user_id)` 在 endpoint 参数校验第1步调用 | `app/api/search.py` | ✅ |
| §10.3 敏感度过滤 | `BLOCKED_SENSITIVITY = {"high", "confidential"}` | `services/llm/nlq_service.py` | ✅ |
| §10.3 敏感度过滤 | `is_datasource_sensitivity_blocked(luid)` 查询 `TableauDatasourceSemantics` | `services/llm/nlq_service.py` | ✅ |
| §10.3 敏感度过滤 | `route_datasource()` 过滤 BLOCKED 数据源后再评分 | `services/llm/nlq_service.py` | ✅ |
| §10.3 敏感度过滤 | 显式 luid 时在参数校验第3步拦截（NLQ_009）| `app/api/search.py` | ✅ |

**Alembic 迁移链**：`07c4d16b8335` → `a1b2c3d4e5f6` → `add_knowledge_base` → `add_nlq_query_logs`

**§10.1/10.2/10.3 PRD 对齐校验**：

| 功能点 | PRD 定义 | 实现状态 | 是否对齐 |
|--------|----------|---------|---------|
| 审计日志触发 | 每次请求（成功或失败）均记录 | `finally` 块无论路径均调用 `log_nlq_query()` | ✅ |
| 审计记录字段 | user_id/question/intent/datasource_luid/vizql_json/response_type/execution_time_ms/error_code | `NlqQueryLog` 模型完全一致 | ✅ |
| vizql_json 隔离 | 仅记录查询结构，不记录结果数据 | JSONB 列，`query_result` 数据不写入 | ✅ |
| 限速阈值 | 单用户 20 次/分钟 | `RATE_LIMIT_MAX = 20`，Redis ZCARD 检查 | ✅ |
| 限速实现 | Redis 滑动窗口计数器 | `zremrangebyscore` + `zadd` + `zcard` + `expire` | ✅ |
| 限速失败响应 | NLQ_010 | `raise _nlq_error_response("NLQ_010", ...)` | ✅ |
| 敏感度拦截 | HIGH/CONFIDENTIAL 级别禁止查询 | `BLOCKED_SENSITIVITY = {"high", "confidential"}` | ✅ |
| 敏感度 join | `TableauDatasourceSemantics.tableau_datasource_id` = `TableauAsset.datasource_luid` | `join(TableauDatasourceSemantics).filter(tableau_datasource_id == luid)` | ✅ |
| 隐式路由过滤 | `route_datasource()` 评分前过滤 BLOCKED | `is_datasource_sensitivity_blocked()` 在 `calculate_routing_score()` 前调用 | ✅ |
| 显式 luid 拦截 | 用户指定 luid 时直接拦截 | `is_datasource_sensitivity_blocked(datasource_luid)` 在参数校验第3步 | ✅ |

---

# 语义↔LLM 集成模块实现笔记（Spec 12 v1.1）

## 新增 / 修改文件清单

| 文件路径 | 操作 |
|---------|------|
| `services/semantic_maintenance/context_assembler.py` | **新增** — P0 前置：Token 估算 / 字段序列化 / P0-P5 优先级截断 / 敏感度过滤 |
| `services/semantic_maintenance/__init__.py` | **修改** — 导出 `ContextAssembler`, `BLOCKED_FOR_LLM`, `sanitize_fields_for_llm` |
| `services/llm/prompts.py` | **修改** — 新增 `AI_SEMANTIC_DS_TEMPLATE` 和 `AI_SEMANTIC_FIELD_TEMPLATE` |
| `services/semantic_maintenance/service.py` | **修改** — `generate_ai_draft_datasource/field` 重构为 ContextAssembler 驱动 |
| `requirements.txt` | **修改** — 新增 `tiktoken>=0.7.0`（精确 Token 估算） |

---

## 核心函数对照

| 函数 / 类 | 说明 | PRD 章节 |
|---------|------|---------|
| `estimate_tokens(text, encoder)` | tiktoken 精确估算，有则用 cl100k_base，无则回退字符法 | §3.2 OI-02 |
| `_classify_priority(field)` | P0~P5 优先级分类（P0=核心度量，P1=核心维度...）| §3.4 |
| `serialize_field(field, truncate_formula)` | 字段序列化为 `- {name} ({caption}) [{type}] [{role}]` 格式 | §3.3 |
| `sanitize_fields_for_llm(fields, blocked_levels)` | 移除 HIGH/CONFIDENTIAL 字段，枚举值截断 20 个 | §9.2 |
| `truncate_context(fields, budget_tokens, encoder)` | P0→P5 逐级添加，超预算即停 | §3.4 |
| `ContextAssembler.build_field_context()` | 对外主接口：sanitize → truncate → serialize | §3 |
| `ContextAssembler.build_datasource_context()` | 数据源上下文（Data Context Block）| §4.3 |
| `ContextAssembler.build_field_context_for_ds()` | 数据源 AI 生成中的字段上下文 | §4.3 |
| `_pre_llm_sensitivity_check()` | SLI_005 前置检查，敏感级别为 high/confidential 时返回错误 | §9.1 |
| `_parse_llm_json_response()` | 解析 ```code block``` 包裹的 JSON，兼容 LLM 输出格式 | §7.2 |
| `generate_ai_draft_datasource()` | AI 生成数据源语义草稿，ContextAssembler 驱动 | §5 |
| `generate_ai_draft_field()` | AI 生成字段语义草稿，ContextAssembler 驱动 | §5 |

---

## 对比校验表

| 功能点 | PRD 定义 | 实际实现状态 | 是否对齐 |
|--------|----------|--------------|---------|
| Token 上限 | 3000 max_context_tokens | `MAX_CONTEXT_TOKENS = 3000` | ✅ |
| System Prompt 预留 | 200 tokens | `SYSTEM_PROMPT_TOKENS = 200` | ✅ |
| User Instruction 预留 | 300 tokens | `USER_INSTRUCTION_TOKENS = 300` | ✅ |
| tiktoken 估算 | cl100k_base | `_get_token_estimator()` 懒加载 cl100k_base | ✅ |
| 字符回退 | 中文 1.5 token/字，英文 1.3 token/字 | `estimate_tokens()` 无 encoder 时回退 | ✅ |
| P0 核心度量 | is_core_field=True 且 role=measure | `_classify_priority()` 第一优先级 | ✅ |
| P1 核心维度 | is_core_field=True 且 role=dimension | `_classify_priority()` 第二优先级 | ✅ |
| P2 普通度量 | role=measure | `_classify_priority()` 第三优先级 | ✅ |
| P3 普通维度 | role=dimension | `_classify_priority()` 第四优先级 | ✅ |
| P4 计算字段 | 有 formula | `_classify_priority()` 第五优先级 | ✅ |
| P5 其他字段 | 其他 | `_classify_priority()` 最低优先级 | ✅ |
| 公式截断 | P2/P3 截断公式（不保留全文）| `serialize_field(truncate_formula=True)` 输出 `[公式已截断]` | ✅ |
| HIGH 过滤 | sensitivity_level=HIGH 不进入 LLM 上下文 | `BLOCKED_FOR_LLM = {"high", "confidential"}` | ✅ |
| CONFIDENTIAL 过滤 | sensitivity_level=CONFIDENTIAL 不进入 LLM 上下文 | `BLOCKED_FOR_LLM = {"high", "confidential"}` | ✅ |
| 枚举值截断 | 最多 20 个示例值 | `sanitize_fields_for_llm()` 中 `enum_values[:20]` | ✅ |
| SLI_005 前置检查 | 高敏感级别调用 AI 前返回错误 | `_pre_llm_sensitivity_check()` 在 LLM 调用前执行 | ✅ |
| JSON 解析 | 支持 ```code block``` 包裹 | `_parse_llm_json_response()` strip 后解 ``` | ✅ |
| AI_SEMANTIC_DS_TEMPLATE | §4.3 模板字段：ds_name/description/field_context 等 | `prompts.py` 完全一致 | ✅ |
| AI_SEMANTIC_FIELD_TEMPLATE | §4.4 模板字段：field_name/data_type/role/formula 等 | `prompts.py` 完全一致 | ✅ |
| ai_confidence 映射 | LLM 输出 `confidence`，ORM 映射到 `ai_confidence` 列 | `update_*_semantics()` 中 `ai_confidence=parsed.get("ai_confidence")` | ✅ |
| 状态转移 | AI 生成后 status=AI_GENERATED，source=AI | `generate_ai_draft_datasource()` 中硬编码 | ✅ |
| 变更原因 | AI 生成时 change_reason="ai_generated" | `db.update_*_semantics(..., change_reason="ai_generated")` | ✅ |
| Prompt 系统人设 | 数据源："专业的 BI 数据语义专家"；字段："专业的 BI 字段语义专家" | `generate_ai_draft_datasource/field` 中 system prompt | ✅ |

---

## 技术冲突警报

**无阻塞性冲突。** 以下为已识别并妥善处理的细节：

1. **tiktoken 未安装**：环境无 tiktoken 时，`_get_token_estimator()` 返回 None，`estimate_tokens()` 降级为保守字符估算（中 1.5/英 1.3 token/字），提示 WARNING 日志。建议安装 `pip install tiktoken`。

2. **Spec 12 与 Spec 14 边界**：Spec 12 v1.1 已移除 §6 NL-to-VizQL 协议内容，NL-to-Query 完整实现位于 `Spec 14 §NL-to-Query`。`AI_SEMANTIC_DS_TEMPLATE` 和 `AI_SEMANTIC_FIELD_TEMPLATE` 仅用于语义生成，不涉及 NL-to-VizQL 查询转换。

3. **confidence 与 ai_confidence 字段名**：LLM JSON 输出使用 `confidence`（符合 LLM 通用命名），ORM 层映射到数据库 `ai_confidence` 列（Spec 12 §5.3 v1.1 note 明确此映射关系）。

4. **BLOCKED_FOR_LLM 与 NLQ 的 BLOCKED_SENSITIVITY**：前者用于语义维护模块 AI 生成前的上下文过滤（Spec 12 §9.2），后者用于 NL-to-Query 路由过滤（Spec 14 §10.3），两者职责分离但定义一致（`{"high", "confidential"}`）。

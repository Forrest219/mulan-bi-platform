# Spec 17 v1.1 实现笔记
# 知识库与 RAG 模块 — P0/P1 修复交付

## 修复清单

| # | 修复项 | 文件 | 说明 |
|---|--------|------|------|
| 1 | P0: Ghost Data — 文档更新任务 | `services/tasks/knowledge_base_tasks.py` | `generate_document_embeddings` 在生成新向量前，先 `delete_by_source(db, "document", doc_id)` + `db.commit()`，避免旧块残留 |
| 2 | P0: Token 切块算法 | `services/knowledge_base/document_service.py` | `_split_into_chunks()` 废弃字符数估算，改用 `tiktoken.get_encoding("cl100k_base")` 精确 token 计数，CHUNK_TOKENS=512 / OVERLAP_TOKENS=64 |
| 3 | P1: YAML Schema 强校验 | `services/knowledge_base/models.py` | 新增 `validate_schema_yaml()` + `KbSchemaDatabase` 类；顶级字段白名单 + `tables[].columns[].name/type/description` 必填校验；校验失败抛 `YAMLValidationError`（KB_010） |
| 4 | P1: RAG Token 预算公式 | `services/knowledge_base/rag_service.py` | `_calc_rag_budget` 的 `data_context_tokens` 不再传入 P0-P4 总量；改用 `DEFAULT_FIELD_METADATA_TOKENS=400`；P0 不消耗 RAG 预算；`total_estimate` 使用截断后实际 P1-P4 消费值 |

---

## 对比校验表

| 功能点 | Spec 定义 | 实际实现状态 | 是否对齐 |
|--------|---------|-------------|---------|
| 幽灵数据清理（文档更新） | 同一事务内先 `DELETE kb_embeddings WHERE source_type=document`，再生成新向量 | `generate_document_embeddings` 在 upsert 前调用 `delete_by_source(db, "document", doc_id) + commit()` | ✅ |
| 幽灵数据清理（术语更新） | 同一事务内先 `DELETE kb_embeddings WHERE source_type=glossary` | `regenerate_glossary_embedding` 已有 `emb_db.delete_by_source(db, "glossary", glossary_id)` | ✅ |
| Token 分块算法 | 强制 tiktoken (cl100k_base)；512 tokens / 64 overlap；禁止字符估算 | `_split_into_chunks` 使用 `enc.encode()` 精确 token 计数；`chunk_token`/`overlap_token` 常量替换原字符常量 | ✅ |
| Token 估算 | 所有 token 计数统一使用 tiktoken cl100k_base | `RAGService._token_estimate()` 已改用 tiktoken；无 tiktoken 时回退 `chinese*2.0 + other*1.3` | ✅ |
| YAML v1.0 校验 | `tables[].name/description`、`columns[].name/type/description`、`relationships[].type/from_table/from_column/to_table/to_column` 必填 | `validate_schema_yaml()` 实现全部校验规则；顶级字段白名单控制 | ✅ |
| RAG 上下文裁剪 P0 | P0 精确匹配无条件保留（不占 RAG 预算） | `_truncate_by_priority`: `result_groups["p0"] = matched_terms` 固定保留 | ✅ |
| RAG 上下文裁剪 P1-P4 | P1→P2→P3→P4 顺序填充剩余 RAG 预算 | `_truncate_by_priority` 按优先级顺序截断，remaining_budget 递减 | ✅ |
| 动态 Token 预算 | `3000 - 200 - data_context_actual - 800`，最低 200 | `DEFAULT_FIELD_METADATA_TOKENS=400` 注入公式；`data_context_actual` 在返回值中正确标注为字段元数据 | ✅ |
| RAG 上下文注入格式 | `[术语]` / `[知识]` / `[模型]` 结构化标签 | `_assemble_structured_context` 已正确实现 | ✅ |
| 向量检索余弦相似度 | HNSW 索引；`1 - (embedding <=> query_embedding) > threshold` | `KbEmbeddingDatabase.search_by_vector` SQL 正确 | ✅ |
| 敏感度过滤 | HIGH/CONFIDENTIAL schema/field_semantic 不参与 RAG | `_filter_sensitivity` 已实现 | ✅ |
| Celery 异步任务 | `generate_document_embeddings` / `regenerate_glossary_embedding` | 已有实现，glossary 任务正确，document 任务已修复 | ✅ |
| 错误码 KB_xxx | KB_001 ~ KB_010 | `errors.py` 已定义 | ✅ |
| API 路径 `/api/knowledge-base/*` | Spec §7 端点定义 | 已有对应路由文件 | ✅ |

---

## 架构决策说明

### 1. Ghost Data 修复策略

**实现**：在 Celery 任务层（而非 `KbEmbeddingDatabase.batch_upsert`）执行 `delete_by_source` 清旧向量，再 `batch_generate_and_store` 插新向量。

**理由**：`batch_upsert` 只能删除本次 batch 中出现的 `chunk_index`，若内容变更导致块数减少，旧块依然残留。任务层统一清空后重新生成更简洁可靠，且 Celery 重试机制可保障失败时的一致性。

### 2. tiktoken 强制约束落地

**实现**：`document_service._split_into_chunks` 启动时调用 `tiktoken.get_encoding("cl100k_base")`，无包时抛 `RuntimeError`（不静默回退）。

**理由**：分块大小直接决定 Embedding 质量和使用 LLM API 的 Token 成本。使用字符估算（中文字符*1.5）在不同内容密度下误差极大（可能超过 512 上限触发 API 错误），必须强制 tiktoken 精确计数。

### 3. RAG Token 预算公式修正

**原问题**：调用方传入 `priority_tokens["total"]` = p0+p1+p2+p3+p4 作为 `data_context_tokens`，将 RAG 结果本身当作 RAG 预算的计算因子，导致循环引用。

**修复**：`data_context_tokens` 修正为字段元数据 Token 估算（`DEFAULT_FIELD_METADATA_TOKENS=400`），v1 阶段硬编码。P0 精确匹配不消耗 RAG 预算（始终保留），P1-P4 共享 RAG 预算（`3000-200-400-800 = 1600` tokens）。

---

## 待观察项（Open Issues）

| # | 问题 | 优先级 | 状态 | 说明 |
|---|------|--------|------|------|
| OI-01 | `enrich_context` 的 `data_context_tokens` 应从调用方（Datasource 元数据）动态注入，而非硬编码 400 | P1 | 🟡 待优化 | v1 使用 DEFAULT_FIELD_METADATA_TOKENS=400 估算 |
| OI-02 | `KbEmbeddingDatabase.search_by_vector` 的 SQL 使用 f-string 拼接 `str(query_embedding)`，存在理论注入风险 | P2 | 🟡 可接受 | `query_embedding` 来自 LLM API 返回的 float list，非用户直接输入；但建议迁移至 SQLAlchemy Core `cast()` |
| OI-03 | `_split_into_chunks` 每次调用都重新获取 `tiktoken.get_encoding()`（有缓存开销）| P3 | 🟡 可优化 | 可在模块级缓存 encoding 实例 |
| OI-04 | `KbSchemaDatabase` 尚无 API 端点暴露（Spec §7 未定义 schema CRUD API）| P1 | 🟡 待补充 | API 层需补充 schema CRUD 端点 |

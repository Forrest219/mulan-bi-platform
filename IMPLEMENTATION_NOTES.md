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

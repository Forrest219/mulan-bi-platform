# 知识库 HNSW 向量索引维护手册

> **Version:** v1.0
> **Date:** 2026-04-07
> **关联 Spec:** Spec 14 (NL-to-Query Pipeline) v1.1 §5.4

---

## 1. 索引概况

### 1.1 当前配置

| 参数 | 值 | 说明 |
|------|----|------|
| 索引名 | `ix_emb_hnsw` |  |
| 索引类型 | HNSW（层次可导航小世界图） | |
| 向量操作符 | `vector_cosine_ops` | 余弦距离 |
| 向量存储类型 | JSONB（1536 维 float 数组） | 查询时 cast to `::vector` |
| m（每层连接数） | 16 | pgvector 0.5 默认值 |
| ef_construction | 200 | 构建时的动态列表大小 |
| 表名 | `kb_embeddings` |  |
| 数据来源 | `document`, `glossary` |  |

**关键警告：`REINDEX CONCURRENTLY` 不支持 HNSW 索引（pgvector 0.5 限制）。执行 REINDEX 时会持有 `AccessExclusiveLock`，阻塞所有写入操作。**

### 1.2 索引用途

- `EmbeddingService.search()` 调用 `KbEmbeddingDatabase.search_by_vector()`
- RAG 查询时，对用户问题 embedding 做最近邻检索
- 检索结果用于 LLM 上下文注入

---

## 2. 自动维护任务

### 2.1 Celery Beat Schedule

| 任务 | 调度规则 | 说明 |
|------|----------|------|
| `hnsw-reindex` | 每月第一个周日凌晨 3:00 | REINDEX ix_emb_hnsw |
| `hnsw-vacuum-analyze` | 每周周日凌晨 3:00 | VACUUM ANALYZE kb_embeddings |
| `events-purge-old` | 每天凌晨 3:00 | bi_events 归档（90 天保留）|

配置位置：`backend/services/tasks/__init__.py` `beat_schedule`

### 2.2 `reindex_hnsw_task`

```python
# backend/services/services/tasks/knowledge_base_tasks.py

@shared_task
def reindex_hnsw_task():
    """重建 HNSW 向量索引（ix_emb_hnsw）"""
    with engine.connect() as conn:
        # 检查索引是否存在
        result = conn.execute(
            text("SELECT 1 FROM pg_indexes WHERE indexname = 'ix_emb_hnsw'")
        )
        # ...
        conn.execute(text("REINDEX INDEX ix_emb_hnsw"))
        conn.commit()
```

**执行时长估算：**

| kb_embeddings 行数 | 预估执行时间 |
|--------------------|-------------|
| < 10,000 | < 1 分钟 |
| 10,000–100,000 | 1–5 分钟 |
| 100,000–1,000,000 | 5–30 分钟 |
| > 1,000,000 | 30 分钟以上，建议业务低峰期执行 |

### 2.3 `vacuum_analyze_embeddings_task`

```python
@shared_task
def vacuum_analyze_embeddings_task():
    """对 kb_embeddings 表执行 VACUUM ANALYZE"""
    with engine.connect() as conn:
        conn.execute(text("VACUUM ANALYZE kb_embeddings"))
        conn.commit()
```

- 无锁，不阻塞读写
- 清理 dead tuples，更新统计信息
- 建议在 reindex 之后立即执行

---

## 3. 手动维护操作

### 3.1 紧急重建索引

当出现以下情况时，需要手动执行 REINDEX：

- 索引明显膨胀（`pg_relation_size('ix_emb_hnsw')` 远超数据量）
- 查询延迟异常升高
- 大量 delete/update 后索引碎片化

```sql
-- 确认当前索引大小
SELECT
    indexname,
    pg_size_pretty(pg_relation_size(indexname::regclass)) AS size
FROM pg_indexes
WHERE indexname = 'ix_emb_hnsw';

-- 查看表行数
SELECT COUNT(*) FROM kb_embeddings;

-- 执行重建（⚠️ 会阻塞写入，建议在维护窗口执行）
REINDEX INDEX ix_emb_hnsw;

-- 重建后再次检查大小
SELECT
    indexname,
    pg_size_pretty(pg_relation_size(indexname::regclass)) AS size
FROM pg_indexes
WHERE indexname = 'ix_emb_hnsw';
```

### 3.2 监控索引健康

```sql
-- 查看索引使用统计（自上次 ANALYZE 以来的扫描次数）
SELECT
    schemaname,
    tablename,
    indexname,
    idx_scan,
    idx_tup_read,
    idx_tup_fetch,
    pg_size_pretty(pg_relation_size(indexname::regclass)) AS index_size
FROM pg_stat_user_indexes
WHERE indexname = 'ix_emb_hnsw';

-- 查看表的 live/dead tuples
SELECT
    relname,
    n_live_tup,
    n_dead_tup,
    n_mod_since_analyze,
    last_vacuum,
    last_autovacuum,
    vacuum_count,
    autovacuum_count
FROM pg_stat_user_tables
WHERE relname = 'kb_embeddings';

-- 检查 pgvector 版本
SELECT extversion FROM pg_extension WHERE extname = 'vector';
```

### 3.3 索引碎片率检测

HNSW 索引碎片率可通过对比 `pg_relation_size`（表大小）和实际向量数据估算：

```sql
-- 估算平均每条记录大小（byte）
SELECT
    pg_size_pretty(
        pg_relation_size('kb_embeddings') / NULLIF COUNT(*), 1
    ) AS avg_row_size,
    COUNT(*) AS total_rows
FROM kb_embeddings;
```

如果平均行大小持续增长（无新增数据），说明存在索引膨胀。

---

## 4. pgvector 版本注意事项

| pgvector 版本 | REINDEX CONCURRENTLY | HNSW 支持 |
|--------------|----------------------|-----------|
| 0.4.x | ❌ 不支持 | ✅ 支持 |
| 0.5.x（当前） | ❌ 不支持 | ✅ 支持 |
| 0.6.x+ | ✅ 支持 | ✅ 支持 |

**升级 pgvector 到 0.6+ 后，可改用 `REINDEX INDEX CONCURRENTLY ix_emb_hnsw`，实现零停机重建。**

---

## 5. 告警阈值建议

建议在监控系统中设置以下告警：

| 指标 | 告警阈值 | 处理动作 |
|------|----------|----------|
| `ix_emb_hnsw` 索引大小 | 超过 10GB | 手动检查碎片化，触发 reindex |
| `kb_embeddings` dead_tuples | 超过行数 10% | 手动执行 VACUUM ANALYZE |
| `ix_emb_hnsw` idx_scan | 连续 7 天为 0 | 索引可能损坏，检查并重建 |
| 查询延迟（P99） | 超过 500ms | 检查索引是否有效，考虑重建 |

---

## 6. 维护窗口规划

### 建议时间窗口

| 任务 | 建议执行时间 |
|------|-------------|
| HNSW REINDEX | 每月第一个周日凌晨 2:00–4:00（低峰期） |
| VACUUM ANALYZE | 每周日凌晨 3:00（在 REINDEX 之后） |
| 手动紧急 REINDEX | 业务低峰期，提前通知用户 |

### 维护前检查清单

- [ ] 确认 Celery Beat 运行中：`celery -A services.tasks beat --detach`
- [ ] 确认 Worker 运行中：`celery -A services.tasks worker --detach`
- [ ] 检查当前索引大小和表行数
- [ ] 确认业务低峰期（无大批量导入/同步任务）
- [ ] （可选）将 PG 切换到单用户模式进行维护

---

## 7. 故障处理

### REINDEX 期间写入阻塞

**现象**：写入超时，`AccessExclusiveLock` 等待

**处理**：
1. 检查 `pg_locks` 确认锁状态：
   ```sql
   SELECT pid, relation::regclass, mode, granted
   FROM pg_locks
   WHERE relation = 'ix_emb_hnsw'::regclass;
   ```
2. 如果 REINDEX 已完成但锁未释放，杀掉持有锁的进程：
   ```sql
   SELECT pg_cancel_backend(pid);  -- 先尝试优雅取消
   SELECT pg_terminate_backend(pid);  -- 如果 cancel 失败，强制终止
   ```
3. 确认写入恢复：`SELECT COUNT(*) FROM kb_embeddings;`

### 向量维度不匹配（pgvector 0.5 升级后）

如果 embedding 维度变化（如 1536 → 1024），旧的 JSONB 存储无法直接用于新向量索引。

**处理**：
1. 备份旧向量数据
2. 清空 `kb_embeddings` 表
3. 重新执行 Embedding 生成任务

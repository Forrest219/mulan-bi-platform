"""
知识库 Celery 异步任务 — 包含 Embedding 生成和 HNSW 索引维护

HNSW 维护说明（Spec 14 v1.1 §5.4）：
- pgvector 0.5+ HNSW 索引参数：m=16, ef_construction=200
- REINDEX CONCURRENTLY 不支持 HNSW（pgvector 0.5 限制），须在维护窗口执行
- 建议每月低峰期执行一次 REINDEX，防止索引碎片化
"""
import logging

from celery import shared_task
from sqlalchemy import text

from app.core.database import engine
from services.tasks import celery_app
from services.tasks.decorators import beat_guarded

logger = logging.getLogger(__name__)


@celery_app.task(bind=True, max_retries=3, default_retry_delay=60)
def generate_document_embeddings(self, doc_id: int):
    """
    文档异步 Embedding 生成任务（PRD §4.3 副作用）。

    由 DocumentService.create_document() 触发，Celery Worker 异步执行：
    1. 分块文档内容
    2. 按 PRD §5.1 格式构造 Embedding 文本（document 类型直接用 chunk 原始文本）
    3. 调用 LLMService 生成向量并写入 kb_embeddings
    4. 更新 kb_documents.chunk_count 和 last_embedded_at
    """
    from app.core.database import SessionLocal
    from services.knowledge_base.models import KbDocument, KbDocumentDatabase, KbEmbeddingDatabase
    from services.knowledge_base.embedding_service import EmbeddingService

    db = SessionLocal()
    try:
        doc_db = KbDocumentDatabase()
        emb_db = KbEmbeddingDatabase()
        emb_svc = EmbeddingService()

        doc = doc_db.get(db, doc_id)
        if not doc:
            logger.warning("Document %d not found, skipping embedding task", doc_id)
            return {"status": "error", "message": "文档不存在"}

        # 重新获取 session 以确保关联正确
        db.refresh(doc)

        # 分块
        from services.knowledge_base.document_service import document_service
        chunks = document_service._split_into_chunks(doc.content)
        if not chunks:
            logger.warning("Document %d has empty content, skipping", doc_id)
            return {"status": "skipped", "message": "文档内容为空"}

        # 批量生成 Embedding（document 类型使用原始 chunk 文本）
        # Ghost Data Fix: 先删除旧向量，再插入新向量（同一事务外执行，由 Celery 重试保障）
        emb_db.delete_by_source(db, "document", doc_id)
        db.commit()

        import asyncio

        async def _batch_embed():
            return await emb_svc.batch_generate_and_store(
                db=db,
                source_type="document",
                source_id=doc_id,
                chunks=[{"chunk_index": i, "chunk_text": c} for i, c in enumerate(chunks)],
            )

        count = asyncio.run(_batch_embed())

        # 更新文档元数据
        doc_db.update_embedding_meta(db, doc_id, chunk_count=count)

        logger.info("Document %d embedding complete: %d chunks", doc_id, count)
        return {"status": "success", "doc_id": doc_id, "chunk_count": count}

    except Exception as e:
        logger.error("Document %d embedding failed: %s", doc_id, e, exc_info=True)
        raise self.retry(exc=e)
    finally:
        db.close()


@celery_app.task(bind=True, max_retries=3, default_retry_delay=60)
def regenerate_glossary_embedding(self, glossary_id: int):
    """
    术语 Embedding 重新生成任务（术语创建/更新时触发）。
    """
    from app.core.database import SessionLocal
    from services.knowledge_base.models import KbGlossary, KbGlossaryDatabase, KbEmbeddingDatabase
    from services.knowledge_base.embedding_service import EmbeddingService

    db = SessionLocal()
    try:
        glossary_db = KbGlossaryDatabase()
        emb_db = KbEmbeddingDatabase()
        emb_svc = EmbeddingService()

        glossary = glossary_db.get(db, glossary_id)
        if not glossary:
            logger.warning("Glossary %d not found", glossary_id)
            return {"status": "error", "message": "术语不存在"}

        # 删除旧记录
        emb_db.delete_by_source(db, "glossary", glossary_id)

        # 构造 Embedding 文本（glossary 格式）
        embedding_text = glossary.build_embedding_text()

        import asyncio

        async def _embed():
            return await emb_svc.generate_and_store(
                db=db,
                source_type="glossary",
                source_id=glossary_id,
                chunk_index=0,
                chunk_text=embedding_text,
            )

        asyncio.run(_embed())

        logger.info("Glossary %d embedding regenerated", glossary_id)
        return {"status": "success", "glossary_id": glossary_id}

    except Exception as e:
        logger.error("Glossary %d embedding failed: %s", glossary_id, e, exc_info=True)
        raise self.retry(exc=e)
    finally:
        db.close()


# ──────────────────────────────────────────────────────────────
# HNSW 索引维护任务（Spec 14 v1.1 §5.4）
# ──────────────────────────────────────────────────────────────

@shared_task
@beat_guarded("hnsw-reindex")
def reindex_hnsw_task():
    """
    重建 HNSW 向量索引（ix_emb_hnsw）。

    ⚠️  pgvector 0.5 不支持 REINDEX CONCURRENTLY，
        须在维护窗口执行（需要 AccessExclusiveLock，阻塞写入）。

    建议执行时间：每月第一个周日凌晨 03:00
    """
    try:
        with engine.connect() as conn:
            # 检查索引是否存在
            result = conn.execute(
                text("SELECT 1 FROM pg_indexes WHERE indexname = 'ix_emb_hnsw'")
            )
            if not result.fetchone():
                logger.warning("ix_emb_hnsw 索引不存在，跳过重建")
                return {"status": "skipped", "reason": "index_not_found"}

            # 记录重建前索引大小
            size_before = conn.execute(
                text("""
                    SELECT pg_size_pretty(pg_relation_size('ix_emb_hnsw'))
                """)
            ).scalar()

            # 重建索引（非并发，会阻塞写入，约需数秒到数分钟）
            conn.execute(text("REINDEX INDEX ix_emb_hnsw"))
            conn.commit()

            # 记录重建后索引大小
            size_after = conn.execute(
                text("""
                    SELECT pg_size_pretty(pg_relation_size('ix_emb_hnsw'))
                """)
            ).scalar()

            logger.info(
                "reindex_hnsw: done. size_before=%s, size_after=%s",
                size_before, size_after
            )
            return {"status": "success", "size_before": size_before, "size_after": size_after}

    except Exception as e:
        logger.error("reindex_hnsw failed: %s", e, exc_info=True)
        raise


@shared_task
@beat_guarded("hnsw-vacuum-analyze")
def vacuum_analyze_embeddings_task():
    """
    对 kb_embeddings 表执行 VACUUM ANALYZE。

    清理已删除记录、更新统计信息，保持查询计划准确性。
    无锁，不阻塞读写，建议每周期执行。

    建议执行时间：每周日凌晨 03:00（在 reindex_hnsw_task 之后）
    """
    try:
        with engine.connect() as conn:
            conn.execute(text("VACUUM ANALYZE kb_embeddings"))
            conn.commit()

            # 记录表统计信息
            stats = conn.execute(
                text("""
                    SELECT
                        pg_size_pretty(pg_relation_size('kb_embeddings')),
                        pg_size_pretty(pg_total_relation_size('kb_embeddings')),
                        n_live_tup,
                        n_dead_tup,
                        last_vacuum,
                        last_autovacuum
                    FROM pg_stat_user_tables
                    WHERE relname = 'kb_embeddings'
                """)
            ).fetchone()

            logger.info(
                "vacuum_analyze_embeddings: table_size=%s, total_size=%s, "
                "live_tuples=%s, dead_tuples=%s, last_vacuum=%s, last_autovacuum=%s",
                stats[0], stats[1], stats[2], stats[3], stats[4], stats[5]
            )
            return {
                "status": "success",
                "table_size": stats[0],
                "total_size": stats[1],
                "live_tuples": stats[2],
                "dead_tuples": stats[3],
                "last_vacuum": str(stats[4]),
                "last_autovacuum": str(stats[5]),
            }

    except Exception as e:
        logger.error("vacuum_analyze_embeddings failed: %s", e, exc_info=True)
        raise

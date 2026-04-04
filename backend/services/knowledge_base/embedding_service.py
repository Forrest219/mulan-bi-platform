"""Embedding 服务（知识库 §5）"""
import logging
from typing import List, Dict, Any

from sqlalchemy.orm import Session

from .models import KbEmbedding, KbEmbeddingDatabase
from services.llm.service import llm_service

logger = logging.getLogger(__name__)


class EmbeddingService:
    """向量嵌入服务 — 生成 + 存储 + 检索"""

    def __init__(self):
        self._db = KbEmbeddingDatabase()

    async def generate_and_store(
        self, db: Session, source_type: str, source_id: int,
        chunk_index: int, chunk_text: str, model: str = "text-embedding-3-small"
    ) -> KbEmbedding:
        """
        生成单条 Embedding 并存储（PRD §5.1）。
        1. 调用 LLMService.generate_embedding() 生成向量
        2. 写入 kb_embeddings
        """
        result = await llm_service.generate_embedding(text=chunk_text, model=model)
        if "error" in result:
            raise RuntimeError(f"Embedding 生成失败: {result['error']}")

        embedding = result["embedding"]
        token_count = result.get("token_count")

        return self._db.upsert(
            db=db,
            source_type=source_type,
            source_id=source_id,
            chunk_index=chunk_index,
            chunk_text=chunk_text,
            embedding=embedding,
            model_name=model,
            token_count=token_count,
        )

    async def batch_generate_and_store(
        self, db: Session, source_type: str, source_id: int,
        chunks: List[Dict[str, Any]], model: str = "text-embedding-3-small"
    ) -> int:
        """
        批量生成并存储 Embedding（PRD §5.2）。
        chunks: [{"chunk_index": int, "chunk_text": str}, ...]
        返回成功写入的记录数。
        """
        from services.llm.service import llm_service

        records = []
        for chunk in chunks:
            result = await llm_service.generate_embedding(
                text=chunk["chunk_text"], model=model
            )
            if "error" in result:
                logger.warning(
                    "Embedding 生成失败 [%s/%s] chunk_index=%d: %s",
                    source_type, source_id, chunk["chunk_index"], result["error"]
                )
                continue

            records.append({
                "source_type": source_type,
                "source_id": source_id,
                "chunk_index": chunk["chunk_index"],
                "chunk_text": chunk["chunk_text"],
                "embedding": result["embedding"],
                "model_name": model,
                "token_count": result.get("token_count"),
            })

        return self._db.batch_upsert(db, records)

    def search(
        self, db: Session, query_embedding: List[float],
        top_k: int = 5, threshold: float = 0.7, source_type: str = None
    ) -> List[Dict[str, Any]]:
        """
        向量相似度检索（PRD §5.3，HNSW 索引）。
        使用余弦相似度 1 - cosine_distance，按 similarity 降序返回。
        """
        return self._db.search_by_vector(
            db=db,
            query_embedding=query_embedding,
            top_k=top_k,
            threshold=threshold,
            source_type=source_type,
        )

    async def embed_text(self, text: str, model: str = "text-embedding-3-small") -> List[float]:
        """对外暴露的 Embedding 生成接口（供 RAG 服务调用）"""
        result = await llm_service.generate_embedding(text=text, model=model)
        if "error" in result:
            raise RuntimeError(f"Embedding 生成失败: {result['error']}")
        return result["embedding"]


embedding_service = EmbeddingService()

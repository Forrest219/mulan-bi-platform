"""基于 embedding 的字段召回（PRD §14 §3.1）

cosine Top-K 召回字段语义。
"""
from __future__ import annotations

import logging
from typing import Any, Optional

from sqlalchemy import text

from app.core.database import SessionLocal
from services.llm.service import llm_service

logger = logging.getLogger(__name__)

DEFAULT_TOP_K = 10
MAX_CONTEXT_FIELDS = 10


async def recall_fields(
    question: str,
    datasource_ids: Optional[list[int]] = None,
    top_k: int = DEFAULT_TOP_K,
) -> list[dict[str, Any]]:
    """对 question 做 embedding → cosine Top-K 召回字段语义。

    Returns: [{
        "id": int,
        "datasource_id": int,
        "semantic_name": str,
        "semantic_name_zh": str,
        "metric_definition": str,
        "dimension_definition": str,
        "unit": str,
        "similarity": float,
    }, ...]
    """
    emb_result = await llm_service.generate_embedding("query: " + question)
    if "error" in emb_result:
        raise RuntimeError(f"embedding 失败: {emb_result['error']}")
    query_vec = emb_result["embedding"]

    where_ds = ""
    params: dict[str, Any] = {"query_vec": str(query_vec), "top_k": min(top_k, MAX_CONTEXT_FIELDS)}
    if datasource_ids:
        where_ds = "AND connection_id = ANY(:dsids)"
        params["dsids"] = datasource_ids

    # Use 1 - (embedding <=> query_vec) for cosine similarity
    sql = text(f"""
        SELECT
            id,
            connection_id,
            semantic_name,
            semantic_name_zh,
            metric_definition,
            dimension_definition,
            unit,
            1 - (embedding <=> (:query_vec)::vector) AS similarity
        FROM tableau_field_semantics
        WHERE embedding IS NOT NULL {where_ds}
        ORDER BY embedding <=> (:query_vec)::vector
        LIMIT :top_k
    """)
    db = SessionLocal()
    try:
        rows = db.execute(sql, params).fetchall()
        return [dict(r._mapping) for r in rows]
    finally:
        db.close()

"""
回填 tableau_field_semantics.embedding

幂等: WHERE embedding IS NULL
批量: 每次 32 条 texts 发一次 MiniMax
限速: 默认 2 req/s（可配置）
可恢复: 失败写日志，下次重跑跳过已填
"""
import argparse
import asyncio
import logging
import sys
import time
from pathlib import Path
from typing import Optional

# Add backend to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy import text
from app.core.database import SessionLocal
from services.llm.service import llm_service

BATCH_SIZE = 32
RATE_LIMIT_SECONDS = 0.5  # 2 req/s


def build_text(row) -> str:
    """
    字段语义拼装: 优先 semantic_name_zh > semantic_name >
    metric_definition > dimension_definition > tags_json
    """
    parts = [
        row.semantic_name_zh or row.semantic_name or "",
        row.metric_definition or "",
        row.dimension_definition or "",
        " ".join(row.tags_json) if row.tags_json else "",
    ]
    return " · ".join([p for p in parts if p])[:512]


async def run(datasource_id: Optional[int], dry_run: bool):
    db = SessionLocal()
    where = "embedding IS NULL"
    params = {}
    if datasource_id:
        where += " AND datasource_id = :dsid"
        params["dsid"] = datasource_id

    rows = db.execute(
        text(
            f"SELECT id, semantic_name, semantic_name_zh, "
            f"metric_definition, dimension_definition, tags_json "
            f"FROM tableau_field_semantics WHERE {where}"
        ),
        params,
    ).fetchall()

    logging.info("待回填 %d 条", len(rows))
    if dry_run:
        for r in rows[:5]:
            logging.info("  [%s] %s", r.id, build_text(r))
        db.close()
        return

    for i in range(0, len(rows), BATCH_SIZE):
        batch = rows[i : i + BATCH_SIZE]
        texts = [build_text(r) for r in batch]
        result = await llm_service.generate_embedding_minimax(texts, type="db")
        if "error" in result:
            logging.error("batch %d 失败: %s", i, result["error"])
            time.sleep(RATE_LIMIT_SECONDS)
            continue
        for r, emb in zip(batch, result["embeddings"]):
            db.execute(
                text(
                    "UPDATE tableau_field_semantics "
                    "SET embedding = :emb::vector, "
                    "embedding_model = 'embo-01', "
                    "embedding_generated_at = NOW() "
                    "WHERE id = :id"
                ),
                {"emb": str(emb), "id": r.id},
            )
        db.commit()
        logging.info("已填 %d/%d", min(i + BATCH_SIZE, len(rows)), len(rows))
        time.sleep(RATE_LIMIT_SECONDS)

    db.close()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    p = argparse.ArgumentParser(description="回填 tableau_field_semantics.embedding")
    p.add_argument("--datasource-id", type=int, default=None, help="仅回填指定数据源")
    p.add_argument("--dry-run", action="store_true", help="仅打印前 5 条拼装文本")
    args = p.parse_args()
    asyncio.run(run(args.datasource_id, args.dry_run))

"""fix kb_embeddings.embedding column type JSONB -> Vector(1024)

Revision ID: 20260428_0001
Revises: 20260427_0001
"""
from typing import Union

from alembic import op
import sqlalchemy as sa

revision: str = "20260428_0001"
down_revision: Union[str, None] = "20260427_0001"

EMBEDDING_DIM = 1024


def upgrade():
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    op.execute(
        f"ALTER TABLE kb_embeddings "
        f"ALTER COLUMN embedding TYPE vector({EMBEDDING_DIM}) "
        f"USING embedding::text::vector({EMBEDDING_DIM})"
    )

    op.execute(
        "CREATE INDEX ix_kb_emb_hnsw ON kb_embeddings "
        "USING hnsw (embedding vector_cosine_ops) WITH (m=16, ef_construction=200)"
    )


def downgrade():
    op.execute("DROP INDEX IF EXISTS ix_kb_emb_hnsw")

    op.execute(
        "ALTER TABLE kb_embeddings "
        "ALTER COLUMN embedding TYPE jsonb "
        "USING embedding::text::jsonb"
    )

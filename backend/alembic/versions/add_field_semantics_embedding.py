"""add embedding column to tableau_field_semantics

Revision ID: add_field_semantics_embedding
Revises: add_quality_tables_v1
"""
from typing import Union

from alembic import op
import sqlalchemy as sa
from pgvector.sqlalchemy import Vector

revision = "add_field_semantics_embedding"
down_revision = "add_quality_tables_v1"

# MiniMax embo-01 embedding dimension (confirmed by MiniMax API spec)
EMBEDDING_DIM = 1024


def upgrade():
    # Ensure vector extension exists (idempotent)
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    op.add_column(
        "tableau_field_semantics",
        sa.Column("embedding", Vector(EMBEDDING_DIM), nullable=True),
    )
    op.add_column(
        "tableau_field_semantics",
        sa.Column("embedding_model", sa.String(64), nullable=True),
    )
    op.add_column(
        "tableau_field_semantics",
        sa.Column("embedding_generated_at", sa.DateTime, nullable=True),
    )

    op.execute(
        "CREATE INDEX ix_tfs_embedding_hnsw ON tableau_field_semantics "
        "USING hnsw (embedding vector_cosine_ops) WITH (m=16, ef_construction=200)"
    )


def downgrade():
    op.execute("DROP INDEX IF EXISTS ix_tfs_embedding_hnsw")
    op.drop_column("tableau_field_semantics", "embedding_generated_at")
    op.drop_column("tableau_field_semantics", "embedding_model")
    op.drop_column("tableau_field_semantics", "embedding")

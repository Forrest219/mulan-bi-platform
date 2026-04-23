"""add chunk_text column to tableau_field_semantics

Revision ID: add_field_semantics_chunk_text
Revises: add_field_semantics_embedding
"""
from typing import Union

from alembic import op
import sqlalchemy as sa

revision = "add_field_semantics_chunk_text"
down_revision = "add_field_semantics_embedding"


def upgrade():
    op.add_column(
        "tableau_field_semantics",
        sa.Column("chunk_text", sa.Text, nullable=True),
    )


def downgrade():
    op.drop_column("tableau_field_semantics", "chunk_text")

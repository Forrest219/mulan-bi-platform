"""add query_feedback table for ask-data thumbs up/down

Revision ID: add_query_feedback_table
Revises: add_tableau_assets_composite_idx
"""
from alembic import op
import sqlalchemy as sa

revision = "add_query_feedback_table"
down_revision = "add_tableau_assets_composite_idx"


def upgrade():
    op.create_table(
        "query_feedback",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("user_id", sa.Integer, nullable=False),
        sa.Column("username", sa.String(128), nullable=False, server_default=""),
        sa.Column("trace_id", sa.String(64), nullable=False),
        sa.Column("rating", sa.String(4), nullable=False),
        sa.Column("question", sa.Text, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("rating IN ('up', 'down')", name="ck_query_feedback_rating"),
    )
    op.create_index("ix_query_feedback_trace_id", "query_feedback", ["trace_id"])
    op.create_index("ix_query_feedback_user_id", "query_feedback", ["user_id"])


def downgrade():
    op.drop_table("query_feedback")

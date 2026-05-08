"""add_token_usage_logs

Revision ID: 20260508_120000
Revises: fc37b0a529f5, 20260508_000003
Create Date: 2026-05-08 12:00:00.000000
"""
from alembic import op
import sqlalchemy as sa

revision = "20260508_120000"
down_revision = ("fc37b0a529f5", "20260508_000003")
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "ai_token_usage_logs",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("user_id", sa.Integer(), nullable=True),
        sa.Column("purpose", sa.String(50), nullable=False),
        sa.Column("provider", sa.String(32), nullable=False),
        sa.Column("model", sa.String(200), nullable=False),
        sa.Column("prompt_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("completion_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("total_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("ix_token_usage_user_created", "ai_token_usage_logs", ["user_id", "created_at"])
    op.create_index("ix_token_usage_purpose_model", "ai_token_usage_logs", ["purpose", "model"])


def downgrade() -> None:
    op.drop_index("ix_token_usage_purpose_model", table_name="ai_token_usage_logs")
    op.drop_index("ix_token_usage_user_created", table_name="ai_token_usage_logs")
    op.drop_table("ai_token_usage_logs")

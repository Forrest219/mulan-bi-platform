"""add updated_at to auth_user_groups

Revision ID: 20260421_040000
Revises: 20260421_030000
Create Date: 2026-04-21
"""
from alembic import op, context
import sqlalchemy as sa

revision = "20260421_040000"
down_revision = "20260421_030000"
branch_labels = None
depends_on = None


def upgrade() -> None:
    if not context.is_offline_mode():
        conn = op.get_bind()
        result = conn.execute(sa.text(
            "SELECT 1 FROM information_schema.columns "
            "WHERE table_name='auth_user_groups' AND column_name='updated_at'"
        ))
        if result.fetchone():
            return  # column already exists
    op.add_column(
        "auth_user_groups",
        sa.Column("updated_at", sa.DateTime(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("auth_user_groups", "updated_at")

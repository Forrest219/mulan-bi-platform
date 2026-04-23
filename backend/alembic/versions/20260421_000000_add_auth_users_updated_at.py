"""add updated_at to auth_users

Revision ID: 20260421_000000
Revises: 20260420_010000
Create Date: 2026-04-21
"""
from alembic import op
import sqlalchemy as sa

revision = "20260421_000000"
down_revision = "20260420_010000"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "auth_users",
        sa.Column(
            "updated_at",
            sa.DateTime(),
            server_default=sa.text("now()"),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column("auth_users", "updated_at")

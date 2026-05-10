"""add_is_business_key_to_dw_asset_columns

Revision ID: 20260508_210000
Revises: 20260508_merge_skills_heads
Create Date: 2026-05-08 21:00:00.000000
"""
from alembic import op
import sqlalchemy as sa

revision = "20260508_210000"
down_revision = "20260508_merge_skills_heads"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "dw_asset_columns",
        sa.Column("is_business_key", sa.Boolean(), nullable=False, server_default=sa.text("false")),
    )


def downgrade() -> None:
    op.drop_column("dw_asset_columns", "is_business_key")

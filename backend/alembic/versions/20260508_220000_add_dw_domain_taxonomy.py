"""add_dw_domain_taxonomy

Revision ID: 20260508_220000
Revises: 20260508_210000
Create Date: 2026-05-08 22:00:00.000000
"""
from alembic import op
import sqlalchemy as sa

revision = "20260508_220000"
down_revision = "20260508_210000"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "dw_domain_taxonomy",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("l1", sa.String(64), nullable=False),
        sa.Column("l2", sa.String(64), nullable=True),
        sa.Column(
            "display_order",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )


def downgrade() -> None:
    op.drop_table("dw_domain_taxonomy")

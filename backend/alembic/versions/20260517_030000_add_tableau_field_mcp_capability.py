"""add Tableau datasource field MCP capability metadata

Revision ID: 20260517_030000
Revises: 20260517_020000
Create Date: 2026-05-17 15:00:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260517_030000"
down_revision: Union[str, None] = "20260517_020000"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("tableau_datasource_fields", sa.Column("mcp_queryable", sa.Boolean(), nullable=True))
    op.add_column("tableau_datasource_fields", sa.Column("mcp_field_name", sa.String(length=256), nullable=True))
    op.add_column("tableau_datasource_fields", sa.Column("mcp_field_caption", sa.String(length=256), nullable=True))
    op.add_column("tableau_datasource_fields", sa.Column("mcp_checked_at", sa.DateTime(), nullable=True))
    op.add_column("tableau_datasource_fields", sa.Column("mcp_last_error", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("tableau_datasource_fields", "mcp_last_error")
    op.drop_column("tableau_datasource_fields", "mcp_checked_at")
    op.drop_column("tableau_datasource_fields", "mcp_field_caption")
    op.drop_column("tableau_datasource_fields", "mcp_field_name")
    op.drop_column("tableau_datasource_fields", "mcp_queryable")

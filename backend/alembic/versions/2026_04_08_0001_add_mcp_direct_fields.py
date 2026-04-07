"""add mcp_direct_enabled and mcp_server_url to tableau_connections

Revision ID: add_mcp_direct_fields
Revises: add_ddl_compliance_fields
Create Date: 2026-04-08 00:01:00.000000

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers
revision = 'add_mcp_direct_fields'
down_revision = 'add_ddl_compliance_fields'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Spec 13 §9.1: MCP V2 直连开关
    op.add_column('tableau_connections',
        sa.Column('mcp_direct_enabled', sa.Boolean(), nullable=False, server_default='false')
    )
    # Spec 13 §9.1: MCP Server URL（可选，覆盖全局配置）
    op.add_column('tableau_connections',
        sa.Column('mcp_server_url', sa.String(length=512), nullable=True)
    )


def downgrade() -> None:
    op.drop_column('tableau_connections', 'mcp_server_url')
    op.drop_column('tableau_connections', 'mcp_direct_enabled')

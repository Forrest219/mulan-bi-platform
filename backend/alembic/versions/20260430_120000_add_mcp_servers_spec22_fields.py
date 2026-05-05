"""add mcp_servers spec22 multi-site fields

Revision ID: 20260430_120000
Revises: add_extra_settings_ps
Create Date: 2026-04-30 12:00:00.000000

Spec 22 P0: 修复 services/mcp/models.py::McpServer 与数据库 mcp_servers 表的 schema drift。
新增 5 个字段（site_name, is_default, priority, health_status, consecutive_failures）
以及 site_selector 路由查询所需的两个索引。

详见 docs/specs/spec-22-p0-mcp-servers-schema-fix-SPEC.md。
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '20260430_120000'
down_revision: Union[str, None] = 'add_extra_settings_ps'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'mcp_servers',
        sa.Column('site_name', sa.String(length=128), nullable=True),
    )
    op.add_column(
        'mcp_servers',
        sa.Column(
            'is_default',
            sa.Boolean(),
            nullable=False,
            server_default=sa.text('false'),
        ),
    )
    op.add_column(
        'mcp_servers',
        sa.Column(
            'priority',
            sa.Integer(),
            nullable=False,
            server_default=sa.text('0'),
        ),
    )
    op.add_column(
        'mcp_servers',
        sa.Column(
            'health_status',
            sa.String(length=32),
            nullable=False,
            server_default=sa.text("'unknown'"),
        ),
    )
    op.add_column(
        'mcp_servers',
        sa.Column(
            'consecutive_failures',
            sa.Integer(),
            nullable=False,
            server_default=sa.text('0'),
        ),
    )

    # 多站点路由查询用索引：
    # - is_default + is_active：site_selector 选默认站点
    # - health_status：round-robin 健康过滤
    op.create_index(
        'ix_mcp_servers_default_active',
        'mcp_servers',
        ['is_default', 'is_active'],
    )
    op.create_index(
        'ix_mcp_servers_health',
        'mcp_servers',
        ['health_status'],
    )


def downgrade() -> None:
    op.drop_index('ix_mcp_servers_health', table_name='mcp_servers')
    op.drop_index('ix_mcp_servers_default_active', table_name='mcp_servers')
    op.drop_column('mcp_servers', 'consecutive_failures')
    op.drop_column('mcp_servers', 'health_status')
    op.drop_column('mcp_servers', 'priority')
    op.drop_column('mcp_servers', 'is_default')
    op.drop_column('mcp_servers', 'site_name')

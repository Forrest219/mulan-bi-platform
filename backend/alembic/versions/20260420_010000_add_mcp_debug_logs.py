"""add mcp_debug_logs table

Revision ID: 20260420_010000
Revises: 20260420_000000
Create Date: 2026-04-20

MCP Debugger Phase 1 — 记录管理员调用 MCP 工具的调试日志。
关联 Spec: docs/specs/26-agentic-tableau-mcp-spec.md
"""
from typing import Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = '20260420_010000'
down_revision: Union[str, None] = '20260420_000000'
branch_labels: Union[str, None] = None
depends_on: Union[str, None] = None


def upgrade() -> None:
    op.create_table(
        'mcp_debug_logs',
        sa.Column('id', sa.Integer(), nullable=False, autoincrement=True),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('username', sa.String(length=64), nullable=False),
        sa.Column('tool_name', sa.String(length=128), nullable=False),
        sa.Column('arguments_json', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('status', sa.String(length=16), nullable=False),
        sa.Column('result_summary', sa.Text(), nullable=True),
        sa.Column('error_message', sa.Text(), nullable=True),
        sa.Column('duration_ms', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.text('NOW()')),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_mcp_debug_logs_user_id', 'mcp_debug_logs', ['user_id'])
    op.create_index('ix_mcp_debug_logs_tool_name', 'mcp_debug_logs', ['tool_name'])
    op.create_index('ix_mcp_debug_logs_created_at', 'mcp_debug_logs', ['created_at'])


def downgrade() -> None:
    op.drop_index('ix_mcp_debug_logs_created_at', table_name='mcp_debug_logs')
    op.drop_index('ix_mcp_debug_logs_tool_name', table_name='mcp_debug_logs')
    op.drop_index('ix_mcp_debug_logs_user_id', table_name='mcp_debug_logs')
    op.drop_table('mcp_debug_logs')

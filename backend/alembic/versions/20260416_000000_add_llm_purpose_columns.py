"""add purpose, display_name, priority to ai_llm_configs

Revision ID: add_llm_purpose_columns
Revises: add_mcp_direct_fields
Create Date: 2026-04-16 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers
revision = 'add_llm_purpose_columns'
down_revision = 'add_mcp_direct_fields'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('ai_llm_configs', sa.Column('purpose', sa.String(50), nullable=False, server_default='default'))
    op.add_column('ai_llm_configs', sa.Column('display_name', sa.String(100), nullable=True))
    op.add_column('ai_llm_configs', sa.Column('priority', sa.Integer(), nullable=False, server_default='0'))


def downgrade() -> None:
    op.drop_column('ai_llm_configs', 'priority')
    op.drop_column('ai_llm_configs', 'display_name')
    op.drop_column('ai_llm_configs', 'purpose')

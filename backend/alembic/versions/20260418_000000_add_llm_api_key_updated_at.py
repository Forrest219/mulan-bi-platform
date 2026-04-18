"""add api_key_updated_at to ai_llm_configs

Revision ID: add_llm_api_key_updated_at
Revises: add_llm_purpose_columns
Create Date: 2026-04-18 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers
revision = 'add_llm_api_key_updated_at'
down_revision = 'add_llm_purpose_columns'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        'ai_llm_configs',
        sa.Column('api_key_updated_at', sa.DateTime(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column('ai_llm_configs', 'api_key_updated_at')

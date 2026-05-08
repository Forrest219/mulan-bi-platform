"""add sources_count and top_sources to agent_conversation_messages

Revision ID: 20260508_sources
Revises: 20260508_120000
Create Date: 2026-05-08

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision: str = '20260508_sources'
down_revision: Union[str, None] = '20260508_120000'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'agent_conversation_messages',
        sa.Column('sources_count', sa.Integer(), nullable=True),
    )
    op.add_column(
        'agent_conversation_messages',
        sa.Column('top_sources', JSONB(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column('agent_conversation_messages', 'top_sources')
    op.drop_column('agent_conversation_messages', 'sources_count')

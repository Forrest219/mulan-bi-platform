"""create conversations tables

Revision ID: 20260416_010000
Revises: add_llm_purpose_columns
Create Date: 2026-04-16 01:00:00.000000
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = '20260416_010000'
down_revision = 'add_llm_purpose_columns'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'conversations',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column(
            'user_id',
            sa.Integer,
            sa.ForeignKey('auth_users.id', ondelete='CASCADE'),
            nullable=False,
        ),
        sa.Column('title', sa.String(100), nullable=False, server_default='新对话'),
        sa.Column(
            'created_at',
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            'updated_at',
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index('ix_conversations_user_id', 'conversations', ['user_id'])
    op.create_index('ix_conversations_updated_at', 'conversations', ['updated_at'])

    op.create_table(
        'conversation_messages',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column(
            'conversation_id',
            sa.String(36),
            sa.ForeignKey('conversations.id', ondelete='CASCADE'),
            nullable=False,
        ),
        sa.Column('role', sa.String(20), nullable=False),   # 'user' | 'assistant'
        sa.Column('content', sa.Text, nullable=False),
        sa.Column('query_context', postgresql.JSONB(astext_type=sa.Text()), nullable=True),  # P2 预留，支持 GIN 索引
        sa.Column(
            'created_at',
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index(
        'ix_conversation_messages_conversation_id',
        'conversation_messages',
        ['conversation_id'],
    )


def downgrade() -> None:
    op.drop_index('ix_conversation_messages_conversation_id', table_name='conversation_messages')
    op.drop_table('conversation_messages')
    op.drop_index('ix_conversations_updated_at', table_name='conversations')
    op.drop_index('ix_conversations_user_id', table_name='conversations')
    op.drop_table('conversations')

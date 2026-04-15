"""add_events_notifications_tables

Revision ID: a1b2c3d4e5f6
Revises: add_mcp_direct_fields
Create Date: 2026-04-05 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'a1b2c3d4e5f6'
down_revision: Union[str, None] = 'add_mcp_direct_fields'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # === bi_events 表 ===
    op.create_table(
        'bi_events',
        sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column('event_type', sa.String(length=64), nullable=False),
        sa.Column('source_module', sa.String(length=32), nullable=False),
        sa.Column('source_id', sa.String(length=128), nullable=True),
        sa.Column('severity', sa.String(length=16), nullable=False, server_default='info'),
        sa.Column('actor_id', sa.BigInteger(), nullable=True),
        sa.Column('payload_json', postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default='{}'),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(['actor_id'], ['auth_users.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_events_type_created', 'bi_events', ['event_type', 'created_at'], unique=False)
    op.create_index('ix_events_source', 'bi_events', ['source_module', 'source_id'], unique=False)
    op.create_index('ix_events_created', 'bi_events', ['created_at'], unique=False)

    # === bi_notifications 表 ===
    op.create_table(
        'bi_notifications',
        sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column('event_id', sa.BigInteger(), nullable=False),
        sa.Column('user_id', sa.BigInteger(), nullable=False),
        sa.Column('title', sa.String(length=256), nullable=False),
        sa.Column('content', sa.Text(), nullable=False),
        sa.Column('level', sa.String(length=16), nullable=False, server_default='info'),
        sa.Column('is_read', sa.Boolean(), nullable=False, server_default='false'),
        sa.Column('read_at', sa.DateTime(), nullable=True),
        sa.Column('link', sa.String(length=512), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(['event_id'], ['bi_events.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['user_id'], ['auth_users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_notif_user_read_created', 'bi_notifications', ['user_id', 'is_read', 'created_at'], unique=False)
    op.create_index('ix_notif_event', 'bi_notifications', ['event_id'], unique=False)


def downgrade() -> None:
    op.drop_index('ix_notif_event', table_name='bi_notifications')
    op.drop_index('ix_notif_user_read_created', table_name='bi_notifications')
    op.drop_table('bi_notifications')
    op.drop_index('ix_events_created', table_name='bi_events')
    op.drop_index('ix_events_source', table_name='bi_events')
    op.drop_index('ix_events_type_created', table_name='bi_events')
    op.drop_table('bi_events')

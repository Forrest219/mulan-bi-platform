"""add_bi_sync_schedules

Revision ID: 20260509_020000
Revises: 20260509_010000
Create Date: 2026-05-09 15:30:00.000000

新建 bi_sync_schedules 同步计划表，tableau_connections 加 schedule_id FK。
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '20260509_020000'
down_revision: Union[str, None] = '20260509_010000'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. 建 bi_sync_schedules 表
    op.create_table(
        'bi_sync_schedules',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('name', sa.String(length=128), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('frequency_type', sa.String(length=20), nullable=False),
        sa.Column('cron_expr', sa.String(length=64), nullable=False),
        sa.Column('priority', sa.Integer(), server_default=sa.text('50'), nullable=False),
        sa.Column('execution_mode', sa.String(length=16), server_default=sa.text("'parallel'"), nullable=False),
        sa.Column('is_enabled', sa.Boolean(), server_default=sa.text('true'), nullable=False),
        sa.Column('created_by', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['created_by'], ['auth_users.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('name')
    )
    op.create_index('ix_sync_sched_name', 'bi_sync_schedules', ['name'], unique=False)
    op.create_index('ix_sync_sched_enabled', 'bi_sync_schedules', ['is_enabled'], unique=False)

    # 2. tableau_connections 加 schedule_id 列 + FK
    op.add_column('tableau_connections', sa.Column('schedule_id', sa.Integer(), nullable=True))
    op.create_foreign_key(
        'fk_connections_schedule',
        'tableau_connections', 'bi_sync_schedules',
        ['schedule_id'], ['id'],
        ondelete='SET NULL'
    )


def downgrade() -> None:
    op.drop_constraint('fk_connections_schedule', 'tableau_connections', type_='foreignkey')
    op.drop_column('tableau_connections', 'schedule_id')
    op.drop_index('ix_sync_sched_enabled', table_name='bi_sync_schedules')
    op.drop_index('ix_sync_sched_name', table_name='bi_sync_schedules')
    op.drop_table('bi_sync_schedules')

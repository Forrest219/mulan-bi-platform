"""add_bi_maintenance_windows_table

Revision ID: 20260429_000002
Revises: 20260429_000001
Create Date: 2026-04-29 23:00:00.000000

Add bi_maintenance_windows table for Metrics Agent maintenance window support.
Spec 30 §4.2.1: admin configures [start, end] time window, detector skips
anomaly detection during this period.
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '20260429_000002'
down_revision = '20260429_000001'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'bi_maintenance_windows',
        sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column('name', sa.String(length=128), nullable=False),
        sa.Column('start_at', sa.DateTime(), nullable=False),
        sa.Column('end_at', sa.DateTime(), nullable=False),
        sa.Column('timezone', sa.String(length=32), server_default='Asia/Shanghai', nullable=True),
        sa.Column('reason', sa.String(length=512), nullable=True),
        sa.Column('created_by', sa.BigInteger(), nullable=True),
        sa.Column('is_active', sa.Boolean(), server_default='true', nullable=False),
        sa.Column('created_at', sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint('id')
    )
    # Index for querying active windows
    op.create_index(
        'ix_mw_active_window',
        'bi_maintenance_windows',
        ['is_active', 'start_at', 'end_at'],
        unique=False
    )


def downgrade() -> None:
    op.drop_index('ix_mw_active_window', table_name='bi_maintenance_windows')
    op.drop_table('bi_maintenance_windows')

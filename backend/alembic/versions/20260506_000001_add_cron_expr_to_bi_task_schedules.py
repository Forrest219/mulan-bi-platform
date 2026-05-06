"""add_cron_expr_to_bi_task_schedules

Revision ID: 20260506_000001
Revises: fc37b0a529f5
Create Date: 2026-05-06 00:00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '20260506_000001'
down_revision: Union[str, None] = 'fc37b0a529f5'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('bi_task_schedules', sa.Column('cron_expr', sa.String(64), nullable=True))

    # Populate cron_expr for existing rows
    op.execute("""
        UPDATE bi_task_schedules SET cron_expr = '0 0,12 * * *'
        WHERE schedule_key = 'tableau-auto-sync'
    """)
    op.execute("""
        UPDATE bi_task_schedules SET cron_expr = '0 3 * * *'
        WHERE schedule_key = 'events-purge-old'
    """)
    op.execute("""
        UPDATE bi_task_schedules SET cron_expr = '0 3 1-7 * 0'
        WHERE schedule_key = 'hnsw-reindex'
    """)
    op.execute("""
        UPDATE bi_task_schedules SET cron_expr = '0 3 * * 0'
        WHERE schedule_key = 'hnsw-vacuum-analyze'
    """)
    op.execute("""
        UPDATE bi_task_schedules SET cron_expr = '0 4 * * *'
        WHERE schedule_key = 'dqc-cycle-daily'
    """)
    op.execute("""
        UPDATE bi_task_schedules SET cron_expr = '10 3 1 * *'
        WHERE schedule_key = 'dqc-partition-maintenance'
    """)
    op.execute("""
        UPDATE bi_task_schedules SET cron_expr = '30 3 * * *'
        WHERE schedule_key = 'dqc-cleanup-old-analyses'
    """)
    op.execute("""
        UPDATE bi_task_schedules SET cron_expr = '0 2 * * *'
        WHERE schedule_key = 'task-runs-cleanup'
    """)

    # Also fix schedule_expr for tasks that previously showed interval text
    op.execute("""
        UPDATE bi_task_schedules SET schedule_expr = '每日 03:00'
        WHERE schedule_key = 'events-purge-old'
    """)
    op.execute("""
        UPDATE bi_task_schedules SET schedule_expr = '每日 02:00'
        WHERE schedule_key = 'task-runs-cleanup'
    """)


def downgrade() -> None:
    op.drop_column('bi_task_schedules', 'cron_expr')

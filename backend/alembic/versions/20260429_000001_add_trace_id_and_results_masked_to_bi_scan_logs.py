"""add_trace_id_and_results_masked_to_bi_scan_logs

Revision ID: 20260429_000001
Revises: 20260426_0002
Create Date: 2026-04-29 22:59:00.000000

Add trace_id and results_masked columns to bi_scan_logs table:
- trace_id: VARCHAR(64), nullable, for request trace tracking
- results_masked: TEXT, nullable, for storing masked check results
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '20260429_000001'
down_revision = '20260426_0002'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Add trace_id column (VARCHAR(64))
    op.add_column(
        'bi_scan_logs',
        sa.Column('trace_id', sa.String(length=64), nullable=True)
    )
    # Add results_masked column (TEXT)
    op.add_column(
        'bi_scan_logs',
        sa.Column('results_masked', sa.Text(), nullable=True)
    )


def downgrade() -> None:
    op.drop_column('bi_scan_logs', 'results_masked')
    op.drop_column('bi_scan_logs', 'trace_id')
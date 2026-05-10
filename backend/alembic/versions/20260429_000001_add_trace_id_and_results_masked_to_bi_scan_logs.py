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
    existing_columns = {
        col["name"]
        for col in sa.inspect(op.get_bind()).get_columns("bi_scan_logs")
    }
    if "trace_id" not in existing_columns:
        op.add_column(
            'bi_scan_logs',
            sa.Column('trace_id', sa.String(length=64), nullable=True)
        )
    if "results_masked" not in existing_columns:
        op.add_column(
            'bi_scan_logs',
            sa.Column('results_masked', sa.Text(), nullable=True)
        )


def downgrade() -> None:
    existing_columns = {
        col["name"]
        for col in sa.inspect(op.get_bind()).get_columns("bi_scan_logs")
    }
    if "results_masked" in existing_columns:
        op.drop_column('bi_scan_logs', 'results_masked')
    if "trace_id" in existing_columns:
        op.drop_column('bi_scan_logs', 'trace_id')

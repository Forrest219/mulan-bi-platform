"""add_ip_address_user_agent_trace_id_to_bi_operation_logs

Revision ID: 31b9d407f9d3
Revises: 20260509_020000
Create Date: 2026-05-10 15:22:48.916321

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = '31b9d407f9d3'
down_revision: Union[str, None] = '20260509_020000'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('bi_operation_logs', sa.Column('ip_address', sa.String(length=64), nullable=True))
    op.add_column('bi_operation_logs', sa.Column('user_agent', sa.String(length=512), nullable=True))
    op.add_column('bi_operation_logs', sa.Column('trace_id', sa.String(length=64), nullable=True))


def downgrade() -> None:
    op.drop_column('bi_operation_logs', 'ip_address')
    op.drop_column('bi_operation_logs', 'user_agent')
    op.drop_column('bi_operation_logs', 'trace_id')
"""add consecutive_sync_failures to tableau_connections

Revision ID: 20260504_000001
Revises: 20260430_130000
Create Date: 2026-05-04

Idempotent: checks column does not exist before adding.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = '20260504_000001'
down_revision: Union[str, None] = '20260430_130000'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()
    result = conn.execute(sa.text(
        "SELECT column_name FROM information_schema.columns "
        "WHERE table_name='tableau_connections' AND column_name='consecutive_sync_failures'"
    ))
    if result.fetchone() is None:
        op.add_column('tableau_connections',
            sa.Column('consecutive_sync_failures', sa.Integer(), server_default=sa.text('0'), nullable=False))


def downgrade() -> None:
    op.drop_column('tableau_connections', 'consecutive_sync_failures')

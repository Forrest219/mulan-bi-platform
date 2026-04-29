"""add_publish_log_rollback_fields

Revision ID: 20260428_100000
Revises: 95cdeeefd3ab
Create Date: 2026-04-28 10:00:00.000000

Spec 19: Add action and previous_version_snapshot fields to tableau_publish_logs
- action: 'rollback' / None
- previous_version_snapshot: JSONB snapshot before rollback
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '20260428_100000'
down_revision: Union[str, None] = '95cdeeefd3ab'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'tableau_publish_logs',
        sa.Column('action', sa.String(32), nullable=True)
    )
    op.add_column(
        'tableau_publish_logs',
        sa.Column('previous_version_snapshot', sa.JSONB(), nullable=True, server_default=sa.text("'{}'::jsonb"))
    )
    # 创建索引加速按 action 查询
    op.create_index('ix_publish_log_action', 'tableau_publish_logs', ['action'])


def downgrade() -> None:
    op.drop_index('ix_publish_log_action', table_name='tableau_publish_logs')
    op.drop_column('tableau_publish_logs', 'previous_version_snapshot')
    op.drop_column('tableau_publish_logs', 'action')

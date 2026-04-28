"""add_publish_log_indexes

Revision ID: 95cdeeefd3ab
Revises: 7e5fa32da72b
Create Date: 2026-04-27 23:46:08.315668

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '95cdeeefd3ab'
down_revision: Union[str, None] = '7e5fa32da72b'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Spec 19: add indexes on tableau_publish_logs for efficient filtering
    op.create_index('ix_publish_log_operator', 'tableau_publish_logs', ['operator'])
    op.create_index('ix_publish_log_created_at', 'tableau_publish_logs', ['created_at'])


def downgrade() -> None:
    op.drop_index('ix_publish_log_created_at', table_name='tableau_publish_logs')
    op.drop_index('ix_publish_log_operator', table_name='tableau_publish_logs')

"""add_display_group_to_rule_configs

Revision ID: 098fca1daa01
Revises: f7e8d9c0b1a2
Create Date: 2026-05-06 15:32:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = '098fca1daa01'
down_revision: Union[str, None] = 'f7e8d9c0b1a2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'bi_rule_configs',
        sa.Column('display_group', sa.String(length=32), server_default='other', nullable=False)
    )


def downgrade() -> None:
    op.drop_column('bi_rule_configs', 'display_group')

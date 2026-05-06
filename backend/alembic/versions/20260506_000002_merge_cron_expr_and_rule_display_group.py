"""merge: add_cron_expr + add_display_group_to_rule_configs

Revision ID: 20260506_000002
Revises: 20260506_000001, 098fca1daa01
Create Date: 2026-05-06 00:00:02

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '20260506_000002'
down_revision: Union[str, None] = ('20260506_000001', '098fca1daa01')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass

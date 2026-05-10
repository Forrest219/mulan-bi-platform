"""preserve legacy add_quality_tables revision as a no-op

Revision ID: 7e5fa32da72b
Revises: 20260427_0001
Create Date: 2026-04-27 23:41:27.708702

This revision previously contained an unsafe autogenerate diff that mixed
duplicate auth table creation with destructive drops for unrelated tables.
The actual quality/auth/task schemas are managed by adjacent explicit
migrations, so this revision is retained only to keep the Alembic graph intact.
"""
from typing import Sequence, Union


revision: str = '7e5fa32da72b'
down_revision: Union[str, None] = '20260427_0001'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass

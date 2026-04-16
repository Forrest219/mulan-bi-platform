"""merge_p1_migrations

Revision ID: 84c2295c782b
Revises: 20260416_010000, add_tableau_assets_composite_idx
Create Date: 2026-04-16 13:29:03.054721

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = '84c2295c782b'
down_revision: Union[str, None] = ('20260416_010000', 'add_tableau_assets_composite_idx')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass

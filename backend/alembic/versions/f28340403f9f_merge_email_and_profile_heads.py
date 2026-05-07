"""merge_email_and_profile_heads

Revision ID: f28340403f9f
Revises: 20260507_220000, 20260508_000002
Create Date: 2026-05-07 23:50:09.491707

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = 'f28340403f9f'
down_revision: Union[str, None] = ('20260507_220000', '20260508_000002')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass

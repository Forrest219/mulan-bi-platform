"""merge: add_platform_settings + spec28_analysis_tables

Revision ID: ba52b50f68f8
Revises: add_platform_settings, 20260426_0001
Create Date: 2026-04-25 13:18:04.365681

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = 'ba52b50f68f8'
down_revision: Union[str, None] = ('add_platform_settings', '20260426_0001')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass

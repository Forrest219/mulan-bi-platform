"""merge_multiple_heads

Revision ID: fc37b0a529f5
Revises: 20260427_0002, 20260428_0001b, 20260428_0002, add_anomaly_algorithm_column, 20260428_100000, 20260429_000002, 20260429_120000, 20260504_000001
Create Date: 2026-05-05 21:53:01.362612

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = 'fc37b0a529f5'
down_revision: Union[str, None] = ('20260427_0002', '20260428_0001b', '20260428_0002', 'add_anomaly_algorithm_column', '20260428_100000', '20260429_000002', '20260429_120000', '20260504_000001')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass

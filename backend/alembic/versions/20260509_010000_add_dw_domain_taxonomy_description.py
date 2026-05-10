"""add_dw_domain_taxonomy_description

Revision ID: 20260509_010000
Revises: 20260508_220000
Create Date: 2026-05-09

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = '20260509_010000'
down_revision: Union[str, None] = '20260508_220000'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('dw_domain_taxonomy', sa.Column('description', sa.String(200), nullable=True))


def downgrade() -> None:
    op.drop_column('dw_domain_taxonomy', 'description')

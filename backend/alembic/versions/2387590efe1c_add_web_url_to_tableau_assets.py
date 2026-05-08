"""add_web_url_to_tableau_assets

Revision ID: 2387590efe1c
Revises: 20260508_task_ddl
Create Date: 2026-05-08 12:47:47.240594

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '2387590efe1c'
down_revision: Union[str, None] = '20260508_task_ddl'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('tableau_assets', sa.Column('web_url', sa.String(length=1024), nullable=True))


def downgrade() -> None:
    op.drop_column('tableau_assets', 'web_url')

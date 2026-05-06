"""add_metric_dimension_def_to_datasource_semantics

Revision ID: 20260506_233000
Revises: 20260506_180000
Create Date: 2026-05-06 23:30:00

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = '20260506_233000'
down_revision: Union[str, None] = '20260506_180000'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('tableau_datasource_semantics', sa.Column('metric_definition', sa.Text(), nullable=True))
    op.add_column('tableau_datasource_semantics', sa.Column('dimension_definition', sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column('tableau_datasource_semantics', 'dimension_definition')
    op.drop_column('tableau_datasource_semantics', 'metric_definition')

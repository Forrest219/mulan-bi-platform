"""add_related_metric_ids_to_kb_glossary

Revision ID: 20260508_kb_metric_ids
Revises: 2387590efe1c
Create Date: 2026-05-08

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision: str = '20260508_kb_metric_ids'
down_revision: Union[str, None] = '2387590efe1c'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'kb_glossary',
        sa.Column(
            'related_metric_ids_json',
            JSONB,
            nullable=True,
            server_default=sa.text("'[]'::jsonb"),
        ),
    )


def downgrade() -> None:
    op.drop_column('kb_glossary', 'related_metric_ids_json')

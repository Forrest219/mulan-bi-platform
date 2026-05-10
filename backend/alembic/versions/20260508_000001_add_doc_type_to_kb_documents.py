"""add_doc_type_to_kb_documents

Revision ID: 20260508_000001
Revises: fc37b0a529f5
Create Date: 2026-05-08 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '20260508_000001'
down_revision: Union[str, None] = 'fc37b0a529f5'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'kb_documents',
        sa.Column('doc_type', sa.String(32), nullable=False, server_default='general'),
    )


def downgrade() -> None:
    op.drop_column('kb_documents', 'doc_type')

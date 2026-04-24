"""merge_heads_before_task_tables

Revision ID: 04e780a305b9
Revises: 20260421_060000, add_field_semantics_chunk_text
Create Date: 2026-04-24 12:18:45.445679

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = '04e780a305b9'
down_revision: Union[str, None] = ('20260421_060000', 'add_field_semantics_chunk_text')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass

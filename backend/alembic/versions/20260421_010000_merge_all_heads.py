"""merge all heads

Revision ID: 20260421_010000
Revises: 20260421_000000, add_message_feedback_table
Create Date: 2026-04-21

合并 updated_at 链 + feedback 链。
"""
from alembic import op
import sqlalchemy as sa
from typing import Union

revision: str = "20260421_010000"
down_revision: Union[tuple, None] = ("20260421_000000", "add_message_feedback_table")
branch_labels = None
depends_on = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass

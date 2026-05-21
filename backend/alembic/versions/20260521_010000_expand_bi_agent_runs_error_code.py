"""expand_bi_agent_runs_error_code

Revision ID: 20260521_010000
Revises: 20260519_010000
Create Date: 2026-05-21 10:01:51.746122
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "20260521_010000"
down_revision: Union[str, None] = "20260519_010000"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.alter_column(
        "bi_agent_runs",
        "error_code",
        existing_type=sa.String(length=16),
        type_=sa.String(length=128),
        existing_nullable=True,
    )


def downgrade() -> None:
    op.alter_column(
        "bi_agent_runs",
        "error_code",
        existing_type=sa.String(length=128),
        type_=sa.String(length=16),
        existing_nullable=True,
    )

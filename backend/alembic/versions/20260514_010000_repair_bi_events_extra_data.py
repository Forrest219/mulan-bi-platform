"""repair missing bi_events extra_data column

Revision ID: 20260514_010000
Revises: 20260513_020000
Create Date: 2026-05-14 00:10:00.000000

This migration repairs environments whose alembic_version table reached head
while the physical bi_events.extra_data column was missing.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import text
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = "20260514_010000"
down_revision: Union[str, None] = "20260513_020000"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _bi_events_exists() -> bool:
    conn = op.get_bind()
    return (
        conn.execute(
            text(
                "SELECT 1 FROM information_schema.tables "
                "WHERE table_schema = current_schema() AND table_name = 'bi_events'"
            )
        ).fetchone()
        is not None
    )


def _extra_data_exists() -> bool:
    conn = op.get_bind()
    return (
        conn.execute(
            text(
                "SELECT 1 FROM information_schema.columns "
                "WHERE table_schema = current_schema() "
                "AND table_name = 'bi_events' AND column_name = 'extra_data'"
            )
        ).fetchone()
        is not None
    )


def upgrade() -> None:
    if not _bi_events_exists() or _extra_data_exists():
        return

    op.add_column(
        "bi_events",
        sa.Column(
            "extra_data",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
            server_default=sa.text("'{}'::jsonb"),
        ),
    )


def downgrade() -> None:
    if _bi_events_exists() and _extra_data_exists():
        op.drop_column("bi_events", "extra_data")

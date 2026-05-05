"""add bi_events extra_data column (Spec 9 → Spec 16)

Revision ID: 20260430_130000
Revises: 20260430_120000
Create Date: 2026-04-30 13:00:00.000000

Idempotent: checks column does not exist before adding.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from sqlalchemy import text

# revision identifiers, used by Alembic.
revision: str = '20260430_130000'
down_revision: Union[str, None] = '20260430_120000'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Idempotent: only add column if it does not already exist
    conn = op.get_bind()
    result = conn.execute(
        text(
            "SELECT 1 FROM information_schema.columns "
            "WHERE table_name = 'bi_events' AND column_name = 'extra_data'"
        )
    ).fetchone()

    if result is None:
        op.add_column(
            'bi_events',
            sa.Column(
                'extra_data',
                postgresql.JSONB(astext_type=sa.Text()),
                nullable=True,
                server_default=sa.text("'{}'::jsonb"),
            )
        )
    # else: column already exists — nothing to do (idempotent)


def downgrade() -> None:
    # Idempotent: only drop column if it exists
    conn = op.get_bind()
    result = conn.execute(
        text(
            "SELECT 1 FROM information_schema.columns "
            "WHERE table_name = 'bi_events' AND column_name = 'extra_data'"
        )
    ).fetchone()

    if result is not None:
        op.drop_column('bi_events', 'extra_data')
    # else: column does not exist — nothing to do (idempotent)

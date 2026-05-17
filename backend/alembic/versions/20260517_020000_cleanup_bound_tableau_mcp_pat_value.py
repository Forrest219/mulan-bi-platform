"""cleanup bound legacy tableau mcp pat_value

Revision ID: 20260517_020000
Revises: 20260517_010000
Create Date: 2026-05-17 02:00:00.000000

This data-only follow-up is intentionally idempotent. It covers local or
deployed databases that already applied the initial unify-tableau-mcp-entry
migration before the successful-backfill PAT cleanup rule was finalized.
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260517_020000"
down_revision: Union[str, None] = "20260517_010000"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        sa.text(
            """
            UPDATE mcp_servers
            SET credentials = credentials - 'pat_value'
            WHERE type = 'tableau'
              AND tableau_connection_id IS NOT NULL
              AND binding_source = 'legacy_mcp_backfill'
              AND credentials IS NOT NULL
              AND credentials ? 'pat_value'
            """
        )
    )


def downgrade() -> None:
    # Sensitive cleanup is not reversible.
    pass

"""metric binding unique identity

Revision ID: 20260518_010000
Revises: 20260517_030000
Create Date: 2026-05-18 01:00:00.000000
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op


revision: str = "20260518_010000"
down_revision: Union[str, None] = "20260517_030000"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS uq_bmb_active_tableau_binding_identity
        ON bi_metric_bindings (
            tenant_id,
            metric_id,
            tableau_connection_id,
            tableau_datasource_luid
        )
        WHERE is_active = true
          AND source_type = 'tableau_published_datasource'
        """
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS uq_bmb_active_tableau_binding_identity")

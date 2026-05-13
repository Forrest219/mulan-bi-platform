"""backfill_agent_conversation_updated_at

Revision ID: 20260513_020000
Revises: 20260513_010000
Create Date: 2026-05-13
"""

from typing import Sequence, Union

from alembic import op


revision: str = "20260513_020000"
down_revision: Union[str, None] = "20260513_010000"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        UPDATE agent_conversations AS c
        SET updated_at = m.last_message_at
        FROM (
            SELECT conversation_id, MAX(created_at) AS last_message_at
            FROM agent_conversation_messages
            GROUP BY conversation_id
        ) AS m
        WHERE c.id = m.conversation_id
          AND (c.updated_at IS NULL OR c.updated_at < m.last_message_at)
        """
    )


def downgrade() -> None:
    pass

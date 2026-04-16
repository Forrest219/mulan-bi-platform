"""alter conversation_messages.query_context to JSONB

Revision ID: 20260416_020000
Revises: 84c2295c782b
Create Date: 2026-04-16 02:00:00.000000
"""
from alembic import op

revision = '20260416_020000'
down_revision = '84c2295c782b'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE conversation_messages "
        "ALTER COLUMN query_context TYPE JSONB "
        "USING query_context::jsonb"
    )


def downgrade() -> None:
    op.execute(
        "ALTER TABLE conversation_messages "
        "ALTER COLUMN query_context TYPE JSON "
        "USING query_context::json"
    )

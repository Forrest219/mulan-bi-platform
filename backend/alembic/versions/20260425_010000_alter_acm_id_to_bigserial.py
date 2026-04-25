"""alter_acm_id_to_bigserial

Revision ID: 20260425_010000
Revises: 20260424_010000
Create Date: 2026-04-25

Spec 36 §4.1 — agent_conversation_messages.id 从 SERIAL 升级为 BIGSERIAL，
避免高频写入场景下 INTEGER 溢出。
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "20260425_010000"
down_revision: Union[str, None] = "20260424_010000"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.alter_column(
        "agent_conversation_messages",
        "id",
        existing_type=sa.Integer(),
        type_=sa.BigInteger(),
        existing_nullable=False,
        existing_autoincrement=True,
    )


def downgrade() -> None:
    op.alter_column(
        "agent_conversation_messages",
        "id",
        existing_type=sa.BigInteger(),
        type_=sa.Integer(),
        existing_nullable=False,
        existing_autoincrement=True,
    )

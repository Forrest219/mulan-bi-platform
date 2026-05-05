"""add_intent_log_fields — Spec 36 §15.E

新增字段：
- fallback_chain VARCHAR(64)  — 记录完整 fallback 链路，如 context_aware→keyword→llm→chat
- input_excerpt VARCHAR(256) — 用户消息截断至 256 字符

Revision ID: add_intent_log_fields
Revises: add_bi_agent_intent_log
Create Date: 2026-04-29
"""
from typing import Union

from alembic import op
import sqlalchemy as sa

# revision identifiers
revision: str = "add_intent_log_fields"
down_revision: Union[str, None] = "add_bi_agent_intent_log"
branch_labels: Union[str, tuple[str], None] = None
depends_on: Union[str, tuple[str], None] = None


def upgrade() -> None:
    op.add_column(
        "bi_agent_intent_log",
        sa.Column("fallback_chain", sa.String(64), nullable=True),
    )
    op.add_column(
        "bi_agent_intent_log",
        sa.Column("input_excerpt", sa.String(256), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("bi_agent_intent_log", "input_excerpt")
    op.drop_column("bi_agent_intent_log", "fallback_chain")

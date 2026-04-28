"""add_bi_agent_intent_log — Spec 36 §15

意图识别日志表（90天保留）：
- question: 原始问题（截断至2000字符）
- intent: 识别结果（chat / query / analysis / report / chart）
- confidence: 置信度
- strategy: 触发的策略名（context_aware / keyword_match / llm_classify / fallback）
- trace_id / user_id: 审计追踪
- error: 可选的错误信息

Revision ID: add_bi_agent_intent_log
Revises: add_bi_agent_dual_write_audit
Create Date: 2026-04-28
"""
from typing import Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers
revision: str = "add_bi_agent_intent_log"
down_revision: Union[str, None] = "add_bi_agent_dual_write_audit"
branch_labels: Union[str, tuple[str], None] = None
depends_on: Union[str, tuple[str], None] = None


def upgrade() -> None:
    op.create_table(
        "bi_agent_intent_log",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        # 原始问题
        sa.Column("question", sa.Text(), nullable=False),
        # 识别结果
        sa.Column("intent", sa.String(32), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("strategy", sa.String(64), nullable=False),
        # 审计追踪
        sa.Column("trace_id", sa.String(64), nullable=True, index=True),
        sa.Column("user_id", sa.Integer(), nullable=True, index=True),
        # 可选错误
        sa.Column("error", sa.Text(), nullable=True),
        # 时间戳
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now(), index=True),
        # 按月分区键
        sa.Column("partition_key", sa.String(6), nullable=False, index=True),
    )

    # 组合索引
    op.create_index(
        "ix_bi_agent_intent_log_user_trace",
        "bi_agent_intent_log",
        ["user_id", "trace_id"],
    )


def downgrade() -> None:
    op.drop_table("bi_agent_intent_log")
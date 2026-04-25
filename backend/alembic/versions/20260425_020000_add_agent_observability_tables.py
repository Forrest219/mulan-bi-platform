"""add_agent_observability_tables

Revision ID: 20260425_020000
Revises: 20260425_010000
Create Date: 2026-04-25

Spec 36 §Phase 3 — Data Agent 可观测性表：
- bi_agent_runs: 每次 agent 调用的运行记录
- bi_agent_steps: 每个 ReAct step 的执行明细
- bi_agent_feedback: 用户反馈（thumbs up/down）

索引策略：
- ix_bar_user_created: (user_id, created_at DESC) — 用户运行历史
- ix_bar_status: (status) — 按状态筛选
- ix_bas_run_step: (run_id, step_number) — 步骤时序查询

迁移顺序（升级）：
  bi_agent_runs → bi_agent_steps → bi_agent_feedback

回滚顺序（降级）：
  bi_agent_feedback → bi_agent_steps → bi_agent_runs
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "20260425_020000"
down_revision: Union[str, None] = "20260425_010000"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ==================== bi_agent_runs ====================
    # Agent 运行记录 — 每次 POST /api/agent/stream 调用一行
    op.create_table(
        "bi_agent_runs",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "conversation_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("question", sa.Text(), nullable=False),
        sa.Column("connection_id", sa.Integer(), nullable=True),
        sa.Column(
            "status",
            sa.String(length=16),
            nullable=False,
            server_default=sa.text("'running'"),
        ),
        sa.Column("error_code", sa.String(length=16), nullable=True),
        sa.Column("steps_count", sa.Integer(), server_default=sa.text("0")),
        sa.Column("tools_used", postgresql.ARRAY(sa.Text()), nullable=True),
        sa.Column("response_type", sa.String(length=16), nullable=True),
        sa.Column("execution_time_ms", sa.Integer(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(
            ["conversation_id"],
            ["agent_conversations.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_bar_user_created",
        "bi_agent_runs",
        ["user_id", sa.text("created_at DESC")],
        unique=False,
    )
    op.create_index(
        "ix_bar_status",
        "bi_agent_runs",
        ["status"],
        unique=False,
    )

    # ==================== bi_agent_steps ====================
    # Agent 步骤记录 — 每个 ReAct step 一行
    op.create_table(
        "bi_agent_steps",
        sa.Column(
            "id",
            sa.BigInteger(),
            autoincrement=True,
            nullable=False,
        ),
        sa.Column(
            "run_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column("step_number", sa.Integer(), nullable=False),
        sa.Column("step_type", sa.String(length=16), nullable=False),
        sa.Column("tool_name", sa.String(length=64), nullable=True),
        sa.Column(
            "tool_params",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
        sa.Column("tool_result_summary", sa.Text(), nullable=True),
        sa.Column("content", sa.Text(), nullable=True),
        sa.Column("execution_time_ms", sa.Integer(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.ForeignKeyConstraint(
            ["run_id"],
            ["bi_agent_runs.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_bas_run_step",
        "bi_agent_steps",
        ["run_id", "step_number"],
        unique=False,
    )

    # ==================== bi_agent_feedback ====================
    # 用户反馈 — 每个 run 每个用户最多一条
    op.create_table(
        "bi_agent_feedback",
        sa.Column(
            "id",
            sa.BigInteger(),
            autoincrement=True,
            nullable=False,
        ),
        sa.Column(
            "run_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("rating", sa.String(length=8), nullable=False),
        sa.Column("comment", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.ForeignKeyConstraint(
            ["run_id"],
            ["bi_agent_runs.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("run_id", "user_id", name="uq_baf_run_user"),
    )


def downgrade() -> None:
    # 反序 DROP：先删子表/依赖表，最后删基础表
    op.drop_table("bi_agent_feedback")

    op.drop_index("ix_bas_run_step", table_name="bi_agent_steps")
    op.drop_table("bi_agent_steps")

    op.drop_index("ix_bar_status", table_name="bi_agent_runs")
    op.drop_index("ix_bar_user_created", table_name="bi_agent_runs")
    op.drop_table("bi_agent_runs")

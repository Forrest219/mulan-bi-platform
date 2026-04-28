"""add_taskrun_core_tables

Revision ID: 20260428_0002
Revises: 20260428_0001
Create Date: 2026-04-28

Spec 24 §2.1 — Task Runtime 三表：
- bi_taskrun_runs: TaskRun 主表
- bi_taskrun_steps: StepRun 步骤表
- bi_taskrun_events: 事件表（append-only）
"""
from typing import Sequence, Union

from alembic import op, context
import sqlalchemy as sa


revision: str = "20260428_0002"
down_revision: Union[str, None] = "20260428_0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ==================== bi_taskrun_runs ====================
    op.create_table(
        "bi_taskrun_runs",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("trace_id", sa.String(length=64), nullable=False),
        sa.Column("conversation_id", sa.Integer(), nullable=True),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("intent", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="queued"),
        sa.Column("input_payload", sa.JSONB(), nullable=False),
        sa.Column("output_payload", sa.JSONB(), nullable=True),
        sa.Column("error_code", sa.String(length=16), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(), nullable=False, server_default=sa.text("NOW()")),
        sa.Column("finished_at", sa.DateTime(), nullable=True),
        sa.Column("timeout_seconds", sa.Integer(), nullable=False, server_default="120"),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("NOW()")),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.text("NOW()")),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("trace_id", name="ux_runs_trace"),
        sa.CheckConstraint("status IN ('queued', 'running', 'succeeded', 'failed', 'cancelling', 'cancelled')", name="ck_runs_status"),
        sa.CheckConstraint("timeout_seconds >= 5 AND timeout_seconds <= 600", name="ck_runs_timeout"),
    )

    # Index: (user_id, status, started_at DESC)
    op.create_index("ix_runs_user_status", "bi_taskrun_runs", ["user_id", "status", "started_at"], unique=False)
    # Unique index on trace_id is already created via UniqueConstraint

    # FK: user_id → auth_users(id)
    op.create_foreign_key(
        "fk_runs_user",
        "bi_taskrun_runs", "auth_users",
        ["user_id"], ["id"],
    )

    # NOTE: conversation_id FK is intentionally omitted — no conversations table exists yet.
    # It is a nullable column for future use when Spec 21 conversation model is implemented.

    # ==================== bi_taskrun_steps ====================
    op.create_table(
        "bi_taskrun_steps",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("task_run_id", sa.Integer(), nullable=False),
        sa.Column("seq", sa.Integer(), nullable=False),
        sa.Column("step_type", sa.String(length=32), nullable=False),
        sa.Column("capability_name", sa.String(length=64), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="pending"),
        sa.Column("input_ref", sa.Text(), nullable=True),
        sa.Column("output_ref", sa.Text(), nullable=True),
        sa.Column("error_code", sa.String(length=16), nullable=True),
        sa.Column("started_at", sa.DateTime(), nullable=True),
        sa.Column("finished_at", sa.DateTime(), nullable=True),
        sa.Column("latency_ms", sa.Integer(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("task_run_id", "seq", name="ux_steps_run_seq"),
        sa.CheckConstraint("status IN ('pending', 'running', 'succeeded', 'failed', 'skipped')", name="ck_steps_status"),
    )

    # Index: (task_run_id, seq) — unique index already via UniqueConstraint
    op.create_index("ix_steps_run", "bi_taskrun_steps", ["task_run_id", "seq"], unique=False)

    # FK: task_run_id → bi_taskrun_runs(id) ON DELETE CASCADE
    op.create_foreign_key(
        "fk_steps_run",
        "bi_taskrun_steps", "bi_taskrun_runs",
        ["task_run_id"], ["id"],
        ondelete="CASCADE",
    )

    # ==================== bi_taskrun_events ====================
    op.create_table(
        "bi_taskrun_events",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("task_run_id", sa.Integer(), nullable=False),
        sa.Column("step_id", sa.Integer(), nullable=True),
        sa.Column("event_type", sa.String(length=32), nullable=False),
        sa.Column("payload", sa.JSONB(), nullable=False),
        sa.Column("emitted_at", sa.DateTime(), nullable=False, server_default=sa.text("NOW()")),
        sa.PrimaryKeyConstraint("id"),
    )

    # Index: (task_run_id, emitted_at)
    op.create_index("ix_events_run_time", "bi_taskrun_events", ["task_run_id", "emitted_at"], unique=False)

    # FK: task_run_id → bi_taskrun_runs(id) ON DELETE CASCADE
    op.create_foreign_key(
        "fk_events_run",
        "bi_taskrun_events", "bi_taskrun_runs",
        ["task_run_id"], ["id"],
        ondelete="CASCADE",
    )


def downgrade() -> None:
    # Drop FKs first (in reverse dependency order)
    op.drop_constraint("fk_events_run", "bi_taskrun_events", type_="foreignkey")
    op.drop_constraint("fk_steps_run", "bi_taskrun_steps", type_="foreignkey")
    op.drop_constraint("fk_runs_user", "bi_taskrun_runs", type_="foreignkey")
    op.drop_constraint("fk_runs_conversation", "bi_taskrun_runs", type_="foreignkey")

    # Drop tables in reverse order
    op.drop_table("bi_taskrun_events")
    op.drop_table("bi_taskrun_steps")
    op.drop_table("bi_taskrun_runs")

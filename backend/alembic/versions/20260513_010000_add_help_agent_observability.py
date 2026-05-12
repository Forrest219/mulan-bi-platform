"""add_help_agent_observability

Revision ID: 20260513_010000
Revises: 20260512_000000
Create Date: 2026-05-13
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision: str = "20260513_010000"
down_revision: Union[str, None] = "20260512_000000"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "bi_agent_steps",
        sa.Column("structured_error", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )
    op.add_column(
        "bi_task_runs",
        sa.Column("structured_error", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )

    op.create_table(
        "help_agent_conversations",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(length=256), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False, server_default=sa.text("'active'")),
        sa.Column("last_page_path", sa.String(length=256), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_help_agent_conversations_user_id", "help_agent_conversations", ["user_id"])
    op.create_index(
        "ix_hac_user_status_updated",
        "help_agent_conversations",
        ["user_id", "status", sa.text("updated_at DESC")],
    )

    op.create_table(
        "help_agent_messages",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("conversation_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("role", sa.String(length=16), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("response_type", sa.String(length=16), nullable=True),
        sa.Column("response_data", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("tools_used", postgresql.ARRAY(sa.Text()), nullable=True),
        sa.Column("trace_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("steps_count", sa.Integer(), nullable=True),
        sa.Column("execution_time_ms", sa.Integer(), nullable=True),
        sa.Column("sources_count", sa.Integer(), nullable=True),
        sa.Column("top_sources", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["conversation_id"], ["help_agent_conversations.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_ham_conv_created", "help_agent_messages", ["conversation_id", "created_at"])

    op.create_table(
        "help_agent_runs",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("conversation_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("question", sa.Text(), nullable=False),
        sa.Column("page_context", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False, server_default=sa.text("'running'")),
        sa.Column("error_code", sa.String(length=16), nullable=True),
        sa.Column("structured_error", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("steps_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("tools_used", postgresql.ARRAY(sa.Text()), nullable=True),
        sa.Column("response_type", sa.String(length=16), nullable=True),
        sa.Column("execution_time_ms", sa.Integer(), nullable=True),
        sa.Column("snapshot_started_at", sa.DateTime(), nullable=False),
        sa.Column("snapshot_completed_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["conversation_id"], ["help_agent_conversations.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_help_agent_runs_user_id", "help_agent_runs", ["user_id"])
    op.create_index("ix_har_user_created", "help_agent_runs", ["user_id", sa.text("created_at DESC")])
    op.create_index("ix_har_status_created", "help_agent_runs", ["status", sa.text("created_at DESC")])
    op.create_index("ix_har_conversation_created", "help_agent_runs", ["conversation_id", "created_at"])

    op.create_table(
        "help_agent_steps",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("run_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("step_number", sa.Integer(), nullable=False),
        sa.Column("step_type", sa.String(length=16), nullable=False),
        sa.Column("tool_name", sa.String(length=64), nullable=True),
        sa.Column("tool_params", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("tool_result_summary", sa.Text(), nullable=True),
        sa.Column("content", sa.Text(), nullable=True),
        sa.Column("diagnostic_payload", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("structured_error", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("related_entities", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("snapshot_at", sa.DateTime(), nullable=True),
        sa.Column("execution_time_ms", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["run_id"], ["help_agent_runs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_has_run_step", "help_agent_steps", ["run_id", "step_number"])


def downgrade() -> None:
    op.drop_index("ix_has_run_step", table_name="help_agent_steps")
    op.drop_table("help_agent_steps")

    op.drop_index("ix_har_conversation_created", table_name="help_agent_runs")
    op.drop_index("ix_har_status_created", table_name="help_agent_runs")
    op.drop_index("ix_har_user_created", table_name="help_agent_runs")
    op.drop_index("ix_help_agent_runs_user_id", table_name="help_agent_runs")
    op.drop_table("help_agent_runs")

    op.drop_index("ix_ham_conv_created", table_name="help_agent_messages")
    op.drop_table("help_agent_messages")

    op.drop_index("ix_hac_user_status_updated", table_name="help_agent_conversations")
    op.drop_index("ix_help_agent_conversations_user_id", table_name="help_agent_conversations")
    op.drop_table("help_agent_conversations")

    op.drop_column("bi_task_runs", "structured_error")
    op.drop_column("bi_agent_steps", "structured_error")

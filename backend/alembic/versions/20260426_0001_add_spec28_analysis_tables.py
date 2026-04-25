"""add_spec28_analysis_tables

Revision ID: 20260426_0001
Revises: 20260425_020000
Create Date: 2026-04-26

Spec 28 §3 — Data Agent 分析表：
- bi_analysis_sessions:     可变会话状态（归因/报告/洞察）
- bi_analysis_session_steps: 不可变步骤历史（Append-Only）
- bi_analysis_insights:     已发布洞察
- bi_analysis_reports:      分析报告

迁移顺序（升级）：
  bi_analysis_sessions → bi_analysis_session_steps → bi_analysis_insights → bi_analysis_reports

回滚顺序（降级）：
  bi_analysis_reports → bi_analysis_insights → bi_analysis_session_steps → bi_analysis_sessions
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "20260426_0001"
down_revision: Union[str, None] = "20260425_020000"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ==================== bi_analysis_sessions ====================
    op.create_table(
        "bi_analysis_sessions",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False, server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("agent_type", sa.String(length=32), nullable=False, server_default=sa.text("'data_agent'")),
        sa.Column("task_type", sa.String(length=16), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False, server_default=sa.text("'created'")),
        sa.Column("expiration_reason", sa.String(length=32), nullable=True),
        sa.Column("hypothesis_tree", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("current_step", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("context_snapshot", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("metadata", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("created_by", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.Column("expired_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_as_tenant_status", "bi_analysis_sessions", ["tenant_id", "status"], unique=False)
    op.create_index("ix_as_user_status", "bi_analysis_sessions", ["tenant_id", "created_by", "status"], unique=False)
    op.create_index("ix_as_task_type", "bi_analysis_sessions", ["task_type"], unique=False)
    op.create_index("ix_as_created", "bi_analysis_sessions", [sa.text("created_at DESC")], unique=False)

    # ==================== bi_analysis_session_steps ====================
    # Create sequence for sequence_no BIGSERIAL emulation
    op.execute("CREATE SEQUENCE IF NOT EXISTS bi_analysis_session_steps_seq")

    op.create_table(
        "bi_analysis_session_steps",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "session_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column(
            "sequence_no",
            sa.BigInteger(),
            nullable=False,
            server_default=sa.text("nextval('bi_analysis_session_steps_seq'::regclass)"),
        ),
        sa.Column("step_no", sa.Integer(), nullable=False),
        sa.Column("branch_id", sa.String(length=32), nullable=False, server_default=sa.text("'main'")),
        sa.Column("parent_sequence_no", sa.BigInteger(), nullable=True),
        sa.Column("idempotency_key", sa.String(length=128), nullable=True),
        sa.Column("reasoning_trace", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("query_log", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("context_delta", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["session_id"], ["bi_analysis_sessions.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("session_id", "step_no", "branch_id", name="uq_ass_step_branch"),
    )
    op.create_index("ix_ass_tenant", "bi_analysis_session_steps", ["tenant_id", "session_id"], unique=False)
    op.create_index("ix_ass_session_step", "bi_analysis_session_steps", ["tenant_id", "session_id", sa.text("step_no DESC")], unique=False)
    op.create_index("ix_ass_sequence", "bi_analysis_session_steps", ["session_id", "sequence_no"], unique=False)
    # Idempotency key partial unique index
    op.execute(
        "CREATE UNIQUE INDEX uq_ass_idem_key ON bi_analysis_session_steps (session_id, idempotency_key) "
        "WHERE idempotency_key IS NOT NULL"
    )

    # ==================== bi_analysis_insights ====================
    op.create_table(
        "bi_analysis_insights",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False, server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("session_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("insight_type", sa.String(length=16), nullable=False),
        sa.Column("title", sa.String(length=256), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("detail_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("impact_scope", sa.String(length=128), nullable=True),
        sa.Column("push_targets", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False, server_default=sa.text("'draft'")),
        sa.Column("created_by", sa.Integer(), nullable=False),
        sa.Column("lineage_status", sa.String(length=16), nullable=False, server_default=sa.text("'resolved'")),
        sa.Column("datasource_ids", postgresql.ARRAY(sa.Integer()), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("metric_names", postgresql.ARRAY(sa.Text()), nullable=True),
        sa.Column("visibility", sa.String(length=16), nullable=False, server_default=sa.text("'private'")),
        sa.Column("allowed_roles", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("published_at", sa.DateTime(), nullable=True),
        sa.Column("provenance_info", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["session_id"], ["bi_analysis_sessions.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_ai_session", "bi_analysis_insights", ["session_id"], unique=False)
    op.create_index("ix_ai_type_status", "bi_analysis_insights", ["insight_type", "status"], unique=False)
    op.create_index("ix_ai_published", "bi_analysis_insights", [sa.text("published_at DESC")], unique=False)
    op.create_index("ix_ai_ds", "bi_analysis_insights", ["datasource_ids"], unique=False, postgresql_using="gin")
    op.create_index("ix_ai_roles", "bi_analysis_insights", ["allowed_roles"], unique=False, postgresql_using="gin")
    op.create_index("ix_ai_vis_pub", "bi_analysis_insights", ["visibility", "status", sa.text("published_at DESC")], unique=False)

    # ==================== bi_analysis_reports ====================
    op.create_table(
        "bi_analysis_reports",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False, server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("session_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("subject", sa.String(length=256), nullable=False),
        sa.Column("time_range", sa.String(length=64), nullable=True),
        sa.Column("content_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("content_md", sa.Text(), nullable=True),
        sa.Column("author", sa.Integer(), nullable=False),
        sa.Column("lineage_status", sa.String(length=16), nullable=False, server_default=sa.text("'resolved'")),
        sa.Column("datasource_ids", postgresql.ARRAY(sa.Integer()), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("visibility", sa.String(length=16), nullable=False, server_default=sa.text("'private'")),
        sa.Column("allowed_roles", postgresql.ARRAY(sa.Text()), nullable=True),
        sa.Column("allowed_user_groups", postgresql.ARRAY(sa.Text()), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False, server_default=sa.text("'draft'")),
        sa.Column("published_at", sa.DateTime(), nullable=True),
        sa.Column("provenance_info", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["session_id"], ["bi_analysis_sessions.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_ar_session", "bi_analysis_reports", ["session_id"], unique=False)
    op.create_index("ix_ar_author", "bi_analysis_reports", ["author"], unique=False)
    op.create_index("ix_ar_ds", "bi_analysis_reports", ["datasource_ids"], unique=False, postgresql_using="gin")
    op.create_index("ix_ar_roles", "bi_analysis_reports", ["allowed_roles"], unique=False, postgresql_using="gin")
    op.create_index("ix_ar_groups", "bi_analysis_reports", ["allowed_user_groups"], unique=False, postgresql_using="gin")
    op.create_index("ix_ar_vis_pub", "bi_analysis_reports", ["visibility", "status", sa.text("published_at DESC")], unique=False)


def downgrade() -> None:
    # 反序 DROP
    op.drop_index("ix_ar_vis_pub", table_name="bi_analysis_reports")
    op.drop_index("ix_ar_groups", table_name="bi_analysis_reports")
    op.drop_index("ix_ar_roles", table_name="bi_analysis_reports")
    op.drop_index("ix_ar_ds", table_name="bi_analysis_reports")
    op.drop_index("ix_ar_author", table_name="bi_analysis_reports")
    op.drop_index("ix_ar_session", table_name="bi_analysis_reports")
    op.drop_table("bi_analysis_reports")

    op.drop_index("ix_ai_vis_pub", table_name="bi_analysis_insights")
    op.drop_index("ix_ai_roles", table_name="bi_analysis_insights")
    op.drop_index("ix_ai_ds", table_name="bi_analysis_insights")
    op.drop_index("ix_ai_published", table_name="bi_analysis_insights")
    op.drop_index("ix_ai_type_status", table_name="bi_analysis_insights")
    op.drop_index("ix_ai_session", table_name="bi_analysis_insights")
    op.drop_table("bi_analysis_insights")

    op.execute("DROP SEQUENCE IF EXISTS bi_analysis_session_steps_seq")
    op.drop_index("ix_ass_sequence", table_name="bi_analysis_session_steps")
    op.drop_index("ix_ass_session_step", table_name="bi_analysis_session_steps")
    op.drop_index("ix_ass_tenant", table_name="bi_analysis_session_steps")
    op.drop_table("bi_analysis_session_steps")

    op.drop_index("ix_as_created", table_name="bi_analysis_sessions")
    op.drop_index("ix_as_task_type", table_name="bi_analysis_sessions")
    op.drop_index("ix_as_user_status", table_name="bi_analysis_sessions")
    op.drop_index("ix_as_tenant_status", table_name="bi_analysis_sessions")
    op.drop_table("bi_analysis_sessions")

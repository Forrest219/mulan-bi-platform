"""add_metrics_agent_tables

Revision ID: 20260421_020000
Revises: 20260421_010000
Create Date: 2026-04-21 00:00:00.000000

Metrics Agent T1 — 5 张核心表：
- bi_metric_definitions: 指标定义（主表）
- bi_metric_lineage: 字段血缘
- bi_metric_versions: 变更版本历史
- bi_metric_anomalies: 异常检测记录
- bi_metric_consistency_checks: 跨数据源一致性校验
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "20260421_020000"
down_revision: Union[str, None] = "20260421_010000"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ==================== bi_metric_definitions（主表，最先创建）====================
    op.create_table(
        "bi_metric_definitions",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("name_zh", sa.String(length=256), nullable=True),
        sa.Column("metric_type", sa.String(length=16), nullable=False),
        sa.Column("business_domain", sa.String(length=64), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("formula", sa.Text(), nullable=True),
        sa.Column("formula_template", sa.String(length=256), nullable=True),
        sa.Column("aggregation_type", sa.String(length=16), nullable=True),
        sa.Column("result_type", sa.String(length=16), nullable=True),
        sa.Column("unit", sa.String(length=32), nullable=True),
        sa.Column("precision", sa.Integer(), nullable=False, server_default="2"),
        sa.Column("datasource_id", sa.Integer(), nullable=False),
        sa.Column("table_name", sa.String(length=128), nullable=False),
        sa.Column("column_name", sa.String(length=128), nullable=False),
        sa.Column("filters", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("lineage_status", sa.String(length=16), nullable=False, server_default="unknown"),
        sa.Column("sensitivity_level", sa.String(length=16), nullable=False, server_default="public"),
        sa.Column("created_by", sa.Integer(), nullable=False),
        sa.Column("reviewed_by", sa.Integer(), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(), nullable=True),
        sa.Column("published_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["datasource_id"], ["bi_data_sources.id"]),
        sa.ForeignKeyConstraint(["created_by"], ["auth_users.id"]),
        sa.ForeignKeyConstraint(["reviewed_by"], ["auth_users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id", "name", name="uq_bmd_tenant_name"),
    )
    op.create_index("ix_bmd_tenant", "bi_metric_definitions", ["tenant_id", "is_active"], unique=False)
    op.create_index("ix_bmd_datasource", "bi_metric_definitions", ["datasource_id"], unique=False)
    op.create_index("ix_bmd_domain", "bi_metric_definitions", ["tenant_id", "business_domain"], unique=False)
    op.create_index("ix_bmd_sensitivity", "bi_metric_definitions", ["tenant_id", "sensitivity_level"], unique=False)

    # ==================== bi_metric_lineage ====================
    op.create_table(
        "bi_metric_lineage",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("metric_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("datasource_id", sa.Integer(), nullable=False),
        sa.Column("table_name", sa.String(length=128), nullable=False),
        sa.Column("column_name", sa.String(length=128), nullable=False),
        sa.Column("column_type", sa.String(length=32), nullable=True),
        sa.Column("relationship_type", sa.String(length=16), nullable=False),
        sa.Column("hop_number", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("transformation_logic", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["metric_id"], ["bi_metric_definitions.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_bml_metric", "bi_metric_lineage", ["metric_id"], unique=False)
    op.create_index("ix_bml_tenant", "bi_metric_lineage", ["tenant_id", "metric_id"], unique=False)

    # ==================== bi_metric_versions ====================
    op.create_table(
        "bi_metric_versions",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("metric_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("change_type", sa.String(length=16), nullable=False),
        sa.Column("changes", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("changed_by", sa.Integer(), nullable=False),
        sa.Column("change_reason", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["metric_id"], ["bi_metric_definitions.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_bmv_metric_version", "bi_metric_versions", ["metric_id", "version"], unique=False)
    op.create_index("ix_bmv_tenant", "bi_metric_versions", ["tenant_id"], unique=False)

    # ==================== bi_metric_anomalies ====================
    op.create_table(
        "bi_metric_anomalies",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("metric_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("datasource_id", sa.Integer(), nullable=False),
        sa.Column("detection_method", sa.String(length=32), nullable=False),
        sa.Column("metric_value", sa.Float(), nullable=False),
        sa.Column("expected_value", sa.Float(), nullable=False),
        sa.Column("deviation_score", sa.Float(), nullable=False),
        sa.Column("deviation_threshold", sa.Float(), nullable=False),
        sa.Column("dimension_context", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("detected_at", sa.DateTime(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="detected"),
        sa.Column("resolved_by", sa.Integer(), nullable=True),
        sa.Column("resolved_at", sa.DateTime(), nullable=True),
        sa.Column("resolution_note", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["metric_id"], ["bi_metric_definitions.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_bma_metric", "bi_metric_anomalies", ["metric_id", "detected_at"], unique=False)
    op.create_index("ix_bma_status", "bi_metric_anomalies", ["tenant_id", "status", "detected_at"], unique=False)
    op.create_index("ix_bma_datasource", "bi_metric_anomalies", ["datasource_id", "detected_at"], unique=False)

    # ==================== bi_metric_consistency_checks ====================
    op.create_table(
        "bi_metric_consistency_checks",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("metric_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("metric_name", sa.String(length=128), nullable=False),
        sa.Column("datasource_id_a", sa.Integer(), nullable=False),
        sa.Column("datasource_id_b", sa.Integer(), nullable=False),
        sa.Column("value_a", sa.Float(), nullable=True),
        sa.Column("value_b", sa.Float(), nullable=True),
        sa.Column("difference", sa.Float(), nullable=True),
        sa.Column("difference_pct", sa.Float(), nullable=True),
        sa.Column("tolerance_pct", sa.Float(), nullable=False, server_default="5.0"),
        sa.Column("check_status", sa.String(length=16), nullable=False),
        sa.Column("checked_at", sa.DateTime(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["metric_id"], ["bi_metric_definitions.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_bmcc_metric", "bi_metric_consistency_checks", ["metric_id", "checked_at"], unique=False)
    op.create_index("ix_bmcc_tenant_status", "bi_metric_consistency_checks", ["tenant_id", "check_status", "checked_at"], unique=False)


def downgrade() -> None:
    # 先删子表，最后删主表
    op.drop_index("ix_bmcc_tenant_status", table_name="bi_metric_consistency_checks")
    op.drop_index("ix_bmcc_metric", table_name="bi_metric_consistency_checks")
    op.drop_table("bi_metric_consistency_checks")

    op.drop_index("ix_bma_datasource", table_name="bi_metric_anomalies")
    op.drop_index("ix_bma_status", table_name="bi_metric_anomalies")
    op.drop_index("ix_bma_metric", table_name="bi_metric_anomalies")
    op.drop_table("bi_metric_anomalies")

    op.drop_index("ix_bmv_tenant", table_name="bi_metric_versions")
    op.drop_index("ix_bmv_metric_version", table_name="bi_metric_versions")
    op.drop_table("bi_metric_versions")

    op.drop_index("ix_bml_tenant", table_name="bi_metric_lineage")
    op.drop_index("ix_bml_metric", table_name="bi_metric_lineage")
    op.drop_table("bi_metric_lineage")

    op.drop_index("ix_bmd_sensitivity", table_name="bi_metric_definitions")
    op.drop_index("ix_bmd_domain", table_name="bi_metric_definitions")
    op.drop_index("ix_bmd_datasource", table_name="bi_metric_definitions")
    op.drop_index("ix_bmd_tenant", table_name="bi_metric_definitions")
    op.drop_table("bi_metric_definitions")

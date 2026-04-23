"""add_dqc_tables

Revision ID: 20260421_060000
Revises: 20260421_050000
Create Date: 2026-04-21

Spec 31 DQC Pipeline — 7 张核心表：
- bi_dqc_monitored_assets: 被监控资产注册表
- bi_dqc_quality_rules: DQC 规则定义
- bi_dqc_cycles: 执行周期（UUID 主键）
- bi_dqc_dimension_scores: 维度评分时序（Append-Only，月分区 on computed_at）
- bi_dqc_asset_snapshots: 资产聚合快照（Append-Only，月分区 on computed_at）
- bi_dqc_rule_results: 规则执行明细（Append-Only，月分区 on executed_at）
- bi_dqc_llm_analyses: LLM 根因 / 规则建议
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "20260421_060000"
down_revision: Union[str, None] = "20260421_050000"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _is_postgres() -> bool:
    bind = op.get_bind()
    return bind.dialect.name == "postgresql"


_WEIGHTS_DEFAULT = (
    '{"completeness":0.1667,"accuracy":0.1667,"timeliness":0.1667,'
    '"validity":0.1667,"uniqueness":0.1666,"consistency":0.1666}'
)
_THRESHOLDS_DEFAULT = (
    '{"p0_score":60,"p1_score":80,"drift_p0":20,"drift_p1":10,'
    '"confidence_p0":60,"confidence_p1":80}'
)

_MONTHLY_PARTITIONED_TABLES = [
    ("bi_dqc_dimension_scores", "computed_at"),
    ("bi_dqc_asset_snapshots", "computed_at"),
    ("bi_dqc_rule_results", "executed_at"),
]


def _create_monthly_partitions(table_name: str, partition_key: str) -> None:
    """为未来 3 个月创建分区（含当月）"""
    if not _is_postgres():
        return
    from datetime import datetime

    now = datetime.utcnow().replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    months = []
    year, month = now.year, now.month
    for _ in range(4):
        months.append((year, month))
        month += 1
        if month > 12:
            month = 1
            year += 1
    months.append((year, month))

    for idx in range(len(months) - 1):
        y0, m0 = months[idx]
        y1, m1 = months[idx + 1]
        partition_name = f"{table_name}_{y0:04d}_{m0:02d}"
        op.execute(
            f"CREATE TABLE IF NOT EXISTS {partition_name} PARTITION OF {table_name} "
            f"FOR VALUES FROM ('{y0:04d}-{m0:02d}-01') TO ('{y1:04d}-{m1:02d}-01')"
        )


def upgrade() -> None:
    # ==================== bi_dqc_monitored_assets ====================
    op.create_table(
        "bi_dqc_monitored_assets",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("datasource_id", sa.Integer(), nullable=False),
        sa.Column("schema_name", sa.String(length=128), nullable=False),
        sa.Column("table_name", sa.String(length=128), nullable=False),
        sa.Column("display_name", sa.String(length=256), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column(
            "dimension_weights",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=_WEIGHTS_DEFAULT,
        ),
        sa.Column(
            "signal_thresholds",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=_THRESHOLDS_DEFAULT,
        ),
        sa.Column("profile_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="enabled"),
        sa.Column("owner_id", sa.Integer(), nullable=False),
        sa.Column("created_by", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["datasource_id"], ["bi_data_sources.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "datasource_id", "schema_name", "table_name", name="uq_dqc_asset_ds_sch_tbl"
        ),
    )
    op.create_index("ix_dqc_asset_datasource", "bi_dqc_monitored_assets", ["datasource_id"], unique=False)
    op.create_index("ix_dqc_asset_status", "bi_dqc_monitored_assets", ["status"], unique=False)
    op.create_index("ix_dqc_asset_owner", "bi_dqc_monitored_assets", ["owner_id"], unique=False)

    # ==================== bi_dqc_quality_rules ====================
    op.create_table(
        "bi_dqc_quality_rules",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("asset_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=256), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("dimension", sa.String(length=32), nullable=False),
        sa.Column("rule_type", sa.String(length=32), nullable=False),
        sa.Column(
            "rule_config",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default="{}",
        ),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("is_system_suggested", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("suggested_by_llm_analysis_id", sa.Integer(), nullable=True),
        sa.Column("created_by", sa.Integer(), nullable=False),
        sa.Column("updated_by", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["asset_id"], ["bi_dqc_monitored_assets.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_dqc_rule_asset", "bi_dqc_quality_rules", ["asset_id"], unique=False)
    op.create_index("ix_dqc_rule_asset_dim", "bi_dqc_quality_rules", ["asset_id", "dimension"], unique=False)
    op.create_index("ix_dqc_rule_asset_active", "bi_dqc_quality_rules", ["asset_id", "is_active"], unique=False)

    # ==================== bi_dqc_cycles ====================
    op.create_table(
        "bi_dqc_cycles",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("trigger_type", sa.String(length=16), nullable=False, server_default="scheduled"),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="pending"),
        sa.Column("scope", sa.String(length=16), nullable=False, server_default="full"),
        sa.Column("started_at", sa.DateTime(), nullable=True),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.Column("assets_total", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("assets_processed", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("assets_failed", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("rules_executed", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("p0_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("p1_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("triggered_by", sa.Integer(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_dqc_cycle_status_created", "bi_dqc_cycles", ["status", "created_at"], unique=False)
    op.create_index("ix_dqc_cycle_started", "bi_dqc_cycles", ["started_at"], unique=False)

    # ==================== bi_dqc_dimension_scores (Append-Only, monthly partition) ====================
    if _is_postgres():
        op.execute(
            """
            CREATE TABLE bi_dqc_dimension_scores (
                id BIGSERIAL NOT NULL,
                cycle_id UUID NOT NULL,
                asset_id INTEGER NOT NULL,
                dimension VARCHAR(32) NOT NULL,
                score DOUBLE PRECISION NOT NULL,
                signal VARCHAR(8) NOT NULL,
                prev_score DOUBLE PRECISION,
                drift_24h DOUBLE PRECISION,
                drift_vs_7d_avg DOUBLE PRECISION,
                rules_total INTEGER NOT NULL DEFAULT 0,
                rules_passed INTEGER NOT NULL DEFAULT 0,
                rules_failed INTEGER NOT NULL DEFAULT 0,
                computed_at TIMESTAMP NOT NULL DEFAULT now(),
                PRIMARY KEY (id, computed_at)
            ) PARTITION BY RANGE (computed_at)
            """
        )
    else:
        op.create_table(
            "bi_dqc_dimension_scores",
            sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
            sa.Column("cycle_id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("asset_id", sa.Integer(), nullable=False),
            sa.Column("dimension", sa.String(length=32), nullable=False),
            sa.Column("score", sa.Float(), nullable=False),
            sa.Column("signal", sa.String(length=8), nullable=False),
            sa.Column("prev_score", sa.Float(), nullable=True),
            sa.Column("drift_24h", sa.Float(), nullable=True),
            sa.Column("drift_vs_7d_avg", sa.Float(), nullable=True),
            sa.Column("rules_total", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("rules_passed", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("rules_failed", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("computed_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
            sa.PrimaryKeyConstraint("id"),
        )
    op.create_index(
        "ix_dqc_dim_asset_dim_computed",
        "bi_dqc_dimension_scores",
        ["asset_id", "dimension", "computed_at"],
        unique=False,
    )
    op.create_index("ix_dqc_dim_cycle", "bi_dqc_dimension_scores", ["cycle_id"], unique=False)
    op.create_index("ix_dqc_dim_signal", "bi_dqc_dimension_scores", ["signal"], unique=False)

    # ==================== bi_dqc_asset_snapshots (Append-Only, monthly partition) ====================
    if _is_postgres():
        op.execute(
            """
            CREATE TABLE bi_dqc_asset_snapshots (
                id BIGSERIAL NOT NULL,
                cycle_id UUID NOT NULL,
                asset_id INTEGER NOT NULL,
                confidence_score DOUBLE PRECISION NOT NULL,
                signal VARCHAR(8) NOT NULL,
                prev_signal VARCHAR(8),
                dimension_scores JSONB NOT NULL DEFAULT '{}',
                dimension_signals JSONB NOT NULL DEFAULT '{}',
                row_count_snapshot BIGINT,
                computed_at TIMESTAMP NOT NULL DEFAULT now(),
                PRIMARY KEY (id, computed_at)
            ) PARTITION BY RANGE (computed_at)
            """
        )
    else:
        op.create_table(
            "bi_dqc_asset_snapshots",
            sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
            sa.Column("cycle_id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("asset_id", sa.Integer(), nullable=False),
            sa.Column("confidence_score", sa.Float(), nullable=False),
            sa.Column("signal", sa.String(length=8), nullable=False),
            sa.Column("prev_signal", sa.String(length=8), nullable=True),
            sa.Column(
                "dimension_scores",
                postgresql.JSONB(astext_type=sa.Text()),
                nullable=False,
                server_default="{}",
            ),
            sa.Column(
                "dimension_signals",
                postgresql.JSONB(astext_type=sa.Text()),
                nullable=False,
                server_default="{}",
            ),
            sa.Column("row_count_snapshot", sa.BigInteger(), nullable=True),
            sa.Column("computed_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
            sa.PrimaryKeyConstraint("id"),
        )
    op.create_index(
        "ix_dqc_snap_asset_computed",
        "bi_dqc_asset_snapshots",
        ["asset_id", "computed_at"],
        unique=False,
    )
    op.create_index("ix_dqc_snap_cycle", "bi_dqc_asset_snapshots", ["cycle_id"], unique=False)
    op.create_index("ix_dqc_snap_signal", "bi_dqc_asset_snapshots", ["signal"], unique=False)

    # ==================== bi_dqc_rule_results (Append-Only, monthly partition) ====================
    if _is_postgres():
        op.execute(
            """
            CREATE TABLE bi_dqc_rule_results (
                id BIGSERIAL NOT NULL,
                cycle_id UUID NOT NULL,
                asset_id INTEGER NOT NULL,
                rule_id INTEGER NOT NULL,
                dimension VARCHAR(32) NOT NULL,
                rule_type VARCHAR(32) NOT NULL,
                passed BOOLEAN NOT NULL,
                actual_value DOUBLE PRECISION,
                expected_config JSONB,
                error_message TEXT,
                execution_time_ms INTEGER,
                executed_at TIMESTAMP NOT NULL DEFAULT now(),
                PRIMARY KEY (id, executed_at)
            ) PARTITION BY RANGE (executed_at)
            """
        )
    else:
        op.create_table(
            "bi_dqc_rule_results",
            sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
            sa.Column("cycle_id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("asset_id", sa.Integer(), nullable=False),
            sa.Column("rule_id", sa.Integer(), nullable=False),
            sa.Column("dimension", sa.String(length=32), nullable=False),
            sa.Column("rule_type", sa.String(length=32), nullable=False),
            sa.Column("passed", sa.Boolean(), nullable=False),
            sa.Column("actual_value", sa.Float(), nullable=True),
            sa.Column("expected_config", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
            sa.Column("error_message", sa.Text(), nullable=True),
            sa.Column("execution_time_ms", sa.Integer(), nullable=True),
            sa.Column("executed_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
            sa.PrimaryKeyConstraint("id"),
        )
    op.create_index(
        "ix_dqc_rres_cycle_asset",
        "bi_dqc_rule_results",
        ["cycle_id", "asset_id"],
        unique=False,
    )
    op.create_index(
        "ix_dqc_rres_asset_rule",
        "bi_dqc_rule_results",
        ["asset_id", "rule_id"],
        unique=False,
    )
    op.create_index(
        "ix_dqc_rres_passed_executed",
        "bi_dqc_rule_results",
        ["passed", "executed_at"],
        unique=False,
    )

    # ==================== bi_dqc_llm_analyses ====================
    op.create_table(
        "bi_dqc_llm_analyses",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("cycle_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("asset_id", sa.Integer(), nullable=False),
        sa.Column("trigger", sa.String(length=32), nullable=False),
        sa.Column("signal", sa.String(length=8), nullable=True),
        sa.Column("prompt_tokens", sa.Integer(), nullable=True),
        sa.Column("completion_tokens", sa.Integer(), nullable=True),
        sa.Column("latency_ms", sa.Integer(), nullable=True),
        sa.Column("root_cause", sa.Text(), nullable=True),
        sa.Column("fix_suggestion", sa.Text(), nullable=True),
        sa.Column("fix_sql", sa.Text(), nullable=True),
        sa.Column("confidence", sa.String(length=8), nullable=True),
        sa.Column("suggested_rules", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("raw_response", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="success"),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_dqc_llm_analyses_cycle_id", "bi_dqc_llm_analyses", ["cycle_id"], unique=False
    )
    op.create_index(
        "ix_dqc_llm_analyses_asset_id", "bi_dqc_llm_analyses", ["asset_id"], unique=False
    )
    op.create_index(
        "ix_dqc_llm_analyses_created_at", "bi_dqc_llm_analyses", ["created_at"], unique=False
    )
    op.create_index(
        "ix_dqc_llm_asset_created", "bi_dqc_llm_analyses", ["asset_id", "created_at"], unique=False
    )

    # 创建首批月分区（PostgreSQL only）
    for tbl, key in _MONTHLY_PARTITIONED_TABLES:
        _create_monthly_partitions(tbl, key)


def downgrade() -> None:
    # 倒序 DROP：先子表（引用 assets / cycles）再父表
    op.drop_index("ix_dqc_llm_asset_created", table_name="bi_dqc_llm_analyses")
    op.drop_index("ix_dqc_llm_analyses_created_at", table_name="bi_dqc_llm_analyses")
    op.drop_index("ix_dqc_llm_analyses_asset_id", table_name="bi_dqc_llm_analyses")
    op.drop_index("ix_dqc_llm_analyses_cycle_id", table_name="bi_dqc_llm_analyses")
    op.drop_table("bi_dqc_llm_analyses")

    op.drop_index("ix_dqc_rres_passed_executed", table_name="bi_dqc_rule_results")
    op.drop_index("ix_dqc_rres_asset_rule", table_name="bi_dqc_rule_results")
    op.drop_index("ix_dqc_rres_cycle_asset", table_name="bi_dqc_rule_results")
    op.execute("DROP TABLE IF EXISTS bi_dqc_rule_results CASCADE")

    op.drop_index("ix_dqc_snap_signal", table_name="bi_dqc_asset_snapshots")
    op.drop_index("ix_dqc_snap_cycle", table_name="bi_dqc_asset_snapshots")
    op.drop_index("ix_dqc_snap_asset_computed", table_name="bi_dqc_asset_snapshots")
    op.execute("DROP TABLE IF EXISTS bi_dqc_asset_snapshots CASCADE")

    op.drop_index("ix_dqc_dim_signal", table_name="bi_dqc_dimension_scores")
    op.drop_index("ix_dqc_dim_cycle", table_name="bi_dqc_dimension_scores")
    op.drop_index("ix_dqc_dim_asset_dim_computed", table_name="bi_dqc_dimension_scores")
    op.execute("DROP TABLE IF EXISTS bi_dqc_dimension_scores CASCADE")

    op.drop_index("ix_dqc_cycle_started", table_name="bi_dqc_cycles")
    op.drop_index("ix_dqc_cycle_status_created", table_name="bi_dqc_cycles")
    op.drop_table("bi_dqc_cycles")

    op.drop_index("ix_dqc_rule_asset_active", table_name="bi_dqc_quality_rules")
    op.drop_index("ix_dqc_rule_asset_dim", table_name="bi_dqc_quality_rules")
    op.drop_index("ix_dqc_rule_asset", table_name="bi_dqc_quality_rules")
    op.drop_table("bi_dqc_quality_rules")

    op.drop_index("ix_dqc_asset_owner", table_name="bi_dqc_monitored_assets")
    op.drop_index("ix_dqc_asset_status", table_name="bi_dqc_monitored_assets")
    op.drop_index("ix_dqc_asset_datasource", table_name="bi_dqc_monitored_assets")
    op.drop_table("bi_dqc_monitored_assets")

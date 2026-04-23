"""DQC - Data Quality Core 数据模型

遵循项目规范：
- 表前缀 bi_dqc_
- snake_case 字段名
- TIMESTAMP WITHOUT TIME ZONE
- JSONB 用 app.core.database.JSONB
- to_dict() 时间使用 "%Y-%m-%d %H:%M:%S" 格式
- Append-Only 表按月分区（由 Alembic 迁移创建分区）
"""
from typing import Any, Dict
from uuid import uuid4

from sqlalchemy import (
    BigInteger,
    Boolean,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    PrimaryKeyConstraint,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID as PG_UUID

from app.core.database import Base, JSONB, sa_func, sa_text
from sqlalchemy import literal_column


class DqcMonitoredAsset(Base):
    """被监控的数据资产（表粒度）"""
    __tablename__ = "bi_dqc_monitored_assets"

    id = Column(Integer, primary_key=True, autoincrement=True)
    datasource_id = Column(
        Integer,
        ForeignKey("bi_data_sources.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    schema_name = Column(String(128), nullable=False)
    table_name = Column(String(128), nullable=False)
    display_name = Column(String(256), nullable=True)
    description = Column(Text, nullable=True)

    dimension_weights = Column(
        JSONB,
        nullable=False,
        server_default=literal_column(
            "'{\"completeness\":0.1667,\"accuracy\":0.1667,\"timeliness\":0.1667,"
            "\"validity\":0.1667,\"uniqueness\":0.1666,\"consistency\":0.1666}'"
        ),
    )
    signal_thresholds = Column(
        JSONB,
        nullable=False,
        server_default=literal_column(
            "'{\"p0_score\":60,\"p1_score\":80,\"drift_p0\":20,\"drift_p1\":10,"
            "\"confidence_p0\":60,\"confidence_p1\":80}'"
        ),
    )
    profile_json = Column(JSONB, nullable=True)

    status = Column(String(16), nullable=False, server_default=sa_text("'enabled'"))
    owner_id = Column(Integer, nullable=False, index=True)
    created_by = Column(Integer, nullable=False)
    created_at = Column(DateTime, nullable=False, server_default=sa_func.now())
    updated_at = Column(DateTime, nullable=False, server_default=sa_func.now(), onupdate=sa_func.now())

    __table_args__ = (
        UniqueConstraint("datasource_id", "schema_name", "table_name", name="uq_dqc_asset_ds_sch_tbl"),
        Index("ix_dqc_asset_status", "status"),
        Index("ix_dqc_asset_owner", "owner_id"),
    )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "datasource_id": self.datasource_id,
            "schema_name": self.schema_name,
            "table_name": self.table_name,
            "display_name": self.display_name,
            "description": self.description,
            "dimension_weights": self.dimension_weights,
            "signal_thresholds": self.signal_thresholds,
            "profile_json": self.profile_json,
            "status": self.status,
            "owner_id": self.owner_id,
            "created_by": self.created_by,
            "created_at": self.created_at.strftime("%Y-%m-%d %H:%M:%S") if self.created_at else None,
            "updated_at": self.updated_at.strftime("%Y-%m-%d %H:%M:%S") if self.updated_at else None,
        }


class DqcQualityRule(Base):
    """DQC 质量规则（关联到 monitored_asset）"""
    __tablename__ = "bi_dqc_quality_rules"

    id = Column(Integer, primary_key=True, autoincrement=True)
    asset_id = Column(
        Integer,
        ForeignKey("bi_dqc_monitored_assets.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    name = Column(String(256), nullable=False)
    description = Column(Text, nullable=True)
    dimension = Column(String(32), nullable=False)
    rule_type = Column(String(32), nullable=False)
    rule_config = Column(JSONB, nullable=False, server_default=sa_text("'{}'"))

    is_active = Column(Boolean, nullable=False, server_default=sa_text("true"))
    is_system_suggested = Column(Boolean, nullable=False, server_default=sa_text("false"))
    suggested_by_llm_analysis_id = Column(Integer, nullable=True)

    created_by = Column(Integer, nullable=False)
    updated_by = Column(Integer, nullable=True)
    created_at = Column(DateTime, nullable=False, server_default=sa_func.now())
    updated_at = Column(DateTime, nullable=False, server_default=sa_func.now(), onupdate=sa_func.now())

    __table_args__ = (
        Index("ix_dqc_rule_asset_dim", "asset_id", "dimension"),
        Index("ix_dqc_rule_asset_active", "asset_id", "is_active"),
    )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "asset_id": self.asset_id,
            "name": self.name,
            "description": self.description,
            "dimension": self.dimension,
            "rule_type": self.rule_type,
            "rule_config": self.rule_config,
            "is_active": self.is_active,
            "is_system_suggested": self.is_system_suggested,
            "suggested_by_llm_analysis_id": self.suggested_by_llm_analysis_id,
            "created_by": self.created_by,
            "updated_by": self.updated_by,
            "created_at": self.created_at.strftime("%Y-%m-%d %H:%M:%S") if self.created_at else None,
            "updated_at": self.updated_at.strftime("%Y-%m-%d %H:%M:%S") if self.updated_at else None,
        }


class DqcCycle(Base):
    """DQC 执行周期"""
    __tablename__ = "bi_dqc_cycles"

    id = Column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    trigger_type = Column(String(16), nullable=False, server_default=sa_text("'scheduled'"))
    status = Column(String(16), nullable=False, server_default=sa_text("'pending'"))
    scope = Column(String(16), nullable=False, server_default=sa_text("'full'"))
    started_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)

    assets_total = Column(Integer, nullable=False, server_default=sa_text("0"))
    assets_processed = Column(Integer, nullable=False, server_default=sa_text("0"))
    assets_failed = Column(Integer, nullable=False, server_default=sa_text("0"))
    rules_executed = Column(Integer, nullable=False, server_default=sa_text("0"))
    p0_count = Column(Integer, nullable=False, server_default=sa_text("0"))
    p1_count = Column(Integer, nullable=False, server_default=sa_text("0"))

    triggered_by = Column(Integer, nullable=True)
    error_message = Column(Text, nullable=True)
    created_at = Column(DateTime, nullable=False, server_default=sa_func.now())

    __table_args__ = (
        Index("ix_dqc_cycle_status_created", "status", "created_at"),
        Index("ix_dqc_cycle_started", "started_at"),
    )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": str(self.id) if self.id else None,
            "trigger_type": self.trigger_type,
            "status": self.status,
            "scope": self.scope,
            "started_at": self.started_at.strftime("%Y-%m-%d %H:%M:%S") if self.started_at else None,
            "completed_at": self.completed_at.strftime("%Y-%m-%d %H:%M:%S") if self.completed_at else None,
            "assets_total": self.assets_total,
            "assets_processed": self.assets_processed,
            "assets_failed": self.assets_failed,
            "rules_executed": self.rules_executed,
            "p0_count": self.p0_count,
            "p1_count": self.p1_count,
            "triggered_by": self.triggered_by,
            "error_message": self.error_message,
            "created_at": self.created_at.strftime("%Y-%m-%d %H:%M:%S") if self.created_at else None,
        }


class DqcDimensionScore(Base):
    """维度评分时序（Append-Only，月分区）"""
    __tablename__ = "bi_dqc_dimension_scores"

    id = Column(BigInteger, autoincrement=True, nullable=False)
    cycle_id = Column(PG_UUID(as_uuid=True), nullable=False, index=True)
    asset_id = Column(Integer, nullable=False, index=True)
    dimension = Column(String(32), nullable=False)

    score = Column(Float, nullable=False)
    signal = Column(String(8), nullable=False)

    prev_score = Column(Float, nullable=True)
    drift_24h = Column(Float, nullable=True)
    drift_vs_7d_avg = Column(Float, nullable=True)

    rules_total = Column(Integer, nullable=False, server_default=sa_text("0"))
    rules_passed = Column(Integer, nullable=False, server_default=sa_text("0"))
    rules_failed = Column(Integer, nullable=False, server_default=sa_text("0"))

    computed_at = Column(DateTime, nullable=False, server_default=sa_func.now())

    __table_args__ = (
        PrimaryKeyConstraint("id", "computed_at", name="pk_bi_dqc_dimension_scores"),
        Index("ix_dqc_dim_asset_dim_computed", "asset_id", "dimension", "computed_at"),
        Index("ix_dqc_dim_cycle", "cycle_id"),
        Index("ix_dqc_dim_signal", "signal"),
    )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "cycle_id": str(self.cycle_id) if self.cycle_id else None,
            "asset_id": self.asset_id,
            "dimension": self.dimension,
            "score": self.score,
            "signal": self.signal,
            "prev_score": self.prev_score,
            "drift_24h": self.drift_24h,
            "drift_vs_7d_avg": self.drift_vs_7d_avg,
            "rules_total": self.rules_total,
            "rules_passed": self.rules_passed,
            "rules_failed": self.rules_failed,
            "computed_at": self.computed_at.strftime("%Y-%m-%d %H:%M:%S") if self.computed_at else None,
        }


class DqcAssetSnapshot(Base):
    """资产聚合快照（Append-Only，月分区）"""
    __tablename__ = "bi_dqc_asset_snapshots"

    id = Column(BigInteger, autoincrement=True, nullable=False)
    cycle_id = Column(PG_UUID(as_uuid=True), nullable=False, index=True)
    asset_id = Column(Integer, nullable=False, index=True)

    confidence_score = Column(Float, nullable=False)
    signal = Column(String(8), nullable=False)
    prev_signal = Column(String(8), nullable=True)

    dimension_scores = Column(JSONB, nullable=False, server_default=sa_text("'{}'"))
    dimension_signals = Column(JSONB, nullable=False, server_default=sa_text("'{}'"))

    row_count_snapshot = Column(BigInteger, nullable=True)

    computed_at = Column(DateTime, nullable=False, server_default=sa_func.now())

    __table_args__ = (
        PrimaryKeyConstraint("id", "computed_at", name="pk_bi_dqc_asset_snapshots"),
        Index("ix_dqc_snap_asset_computed", "asset_id", "computed_at"),
        Index("ix_dqc_snap_cycle", "cycle_id"),
        Index("ix_dqc_snap_signal", "signal"),
    )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "cycle_id": str(self.cycle_id) if self.cycle_id else None,
            "asset_id": self.asset_id,
            "confidence_score": self.confidence_score,
            "signal": self.signal,
            "prev_signal": self.prev_signal,
            "dimension_scores": self.dimension_scores,
            "dimension_signals": self.dimension_signals,
            "row_count_snapshot": self.row_count_snapshot,
            "computed_at": self.computed_at.strftime("%Y-%m-%d %H:%M:%S") if self.computed_at else None,
        }


class DqcRuleResult(Base):
    """规则执行明细（Append-Only，月分区）"""
    __tablename__ = "bi_dqc_rule_results"

    id = Column(BigInteger, autoincrement=True, nullable=False)
    cycle_id = Column(PG_UUID(as_uuid=True), nullable=False, index=True)
    asset_id = Column(Integer, nullable=False, index=True)
    rule_id = Column(Integer, nullable=False, index=True)
    dimension = Column(String(32), nullable=False)
    rule_type = Column(String(32), nullable=False)

    passed = Column(Boolean, nullable=False)
    actual_value = Column(Float, nullable=True)
    expected_config = Column(JSONB, nullable=True)
    error_message = Column(Text, nullable=True)
    execution_time_ms = Column(Integer, nullable=True)

    executed_at = Column(DateTime, nullable=False, server_default=sa_func.now())

    __table_args__ = (
        PrimaryKeyConstraint("id", "executed_at", name="pk_bi_dqc_rule_results"),
        Index("ix_dqc_rres_cycle_asset", "cycle_id", "asset_id"),
        Index("ix_dqc_rres_asset_rule", "asset_id", "rule_id"),
        Index("ix_dqc_rres_passed_executed", "passed", "executed_at"),
    )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "cycle_id": str(self.cycle_id) if self.cycle_id else None,
            "asset_id": self.asset_id,
            "rule_id": self.rule_id,
            "dimension": self.dimension,
            "rule_type": self.rule_type,
            "passed": self.passed,
            "actual_value": self.actual_value,
            "expected_config": self.expected_config,
            "error_message": self.error_message,
            "execution_time_ms": self.execution_time_ms,
            "executed_at": self.executed_at.strftime("%Y-%m-%d %H:%M:%S") if self.executed_at else None,
        }


class DqcLlmAnalysis(Base):
    """LLM 根因分析结果"""
    __tablename__ = "bi_dqc_llm_analyses"

    id = Column(Integer, primary_key=True, autoincrement=True)
    cycle_id = Column(PG_UUID(as_uuid=True), nullable=True, index=True)
    asset_id = Column(Integer, nullable=False, index=True)
    trigger = Column(String(32), nullable=False)
    signal = Column(String(8), nullable=True)

    prompt_tokens = Column(Integer, nullable=True)
    completion_tokens = Column(Integer, nullable=True)
    latency_ms = Column(Integer, nullable=True)

    root_cause = Column(Text, nullable=True)
    fix_suggestion = Column(Text, nullable=True)
    fix_sql = Column(Text, nullable=True)
    confidence = Column(String(8), nullable=True)

    suggested_rules = Column(JSONB, nullable=True)

    raw_response = Column(Text, nullable=True)
    status = Column(String(16), nullable=False, server_default=sa_text("'success'"))
    error_message = Column(Text, nullable=True)

    created_at = Column(DateTime, nullable=False, server_default=sa_func.now(), index=True)

    __table_args__ = (
        Index("ix_dqc_llm_asset_created", "asset_id", "created_at"),
    )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "cycle_id": str(self.cycle_id) if self.cycle_id else None,
            "asset_id": self.asset_id,
            "trigger": self.trigger,
            "signal": self.signal,
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "latency_ms": self.latency_ms,
            "root_cause": self.root_cause,
            "fix_suggestion": self.fix_suggestion,
            "fix_sql": self.fix_sql,
            "confidence": self.confidence,
            "suggested_rules": self.suggested_rules,
            "status": self.status,
            "error_message": self.error_message,
            "created_at": self.created_at.strftime("%Y-%m-%d %H:%M:%S") if self.created_at else None,
        }

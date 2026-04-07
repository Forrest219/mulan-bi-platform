"""数据质量监控 - 数据模型

定义 bi_quality_rules、bi_quality_results、bi_quality_scores 三张核心表。
遵循 Spec 15 v1.1 的 Append-Only + 分区设计约束。
"""
from typing import Optional, List, Dict, Any

from sqlalchemy import (
    Column, Integer, String, DateTime, Boolean,
    Float, Text, ForeignKey, Index, JSON
)
from app.core.database import Base, JSONB, sa_func, sa_text


class QualityRule(Base):
    """质量规则定义"""
    __tablename__ = "bi_quality_rules"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(256), nullable=False)
    description = Column(Text, nullable=True)
    datasource_id = Column(Integer, ForeignKey("bi_data_sources.id", ondelete="CASCADE"), nullable=False, index=True)
    table_name = Column(String(128), nullable=False)
    field_name = Column(String(128), nullable=True)  # NULL = 表级规则
    rule_type = Column(String(32), nullable=False)
    operator = Column(String(16), nullable=False, server_default=sa_text("'lte'"))
    threshold = Column(JSONB, nullable=False, server_default=sa_text("'{}'"))
    severity = Column(String(16), nullable=False, server_default=sa_text("'MEDIUM'"))
    execution_mode = Column(String(16), nullable=False, server_default=sa_text("'scheduled'"))
    cron = Column(String(64), nullable=True)
    custom_sql = Column(Text, nullable=True)
    enabled = Column(Boolean, nullable=False, server_default=sa_text("true"))
    tags_json = Column(JSONB, nullable=True)
    created_by = Column(Integer, nullable=False)
    updated_by = Column(Integer, nullable=True)
    created_at = Column(DateTime, nullable=False, server_default=sa_func.now())
    updated_at = Column(DateTime, nullable=False, server_default=sa_func.now(), onupdate=sa_func.now())

    __table_args__ = (
        Index("ix_qr_ds_table", "datasource_id", "table_name"),
        Index("ix_qr_enabled", "enabled"),
    )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "datasource_id": self.datasource_id,
            "table_name": self.table_name,
            "field_name": self.field_name,
            "rule_type": self.rule_type,
            "operator": self.operator,
            "threshold": self.threshold,
            "severity": self.severity,
            "execution_mode": self.execution_mode,
            "cron": self.cron,
            "custom_sql": self.custom_sql,
            "enabled": self.enabled,
            "tags_json": self.tags_json,
            "created_by": self.created_by,
            "updated_by": self.updated_by,
            "created_at": self.created_at.strftime("%Y-%m-%d %H:%M:%S") if self.created_at else None,
            "updated_at": self.updated_at.strftime("%Y-%m-%d %H:%M:%S") if self.updated_at else None,
        }


class QualityResult(Base):
    """质量检测结果 - Append-Only，明细数据默认保留 90 天（见 Spec 15 §2.1）"""
    __tablename__ = "bi_quality_results"

    id = Column(Integer, primary_key=True, autoincrement=True)
    rule_id = Column(Integer, ForeignKey("bi_quality_rules.id", ondelete="CASCADE"), nullable=False, index=True)
    datasource_id = Column(Integer, nullable=False, index=True)
    table_name = Column(String(128), nullable=False)
    field_name = Column(String(128), nullable=True)
    # P1 修复：冗余存储 rule_type，支持 scorer.py 维度聚合计算（无需 JOIN 查询）
    rule_type = Column(String(32), nullable=False)
    executed_at = Column(DateTime, nullable=False, server_default=sa_func.now())  # 分区键
    passed = Column(Boolean, nullable=False)
    actual_value = Column(Float, nullable=True)
    expected_value = Column(String(256), nullable=True)
    detail_json = Column(JSONB, nullable=True)
    execution_time_ms = Column(Integer, nullable=True)
    error_message = Column(Text, nullable=True)
    created_at = Column(DateTime, nullable=False, server_default=sa_func.now())

    __table_args__ = (
        Index("ix_qres_rule_exec", "rule_id", "executed_at"),
        Index("ix_qres_ds_exec", "datasource_id", "executed_at"),
        Index("ix_qres_passed", "passed"),
    )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "rule_id": self.rule_id,
            "datasource_id": self.datasource_id,
            "table_name": self.table_name,
            "field_name": self.field_name,
            "rule_type": self.rule_type,
            "executed_at": self.executed_at.strftime("%Y-%m-%d %H:%M:%S") if self.executed_at else None,
            "passed": self.passed,
            "actual_value": self.actual_value,
            "expected_value": self.expected_value,
            "detail_json": self.detail_json,
            "execution_time_ms": self.execution_time_ms,
            "error_message": self.error_message,
            "created_at": self.created_at.strftime("%Y-%m-%d %H:%M:%S") if self.created_at else None,
        }


class QualityScore(Base):
    """质量评分快照 - Append-Only，每次计算新增一条（见 Spec 15 §2.1）"""
    __tablename__ = "bi_quality_scores"

    id = Column(Integer, primary_key=True, autoincrement=True)
    datasource_id = Column(Integer, nullable=False, index=True)
    scope_type = Column(String(16), nullable=False)  # datasource / table / field
    scope_name = Column(String(256), nullable=False)
    overall_score = Column(Float, nullable=False)
    completeness_score = Column(Float, nullable=True)
    consistency_score = Column(Float, nullable=True)
    uniqueness_score = Column(Float, nullable=True)
    timeliness_score = Column(Float, nullable=True)
    conformity_score = Column(Float, nullable=True)
    health_scan_score = Column(Float, nullable=True)
    ddl_compliance_score = Column(Float, nullable=True)
    detail_json = Column(JSONB, nullable=True)
    calculated_at = Column(DateTime, nullable=False, server_default=sa_func.now())  # 分区键

    __table_args__ = (
        Index("ix_qs_ds_scope", "datasource_id", "scope_type", "scope_name", "calculated_at"),
        Index("ix_qs_calc_at", "calculated_at"),
    )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "datasource_id": self.datasource_id,
            "scope_type": self.scope_type,
            "scope_name": self.scope_name,
            "overall_score": self.overall_score,
            "completeness_score": self.completeness_score,
            "consistency_score": self.consistency_score,
            "uniqueness_score": self.uniqueness_score,
            "timeliness_score": self.timeliness_score,
            "conformity_score": self.conformity_score,
            "health_scan_score": self.health_scan_score,
            "ddl_compliance_score": self.ddl_compliance_score,
            "detail_json": self.detail_json,
            "calculated_at": self.calculated_at.strftime("%Y-%m-%d %H:%M:%S") if self.calculated_at else None,
        }

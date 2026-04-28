"""数据治理质量模块 — SQLAlchemy 2.x ORM Models"""

from datetime import datetime
from typing import Optional, Any

from sqlalchemy import (
    Boolean, Float, ForeignKey, Index, Integer, String, Text,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base  # 复用项目已有 Base


class BiQualityRule(Base):
    """质量规则定义表"""
    __tablename__ = "bi_quality_rules"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(256), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    datasource_id: Mapped[int] = mapped_column(Integer, ForeignKey("bi_data_sources.id"), nullable=False)
    table_name: Mapped[str] = mapped_column(String(128), nullable=False)
    field_name: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)  # NULL=表级规则
    rule_type: Mapped[str] = mapped_column(String(32), nullable=False)  # 13种规则类型标识
    operator: Mapped[str] = mapped_column(String(16), nullable=False, server_default="lte")
    threshold: Mapped[Any] = mapped_column(JSONB, nullable=False, server_default="{}")
    severity: Mapped[str] = mapped_column(String(16), nullable=False, server_default="MEDIUM")  # HIGH/MEDIUM/LOW
    execution_mode: Mapped[str] = mapped_column(String(16), nullable=False, server_default="scheduled")  # realtime/scheduled/manual
    cron: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    custom_sql: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")
    tags_json: Mapped[Optional[Any]] = mapped_column(JSONB, nullable=True)
    created_by: Mapped[int] = mapped_column(Integer, nullable=False)
    updated_by: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(nullable=False, server_default=func.now(), onupdate=func.now())

    # 索引
    __table_args__ = (
        Index("ix_qr_ds_table", "datasource_id", "table_name"),
        Index("ix_qr_enabled", "enabled"),
    )


class BiQualityResult(Base):
    """质量执行结果表 — 按 executed_at 分区（分区键）"""
    __tablename__ = "bi_quality_results"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    rule_id: Mapped[int] = mapped_column(Integer, ForeignKey("bi_quality_rules.id"), nullable=False)
    datasource_id: Mapped[int] = mapped_column(Integer, nullable=False)
    table_name: Mapped[str] = mapped_column(String(128), nullable=False)
    field_name: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    executed_at: Mapped[datetime] = mapped_column(nullable=False, server_default=func.now())  # 分区键
    passed: Mapped[bool] = mapped_column(Boolean, nullable=False)
    actual_value: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    expected_value: Mapped[Optional[str]] = mapped_column(String(256), nullable=True)
    detail_json: Mapped[Optional[Any]] = mapped_column(JSONB, nullable=True)
    execution_time_ms: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(nullable=False, server_default=func.now())

    # 索引
    __table_args__ = (
        Index("ix_qres_rule_exec", "rule_id", executed_at.desc()),
        Index("ix_qres_ds_exec", "datasource_id", executed_at.desc()),
        Index("ix_qres_passed", "passed"),
    )


class BiQualityScore(Base):
    """质量评分表 — Append-Only，禁止 UPSERT"""
    __tablename__ = "bi_quality_scores"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    datasource_id: Mapped[int] = mapped_column(Integer, nullable=False)
    scope_type: Mapped[str] = mapped_column(String(16), nullable=False)  # datasource/table/field
    scope_name: Mapped[str] = mapped_column(String(256), nullable=False)
    overall_score: Mapped[float] = mapped_column(Float, nullable=False)
    completeness_score: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    consistency_score: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    uniqueness_score: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    timeliness_score: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    conformity_score: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    health_scan_score: Mapped[Optional[float]] = mapped_column(Float, nullable=True)  # 来自 Spec 11
    ddl_compliance_score: Mapped[Optional[float]] = mapped_column(Float, nullable=True)  # 来自 Spec 06
    detail_json: Mapped[Optional[Any]] = mapped_column(JSONB, nullable=True)
    calculated_at: Mapped[datetime] = mapped_column(nullable=False, server_default=func.now())  # 分区键

    # 索引
    __table_args__ = (
        Index("ix_qs_ds_scope", "datasource_id", "scope_type", "scope_name", calculated_at.desc()),
        Index("ix_qs_calc_at", "calculated_at"),
    )
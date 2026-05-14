"""Metrics Agent — SQLAlchemy 2.x ORM Models"""

import uuid
from datetime import datetime
from typing import Optional, Any

from sqlalchemy import (
    BigInteger, Boolean, CheckConstraint, Float, ForeignKey, Index, Integer, String, Text,
    UniqueConstraint, func, text as sa_text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base  # 复用项目已有 Base


class BiMetricDefinition(Base):
    __tablename__ = "bi_metric_definitions"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    metric_code: Mapped[str] = mapped_column(String(32), nullable=False)
    name: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    name_zh: Mapped[str] = mapped_column(String(256), nullable=False)
    metric_type: Mapped[str] = mapped_column(String(16), nullable=False)
    business_domain: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    formula: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    formula_template: Mapped[Optional[str]] = mapped_column(String(256), nullable=True)
    aggregation_type: Mapped[Optional[str]] = mapped_column(String(16), nullable=True)
    result_type: Mapped[Optional[str]] = mapped_column(String(16), nullable=True)
    unit: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    precision: Mapped[int] = mapped_column(Integer, nullable=False, default=2)
    datasource_id: Mapped[Optional[int]] = mapped_column(Integer, ForeignKey("bi_data_sources.id"), nullable=True)
    table_name: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    column_name: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    filters: Mapped[Optional[Any]] = mapped_column(JSONB, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    lineage_status: Mapped[str] = mapped_column(String(16), nullable=False, server_default="unknown")
    sensitivity_level: Mapped[str] = mapped_column(String(16), nullable=False, server_default="public")
    created_by: Mapped[int] = mapped_column(Integer, ForeignKey("auth_users.id"), nullable=False)
    reviewed_by: Mapped[Optional[int]] = mapped_column(Integer, ForeignKey("auth_users.id"), nullable=True)
    reviewed_at: Mapped[Optional[datetime]] = mapped_column(nullable=True)
    published_at: Mapped[Optional[datetime]] = mapped_column(nullable=True)
    created_at: Mapped[datetime] = mapped_column(nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(nullable=False, server_default=func.now(), onupdate=func.now())

    lineage_records: Mapped[list["BiMetricLineage"]] = relationship(back_populates="metric", cascade="all, delete-orphan")
    versions: Mapped[list["BiMetricVersion"]] = relationship(back_populates="metric", cascade="save-update, merge")
    anomalies: Mapped[list["BiMetricAnomaly"]] = relationship(back_populates="metric", cascade="all, delete-orphan")
    consistency_checks: Mapped[list["BiMetricConsistencyCheck"]] = relationship(back_populates="metric", cascade="all, delete-orphan")
    aliases: Mapped[list["BiMetricAlias"]] = relationship(back_populates="metric", cascade="all, delete-orphan")
    bindings: Mapped[list["BiMetricBinding"]] = relationship(back_populates="metric", cascade="all, delete-orphan")
    dependencies: Mapped[list["BiMetricDependency"]] = relationship(
        back_populates="metric",
        cascade="all, delete-orphan",
        foreign_keys="BiMetricDependency.metric_id",
    )
    dependents: Mapped[list["BiMetricDependency"]] = relationship(
        back_populates="depends_on_metric",
        cascade="all, delete-orphan",
        foreign_keys="BiMetricDependency.depends_on_metric_id",
    )

    __table_args__ = (
        UniqueConstraint("tenant_id", "metric_code", name="uq_bmd_tenant_metric_code"),
        UniqueConstraint("tenant_id", "name", name="uq_bmd_tenant_name"),
        Index("ix_bmd_tenant", "tenant_id", "is_active"),
        Index("ix_bmd_metric_code", "tenant_id", "metric_code"),
        Index("ix_bmd_datasource", "datasource_id"),
        Index("ix_bmd_domain", "tenant_id", "business_domain"),
        Index("ix_bmd_sensitivity", "tenant_id", "sensitivity_level"),
    )


class BiMetricAlias(Base):
    __tablename__ = "bi_metric_aliases"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    metric_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("bi_metric_definitions.id", ondelete="CASCADE"),
        nullable=False,
    )
    alias: Mapped[str] = mapped_column(String(128), nullable=False)
    locale: Mapped[Optional[str]] = mapped_column(String(16), nullable=True)
    priority: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")
    created_at: Mapped[datetime] = mapped_column(nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(nullable=False, server_default=func.now(), onupdate=func.now())

    metric: Mapped["BiMetricDefinition"] = relationship(back_populates="aliases")

    __table_args__ = (
        UniqueConstraint("tenant_id", "metric_id", "alias", name="uq_bma_tenant_metric_alias"),
        Index("ix_bma_tenant_alias_active", "tenant_id", "alias", "is_active"),
        Index("ix_bma_metric_active", "metric_id", "is_active"),
    )


class BiMetricBinding(Base):
    __tablename__ = "bi_metric_bindings"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    metric_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("bi_metric_definitions.id", ondelete="CASCADE"),
        nullable=False,
    )
    source_type: Mapped[str] = mapped_column(String(32), nullable=False)
    datasource_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    tableau_connection_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    tableau_asset_id: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    tableau_datasource_luid: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    field_mappings: Mapped[Optional[Any]] = mapped_column(JSONB, nullable=True)
    required_base_metrics: Mapped[Optional[Any]] = mapped_column(JSONB, nullable=True)
    formula_expression: Mapped[Optional[Any]] = mapped_column(JSONB, nullable=True)
    queryable_fields_snapshot: Mapped[Optional[Any]] = mapped_column(JSONB, nullable=True)
    is_primary: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")
    created_at: Mapped[datetime] = mapped_column(nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(nullable=False, server_default=func.now(), onupdate=func.now())

    metric: Mapped["BiMetricDefinition"] = relationship(back_populates="bindings")

    __table_args__ = (
        Index("ix_bmb_tenant_metric_active", "tenant_id", "metric_id", "is_active"),
        Index("ix_bmb_tableau_source", "tableau_connection_id", "tableau_datasource_luid"),
        Index("ix_bmb_datasource", "datasource_id"),
        Index(
            "uq_bmb_primary_tableau_binding",
            "tenant_id",
            "metric_id",
            unique=True,
            postgresql_where=sa_text(
                "is_active = true AND is_primary = true AND source_type = 'tableau_published_datasource'"
            ),
        ),
    )


class BiMetricDependency(Base):
    __tablename__ = "bi_metric_dependencies"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    metric_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("bi_metric_definitions.id", ondelete="CASCADE"),
        nullable=False,
    )
    depends_on_metric_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("bi_metric_definitions.id", ondelete="RESTRICT"),
        nullable=False,
    )
    dependency_role: Mapped[str] = mapped_column(String(32), nullable=False)
    expression_order: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    weight: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    created_at: Mapped[datetime] = mapped_column(nullable=False, server_default=func.now())

    metric: Mapped["BiMetricDefinition"] = relationship(
        back_populates="dependencies",
        foreign_keys=[metric_id],
    )
    depends_on_metric: Mapped["BiMetricDefinition"] = relationship(
        back_populates="dependents",
        foreign_keys=[depends_on_metric_id],
    )

    __table_args__ = (
        CheckConstraint("metric_id <> depends_on_metric_id", name="ck_bmdp_no_self_dependency"),
        UniqueConstraint(
            "tenant_id",
            "metric_id",
            "depends_on_metric_id",
            "dependency_role",
            name="uq_bmdp_metric_dep_role",
        ),
        Index("ix_bmdp_metric", "tenant_id", "metric_id"),
        Index("ix_bmdp_depends_on", "tenant_id", "depends_on_metric_id"),
        Index("ix_bmdp_role", "tenant_id", "dependency_role"),
    )


class BiMetricLineage(Base):
    __tablename__ = "bi_metric_lineage"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    metric_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("bi_metric_definitions.id"), nullable=False)
    datasource_id: Mapped[int] = mapped_column(Integer, nullable=False)
    table_name: Mapped[str] = mapped_column(String(128), nullable=False)
    column_name: Mapped[str] = mapped_column(String(128), nullable=False)
    column_type: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    relationship_type: Mapped[str] = mapped_column(String(16), nullable=False)
    hop_number: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    transformation_logic: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(nullable=False, server_default=func.now())

    metric: Mapped["BiMetricDefinition"] = relationship(back_populates="lineage_records")

    __table_args__ = (
        Index("ix_bml_metric", "metric_id"),
        Index("ix_bml_tenant", "tenant_id", "metric_id"),
    )


class BiMetricVersion(Base):
    __tablename__ = "bi_metric_versions"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    metric_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("bi_metric_definitions.id"), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    change_type: Mapped[str] = mapped_column(String(16), nullable=False)
    changes: Mapped[Any] = mapped_column(JSONB, nullable=False)
    changed_by: Mapped[int] = mapped_column(Integer, nullable=False)
    change_reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(nullable=False, server_default=func.now())

    metric: Mapped["BiMetricDefinition"] = relationship(back_populates="versions")

    __table_args__ = (
        Index("ix_bmv_metric_version", "metric_id", "version"),
        Index("ix_bmv_tenant", "tenant_id"),
    )


class BiMetricAnomaly(Base):
    __tablename__ = "bi_metric_anomalies"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    metric_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("bi_metric_definitions.id"), nullable=False)
    datasource_id: Mapped[int] = mapped_column(Integer, nullable=False)
    detection_method: Mapped[str] = mapped_column(String(32), nullable=False)
    algorithm: Mapped[Optional[str]] = mapped_column(String(16), nullable=True, comment="zscore | quantile")
    direction: Mapped[Optional[str]] = mapped_column(String(8), nullable=True, comment="up | down")
    dimension_context_hash: Mapped[Optional[str]] = mapped_column(String(64), nullable=True, comment="SHA256 hash of dimension_context")
    magnitude_bucket: Mapped[Optional[str]] = mapped_column(String(16), nullable=True, comment="tiny | small | medium | large | extreme")
    metric_value: Mapped[float] = mapped_column(Float, nullable=False)
    expected_value: Mapped[float] = mapped_column(Float, nullable=False)
    deviation_score: Mapped[float] = mapped_column(Float, nullable=False)
    deviation_threshold: Mapped[float] = mapped_column(Float, nullable=False)
    dimension_context: Mapped[Optional[Any]] = mapped_column(JSONB, nullable=True)
    detected_at: Mapped[datetime] = mapped_column(nullable=False)
    last_seen_at: Mapped[Optional[datetime]] = mapped_column(nullable=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False, server_default="detected")
    resolved_by: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    resolved_at: Mapped[Optional[datetime]] = mapped_column(nullable=True)
    resolution_note: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    alert_sent_at: Mapped[Optional[datetime]] = mapped_column(nullable=True, comment="告警发送时间")
    created_at: Mapped[datetime] = mapped_column(nullable=False, server_default=func.now())

    metric: Mapped["BiMetricDefinition"] = relationship(back_populates="anomalies")

    __table_args__ = (
        Index("ix_bma_metric", "metric_id", "detected_at"),
        Index("ix_bma_status", "tenant_id", "status", "detected_at"),
        Index("ix_bma_datasource", "datasource_id", "detected_at"),
        Index("ix_bma_dedup", "metric_id", "algorithm", "direction", "dimension_context_hash", "detected_at"),
    )


class BiMetricConsistencyCheck(Base):
    __tablename__ = "bi_metric_consistency_checks"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    metric_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("bi_metric_definitions.id"), nullable=False)
    metric_name: Mapped[str] = mapped_column(String(128), nullable=False)
    datasource_id_a: Mapped[int] = mapped_column(Integer, nullable=False)
    datasource_id_b: Mapped[int] = mapped_column(Integer, nullable=False)
    value_a: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    value_b: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    difference: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    difference_pct: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    tolerance_pct: Mapped[float] = mapped_column(Float, nullable=False, server_default="5.0")
    check_status: Mapped[str] = mapped_column(String(16), nullable=False)
    checked_at: Mapped[datetime] = mapped_column(nullable=False)
    created_at: Mapped[datetime] = mapped_column(nullable=False, server_default=func.now())

    metric: Mapped["BiMetricDefinition"] = relationship(back_populates="consistency_checks")

    __table_args__ = (
        Index("ix_bmcc_metric", "metric_id", "checked_at"),
        Index("ix_bmcc_tenant_status", "tenant_id", "check_status", "checked_at"),
    )

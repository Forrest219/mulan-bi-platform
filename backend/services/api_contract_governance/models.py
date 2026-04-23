"""API Contract Governance - 数据模型

表前缀: bi_api_contract_
遵循项目规范：
- snake_case 字段名
- TIMESTAMP WITHOUT TIME ZONE
- JSONB 用 app.core.database.JSONB
- to_dict() 时间使用 "%Y-%m-%d %H:%M:%S" 格式
"""
from typing import Any, Dict, Optional
from uuid import uuid4

from sqlalchemy import (
    Boolean, Column, DateTime, Enum, ForeignKey, Index, Integer,
    String, Text, UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID as PG_UUID

from app.core.database import Base, JSONB, sa_func, sa_text


class ApiContractAsset(Base):
    """监控的 API 接口资产"""
    __tablename__ = "bi_api_contract_assets"

    id = Column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    name = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)

    # === 资产归属 ===
    upstream_system = Column(String(128), nullable=True, comment="上游系统名称")
    owner_id = Column(Integer, nullable=True, comment="责任人用户ID")
    owner_name = Column(String(128), nullable=True, comment="责任人姓名")

    # === 调用信息 ===
    call_frequency = Column(String(64), nullable=True, comment="调用频率，如 '100/min', '10000/day'")
    consumers = Column(JSONB, nullable=True, server_default=sa_text("'[]'"), comment="消费方列表")
    business_usage = Column(Text, nullable=True, comment="业务用途说明")
    current_version = Column(String(32), nullable=True, comment="当前接口版本")

    # === API 端点配置 ===
    endpoint_url = Column(Text, nullable=False)
    method = Column(String(10), nullable=False, server_default=sa_text("'GET'"))
    path_pattern = Column(Text, nullable=True, comment="GraphQL query 或 REST path")

    # === 请求/响应样例 ===
    request_sample = Column(JSONB, nullable=True, comment="请求样例")
    response_sample = Column(JSONB, nullable=True, comment="响应样例")
    standard_schema = Column(JSONB, nullable=True, comment="标准 schema 定义")

    # === 请求配置 ===
    request_headers = Column(JSONB, nullable=True, server_default=sa_text("'{}'"))
    request_body_template = Column(JSONB, nullable=True)
    query_params = Column(JSONB, nullable=True, server_default=sa_text("'{}'"))

    # === 认证配置 ===
    auth_method = Column(
        Enum("none", "bearer", "api_key", "basic", "jwt", name="enum_auth_method"),
        nullable=False,
        server_default=sa_text("'none'"),
    )
    auth_config = Column(JSONB, nullable=True, server_default=sa_text("'{}'"))

    # === 采样配置 ===
    sample_cron = Column(String(100), nullable=True)
    sample_timeout_seconds = Column(Integer, nullable=False, server_default=sa_text("30"))
    sample_retry_count = Column(Integer, nullable=False, server_default=sa_text("3"))

    # === 字段过滤配置 ===
    field_whitelist = Column(JSONB, nullable=True, server_default=sa_text("'[]'"))
    field_blacklist = Column(JSONB, nullable=True, server_default=sa_text("'[]'"))

    # === 告警配置 ===
    alert_config = Column(JSONB, nullable=True, server_default=sa_text("'{}'"))
    auto_alert_on_breaking = Column(Boolean, nullable=False, server_default=sa_text("true"))

    # === 基线状态 ===
    baseline_snapshot_id = Column(PG_UUID(as_uuid=True), nullable=True, comment="基线快照ID，首次采样后设置")

    # === 状态 ===
    is_active = Column(Boolean, nullable=False, server_default=sa_text("true"))
    last_sampled_at = Column(DateTime, nullable=True)
    last_error = Column(Text, nullable=True)

    # === 审计字段 ===
    created_by = Column(Integer, nullable=False)
    created_at = Column(DateTime, nullable=False, server_default=sa_func.now())
    updated_at = Column(DateTime, nullable=False, server_default=sa_func.now(), onupdate=sa_func.now())

    __table_args__ = (
        UniqueConstraint("endpoint_url", "method", name="uq_api_contract_asset_endpoint_method"),
        Index("ix_api_contract_asset_is_active", "is_active"),
        Index("ix_api_contract_asset_endpoint", "endpoint_url"),
        Index("ix_api_contract_asset_owner", "owner_id"),
    )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": str(self.id),
            "name": self.name,
            "description": self.description,
            "upstream_system": self.upstream_system,
            "owner_id": self.owner_id,
            "owner_name": self.owner_name,
            "call_frequency": self.call_frequency,
            "consumers": self.consumers,
            "business_usage": self.business_usage,
            "current_version": self.current_version,
            "endpoint_url": self.endpoint_url,
            "method": self.method,
            "path_pattern": self.path_pattern,
            "request_sample": self.request_sample,
            "response_sample": self.response_sample,
            "standard_schema": self.standard_schema,
            "request_headers": self.request_headers,
            "request_body_template": self.request_body_template,
            "query_params": self.query_params,
            "auth_method": self.auth_method,
            "auth_config": self.auth_config,
            "sample_cron": self.sample_cron,
            "sample_timeout_seconds": self.sample_timeout_seconds,
            "sample_retry_count": self.sample_retry_count,
            "field_whitelist": self.field_whitelist,
            "field_blacklist": self.field_blacklist,
            "alert_config": self.alert_config,
            "auto_alert_on_breaking": self.auto_alert_on_breaking,
            "baseline_snapshot_id": str(self.baseline_snapshot_id) if self.baseline_snapshot_id else None,
            "is_active": self.is_active,
            "last_sampled_at": self.last_sampled_at.strftime("%Y-%m-%d %H:%M:%S") if self.last_sampled_at else None,
            "last_error": self.last_error,
            "created_by": self.created_by,
            "created_at": self.created_at.strftime("%Y-%m-%d %H:%M:%S") if self.created_at else None,
            "updated_at": self.updated_at.strftime("%Y-%m-%d %H:%M:%S") if self.updated_at else None,
        }


class ApiFieldSnapshot(Base):
    """字段快照（append-only 时序表）"""
    __tablename__ = "bi_api_contract_snapshots"

    id = Column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    asset_id = Column(
        PG_UUID(as_uuid=True),
        ForeignKey("bi_api_contract_assets.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # 快照元数据
    snapshot_time = Column(DateTime, nullable=False, server_default=sa_func.now())
    sampling_duration_ms = Column(Integer, nullable=True)
    response_status_code = Column(Integer, nullable=True)
    response_size_bytes = Column(Integer, nullable=True)

    # 字段结构（扁平化存储）
    # {"data[0].user.name": {"type": "string", "value_samples": [...], "enum_values": null}}
    fields_schema = Column(JSONB, nullable=False, server_default=sa_text("'{}'"))
    raw_response_sample = Column(JSONB, nullable=True)

    # 审计字段
    created_at = Column(DateTime, nullable=False, server_default=sa_func.now())

    __table_args__ = (
        Index("ix_api_contract_snap_asset_time", "asset_id", "snapshot_time"),
        Index("ix_api_contract_snap_snapshot_time", "snapshot_time"),
    )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": str(self.id),
            "asset_id": str(self.asset_id),
            "snapshot_time": self.snapshot_time.strftime("%Y-%m-%d %H:%M:%S") if self.snapshot_time else None,
            "sampling_duration_ms": self.sampling_duration_ms,
            "response_status_code": self.response_status_code,
            "response_size_bytes": self.response_size_bytes,
            "fields_schema": self.fields_schema,
            "raw_response_sample": self.raw_response_sample,
            "created_at": self.created_at.strftime("%Y-%m-%d %H:%M:%S") if self.created_at else None,
        }


class ApiFieldChangeEvent(Base):
    """变更事件记录"""
    __tablename__ = "bi_api_contract_change_events"

    id = Column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    asset_id = Column(
        PG_UUID(as_uuid=True),
        ForeignKey("bi_api_contract_assets.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # 变更时间
    detected_at = Column(DateTime, nullable=False, server_default=sa_func.now())

    # 关联的快照
    from_snapshot_id = Column(PG_UUID(as_uuid=True), nullable=False)
    to_snapshot_id = Column(PG_UUID(as_uuid=True), nullable=False)

    # 变更摘要
    change_type = Column(String(50), nullable=False)
    field_path = Column(Text, nullable=False)

    # 变更详情
    change_detail = Column(JSONB, nullable=False, server_default=sa_text("'{}'"))

    # 严重级别: p0_breaking / p1_major / p2_minor / info
    # 按用户 spec:
    # P0: 字段删除、类型变化、关键业务字段路径变化、枚举含义变化、主键/业务唯一键变化
    # P1: required->optional, optional->required, 数组结构变对象, 时间格式变化, 金额精度变化
    # P2: 新增非必填字段、字段顺序变化、描述信息变化
    severity = Column(
        Enum("p0_breaking", "p1_major", "p2_minor", "info", name="enum_change_severity"),
        nullable=False,
        server_default=sa_text("'info'"),
    )

    # 影响消费方
    affected_consumers = Column(JSONB, nullable=True, server_default=sa_text("'[]'"), comment="受影响的消费方列表")

    # 处理状态
    is_resolved = Column(Boolean, nullable=False, server_default=sa_text("false"))
    resolution = Column(
        Enum("accepted", "rejected", "ignored", name="enum_change_resolution"),
        nullable=True,
        comment="接受/拒绝/忽略",
    )
    resolved_at = Column(DateTime, nullable=True)
    resolved_by = Column(String(255), nullable=True)
    resolution_note = Column(Text, nullable=True)

    # 审计字段
    created_at = Column(DateTime, nullable=False, server_default=sa_func.now())

    __table_args__ = (
        Index("ix_api_contract_change_asset_detected", "asset_id", "detected_at"),
        Index("ix_api_contract_change_severity", "severity"),
        Index("ix_api_contract_change_is_resolved", "is_resolved"),
    )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": str(self.id),
            "asset_id": str(self.asset_id),
            "detected_at": self.detected_at.strftime("%Y-%m-%d %H:%M:%S") if self.detected_at else None,
            "from_snapshot_id": str(self.from_snapshot_id),
            "to_snapshot_id": str(self.to_snapshot_id),
            "change_type": self.change_type,
            "field_path": self.field_path,
            "change_detail": self.change_detail,
            "severity": self.severity,
            "affected_consumers": self.affected_consumers,
            "is_resolved": self.is_resolved,
            "resolution": self.resolution,
            "resolved_at": self.resolved_at.strftime("%Y-%m-%d %H:%M:%S") if self.resolved_at else None,
            "resolved_by": self.resolved_by,
            "resolution_note": self.resolution_note,
            "created_at": self.created_at.strftime("%Y-%m-%d %H:%M:%S") if self.created_at else None,
        }


class ApiFieldLineage(Base):
    """字段血缘关系"""
    __tablename__ = "bi_api_contract_field_lineages"

    id = Column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    asset_id = Column(
        PG_UUID(as_uuid=True),
        ForeignKey("bi_api_contract_assets.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # 字段路径
    field_path = Column(Text, nullable=False)

    # 血缘信息
    source_system = Column(String(255), nullable=True)
    source_field = Column(Text, nullable=True)
    transformation_rule = Column(Text, nullable=True)

    # 业务元数据
    business_description = Column(Text, nullable=True)
    data_steward = Column(String(255), nullable=True)

    # 审计字段
    created_by = Column(Integer, nullable=False)
    created_at = Column(DateTime, nullable=False, server_default=sa_func.now())
    updated_at = Column(DateTime, nullable=False, server_default=sa_func.now(), onupdate=sa_func.now())

    __table_args__ = (
        Index("ix_api_contract_lineage_asset_field", "asset_id", "field_path"),
        UniqueConstraint("asset_id", "field_path", name="uq_api_contract_lineage_asset_field"),
    )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": str(self.id),
            "asset_id": str(self.asset_id),
            "field_path": self.field_path,
            "source_system": self.source_system,
            "source_field": self.source_field,
            "transformation_rule": self.transformation_rule,
            "business_description": self.business_description,
            "data_steward": self.data_steward,
            "created_by": self.created_by,
            "created_at": self.created_at.strftime("%Y-%m-%d %H:%M:%S") if self.created_at else None,
            "updated_at": self.updated_at.strftime("%Y-%m-%d %H:%M:%S") if self.updated_at else None,
        }

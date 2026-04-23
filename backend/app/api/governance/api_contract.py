"""API Contract Governance - Pydantic Schemas

请求/响应模型定义
"""
from datetime import datetime
from typing import Any, Optional
from uuid import UUID

from pydantic import BaseModel, Field


# ==================== Asset Schemas ====================


class CreateAssetRequest(BaseModel):
    """创建 API 契约资产请求"""
    name: str = Field(..., max_length=255)
    description: Optional[str] = None

    # 资产归属
    upstream_system: Optional[str] = Field(None, max_length=128)
    owner_id: Optional[int] = None
    owner_name: Optional[str] = Field(None, max_length=128)

    # 调用信息
    call_frequency: Optional[str] = Field(None, max_length=64)
    consumers: list[str] = Field(default_factory=list)
    business_usage: Optional[str] = None
    current_version: Optional[str] = Field(None, max_length=32)

    # API 端点
    endpoint_url: str
    method: str = Field(default="GET", max_length=10)
    path_pattern: Optional[str] = None

    # 请求/响应样例
    request_sample: Optional[dict[str, Any]] = None
    response_sample: Optional[dict[str, Any]] = None
    standard_schema: Optional[dict[str, Any]] = None

    # 请求配置
    request_headers: dict[str, str] = Field(default_factory=dict)
    request_body_template: Optional[dict[str, Any]] = None
    query_params: dict[str, Any] = Field(default_factory=dict)

    # 认证
    auth_method: str = Field(default="none")
    auth_config: dict[str, Any] = Field(default_factory=dict)

    # 采样配置
    sample_cron: Optional[str] = Field(None, max_length=100)
    sample_timeout_seconds: int = Field(default=30, ge=1, le=300)
    sample_retry_count: int = Field(default=3, ge=0, le=10)

    # 字段过滤
    field_whitelist: list[str] = Field(default_factory=list)
    field_blacklist: list[str] = Field(default_factory=list)

    # 告警配置
    alert_config: dict[str, Any] = Field(default_factory=dict)
    auto_alert_on_breaking: bool = True


class UpdateAssetRequest(BaseModel):
    """更新 API 契约资产请求"""
    name: Optional[str] = Field(None, max_length=255)
    description: Optional[str] = None

    upstream_system: Optional[str] = Field(None, max_length=128)
    owner_id: Optional[int] = None
    owner_name: Optional[str] = Field(None, max_length=128)

    call_frequency: Optional[str] = Field(None, max_length=64)
    consumers: Optional[list[str]] = None
    business_usage: Optional[str] = None
    current_version: Optional[str] = Field(None, max_length=32)

    endpoint_url: Optional[str] = None
    method: Optional[str] = Field(None, max_length=10)
    path_pattern: Optional[str] = None

    request_sample: Optional[dict[str, Any]] = None
    response_sample: Optional[dict[str, Any]] = None
    standard_schema: Optional[dict[str, Any]] = None

    request_headers: Optional[dict[str, str]] = None
    request_body_template: Optional[dict[str, Any]] = None
    query_params: Optional[dict[str, Any]] = None

    auth_method: Optional[str] = None
    auth_config: Optional[dict[str, Any]] = None

    sample_cron: Optional[str] = Field(None, max_length=100)
    sample_timeout_seconds: Optional[int] = Field(None, ge=1, le=300)
    sample_retry_count: Optional[int] = Field(None, ge=0, le=10)

    field_whitelist: Optional[list[str]] = None
    field_blacklist: Optional[list[str]] = None

    alert_config: Optional[dict[str, Any]] = None
    auto_alert_on_breaking: Optional[bool] = None

    is_active: Optional[bool] = None


class AssetResponse(BaseModel):
    """API 契约资产响应"""
    id: UUID
    name: str
    description: Optional[str]

    upstream_system: Optional[str]
    owner_id: Optional[int]
    owner_name: Optional[str]

    call_frequency: Optional[str]
    consumers: Optional[list[str]]
    business_usage: Optional[str]
    current_version: Optional[str]

    endpoint_url: str
    method: str
    path_pattern: Optional[str]

    request_sample: Optional[dict]
    response_sample: Optional[dict]
    standard_schema: Optional[dict]

    request_headers: Optional[dict]
    request_body_template: Optional[dict]
    query_params: Optional[dict]

    auth_method: str
    auth_config: Optional[dict]

    sample_cron: Optional[str]
    sample_timeout_seconds: int
    sample_retry_count: int

    field_whitelist: list[str]
    field_blacklist: list[str]

    alert_config: Optional[dict]
    auto_alert_on_breaking: bool

    baseline_snapshot_id: Optional[str]
    is_active: bool
    last_sampled_at: Optional[str]
    last_error: Optional[str]

    created_by: int
    created_at: str
    updated_at: str

    class Config:
        from_attributes = True


class AssetListResponse(BaseModel):
    """资产列表响应"""
    items: list[AssetResponse]
    total: int
    page: int
    page_size: int
    pages: int


# ==================== Snapshot Schemas ====================


class SnapshotResponse(BaseModel):
    """字段快照响应"""
    id: UUID
    asset_id: UUID
    snapshot_time: str
    sampling_duration_ms: Optional[int]
    response_status_code: Optional[int]
    response_size_bytes: Optional[int]
    fields_schema: dict
    created_at: str

    class Config:
        from_attributes = True


class SnapshotListResponse(BaseModel):
    """快照列表响应"""
    items: list[SnapshotResponse]
    total: int


# ==================== Change Event Schemas ====================


class ChangeEventResponse(BaseModel):
    """变更事件响应"""
    id: UUID
    asset_id: UUID
    detected_at: str
    from_snapshot_id: UUID
    to_snapshot_id: UUID
    change_type: str
    field_path: str
    change_detail: dict
    severity: str
    affected_consumers: Optional[list[str]]
    is_resolved: bool
    resolution: Optional[str]
    resolved_at: Optional[str]
    resolved_by: Optional[str]
    resolution_note: Optional[str]
    created_at: str

    class Config:
        from_attributes = True


class ChangeEventListResponse(BaseModel):
    """变更事件列表响应"""
    items: list[ChangeEventResponse]
    total: int


class ResolveChangeEventRequest(BaseModel):
    """标记变更事件已处理请求"""
    resolution: str = Field(..., description="accepted/rejected/ignored")
    resolution_note: Optional[str] = None


# ==================== Field Diff Schemas ====================


class FieldDiffItem(BaseModel):
    """字段差异项"""
    change_type: str
    field_path: str
    from_value: Any
    to_value: Any
    severity: str
    description: str


class FieldDiffResponse(BaseModel):
    """字段差异响应"""
    asset_id: UUID
    from_snapshot_id: UUID
    to_snapshot_id: UUID
    changes: list[FieldDiffItem]
    breaking_changes_count: int
    non_breaking_changes_count: int
    compatibility_score: float


# ==================== Field History Schemas ====================


class FieldHistoryItem(BaseModel):
    """字段历史项"""
    field_path: str
    field_type: str
    value_samples: list[Any]
    enum_values: Optional[list[str]]
    snapshot_time: str


class FieldHistoryResponse(BaseModel):
    """字段历史响应"""
    asset_id: UUID
    field_path: str
    history: list[FieldHistoryItem]


# ==================== Sampling Schemas ====================


class SamplingResponse(BaseModel):
    """采样响应"""
    success: bool
    snapshot_id: Optional[UUID] = None
    fields_count: int = 0
    message: Optional[str] = None


class PromoteBaselineRequest(BaseModel):
    """提升基线请求"""
    snapshot_id: UUID


# ==================== Field Lineage Schemas ====================


class FieldLineageCreate(BaseModel):
    """创建字段血缘请求"""
    field_path: str
    source_system: Optional[str] = None
    source_field: Optional[str] = None
    transformation_rule: Optional[str] = None
    business_description: Optional[str] = None
    data_steward: Optional[str] = None


class FieldLineageResponse(BaseModel):
    """字段血缘响应"""
    id: UUID
    asset_id: UUID
    field_path: str
    source_system: Optional[str]
    source_field: Optional[str]
    transformation_rule: Optional[str]
    business_description: Optional[str]
    data_steward: Optional[str]
    created_by: int
    created_at: str

    class Config:
        from_attributes = True


class FieldLineageListResponse(BaseModel):
    """字段血缘列表响应"""
    items: list[FieldLineageResponse]
    total: int

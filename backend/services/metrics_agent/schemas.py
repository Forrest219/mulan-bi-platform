"""Metrics Agent — Pydantic Schemas"""

import uuid
from datetime import datetime
from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field, field_serializer, field_validator

# P2-1：哨兵时间常量（与 registry.py 中保持一致）
_PENDING_SENTINEL_DT = datetime(1970, 1, 1, 0, 0, 0)


# =============================================================================
# Enums
# =============================================================================

class MetricType(str, Enum):
    atomic = "atomic"
    derived = "derived"
    ratio = "ratio"


class AggregationType(str, Enum):
    SUM = "SUM"
    AVG = "AVG"
    COUNT = "COUNT"
    COUNT_DISTINCT = "COUNT_DISTINCT"
    MAX = "MAX"
    MIN = "MIN"
    none = "none"


class ResultType(str, Enum):
    float_ = "float"
    integer = "integer"
    percentage = "percentage"
    currency = "currency"


class SensitivityLevel(str, Enum):
    public = "public"
    internal = "internal"
    confidential = "confidential"
    restricted = "restricted"


class LineageStatus(str, Enum):
    resolved = "resolved"
    unknown = "unknown"
    manual = "manual"


class MetricBindingInput(BaseModel):
    """Metric execution binding input."""

    id: Optional[uuid.UUID] = None
    source_type: str = Field(default="tableau_published_datasource")
    datasource_id: Optional[int] = None
    tableau_connection_id: Optional[int] = None
    tableau_asset_id: Optional[int] = None
    tableau_datasource_luid: Optional[str] = Field(None, max_length=128)
    field_mappings: Optional[Any] = None
    required_base_metrics: list[str] = Field(default_factory=list)
    formula_expression: Optional[Any] = None
    is_primary: bool = False
    is_active: bool = True


class MetricBindingOutput(BaseModel):
    """Metric execution binding response."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    source_type: str
    datasource_id: Optional[int] = None
    tableau_connection_id: Optional[int] = None
    tableau_asset_id: Optional[int] = None
    tableau_datasource_luid: Optional[str] = None
    field_mappings: Optional[Any] = None
    required_base_metrics: list[str] = Field(default_factory=list)
    formula_expression: Optional[Any] = None
    is_primary: bool
    is_active: bool
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


# =============================================================================
# 创建 / 更新入参
# =============================================================================

class MetricCreate(BaseModel):
    """POST /api/metrics 请求体"""

    name: Optional[str] = Field(
        None,
        pattern=r"^[a-z][a-z0-9_]{1,127}$",
        description="可选技术别名，小写字母开头，仅含小写字母/数字/下划线，2-128 字符",
    )
    name_zh: str = Field(..., min_length=1, max_length=256, description="指标中文名")
    metric_type: MetricType = Field(..., description="指标类型：atomic / derived / ratio")
    business_domain: Optional[str] = Field(None, max_length=64, description="业务域")
    description: Optional[str] = Field(None, description="指标描述")
    formula: Optional[str] = Field(None, max_length=512, description="计算公式（derived/ratio 必填）")
    formula_template: Optional[str] = Field(None, max_length=256, description="公式模板")
    aggregation_type: Optional[AggregationType] = Field(None, description="聚合方式")

    @field_validator("formula")
    @classmethod
    def validate_formula_safety(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return v
        from services.metrics_agent.formula_validator import validate_formula
        return validate_formula(v)
    result_type: Optional[ResultType] = Field(None, description="结果数值类型")
    unit: Optional[str] = Field(None, max_length=32, description="单位，如 元 / 次 / %")
    precision: int = Field(
        default=2,
        ge=0,
        le=10,
        description="小数精度，与Python内置precision无关",
    )
    datasource_id: Optional[int] = Field(None, description="兼容数据库数据源 ID")
    table_name: Optional[str] = Field(None, max_length=128, description="来源表名")
    column_name: Optional[str] = Field(None, max_length=128, description="来源列名")
    filters: Optional[Any] = Field(None, description="过滤条件，JSONB 格式")
    sensitivity_level: SensitivityLevel = Field(
        default=SensitivityLevel.public, description="数据敏感级别"
    )
    tableau_connection_id: Optional[int] = Field(None, description="Tableau connection id")
    tableau_asset_id: Optional[int] = Field(None, description="本地 Tableau asset id")
    tableau_datasource_luid: Optional[str] = Field(None, max_length=128, description="Tableau datasource LUID")
    field_mappings: Optional[Any] = Field(None, description="Tableau fieldCaption 映射")
    required_base_metrics: list[str] = Field(default_factory=list, description="结构化公式依赖基础指标名")
    bindings: Optional[list[MetricBindingInput]] = Field(None, description="Tableau execution bindings")
    dependency_metric_ids: list[uuid.UUID] = Field(default_factory=list, description="derived 基础指标 ID")
    numerator_metric_id: Optional[uuid.UUID] = Field(None, description="ratio 分子指标 ID")
    denominator_metric_id: Optional[uuid.UUID] = Field(None, description="ratio 分母指标 ID")
    formula_expression: Optional[Any] = Field(None, description="结构化公式表达式")


class MetricUpdate(BaseModel):
    """PUT /api/metrics/{metric_id} 请求体，所有字段可选"""

    name: Optional[str] = Field(
        None,
        pattern=r"^[a-z][a-z0-9_]{1,127}$",
        description="指标英文名",
    )
    name_zh: Optional[str] = Field(None, max_length=256)
    metric_type: Optional[MetricType] = None
    business_domain: Optional[str] = Field(None, max_length=64)
    description: Optional[str] = None
    formula: Optional[str] = Field(None, max_length=512)
    formula_template: Optional[str] = Field(None, max_length=256)
    aggregation_type: Optional[AggregationType] = None

    @field_validator("formula")
    @classmethod
    def validate_formula_safety(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return v
        from services.metrics_agent.formula_validator import validate_formula
        return validate_formula(v)
    result_type: Optional[ResultType] = None
    unit: Optional[str] = Field(None, max_length=32)
    precision: Optional[int] = Field(
        None,
        ge=0,
        le=10,
        description="小数精度，与Python内置precision无关",
    )
    datasource_id: Optional[int] = None
    table_name: Optional[str] = Field(None, max_length=128)
    column_name: Optional[str] = Field(None, max_length=128)
    filters: Optional[Any] = None
    sensitivity_level: Optional[SensitivityLevel] = None
    tableau_connection_id: Optional[int] = None
    tableau_asset_id: Optional[int] = None
    tableau_datasource_luid: Optional[str] = Field(None, max_length=128)
    field_mappings: Optional[Any] = None
    required_base_metrics: Optional[list[str]] = None
    bindings: Optional[list[MetricBindingInput]] = None
    dependency_metric_ids: Optional[list[uuid.UUID]] = None
    numerator_metric_id: Optional[uuid.UUID] = None
    denominator_metric_id: Optional[uuid.UUID] = None
    formula_expression: Optional[Any] = None


# =============================================================================
# 响应出参
# =============================================================================

class MetricBase(BaseModel):
    """列表项精简字段"""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    tenant_id: uuid.UUID
    metric_code: str
    name: Optional[str]
    name_zh: str
    metric_type: str
    business_domain: Optional[str]
    aggregation_type: Optional[str]
    result_type: Optional[str]
    datasource_id: Optional[int]
    table_name: Optional[str] = None
    column_name: Optional[str] = None
    tableau_connection_id: Optional[int] = None
    tableau_asset_id: Optional[int] = None
    tableau_datasource_luid: Optional[str] = None
    field_mappings: Optional[Any] = None
    required_base_metrics: list[str] = Field(default_factory=list)
    formula_expression: Optional[Any] = None
    bindings: list[MetricBindingOutput] = Field(default_factory=list)
    primary_binding: Optional[MetricBindingOutput] = None
    binding_errors: list[dict[str, Any]] = Field(default_factory=list)
    is_active: bool
    sensitivity_level: str
    lineage_status: str
    created_at: datetime
    updated_at: datetime


class MetricDetail(BaseModel):
    """详情，完整字段"""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    tenant_id: uuid.UUID
    metric_code: str
    name: Optional[str]
    name_zh: str
    metric_type: str
    business_domain: Optional[str]
    description: Optional[str]
    formula: Optional[str]
    formula_template: Optional[str]
    aggregation_type: Optional[str]
    result_type: Optional[str]
    unit: Optional[str]
    precision: int
    datasource_id: Optional[int]
    table_name: Optional[str]
    column_name: Optional[str]
    filters: Optional[Any]
    tableau_connection_id: Optional[int] = None
    tableau_asset_id: Optional[int] = None
    tableau_datasource_luid: Optional[str] = None
    field_mappings: Optional[Any] = None
    required_base_metrics: list[str] = Field(default_factory=list)
    formula_expression: Optional[Any] = None
    bindings: list[MetricBindingOutput] = Field(default_factory=list)
    primary_binding: Optional[MetricBindingOutput] = None
    dependencies: list[dict[str, Any]] = Field(default_factory=list)
    queryable: bool = False
    binding_errors: list[dict[str, Any]] = Field(default_factory=list)
    is_active: bool
    lineage_status: str
    sensitivity_level: str
    created_by: int
    reviewed_by: Optional[int]
    reviewed_at: Optional[datetime]
    published_at: Optional[datetime]
    created_at: datetime
    updated_at: datetime

    @field_serializer("reviewed_at")
    def serialize_reviewed_at(self, v: Optional[datetime]) -> Optional[str]:
        """P2-1：将 1970-01-01 哨兵值（pending_review 标记）序列化为 null。"""
        if v is None:
            return None
        # 兼容 aware datetime
        naive_v = v.replace(tzinfo=None) if getattr(v, "tzinfo", None) else v
        if naive_v == _PENDING_SENTINEL_DT:
            return None
        return v.isoformat()


class MetricCreatedResponse(BaseModel):
    """创建成功 201 响应"""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    metric_code: str
    name: Optional[str]
    name_zh: str
    metric_type: str
    datasource_id: Optional[int]
    created_at: datetime


# =============================================================================
# 审核流 Schema
# =============================================================================

class RejectRequest(BaseModel):
    """拒绝审核请求体"""

    reason: str = Field(..., min_length=1, max_length=512, description="拒绝原因")


class PublishResponse(BaseModel):
    """发布成功响应"""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    metric_code: str
    name: Optional[str]
    is_active: bool
    published_at: Optional[datetime]


# =============================================================================
# Lookup 接口 Schema
# =============================================================================

class MetricLookupItem(BaseModel):
    """lookup 单条结果——Data Agent 所需字段"""

    model_config = ConfigDict(from_attributes=True)

    metric_code: str
    name: Optional[str]
    name_zh: str
    aliases: list[str] = Field(default_factory=list)
    metric_type: str
    formula: Optional[str]
    formula_template: Optional[str] = None
    aggregation_type: Optional[str]
    result_type: Optional[str]
    unit: Optional[str] = None
    precision: int = 2
    datasource_id: Optional[int]
    tableau_connection_id: Optional[int] = None
    tableau_datasource_luid: Optional[str] = None
    table_name: Optional[str]
    column_name: Optional[str]
    field_mappings: Optional[Any] = None
    required_base_metrics: list[str] = Field(default_factory=list)
    formula_expression: Optional[Any] = None
    bindings: list[MetricBindingOutput] = Field(default_factory=list)
    primary_binding: Optional[MetricBindingOutput] = None
    filters: Optional[Any]
    sensitivity_level: str
    lineage_status: Optional[str] = None
    description: Optional[str] = None
    dependencies: list[dict[str, Any]] = Field(default_factory=list)
    queryable: bool = False
    binding_errors: list[dict[str, Any]] = Field(default_factory=list)


class MetricLookupResponse(BaseModel):
    """批量 lookup 响应"""

    metrics: list[MetricLookupItem]
    not_found: list[str] = Field(default_factory=list, description="未找到的指标名列表")
    binding_errors: list[dict[str, Any]] = Field(
        default_factory=list,
        description="指标命中但当前执行数据源绑定不可用的错误列表",
    )


# =============================================================================
# 分页通用 Schema
# =============================================================================

class PaginatedMetrics(BaseModel):
    """分页指标列表"""

    items: list[MetricBase]
    total: int = Field(..., ge=0)
    page: int = Field(..., ge=1)
    page_size: int = Field(..., ge=1)
    pages: int = Field(..., ge=0)

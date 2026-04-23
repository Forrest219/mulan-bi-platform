"""Metrics Agent — Pydantic Schemas"""

import uuid
from datetime import datetime
from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field, field_serializer

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


# =============================================================================
# 创建 / 更新入参
# =============================================================================

class MetricCreate(BaseModel):
    """POST /api/metrics 请求体"""

    name: str = Field(
        ...,
        pattern=r"^[a-z][a-z0-9_]{1,127}$",
        description="指标英文名，小写字母开头，仅含小写字母/数字/下划线，2-128 字符",
    )
    name_zh: Optional[str] = Field(None, max_length=256, description="指标中文名")
    metric_type: MetricType = Field(..., description="指标类型：atomic / derived / ratio")
    business_domain: Optional[str] = Field(None, max_length=64, description="业务域")
    description: Optional[str] = Field(None, description="指标描述")
    formula: Optional[str] = Field(None, description="计算公式（derived/ratio 必填）")
    formula_template: Optional[str] = Field(None, max_length=256, description="公式模板")
    aggregation_type: Optional[AggregationType] = Field(None, description="聚合方式")
    result_type: Optional[ResultType] = Field(None, description="结果数值类型")
    unit: Optional[str] = Field(None, max_length=32, description="单位，如 元 / 次 / %")
    precision: int = Field(
        default=2,
        ge=0,
        le=10,
        description="小数精度，与Python内置precision无关",
    )
    datasource_id: int = Field(..., description="关联数据源 ID")
    table_name: str = Field(..., max_length=128, description="来源表名")
    column_name: str = Field(..., max_length=128, description="来源列名")
    filters: Optional[Any] = Field(None, description="过滤条件，JSONB 格式")
    sensitivity_level: SensitivityLevel = Field(
        default=SensitivityLevel.public, description="数据敏感级别"
    )


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
    formula: Optional[str] = None
    formula_template: Optional[str] = Field(None, max_length=256)
    aggregation_type: Optional[AggregationType] = None
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


# =============================================================================
# 响应出参
# =============================================================================

class MetricBase(BaseModel):
    """列表项精简字段"""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    tenant_id: uuid.UUID
    name: str
    name_zh: Optional[str]
    metric_type: str
    business_domain: Optional[str]
    aggregation_type: Optional[str]
    result_type: Optional[str]
    datasource_id: int
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
    name: str
    name_zh: Optional[str]
    metric_type: str
    business_domain: Optional[str]
    description: Optional[str]
    formula: Optional[str]
    formula_template: Optional[str]
    aggregation_type: Optional[str]
    result_type: Optional[str]
    unit: Optional[str]
    precision: int
    datasource_id: int
    table_name: str
    column_name: str
    filters: Optional[Any]
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
    name: str
    metric_type: str
    datasource_id: int
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
    name: str
    is_active: bool
    published_at: Optional[datetime]


# =============================================================================
# Lookup 接口 Schema
# =============================================================================

class MetricLookupItem(BaseModel):
    """lookup 单条结果——Data Agent 所需字段"""

    model_config = ConfigDict(from_attributes=True)

    name: str
    name_zh: Optional[str]
    metric_type: str
    formula: Optional[str]
    aggregation_type: Optional[str]
    result_type: Optional[str]
    datasource_id: int
    table_name: str
    column_name: str
    filters: Optional[Any]
    sensitivity_level: str


class MetricLookupResponse(BaseModel):
    """批量 lookup 响应"""

    metrics: list[MetricLookupItem]
    not_found: list[str] = Field(default_factory=list, description="未找到的指标名列表")


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

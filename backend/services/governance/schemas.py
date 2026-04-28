"""质量规则 Pydantic Schema — Spec 15 §3.2"""

from pydantic import BaseModel, Field, field_validator
from typing import Optional, Any, Literal
from datetime import datetime


class RuleCreate(BaseModel):
    name: str = Field(..., max_length=256)
    description: Optional[str] = None
    datasource_id: int
    table_name: str = Field(..., max_length=128)
    field_name: Optional[str] = Field(None, max_length=128)
    rule_type: str  # 13种规则类型之一
    operator: str = "lte"
    threshold: dict = Field(default_factory=dict)
    severity: str = "MEDIUM"  # HIGH/MEDIUM/LOW
    execution_mode: str = "scheduled"  # realtime/scheduled/manual
    cron: Optional[str] = None
    custom_sql: Optional[str] = None
    tags_json: Optional[list[str]] = None

    @field_validator('rule_type')
    def validate_rule_type(cls, v):
        valid_types = ["null_rate", "not_null", "row_count", "duplicate_rate",
                       "unique_count", "referential", "cross_field", "value_range",
                       "freshness", "latency", "format_regex", "enum_check", "custom_sql"]
        if v not in valid_types:
            raise ValueError(f"不支持的规则类型: {v}")
        return v

    @field_validator('threshold')
    def validate_threshold(cls, v, info):
        # 获取 rule_type 字段值来校验 threshold 结构
        # 注意：Pydantic v2 用 model_fields 获取依赖字段
        # 简化处理：在 service 层做联合校验
        return v


class RuleUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    rule_type: Optional[str] = None
    operator: Optional[str] = None
    threshold: Optional[dict] = None
    severity: Optional[str] = None
    execution_mode: Optional[str] = None
    cron: Optional[str] = None
    custom_sql: Optional[str] = None
    tags_json: Optional[list[str]] = None
    enabled: Optional[bool] = None


class RuleResponse(BaseModel):
    id: int
    name: str
    datasource_id: int
    table_name: str
    field_name: Optional[str]
    rule_type: str
    operator: str
    threshold: dict
    severity: str
    execution_mode: str
    cron: Optional[str]
    custom_sql: Optional[str]
    enabled: bool
    tags_json: Optional[list[str]]
    created_by: int
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class QualityResultResponse(BaseModel):
    id: int
    rule_id: int
    datasource_id: int
    table_name: str
    field_name: Optional[str]
    executed_at: datetime
    passed: bool
    actual_value: Optional[float]
    expected_value: Optional[str]
    severity: str
    execution_time_ms: Optional[int]
    detail_json: Optional[dict]
    error_message: Optional[str]

    class Config:
        from_attributes = True


class QualityScoreResponse(BaseModel):
    id: int
    datasource_id: int
    scope_type: str
    scope_name: str
    overall_score: float
    completeness_score: Optional[float]
    consistency_score: Optional[float]
    uniqueness_score: Optional[float]
    timeliness_score: Optional[float]
    conformity_score: Optional[float]
    health_scan_score: Optional[float]
    ddl_compliance_score: Optional[float]
    calculated_at: datetime

    class Config:
        from_attributes = True


class ExecuteRequest(BaseModel):
    datasource_id: Optional[int] = None
    table_name: Optional[str] = None
    rule_ids: Optional[list[int]] = None


class DashboardResponse(BaseModel):
    total_datasources: int
    avg_score: float
    rules_total: int
    rules_passed: int
    rules_failed: int
    datasource_scores: list[dict]
    top_failures: list[dict]
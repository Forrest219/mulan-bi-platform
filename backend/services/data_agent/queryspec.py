"""QuerySpec contract for MCP-first controlled Data Agent QA."""

from __future__ import annotations

from typing import Any, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

QuerySpecIntent = Literal[
    "aggregate",
    "ranking",
    "customer_record",
    "trend_condition",
    "all_period_condition",
    "set_difference",
    "root_cause",
    "asset_inventory",
]
QuerySpecOperator = QuerySpecIntent

ALLOWED_INTENTS: set[str] = {
    "aggregate",
    "ranking",
    "customer_record",
    "trend_condition",
    "all_period_condition",
    "set_difference",
    "root_cause",
    "asset_inventory",
}
ALLOWED_OPERATORS: set[str] = set(ALLOWED_INTENTS)

DATA_QUERY_INTENTS: set[str] = ALLOWED_INTENTS - {"asset_inventory"}
SEMANTIC_OPERATORS: set[str] = DATA_QUERY_INTENTS - {"aggregate"}
AGGREGATIONS: set[str] = {"SUM", "AVG", "COUNT", "COUNTD", "MIN", "MAX", "MEDIAN"}
SORT_DIRECTIONS: set[str] = {"ASC", "DESC"}


class DatasourceSpec(BaseModel):
    """Selected Tableau datasource for a QuerySpec."""

    model_config = ConfigDict(extra="ignore")

    name: Optional[str] = None
    luid: Optional[str] = None


class MetricSpec(BaseModel):
    """Metric field and aggregation requested by the plan."""

    model_config = ConfigDict(extra="ignore")

    field: str
    aggregation: Optional[str] = "SUM"
    alias: Optional[str] = None

    @field_validator("field")
    @classmethod
    def _normalize_field(cls, value: str) -> str:
        return value.strip()

    @field_validator("aggregation")
    @classmethod
    def _normalize_aggregation(cls, value: Optional[str]) -> Optional[str]:
        return value.strip().upper() if isinstance(value, str) and value.strip() else None


class DerivedMetricSpec(BaseModel):
    """Derived metric requested by the plan."""

    model_config = ConfigDict(extra="ignore")

    name: str
    formula: Optional[str] = None
    result_type: Optional[str] = None
    required_base_metrics: list[str] = Field(default_factory=list)

    @field_validator("name", "formula", "result_type")
    @classmethod
    def _normalize_optional_string(cls, value: Optional[str]) -> Optional[str]:
        return value.strip() if isinstance(value, str) else value

    @field_validator("required_base_metrics")
    @classmethod
    def _normalize_required_base_metrics(cls, value: list[str]) -> list[str]:
        return [item.strip() for item in value if isinstance(item, str) and item.strip()]


class TimeSpec(BaseModel):
    """Time field, grain, and range requested by the plan."""

    model_config = ConfigDict(extra="ignore")

    field: str
    grain: Optional[str] = None
    range: dict[str, Any] = Field(default_factory=dict)
    timezone: Optional[str] = None

    @field_validator("field")
    @classmethod
    def _normalize_field(cls, value: str) -> str:
        return value.strip()

    @field_validator("grain")
    @classmethod
    def _normalize_grain(cls, value: Optional[str]) -> Optional[str]:
        return value.strip().upper() if value else None


class FilterSpec(BaseModel):
    """Field filter requested by the plan."""

    model_config = ConfigDict(extra="ignore")

    field: str
    op: str = "IN"
    values: list[Any] = Field(default_factory=list)
    value: Any = None

    @field_validator("field")
    @classmethod
    def _normalize_field(cls, value: str) -> str:
        return value.strip()

    @field_validator("op")
    @classmethod
    def _normalize_op(cls, value: str) -> str:
        return value.strip().upper()


class SortSpec(BaseModel):
    """Sort field and direction requested by the plan."""

    model_config = ConfigDict(extra="ignore")

    field: str
    direction: str = "DESC"

    @field_validator("field")
    @classmethod
    def _normalize_field(cls, value: str) -> str:
        return value.strip()

    @field_validator("direction")
    @classmethod
    def _normalize_direction(cls, value: str) -> str:
        return value.strip().upper()


class AnswerContract(BaseModel):
    """Bounded rendering contract for the final answer."""

    model_config = ConfigDict(extra="ignore")

    max_chars: Optional[int] = None
    must_include: list[str] = Field(default_factory=list)
    forbid: list[str] = Field(default_factory=list)


class SetQueryClause(BaseModel):
    """One side of a set-difference QuerySpec."""

    model_config = ConfigDict(extra="ignore")

    target_dimension: str
    filters: list[FilterSpec] = Field(default_factory=list)
    time: Optional[TimeSpec] = None

    @field_validator("target_dimension")
    @classmethod
    def _normalize_target_dimension(cls, value: str) -> str:
        return value.strip()


class QuerySpec(BaseModel):
    """LLM-filled structured query plan for controlled MCP execution."""

    model_config = ConfigDict(extra="ignore")

    intent: str
    source: Optional[str] = None
    datasource: Optional[DatasourceSpec] = None
    operator: Optional[str] = None
    time: Optional[TimeSpec] = None
    metrics: list[MetricSpec] = Field(default_factory=list)
    derived_metrics: list[DerivedMetricSpec] = Field(default_factory=list)
    dimensions: list[str] = Field(default_factory=list)
    breakdown_dimensions: list[str] = Field(default_factory=list)
    focus_dimension: Optional[str] = None
    filters: list[FilterSpec] = Field(default_factory=list)
    sort: list[SortSpec] = Field(default_factory=list)
    limit: Optional[int] = None
    direction: Optional[str] = None
    operator_spec: dict[str, Any] = Field(default_factory=dict)
    universe: Optional[SetQueryClause] = None
    occurred: Optional[SetQueryClause] = None
    result_shape: Optional[str] = None
    raw_rows: bool = False
    detail_scan: bool = False
    allow_detail_scan: bool = False
    answer_contract: Optional[AnswerContract] = None
    params: dict[str, Any] = Field(default_factory=dict)

    @field_validator("intent", "operator", "direction", "result_shape", "focus_dimension")
    @classmethod
    def _normalize_optional_string(cls, value: Optional[str]) -> Optional[str]:
        return value.strip() if isinstance(value, str) else value

    @field_validator("dimensions", "breakdown_dimensions")
    @classmethod
    def _normalize_string_list(cls, value: list[str]) -> list[str]:
        return [item.strip() for item in value if isinstance(item, str) and item.strip()]

    @property
    def effective_operator(self) -> str:
        """Return the explicit operator, falling back to intent."""
        return self.operator or self.intent

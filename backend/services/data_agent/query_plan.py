"""Controlled query-plan primitives for Data Agent pushdown execution.

This draft is intentionally dependency-light so it can be copied into the
existing backend/services/data_agent package before wiring QueryTool to it.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal, Optional


ResultShape = Literal[
    "scalar",
    "aggregate_table",
    "ranked_table",
    "time_series",
    "key_set",
    "operator_summary",
    "detail_table",
    "dimension_values",
]

QueryIntent = Literal[
    "lookup",
    "analysis",
    "ranking",
    "trend",
    "comparison",
    "root_cause",
    "detail",
]

FallbackType = Literal["clarify", "unsupported", "too_wide", "unsafe_plan", "execution_error"]

AGGREGATE_FUNCTIONS = {"SUM", "AVG", "COUNT", "COUNTD", "MIN", "MAX", "MEDIAN"}
ANALYSIS_INTENTS = {"analysis", "ranking", "trend", "comparison", "root_cause"}


@dataclass(slots=True)
class QueryExecutionPolicy:
    """Execution limits applied before calling Tableau MCP."""

    max_visible_rows: int = 100
    sentinel_fetch_rows: int = 101
    max_key_rows: int = 5000
    allow_detail_scan: bool = False
    allow_internal_key_set: bool = False


@dataclass(slots=True)
class QueryPlanContext:
    question: str
    datasource_luid: str
    datasource_name: str
    connection_id: Optional[int]
    fields: list[str]
    trace_id: str = ""
    intent: QueryIntent = "analysis"
    metric: Optional[str] = None
    dimensions: list[str] = field(default_factory=list)
    time_field: Optional[str] = None
    filters: list[dict[str, Any]] = field(default_factory=list)
    operator_hint: Optional[str] = None
    params: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class QueryPlanStep:
    name: str
    vizql_json: dict[str, Any]
    result_shape: ResultShape
    max_fetch_rows: int = 101
    max_visible_rows: int = 100
    allow_key_set: bool = False
    internal_only: bool = False
    explain: dict[str, Any] = field(default_factory=dict)

    def mcp_limit(self) -> int:
        if self.allow_key_set and self.internal_only:
            return self.max_fetch_rows
        return min(self.max_fetch_rows, self.max_visible_rows + 1)


@dataclass(slots=True)
class DataQueryPlan:
    ctx: QueryPlanContext
    steps: list[QueryPlanStep]
    operator_name: Optional[str] = None
    policy: QueryExecutionPolicy = field(default_factory=QueryExecutionPolicy)
    explain: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class OperatorResult:
    fields: list[Any]
    rows: list[list[Any]]
    summary: str
    intent: str
    confidence: float
    result_shape: ResultShape = "operator_summary"
    table_display: dict[str, Any] | None = None
    explain: dict[str, Any] = field(default_factory=dict)
    diagnostics: dict[str, Any] = field(default_factory=dict)

    def to_tool_data(self, *, datasource_name: str) -> dict[str, Any]:
        payload = {
            "fields": self.fields,
            "rows": self.rows,
            "intent": self.intent,
            "confidence": self.confidence,
            "datasource_name": datasource_name,
            "result_shape": self.result_shape,
            "operator_summary": self.summary,
            "explain": self.explain,
            "diagnostics": self.diagnostics,
        }
        if self.table_display:
            payload["table_display"] = self.table_display
        return payload


@dataclass(slots=True)
class PushdownFallback:
    fallback_type: FallbackType
    error_code: str
    message: str
    user_hint: str
    trace_id: str = ""
    detail: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "fallback_type": self.fallback_type,
            "error_code": self.error_code,
            "message": self.message,
            "user_hint": self.user_hint,
            "trace_id": self.trace_id,
            "detail": self.detail,
        }


class PushdownGuardrailError(ValueError):
    def __init__(self, fallback: PushdownFallback):
        super().__init__(fallback.message)
        self.fallback = fallback


def make_pushdown_fallback(
    *,
    code: str,
    message: str,
    ctx: QueryPlanContext | None = None,
    fallback_type: FallbackType = "unsafe_plan",
    user_hint: str | None = None,
    detail: dict[str, Any] | None = None,
) -> PushdownFallback:
    return PushdownFallback(
        fallback_type=fallback_type,
        error_code=code,
        message=message,
        user_hint=user_hint
        or "这个问题需要先按字段聚合、排序或筛选后再执行。请缩小范围，或明确 TopN、年份、地区、类别等条件。",
        trace_id=ctx.trace_id if ctx else "",
        detail=detail or {},
    )


def normalize_result_table(result: dict[str, Any]) -> tuple[list[Any], list[list[Any]]]:
    """Normalize Tableau MCP result shapes into fields/rows."""

    if "rows" not in result and isinstance(result.get("data"), list):
        data_list = result["data"]
        if data_list and isinstance(data_list[0], dict):
            fields = list(data_list[0].keys())
            return fields, [[row.get(field) for field in fields] for row in data_list]
        return [], []
    return list(result.get("fields") or []), list(result.get("rows") or [])


def compact(value: Any) -> str:
    return str(value or "").strip().lower().replace(" ", "").replace(" ", "")


def field_name(field: Any) -> str:
    if isinstance(field, dict):
        return str(field.get("name") or field.get("fieldAlias") or field.get("fieldCaption") or "")
    return str(field or "")


def numeric_value(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    try:
        return float(str(value).replace(",", "").replace("%", ""))
    except ValueError:
        return None


def vizql_fields(vizql_json: dict[str, Any]) -> list[dict[str, Any]]:
    fields = vizql_json.get("fields") or []
    return [field for field in fields if isinstance(field, dict)]


def is_aggregate_field(field: dict[str, Any]) -> bool:
    function = str(field.get("function") or "").upper()
    return function in AGGREGATE_FUNCTIONS


def has_aggregate_field(vizql_json: dict[str, Any]) -> bool:
    return any(is_aggregate_field(field) for field in vizql_fields(vizql_json))


def has_time_bucket_field(vizql_json: dict[str, Any]) -> bool:
    return any(str(field.get("function") or "").upper() in {"YEAR", "QUARTER", "MONTH", "WEEK", "DAY"} for field in vizql_fields(vizql_json))


def sorted_field(vizql_json: dict[str, Any]) -> dict[str, Any] | None:
    for field in vizql_fields(vizql_json):
        if field.get("sortDirection"):
            return field
    return None


def build_field(field_caption: str, function: str | None = None, **extra: Any) -> dict[str, Any]:
    field: dict[str, Any] = {"fieldCaption": field_caption}
    if function:
        field["function"] = function
    field.update({key: value for key, value in extra.items() if value is not None})
    return field


def metric_agg(ctx: QueryPlanContext, default: str = "SUM") -> dict[str, Any]:
    if not ctx.metric:
        raise ValueError("metric is required for aggregate operators")
    return build_field(ctx.metric, default)


def first_dimension(ctx: QueryPlanContext) -> str:
    if not ctx.dimensions:
        raise ValueError("dimension is required for this operator")
    return ctx.dimensions[0]


def first_time_field(ctx: QueryPlanContext) -> str:
    if not ctx.time_field:
        raise ValueError("time_field is required for this operator")
    return ctx.time_field

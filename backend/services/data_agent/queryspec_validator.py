"""Validator for MCP-first QuerySpec plans."""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from difflib import get_close_matches
from typing import Any, Iterable, Mapping

from pydantic import ValidationError

from services.data_agent.queryspec import (
    AGGREGATIONS,
    ALLOWED_INTENTS,
    ALLOWED_OPERATORS,
    DATA_QUERY_INTENTS,
    SEMANTIC_OPERATORS,
    SORT_DIRECTIONS,
    QuerySpec,
    SetQueryClause,
    SortSpec,
    TimeSpec,
)

AGGREGATE_EXPR_RE = re.compile(r"^\s*(SUM|AVG|COUNT|COUNTD|MIN|MAX|MEDIAN)\s*\((.+)\)\s*$", re.IGNORECASE)
DATE_EXPR_RE = re.compile(r"^\s*(YEAR|QUARTER|MONTH|WEEK|DAY)\s*\((.+)\)\s*$", re.IGNORECASE)

EXPLICIT_METRIC_PATTERNS: dict[str, tuple[str, ...]] = {
    "利润率": (r"利润率",),
    "销售额": (r"销售额", r"销售金额", r"营收", r"收入"),
    "利润": (r"利润(?!率)", r"毛利(?!率)", r"亏损", r"盈利"),
    "客户数": (r"客户数", r"客户数量", r"客户量", r"客户人数", r"客户个数"),
    "客单价": (r"客单价", r"客均价", r"单客价"),
}
KNOWN_SEMANTIC_METRICS = set(EXPLICIT_METRIC_PATTERNS)
OVERVIEW_RE = re.compile(r"(整体情况|整体概况|总体情况|经营概况|业务概览|概览|总览|基本情况|整体表现)")


@dataclass
class ValidationResult:
    """Structured validation result for controlled QuerySpec fallback handling."""

    passed: bool
    code: str
    message: str
    user_hint: str
    detail: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serializable result payload."""
        return asdict(self)


def validate_queryspec(
    spec: QuerySpec | Mapping[str, Any],
    queryable_fields: Iterable[Any],
    current_datasource: Any,
    user_context: Mapping[str, Any] | None = None,
) -> ValidationResult:
    """Validate that a QuerySpec is safe and executable against MCP fields."""
    try:
        queryspec = spec if isinstance(spec, QuerySpec) else QuerySpec.model_validate(spec)
    except ValidationError as exc:
        return _fail(
            "QS_INVALID_JSON",
            "QuerySpec 结构不符合契约。",
            "我没有生成可安全执行的查询计划，请换一种更明确的问法。",
            {"errors": exc.errors()},
        )

    queryable = _normalized_field_set(queryable_fields)
    metadata_only = _metadata_only_fields(current_datasource, user_context, queryable)

    checks = [
        _validate_intent_and_operator(queryspec),
        _validate_datasource(queryspec, current_datasource, user_context),
        _validate_referenced_fields(queryspec, queryable, metadata_only),
        _validate_safe_shape(queryspec),
        _validate_query_requirements(queryspec),
        _validate_operator_requirements(queryspec),
        _validate_semantic_metric_coverage(queryspec, user_context),
    ]
    for result in checks:
        if result is not None:
            return result

    return ValidationResult(
        passed=True,
        code="QS_VALID",
        message="QuerySpec 校验通过。",
        user_hint="",
        detail={
            "intent": queryspec.intent,
            "operator": queryspec.effective_operator,
            "field_count": len(_referenced_fields(queryspec)),
        },
    )


def _validate_intent_and_operator(queryspec: QuerySpec) -> ValidationResult | None:
    if queryspec.intent not in ALLOWED_INTENTS:
        return _fail(
            "QS_UNSUPPORTED_INTENT",
            "QuerySpec intent 不在受控白名单内。",
            "请改为聚合、排名、趋势、集合差异、归因或客户记录等受支持的问题。",
            {"intent": queryspec.intent, "allowed": sorted(ALLOWED_INTENTS)},
        )

    operator = queryspec.effective_operator
    if operator not in ALLOWED_OPERATORS:
        return _fail(
            "QS_UNSUPPORTED_OPERATOR",
            "QuerySpec operator 不在受控白名单内。",
            "请改为受支持的语义算子后重试。",
            {"operator": operator, "allowed": sorted(ALLOWED_OPERATORS)},
        )
    return None


def _validate_datasource(
    queryspec: QuerySpec,
    current_datasource: Any,
    user_context: Mapping[str, Any] | None,
) -> ValidationResult | None:
    requested_luid = queryspec.datasource.luid if queryspec.datasource else None
    if not requested_luid:
        return None

    accessible_luids = _string_set(_mapping_value(user_context or {}, "accessible_datasource_luids", "datasource_luids"))
    if accessible_luids and requested_luid not in accessible_luids:
        return _fail(
            "QS_DATASOURCE_FORBIDDEN",
            "当前账号无权访问 QuerySpec 指定的数据源。",
            "请切换到有权限的数据源后重试。",
            {"requested_luid": requested_luid},
        )

    current_luid = _first_string_value(current_datasource, "luid", "datasource_luid")
    if current_luid and requested_luid != current_luid:
        return _fail(
            "QS_DATASOURCE_MISMATCH",
            "QuerySpec 指定的数据源与当前 Tableau 数据源不一致。",
            "请基于当前已选数据源重新提问，或先切换数据源。",
            {"requested_luid": requested_luid, "current_luid": current_luid},
        )
    return None


def _validate_referenced_fields(
    queryspec: QuerySpec,
    queryable_fields: set[str],
    metadata_only_fields: set[str],
) -> ValidationResult | None:
    fields = _referenced_fields(queryspec)
    metadata_only = sorted(field for field in fields if _normalize_field(field) in metadata_only_fields)
    if metadata_only:
        return _fail(
            "QS_METADATA_FIELD_NOT_QUERYABLE",
            "QuerySpec 使用了仅存在于 metadata_fields、但当前 MCP 不可查询的字段。",
            "元数据存在不代表 published datasource 支持 MCP 查询。请改用当前可查询字段后重试。",
            {"fields": metadata_only},
        )

    unknown = sorted(field for field in fields if _normalize_field(field) not in queryable_fields)
    if unknown:
        suggestions = {
            field: get_close_matches(_normalize_field(field), list(queryable_fields), n=3, cutoff=0.55)
            for field in unknown
        }
        return _fail(
            "QS_UNKNOWN_FIELD",
            "QuerySpec 引用了当前 MCP/VizQL 不可查询的字段。",
            "请改用当前数据源可查询字段后重试。",
            {"fields": unknown, "suggestions": suggestions},
        )
    return None


def _validate_safe_shape(queryspec: QuerySpec) -> ValidationResult | None:
    limit = queryspec.limit if queryspec.limit is not None else 0
    requests_detail = (
        queryspec.raw_rows
        or queryspec.detail_scan
        or str(queryspec.result_shape or "").strip().lower() == "detail_table"
    )
    if requests_detail and not (queryspec.allow_detail_scan and 0 < limit <= 100):
        return _fail(
            "QS_RAW_ROWS_REJECTED",
            "QuerySpec 请求了未受控的明细行扫描。",
            "这个问题需要先做聚合或筛选后才能可靠回答，请补充 TopN、时间范围或维度。",
            {"result_shape": queryspec.result_shape, "limit": queryspec.limit},
        )
    return None


def _validate_query_requirements(queryspec: QuerySpec) -> ValidationResult | None:
    if queryspec.intent not in DATA_QUERY_INTENTS:
        return None

    operator = queryspec.effective_operator
    has_metric = bool(queryspec.metrics)
    if not has_metric and operator not in SEMANTIC_OPERATORS:
        return _fail(
            "QS_QUERY_REQUIRES_METRIC_OR_OPERATOR",
            "问数类 QuerySpec 缺少聚合指标或明确语义算子。",
            "请明确要聚合的指标，或改用排名、趋势、集合差异、归因等受支持的问题类型。",
            {"intent": queryspec.intent, "operator": operator},
        )

    invalid_aggregations = [
        metric.aggregation
        for metric in queryspec.metrics
        if metric.aggregation is not None and metric.aggregation not in AGGREGATIONS
    ]
    if invalid_aggregations:
        return _fail(
            "QS_UNSUPPORTED_AGGREGATION",
            "QuerySpec 使用了不支持的聚合函数。",
            "请改用 SUM、AVG、COUNT、COUNTD、MIN、MAX 或 MEDIAN。",
            {"aggregations": invalid_aggregations, "allowed": sorted(AGGREGATIONS)},
        )

    invalid_sort_directions = [sort.direction for sort in queryspec.sort if sort.direction not in SORT_DIRECTIONS]
    if invalid_sort_directions:
        return _fail(
            "QS_UNSUPPORTED_SORT_DIRECTION",
            "QuerySpec 使用了不支持的排序方向。",
            "请改用 ASC 或 DESC。",
            {"directions": invalid_sort_directions, "allowed": sorted(SORT_DIRECTIONS)},
        )
    return None


def _validate_operator_requirements(queryspec: QuerySpec) -> ValidationResult | None:
    operator = queryspec.effective_operator
    validators = {
        "aggregate": _validate_aggregate,
        "ranking": _validate_ranking,
        "customer_record": _validate_customer_record,
        "trend_condition": _validate_trend_condition,
        "all_period_condition": _validate_all_period_condition,
        "set_difference": _validate_set_difference,
        "root_cause": _validate_root_cause,
    }
    validator = validators.get(operator)
    return validator(queryspec) if validator else None


def _validate_aggregate(queryspec: QuerySpec) -> ValidationResult | None:
    if not queryspec.metrics:
        return _operator_fail("aggregate", "QS_AGGREGATE_REQUIRES_METRIC", "aggregate 必须包含至少一个聚合 metric。")
    return None


def _validate_ranking(queryspec: QuerySpec) -> ValidationResult | None:
    missing = []
    if not queryspec.metrics:
        missing.append("metrics")
    if not queryspec.dimensions:
        missing.append("dimensions")
    if not queryspec.sort:
        missing.append("sort")
    if not queryspec.limit:
        missing.append("limit")
    if missing:
        return _missing_operator_fields("ranking", missing)
    return None


def _validate_customer_record(queryspec: QuerySpec) -> ValidationResult | None:
    if not queryspec.filters and not queryspec.focus_dimension:
        return _operator_fail(
            "customer_record",
            "QS_CUSTOMER_RECORD_REQUIRES_SCOPE",
            "customer_record 必须包含筛选条件或明确 focus_dimension。",
        )
    if queryspec.limit is None or queryspec.limit <= 0 or queryspec.limit > 100:
        return _operator_fail(
            "customer_record",
            "QS_CUSTOMER_RECORD_LIMIT_REQUIRED",
            "customer_record 必须设置 1 到 100 之间的 limit。",
        )
    return None


def _validate_trend_condition(queryspec: QuerySpec) -> ValidationResult | None:
    missing = []
    if not queryspec.time or not queryspec.time.field:
        missing.append("time.field")
    if not queryspec.metrics:
        missing.append("metrics")
    if not _direction(queryspec):
        missing.append("direction")
    if queryspec.time and not _has_complete_range(queryspec.time):
        missing.append("time.range")
    if missing:
        return _missing_operator_fields("trend_condition", missing)
    return None


def _validate_all_period_condition(queryspec: QuerySpec) -> ValidationResult | None:
    missing = []
    if not queryspec.time or not queryspec.time.field:
        missing.append("time.field")
    if not queryspec.dimensions:
        missing.append("dimensions")
    if not queryspec.metrics:
        missing.append("metrics")
    if queryspec.time and not _has_complete_range(queryspec.time):
        missing.append("time.range")
    if missing:
        return _missing_operator_fields("all_period_condition", missing)
    return None


def _validate_set_difference(queryspec: QuerySpec) -> ValidationResult | None:
    missing = []
    if not queryspec.universe:
        missing.append("universe")
    if not queryspec.occurred:
        missing.append("occurred")
    if queryspec.universe and not queryspec.universe.target_dimension:
        missing.append("universe.target_dimension")
    if queryspec.occurred and not queryspec.occurred.target_dimension:
        missing.append("occurred.target_dimension")
    if missing:
        return _missing_operator_fields("set_difference", missing)

    if queryspec.universe and queryspec.occurred:
        universe_target = _normalize_field(queryspec.universe.target_dimension)
        occurred_target = _normalize_field(queryspec.occurred.target_dimension)
        if universe_target != occurred_target:
            return _operator_fail(
                "set_difference",
                "QS_SET_DIFFERENCE_TARGET_MISMATCH",
                "set_difference 的 universe 与 occurred 必须使用同一个目标维度。",
                {"universe": queryspec.universe.target_dimension, "occurred": queryspec.occurred.target_dimension},
            )
    return None


def _validate_root_cause(queryspec: QuerySpec) -> ValidationResult | None:
    missing = []
    if not queryspec.metrics:
        missing.append("metrics")
    if not queryspec.filters and not queryspec.focus_dimension:
        missing.append("filters_or_focus_dimension")
    if not _breakdown_dimensions(queryspec):
        missing.append("breakdown_dimensions")
    if not any(sort.direction == "ASC" for sort in queryspec.sort):
        missing.append("sort.ASC")
    if not queryspec.limit:
        missing.append("limit")
    if missing:
        return _missing_operator_fields("root_cause", missing)
    return None


def _referenced_fields(queryspec: QuerySpec) -> set[str]:
    fields: set[str] = set()
    fields.update(metric.field for metric in queryspec.metrics)
    for derived_metric in _derived_metrics(queryspec):
        fields.update(derived_metric.get("required_base_metrics") or [])
    fields.update(queryspec.dimensions)
    fields.update(queryspec.breakdown_dimensions)
    fields.update(filter_spec.field for filter_spec in queryspec.filters)
    fields.update(_sort_field_ref(sort) for sort in queryspec.sort)
    if queryspec.time:
        fields.add(queryspec.time.field)
    if queryspec.focus_dimension:
        fields.add(queryspec.focus_dimension)
    fields.update(_clause_fields(queryspec.universe))
    fields.update(_clause_fields(queryspec.occurred))
    return {field for field in fields if field}


def _clause_fields(clause: SetQueryClause | None) -> set[str]:
    if not clause:
        return set()
    fields = {clause.target_dimension}
    fields.update(filter_spec.field for filter_spec in clause.filters)
    if clause.time:
        fields.add(clause.time.field)
    return fields


def _sort_field_ref(sort: SortSpec) -> str:
    match = AGGREGATE_EXPR_RE.match(sort.field)
    if match:
        return match.group(2).strip()
    date_match = DATE_EXPR_RE.match(sort.field)
    return date_match.group(2).strip() if date_match else sort.field


def _normalized_field_set(fields: Iterable[Any]) -> set[str]:
    return {_normalize_field(field) for field in _iter_field_names(fields) if _normalize_field(field)}


def _metadata_only_fields(
    current_datasource: Any,
    user_context: Mapping[str, Any] | None,
    queryable_fields: set[str],
) -> set[str]:
    metadata_fields = []
    for source in (current_datasource, user_context or {}):
        metadata_fields.extend(_mapping_value(source, "metadata_fields", "fields") or [])
    return _normalized_field_set(metadata_fields) - queryable_fields


def _iter_field_names(fields: Iterable[Any]) -> Iterable[str]:
    for field_item in fields or []:
        if isinstance(field_item, str):
            yield field_item
        elif isinstance(field_item, Mapping):
            for key in ("name", "caption", "field", "fieldCaption", "field_caption", "fieldAlias"):
                value = field_item.get(key)
                if isinstance(value, str) and value.strip():
                    yield value


def _normalize_field(value: Any) -> str:
    return str(value or "").strip().casefold().replace(" ", "").replace("\u00a0", "")


def _mapping_value(source: Any, *keys: str) -> Any:
    if isinstance(source, Mapping):
        for key in keys:
            if key in source:
                return source[key]
    for key in keys:
        if hasattr(source, key):
            return getattr(source, key)
    return None


def _first_string_value(source: Any, *keys: str) -> str | None:
    value = _mapping_value(source, *keys)
    return value.strip() if isinstance(value, str) and value.strip() else None


def _string_set(value: Any) -> set[str]:
    if not value:
        return set()
    if isinstance(value, str):
        return {value}
    return {str(item) for item in value if item}


def _direction(queryspec: QuerySpec) -> str | None:
    direction = queryspec.direction or queryspec.params.get("direction")
    return str(direction).strip() if direction else None


def _has_complete_range(time: TimeSpec) -> bool:
    if not time.grain:
        return False
    range_spec = time.range or {}
    if not isinstance(range_spec, Mapping):
        return False
    range_type = str(range_spec.get("type") or "").strip().lower()
    if range_type and range_type not in {
        "year",
        "years",
        "year_range",
        "range",
        "period",
        "periods",
        "explicit_periods",
    }:
        return False
    if range_spec.get("value") is not None:
        return True
    if range_spec.get("values"):
        return True
    return (
        range_spec.get("start") is not None
        and range_spec.get("end") is not None
        or range_spec.get("from") is not None
        and range_spec.get("to") is not None
        or range_spec.get("start_year") is not None
        and range_spec.get("end_year") is not None
    )


def _breakdown_dimensions(queryspec: QuerySpec) -> list[str]:
    return queryspec.breakdown_dimensions or queryspec.dimensions


def _validate_semantic_metric_coverage(
    queryspec: QuerySpec,
    user_context: Mapping[str, Any] | None,
) -> ValidationResult | None:
    question = _question_from_context(user_context)
    if not question:
        return None

    explicit_metrics = _explicit_metrics_in_text(question)
    inherited_metrics = _context_metric_names(user_context)
    broad_overview = _is_broad_overview_question(question)

    covered_metrics = _queryspec_metric_names(queryspec, include_base_metrics=False)
    missing = sorted(metric for metric in explicit_metrics if metric not in covered_metrics)
    if missing:
        return _fail(
            "QS_SEMANTIC_METRIC_MISSING",
            "QuerySpec 未覆盖用户明确提到的指标。",
            "请重新生成查询计划，确保显式指标出现在 metrics 或 derived_metrics 中。",
            {
                "question_metrics": sorted(explicit_metrics),
                "covered_metrics": sorted(covered_metrics),
                "missing": missing,
            },
        )

    if queryspec.effective_operator != "aggregate":
        return None

    allowed_unrequested = set(KNOWN_SEMANTIC_METRICS) if broad_overview else set()
    allowed_metrics = explicit_metrics | inherited_metrics | allowed_unrequested
    allowed_metrics.update(_required_base_metrics_for_allowed_derived(queryspec, allowed_metrics))
    planned_metrics = _queryspec_metric_names(queryspec, include_base_metrics=False)
    unexpected = sorted(metric for metric in planned_metrics if metric in KNOWN_SEMANTIC_METRICS and metric not in allowed_metrics)
    if unexpected:
        return _fail(
            "QS_SEMANTIC_METRIC_UNREQUESTED",
            "QuerySpec 引入了用户未请求且上下文未继承的指标。",
            "请只保留用户问题所需指标；概览类问题除外。",
            {
                "question_metrics": sorted(explicit_metrics),
                "inherited_metrics": sorted(inherited_metrics),
                "unexpected": unexpected,
            },
        )
    return None


def _question_from_context(user_context: Mapping[str, Any] | None) -> str:
    if not user_context:
        return ""
    for key in ("question", "user_question", "query"):
        value = user_context.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def _explicit_metrics_in_text(text: str) -> set[str]:
    metrics: set[str] = set()
    compact = _normalize_text(text)
    for metric, patterns in EXPLICIT_METRIC_PATTERNS.items():
        if any(re.search(pattern, compact, flags=re.IGNORECASE) for pattern in patterns):
            metrics.add(metric)
    return metrics


def _is_broad_overview_question(question: str) -> bool:
    return bool(OVERVIEW_RE.search(_normalize_text(question)))


def _queryspec_metric_names(queryspec: QuerySpec, *, include_base_metrics: bool) -> set[str]:
    names: set[str] = set()
    for metric in queryspec.metrics:
        names.update(_metric_names_from_text(metric.alias or ""))
        names.update(_metric_names_from_field(metric.field, metric.aggregation))
    for derived_metric in _derived_metrics(queryspec):
        names.update(_metric_names_from_text(str(derived_metric.get("name") or "")))
        if include_base_metrics:
            for base_metric in derived_metric.get("required_base_metrics") or []:
                names.update(_metric_names_from_field(str(base_metric), "SUM"))
    return names


def _required_base_metrics_for_allowed_derived(queryspec: QuerySpec, allowed_derived_names: set[str]) -> set[str]:
    base_names: set[str] = set()
    for derived_metric in _derived_metrics(queryspec):
        derived_names = _metric_names_from_text(str(derived_metric.get("name") or ""))
        if not derived_names.intersection(allowed_derived_names):
            continue
        for base_metric in derived_metric.get("required_base_metrics") or []:
            base_names.update(_metric_names_from_field(str(base_metric), "SUM"))
    return base_names


def _metric_names_from_text(text: str) -> set[str]:
    return _explicit_metrics_in_text(text)


def _metric_names_from_field(field: str, aggregation: str | None) -> set[str]:
    normalized = _normalize_field(field)
    names: set[str] = set()
    if any(token in normalized for token in ("销售额", "销售金额", "营收", "收入")):
        names.add("销售额")
    if "利润率" in normalized:
        names.add("利润率")
    elif any(token in normalized for token in ("利润", "毛利")):
        names.add("利润")
    if "客单价" in normalized:
        names.add("客单价")
    customer_field = any(token in normalized for token in ("客户数", "客户数量", "客户名称", "客户id", "客户编号", "客户"))
    if customer_field and str(aggregation or "").upper() in {"COUNT", "COUNTD"}:
        names.add("客户数")
    return names


def _derived_metrics(queryspec: QuerySpec) -> list[dict[str, Any]]:
    derived = [metric.model_dump(mode="json") for metric in queryspec.derived_metrics]
    params_derived = queryspec.params.get("derived_metrics") if isinstance(queryspec.params, Mapping) else None
    if isinstance(params_derived, list):
        derived.extend(item for item in params_derived if isinstance(item, Mapping))
    return derived


def _context_metric_names(user_context: Mapping[str, Any] | None) -> set[str]:
    names: set[str] = set()
    for source in _context_sources(user_context):
        for key in ("metric_names", "metrics", "inherited_metric_names", "inherited_metrics"):
            value = source.get(key)
            if isinstance(value, str):
                names.update(_metric_names_from_text(value))
            elif isinstance(value, list | tuple | set):
                for item in value:
                    if isinstance(item, str):
                        names.update(_metric_names_from_text(item))
                        names.update(_metric_names_from_field(item, "SUM"))
                    elif isinstance(item, Mapping):
                        names.update(_metric_names_from_text(str(item.get("name") or item.get("alias") or "")))
                        names.update(_metric_names_from_field(str(item.get("field") or ""), str(item.get("aggregation") or "SUM")))
    return names


def _context_sources(user_context: Mapping[str, Any] | None) -> list[Mapping[str, Any]]:
    if not user_context:
        return []
    sources: list[Mapping[str, Any]] = [user_context]
    analysis_context = user_context.get("analysis_context")
    if isinstance(analysis_context, Mapping):
        sources.append(analysis_context)
    return sources


def _normalize_text(value: Any) -> str:
    return str(value or "").strip().replace(" ", "").replace("\u00a0", "")


def _missing_operator_fields(operator: str, fields: list[str]) -> ValidationResult:
    return _operator_fail(
        operator,
        f"QS_{operator.upper()}_MISSING_REQUIRED_FIELDS",
        f"{operator} 缺少必填 QuerySpec 字段。",
        {"missing": fields},
    )


def _operator_fail(
    operator: str,
    code: str,
    message: str,
    detail: dict[str, Any] | None = None,
) -> ValidationResult:
    payload = {"operator": operator}
    if detail:
        payload.update(detail)
    return _fail(
        code,
        message,
        "请补充该问题所需的指标、维度、时间、筛选、排序或 limit 后重试。",
        payload,
    )


def _fail(code: str, message: str, user_hint: str, detail: dict[str, Any] | None = None) -> ValidationResult:
    return ValidationResult(
        passed=False,
        code=code,
        message=message,
        user_hint=user_hint,
        detail=detail or {},
    )

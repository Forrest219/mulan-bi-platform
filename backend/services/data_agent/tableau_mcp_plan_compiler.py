"""Deterministic compiler for simple Tableau MCP query-datasource plans."""
# ruff: noqa: D101,D102,D107,PLR0911

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from typing import Any, Literal, Mapping, Sequence

CompileStatus = Literal["matched", "clarification", "unsupported"]
FieldRole = Literal["metric", "dimension", "time", "filter"]

_AGGREGATIONS = {"SUM", "AVG", "COUNT", "COUNTD", "MIN", "MAX", "MEDIAN"}
_NUMERIC_TYPES = {
    "INTEGER",
    "INT",
    "LONG",
    "REAL",
    "FLOAT",
    "DOUBLE",
    "DECIMAL",
    "NUMBER",
    "NUMERIC",
}
_TEXT_TYPES = {"STRING", "STR", "BOOLEAN", "BOOL"}
_STOP_TOKENS = {
    "a",
    "an",
    "and",
    "are",
    "as",
    "by",
    "for",
    "from",
    "in",
    "is",
    "me",
    "of",
    "on",
    "per",
    "show",
    "the",
    "to",
    "total",
    "what",
    "with",
}


@dataclass(frozen=True)
class TableauMcpField:
    """Queryable Tableau field with enough metadata for deterministic matching."""

    caption: str
    name: str = ""
    role: str = ""
    data_type: str = ""
    default_aggregation: str = ""
    formula: str = ""
    queryable: bool = True

    @property
    def aliases(self) -> tuple[str, ...]:
        values = [self.caption, self.name]
        return tuple(value for index, value in enumerate(values) if value and value not in values[:index])

    @property
    def is_time(self) -> bool:
        return "DATE" in self.data_type.upper() or "TIME" in self.data_type.upper()

    @property
    def is_metric(self) -> bool:
        role = self.role.upper()
        data_type = self.data_type.upper()
        if self.is_time:
            return False
        if role == "MEASURE":
            return True
        return any(token == data_type or token in data_type for token in _NUMERIC_TYPES)

    @property
    def is_dimension(self) -> bool:
        role = self.role.upper()
        data_type = self.data_type.upper()
        if self.is_time:
            return False
        if role == "DIMENSION":
            return True
        if role == "MEASURE":
            return False
        return not self.is_metric or any(token == data_type or token in data_type for token in _TEXT_TYPES)

    @property
    def is_aggregate_calculation(self) -> bool:
        formula = self.formula.upper()
        return bool(formula) and any(re.search(rf"(?<![A-Z0-9_]){function}\s*\(", formula) for function in _AGGREGATIONS)

    def to_payload(self) -> dict[str, Any]:
        return {
            "fieldCaption": self.caption,
            "name": self.name,
            "role": self.role,
            "dataType": self.data_type,
        }


@dataclass(frozen=True)
class CompileResult:
    """Structured compiler result consumed by the Tableau MCP strategy layer."""

    status: CompileStatus
    compile_reason: str
    compile_confidence: float = 0.0
    query_args: dict[str, Any] | None = None
    tool_name: str | None = None
    pattern: str | None = None
    clarification: dict[str, Any] | None = None
    matched_fields: dict[str, Any] | None = None

    @property
    def arguments(self) -> dict[str, Any] | None:
        return self.query_args

    @property
    def is_matched(self) -> bool:
        return self.status == "matched"

    @classmethod
    def matched(
        cls,
        *,
        pattern: str,
        query_args: dict[str, Any],
        matched_fields: dict[str, Any],
        confidence: float,
        reason: str,
    ) -> "CompileResult":
        return cls(
            status="matched",
            compile_reason=reason,
            compile_confidence=confidence,
            query_args=query_args,
            tool_name="query-datasource",
            pattern=pattern,
            matched_fields=matched_fields,
        )

    @classmethod
    def clarification_needed(
        cls,
        *,
        reason: str,
        clarification: dict[str, Any],
        confidence: float = 0.0,
    ) -> "CompileResult":
        return cls(
            status="clarification",
            compile_reason=reason,
            compile_confidence=confidence,
            clarification=clarification,
        )

    @classmethod
    def unsupported(cls, *, reason: str, confidence: float = 0.0) -> "CompileResult":
        return cls(status="unsupported", compile_reason=reason, compile_confidence=confidence)


@dataclass(frozen=True)
class _FieldSelection:
    field: TableauMcpField | None = None
    ambiguous: tuple[TableauMcpField, ...] = ()
    reason: str = ""

    @property
    def is_ambiguous(self) -> bool:
        return bool(self.ambiguous)


class DeterministicPlanCompiler:
    """Compile simple Tableau MCP aggregate questions without LLM planning."""

    def __init__(self, *, default_limit: int = 100, top_default_limit: int = 10) -> None:
        self.default_limit = default_limit
        self.top_default_limit = top_default_limit

    def compile(
        self,
        question: str,
        *,
        metadata_fields: Sequence[Mapping[str, Any]] | None = None,
        queryable_fields: Sequence[Any] | None = None,
        datasource_context: Mapping[str, Any] | None = None,
    ) -> CompileResult:
        fields = _build_field_catalog(metadata_fields or (), queryable_fields or ())
        if not fields:
            return CompileResult.unsupported(reason="no_queryable_fields")

        datasource_luid = _datasource_luid(datasource_context or {})
        if not datasource_luid:
            return CompileResult.unsupported(reason="missing_datasource_luid")

        question_text = question or ""
        metric = self._select_field(question_text, fields, "metric")
        if metric.is_ambiguous:
            return self._field_ambiguity("metric", metric.ambiguous)
        if not metric.field:
            return CompileResult.clarification_needed(
                reason="metric_not_found",
                clarification={
                    "type": "missing_metric",
                    "message": "请选择要聚合的指标字段。",
                    "candidates": [field.to_payload() for field in fields if field.is_metric][:8],
                },
            )

        filters = self._extract_filters(question_text, fields, excluded={metric.field.caption})
        top_n = _extract_top_n(question_text)
        time_intent = _has_time_intent(question_text)
        time = self._select_field(question_text, fields, "time")
        if time.is_ambiguous:
            return self._field_ambiguity("time", time.ambiguous)
        if time_intent and not time.field:
            time = self._default_time_field(fields)
            if time.is_ambiguous:
                return self._field_ambiguity("time", time.ambiguous)

        dimension = self._select_field(
            question_text,
            fields,
            "dimension",
            excluded={metric.field.caption, *(filter_spec["field"]["fieldCaption"] for filter_spec in filters)},
        )
        if dimension.is_ambiguous:
            return self._field_ambiguity("dimension", dimension.ambiguous)

        if top_n is not None:
            if not dimension.field:
                return CompileResult.clarification_needed(
                    reason="top_n_dimension_not_found",
                    clarification={
                        "type": "missing_dimension",
                        "message": "Top N 查询需要一个分组维度字段。",
                        "candidates": [field.to_payload() for field in fields if field.is_dimension][:8],
                    },
                )
            return self._matched_top_n(datasource_luid, metric.field, dimension.field, filters, top_n)

        if time_intent or time.field:
            if not time.field:
                return CompileResult.clarification_needed(
                    reason="time_field_not_found",
                    clarification={
                        "type": "missing_time_field",
                        "message": "趋势查询需要一个日期或时间字段。",
                        "candidates": [field.to_payload() for field in fields if field.is_time][:8],
                    },
                )
            return self._matched_time(datasource_luid, metric.field, time.field, filters, question_text)

        if dimension.field:
            return self._matched_metric_by_dimension(datasource_luid, metric.field, dimension.field, filters)

        if filters:
            return self._matched_single_metric(datasource_luid, metric.field, filters, pattern="single_metric_with_filters")

        return self._matched_single_metric(datasource_luid, metric.field, filters, pattern="single_metric")

    def _select_field(
        self,
        question: str,
        fields: Sequence[TableauMcpField],
        role: FieldRole,
        *,
        excluded: set[str] | None = None,
    ) -> _FieldSelection:
        excluded_compact = {_compact_text(value) for value in excluded or set()}
        candidates = [
            field
            for field in fields
            if _field_matches_role(field, role) and _compact_text(field.caption) not in excluded_compact
        ]
        scored = _score_fields(question, candidates)
        if not scored:
            return _FieldSelection(reason="no_match")
        best_score = scored[0][0]
        best = tuple(field for score, field in scored if score == best_score)
        if len(best) > 1:
            return _FieldSelection(ambiguous=best, reason="ambiguous")
        return _FieldSelection(field=best[0], reason="matched")

    def _default_time_field(self, fields: Sequence[TableauMcpField]) -> _FieldSelection:
        time_fields = tuple(field for field in fields if field.is_time)
        if len(time_fields) == 1:
            return _FieldSelection(field=time_fields[0], reason="single_time_field")
        if len(time_fields) > 1:
            return _FieldSelection(ambiguous=time_fields, reason="ambiguous_time_field")
        return _FieldSelection(reason="no_time_field")

    def _extract_filters(
        self,
        question: str,
        fields: Sequence[TableauMcpField],
        *,
        excluded: set[str],
    ) -> list[dict[str, Any]]:
        excluded_compact = {_compact_text(value) for value in excluded}
        filters: list[dict[str, Any]] = []
        seen: set[str] = set()
        for field in fields:
            key = _compact_text(field.caption)
            if key in excluded_compact or key in seen or field.is_metric:
                continue
            value = _extract_filter_value(question, field)
            if value is None:
                continue
            filters.append({"field": {"fieldCaption": field.caption}, "filterType": "SET", "values": [value]})
            seen.add(key)
        return filters

    def _matched_metric_by_dimension(
        self,
        datasource_luid: str,
        metric: TableauMcpField,
        dimension: TableauMcpField,
        filters: list[dict[str, Any]],
    ) -> CompileResult:
        query_args = {
            "datasourceLuid": datasource_luid,
            "query": {
                "fields": [
                    {"fieldCaption": dimension.caption},
                    self._metric_field(metric),
                ],
                "filters": filters,
            },
            "limit": self.default_limit,
        }
        return CompileResult.matched(
            pattern="metric_by_dimension",
            query_args=query_args,
            matched_fields={"metric": metric.to_payload(), "dimension": dimension.to_payload(), "filters": filters},
            confidence=0.86,
            reason="matched_metric_and_dimension",
        )

    def _matched_time(
        self,
        datasource_luid: str,
        metric: TableauMcpField,
        time: TableauMcpField,
        filters: list[dict[str, Any]],
        question: str,
    ) -> CompileResult:
        grain = _infer_time_grain(question)
        query_args = {
            "datasourceLuid": datasource_luid,
            "query": {
                "fields": [
                    {"fieldCaption": time.caption, "function": grain, "sortDirection": "ASC", "sortPriority": 1},
                    self._metric_field(metric),
                ],
                "filters": filters,
            },
            "limit": self.default_limit,
        }
        return CompileResult.matched(
            pattern="metric_by_time",
            query_args=query_args,
            matched_fields={"metric": metric.to_payload(), "time": time.to_payload(), "filters": filters},
            confidence=0.84,
            reason="matched_metric_and_time",
        )

    def _matched_top_n(
        self,
        datasource_luid: str,
        metric: TableauMcpField,
        dimension: TableauMcpField,
        filters: list[dict[str, Any]],
        top_n: int,
    ) -> CompileResult:
        metric_field = self._metric_field(metric)
        metric_field["sortDirection"] = "DESC"
        metric_field["sortPriority"] = 1
        query_args = {
            "datasourceLuid": datasource_luid,
            "query": {
                "fields": [{"fieldCaption": dimension.caption}, metric_field],
                "filters": filters,
            },
            "limit": top_n,
        }
        return CompileResult.matched(
            pattern="top_n_metric_by_dimension",
            query_args=query_args,
            matched_fields={"metric": metric.to_payload(), "dimension": dimension.to_payload(), "filters": filters},
            confidence=0.88,
            reason="matched_top_n_metric_by_dimension",
        )

    def _matched_single_metric(
        self,
        datasource_luid: str,
        metric: TableauMcpField,
        filters: list[dict[str, Any]],
        *,
        pattern: str,
    ) -> CompileResult:
        query_args = {
            "datasourceLuid": datasource_luid,
            "query": {"fields": [self._metric_field(metric)], "filters": filters},
            "limit": 1,
        }
        return CompileResult.matched(
            pattern=pattern,
            query_args=query_args,
            matched_fields={"metric": metric.to_payload(), "filters": filters},
            confidence=0.78 if filters else 0.72,
            reason="matched_metric_filters" if filters else "matched_single_metric",
        )

    def _metric_field(self, metric: TableauMcpField) -> dict[str, Any]:
        field = {"fieldCaption": metric.caption}
        if not metric.is_aggregate_calculation:
            field["function"] = _metric_function(metric)
        return field

    def _field_ambiguity(self, role: FieldRole, fields: Sequence[TableauMcpField]) -> CompileResult:
        return CompileResult.clarification_needed(
            reason=f"{role}_field_ambiguous",
            clarification={
                "type": "field_ambiguity",
                "field_role": role,
                "message": "匹配到多个可能字段，请选择一个后继续。",
                "candidates": [field.to_payload() for field in fields],
            },
            confidence=0.0,
        )


def _build_field_catalog(
    metadata_fields: Sequence[Mapping[str, Any]],
    queryable_fields: Sequence[Any],
) -> list[TableauMcpField]:
    metadata_by_key: dict[str, Mapping[str, Any]] = {}
    for item in metadata_fields:
        caption = _field_caption(item)
        name = _field_name(item)
        for value in (caption, name):
            key = _compact_text(value)
            if key:
                metadata_by_key.setdefault(key, item)

    queryable_keys = {_compact_text(_field_caption(item) if isinstance(item, Mapping) else item) for item in queryable_fields}
    use_queryable_filter = bool(queryable_keys)
    raw_items: list[Any] = list(queryable_fields) if queryable_fields else list(metadata_fields)

    fields: list[TableauMcpField] = []
    seen: set[str] = set()
    for raw in raw_items:
        source = raw if isinstance(raw, Mapping) else {}
        caption = _field_caption(source) if isinstance(raw, Mapping) else str(raw or "").strip()
        if not caption:
            continue
        key = _compact_text(caption)
        if not key or key in seen:
            continue
        if use_queryable_filter and key not in queryable_keys:
            continue
        metadata = metadata_by_key.get(key, {})
        merged = {**metadata, **source}
        field = TableauMcpField(
            caption=caption,
            name=_field_name(merged),
            role=_metadata_string(merged, "role"),
            data_type=_metadata_string(merged, "dataType", "data_type", "type"),
            default_aggregation=_metadata_string(merged, "defaultAggregation", "aggregation"),
            formula=_metadata_string(merged, "formula"),
            queryable=True,
        )
        fields.append(field)
        seen.add(key)

    if queryable_fields:
        return fields

    return [field for field in fields if field.queryable]


def _field_matches_role(field: TableauMcpField, role: FieldRole) -> bool:
    if role == "metric":
        return field.is_metric
    if role == "time":
        return field.is_time
    if role in {"dimension", "filter"}:
        return field.is_dimension or field.is_time
    return False


def _score_fields(question: str, fields: Sequence[TableauMcpField]) -> list[tuple[int, TableauMcpField]]:
    question_compact = _compact_text(question)
    question_tokens = set(_tokens(question))
    scored: list[tuple[int, TableauMcpField]] = []
    for field in fields:
        scores: list[int] = []
        for alias in field.aliases:
            alias_compact = _compact_text(alias)
            if not alias_compact:
                continue
            if alias_compact in question_compact:
                scores.append(1000 + len(alias_compact))
                continue
            alias_tokens = [token for token in _tokens(alias) if token not in _STOP_TOKENS and len(token) >= 3]
            overlap = [token for token in alias_tokens if token in question_tokens]
            if overlap:
                scores.append(100 + max(len(token) for token in overlap))
        if scores:
            scored.append((max(scores), field))
    scored.sort(key=lambda item: (-item[0], item[1].caption.casefold()))
    return scored


def _extract_top_n(question: str) -> int | None:
    patterns = [
        r"\btop\s*(\d{1,3})\b",
        r"\bfirst\s*(\d{1,3})\b",
        r"\bhighest\s*(\d{1,3})\b",
        r"前\s*(\d{1,3})",
        r"排名前\s*(\d{1,3})",
        r"最高\s*(\d{1,3})",
    ]
    for pattern in patterns:
        match = re.search(pattern, question, flags=re.IGNORECASE)
        if match:
            return max(1, min(int(match.group(1)), 100))
    if re.search(r"\btop\b|排名|最高|最大", question, flags=re.IGNORECASE):
        return 10
    return None


def _has_time_intent(question: str) -> bool:
    normalized = _normalize_text(question)
    compact = _compact_text(question)
    if re.search(r"\b(trend|over time|by year|by month|by quarter|by day|yearly|monthly|quarterly|daily)\b", normalized):
        return True
    return any(token in compact for token in ("趋势", "走势", "按年", "按月", "按季度", "按日", "逐年", "逐月", "年度", "月份"))


def _infer_time_grain(question: str) -> str:
    normalized = _normalize_text(question)
    compact = _compact_text(question)
    if re.search(r"\bquarter|quarterly\b", normalized) or "季度" in compact:
        return "QUARTER"
    if re.search(r"\bmonth|monthly\b", normalized) or any(token in compact for token in ("按月", "逐月", "月份", "月度")):
        return "MONTH"
    if re.search(r"\bday|date|daily\b", normalized) or any(token in compact for token in ("按日", "逐日", "每天", "日期")):
        return "DAY"
    if re.search(r"\byear|yearly|annual\b", normalized) or any(token in compact for token in ("按年", "逐年", "年度", "年份")):
        return "YEAR"
    return "MONTH"


def _extract_filter_value(question: str, field: TableauMcpField) -> str | None:
    normalized_question = unicodedata.normalize("NFKC", question or "")
    for alias in sorted(field.aliases, key=len, reverse=True):
        if not alias:
            continue
        escaped = re.escape(unicodedata.normalize("NFKC", alias))
        patterns = [
            rf"{escaped}\s*(?:=|:|：|为|是|等于|属于|in|is|equals)\s*([^,，。?？;；]+)",
            rf"(?:where|filter|filtered by|筛选|过滤)\s*{escaped}\s*(?:=|:|：|为|是|等于|属于|in|is|equals)?\s*([^,，。?？;；]+)",
        ]
        for pattern in patterns:
            match = re.search(pattern, normalized_question, flags=re.IGNORECASE)
            if not match:
                continue
            value = _clean_filter_value(match.group(1))
            if value:
                return value
    return None


def _clean_filter_value(value: str) -> str:
    cleaned = value.strip().strip("'\"“”‘’")
    cleaned = re.split(r"\s+(?:and|by|group by|with)\s+|按|分组|统计|汇总", cleaned, maxsplit=1, flags=re.IGNORECASE)[0]
    return cleaned.strip().strip("'\"“”‘’")


def _metric_function(field: TableauMcpField) -> str:
    aggregation = field.default_aggregation.strip().upper()
    if aggregation in _AGGREGATIONS:
        return aggregation
    return "SUM"


def _datasource_luid(context: Mapping[str, Any]) -> str:
    for key in ("datasourceLuid", "datasource_luid", "selected_datasource_luid", "tableau_datasource_luid", "luid"):
        value = context.get(key)
        if value:
            return str(value)
    datasource = context.get("datasource")
    if isinstance(datasource, Mapping):
        return _datasource_luid(datasource)
    return ""


def _field_caption(value: Mapping[str, Any]) -> str:
    for key in ("fieldCaption", "field_caption", "caption", "display_name", "name", "field"):
        raw = value.get(key)
        if raw:
            return str(raw).strip()
    return ""


def _field_name(value: Mapping[str, Any]) -> str:
    for key in ("name", "fieldName", "field_name"):
        raw = value.get(key)
        if raw:
            return str(raw).strip()
    return ""


def _metadata_string(value: Mapping[str, Any], *keys: str) -> str:
    for key in keys:
        raw = value.get(key)
        if raw is not None:
            return str(raw).strip()
    mcp = value.get("mcp")
    if isinstance(mcp, Mapping):
        return _metadata_string(mcp, *keys)
    return ""


def _normalize_text(value: Any) -> str:
    normalized = unicodedata.normalize("NFKC", str(value or "")).casefold()
    normalized = re.sub(r"[_\-./\\]+", " ", normalized)
    normalized = re.sub(r"[^\w\u4e00-\u9fff]+", " ", normalized, flags=re.UNICODE)
    return re.sub(r"\s+", " ", normalized).strip()


def _compact_text(value: Any) -> str:
    return re.sub(r"[\W_]+", "", _normalize_text(value), flags=re.UNICODE)


def _tokens(value: Any) -> list[str]:
    return [token for token in _normalize_text(value).split(" ") if token]


__all__ = [
    "CompileResult",
    "DeterministicPlanCompiler",
    "TableauMcpField",
]

"""Deterministic compiler for simple Tableau MCP query-datasource plans."""
# ruff: noqa: D101,D102,D107,PLR0911

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from typing import Any, Literal, Mapping, Sequence

CompileStatus = Literal["matched_executable", "unsupported", "ambiguous"]
AmbiguityLevel = Literal["hard", "soft"]
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
    "overall",
    "per",
    "show",
    "the",
    "to",
    "total",
    "what",
    "with",
}
_QUESTION_FILLER_TOKENS = {
    "整体",
    "总体",
    "什么",
    "是什么",
    "样子",
    "情况",
    "如何",
    "多少",
    "是多少",
    "查看",
    "展示",
    "统计",
    "汇总",
    "一下",
    "的",
    "和",
    "以及",
    "及",
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

    @property
    def is_calculation(self) -> bool:
        return bool(self.formula.strip())

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
    ambiguity_level: AmbiguityLevel | None = None
    compiler_advisory: dict[str, Any] | None = None

    @property
    def arguments(self) -> dict[str, Any] | None:
        return self.query_args

    @property
    def is_matched(self) -> bool:
        return self.status == "matched_executable"

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
            status="matched_executable",
            compile_reason=reason,
            compile_confidence=confidence,
            query_args=query_args,
            tool_name="query-datasource",
            pattern=pattern,
            matched_fields=matched_fields,
            compiler_advisory=_advisory(
                status="matched_executable",
                reason=reason,
                matched_metrics=_matched_metrics_from_fields(matched_fields),
                rejected_fast_path_reason=None,
            ),
        )

    @classmethod
    def ambiguous(
        cls,
        *,
        reason: str,
        clarification: dict[str, Any],
        ambiguity_level: AmbiguityLevel,
        advisory: dict[str, Any] | None = None,
        confidence: float = 0.0,
    ) -> "CompileResult":
        return cls(
            status="ambiguous",
            compile_reason=reason,
            compile_confidence=confidence,
            clarification=clarification,
            ambiguity_level=ambiguity_level,
            compiler_advisory=advisory
            or _advisory(
                status="ambiguous",
                reason=reason,
                ambiguous_metrics=[],
                rejected_fast_path_reason=reason,
            ),
        )

    @classmethod
    def clarification_needed(
        cls,
        *,
        reason: str,
        clarification: dict[str, Any],
        confidence: float = 0.0,
    ) -> "CompileResult":
        return cls.ambiguous(
            reason=reason,
            clarification=clarification,
            ambiguity_level="hard",
            confidence=confidence,
        )

    @classmethod
    def unsupported(
        cls,
        *,
        reason: str,
        confidence: float = 0.0,
        advisory: dict[str, Any] | None = None,
    ) -> "CompileResult":
        return cls(
            status="unsupported",
            compile_reason=reason,
            compile_confidence=confidence,
            compiler_advisory=advisory
            or _advisory(status="unsupported", reason=reason, rejected_fast_path_reason=reason),
        )


@dataclass(frozen=True)
class _FieldSelection:
    field: TableauMcpField | None = None
    ambiguous: tuple[TableauMcpField, ...] = ()
    reason: str = ""

    @property
    def is_ambiguous(self) -> bool:
        return bool(self.ambiguous)


@dataclass(frozen=True)
class _MetricSelection:
    fields: tuple[TableauMcpField, ...] = ()
    hard_ambiguous: tuple[TableauMcpField, ...] = ()
    soft_ambiguous: tuple[TableauMcpField, ...] = ()
    reason: str = ""

    @property
    def has_hard_ambiguity(self) -> bool:
        return bool(self.hard_ambiguous)

    @property
    def has_soft_ambiguity(self) -> bool:
        return bool(self.soft_ambiguous)


@dataclass(frozen=True)
class _DimensionSelection:
    fields: tuple[TableauMcpField, ...] = ()
    ambiguous: tuple[TableauMcpField, ...] = ()
    reason: str = ""

    @property
    def is_ambiguous(self) -> bool:
        return bool(self.ambiguous)


@dataclass(frozen=True)
class _RequestedFilterInput:
    phrase: str
    values: tuple[str, ...] = ()


@dataclass(frozen=True)
class _RequestedFieldInputs:
    metrics: tuple[str, ...] = ()
    dimensions: tuple[str, ...] = ()
    filters: tuple[_RequestedFilterInput, ...] = ()


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
        analysis_context: Mapping[str, Any] | None = None,
        requested_metrics: Sequence[Any] | None = None,
        requested_dimensions: Sequence[Any] | None = None,
        requested_filters: Sequence[Any] | None = None,
    ) -> CompileResult:
        fields = _build_field_catalog(metadata_fields or (), queryable_fields or ())
        if not fields:
            return CompileResult.unsupported(reason="no_queryable_fields")

        datasource_luid = _datasource_luid(datasource_context or {})
        if not datasource_luid:
            return CompileResult.unsupported(reason="missing_datasource_luid")

        question_text = question or ""
        requested = _current_turn_requested_inputs(
            analysis_context,
            requested_metrics=requested_metrics,
            requested_dimensions=requested_dimensions,
            requested_filters=requested_filters,
        )
        metrics = (
            self._select_metrics_from_phrases(requested.metrics, fields)
            if requested.metrics
            else self._select_metrics(question_text, fields)
        )
        if metrics.has_hard_ambiguity:
            return self._field_ambiguity("metric", metrics.hard_ambiguous, ambiguity_level="hard")
        if metrics.has_soft_ambiguity:
            return self._soft_metric_ambiguity(question_text, fields, metrics.soft_ambiguous, metrics.reason)
        if not metrics.fields:
            return CompileResult.unsupported(
                reason="metric_not_found",
                advisory=self._advisory(
                    status="unsupported",
                    reason="metric_not_found",
                    fields=fields,
                    question=question_text,
                    rejected_fast_path_reason="metric_not_found",
                ),
            )

        metric_fields = list(metrics.fields)
        excluded_metric_captions = {field.caption for field in metric_fields}
        if _has_unmatched_requested_terms(question_text, fields, excluded=excluded_metric_captions):
            return CompileResult.unsupported(
                reason="partial_metric_match",
                advisory=self._advisory(
                    status="unsupported",
                    reason="partial_metric_match",
                    fields=fields,
                    question=question_text,
                    matched_metrics=metric_fields,
                    rejected_fast_path_reason="partial_metric_match",
                ),
            )

        filters = self._extract_filters(question_text, fields, excluded=excluded_metric_captions)
        requested_filter_excluded = {
            *excluded_metric_captions,
            *(filter_spec["field"]["fieldCaption"] for filter_spec in filters),
        }
        filters.extend(self._extract_requested_filters(requested.filters, fields, excluded=requested_filter_excluded))
        top_n = _extract_top_n(question_text)
        time_intent = _has_time_intent(question_text)
        time = self._select_field(question_text, fields, "time")
        if requested.dimensions and not time.field:
            requested_time = self._select_requested_dimension(requested.dimensions, fields, role="time")
            if requested_time.is_ambiguous:
                return self._field_ambiguity("time", requested_time.ambiguous, ambiguity_level="hard")
            if requested_time.field:
                time = requested_time
        if time.is_ambiguous:
            return self._field_ambiguity("time", time.ambiguous, ambiguity_level="hard")
        if time_intent and not time.field:
            time = self._default_time_field(fields)
            if time.is_ambiguous:
                return self._field_ambiguity("time", time.ambiguous, ambiguity_level="hard")

        dimension_excluded = {
            *excluded_metric_captions,
            *(filter_spec["field"]["fieldCaption"] for filter_spec in filters),
            *({time.field.caption} if time.field else set()),
        }
        requested_dimensions = (
            self._select_requested_dimensions(requested.dimensions, fields, role="dimension", excluded=dimension_excluded)
            if requested.dimensions
            else _DimensionSelection()
        )
        if requested_dimensions.is_ambiguous:
            return self._field_ambiguity("dimension", requested_dimensions.ambiguous, ambiguity_level="hard")
        dimension = (
            _FieldSelection(field=requested_dimensions.fields[0], reason="requested_dimension_match")
            if len(requested_dimensions.fields) == 1 and not time.field
            else self._select_field(question_text, fields, "dimension", excluded=dimension_excluded)
        )
        if dimension.is_ambiguous:
            return self._field_ambiguity("dimension", dimension.ambiguous, ambiguity_level="hard")

        primary_metric = metric_fields[0]

        if top_n is not None:
            if len(metric_fields) > 1:
                return CompileResult.unsupported(
                    reason="top_n_multi_metric_unsupported",
                    advisory=self._advisory(
                        status="unsupported",
                        reason="top_n_multi_metric_unsupported",
                        fields=fields,
                        question=question_text,
                        matched_metrics=metric_fields,
                        rejected_fast_path_reason="top_n_multi_metric_unsupported",
                    ),
                )
            if not dimension.field:
                return CompileResult.unsupported(
                    reason="top_n_dimension_not_found",
                    advisory=self._advisory(
                        status="unsupported",
                        reason="top_n_dimension_not_found",
                        fields=fields,
                        question=question_text,
                        matched_metrics=metric_fields,
                        rejected_fast_path_reason="top_n_dimension_not_found",
                    ),
                )
            return self._matched_top_n(datasource_luid, primary_metric, dimension.field, filters, top_n)

        if time_intent or time.field:
            if not time.field:
                return CompileResult.unsupported(
                    reason="time_field_not_found",
                    advisory=self._advisory(
                        status="unsupported",
                        reason="time_field_not_found",
                        fields=fields,
                        question=question_text,
                        matched_metrics=metric_fields,
                        rejected_fast_path_reason="time_field_not_found",
                    ),
                )
            grouping_fields = _dedupe_fields([*requested_dimensions.fields, time.field])
            if len(grouping_fields) > 1:
                return self._matched_metrics_by_dimensions(datasource_luid, metric_fields, grouping_fields, filters, question_text)
            if len(metric_fields) > 1:
                return self._matched_multi_metric_by_time(datasource_luid, metric_fields, time.field, filters, question_text)
            return self._matched_time(datasource_luid, primary_metric, time.field, filters, question_text)

        if len(requested_dimensions.fields) > 1:
            return self._matched_metrics_by_dimensions(datasource_luid, metric_fields, requested_dimensions.fields, filters, question_text)

        if dimension.field:
            if len(metric_fields) > 1:
                return self._matched_multi_metric_by_dimension(datasource_luid, metric_fields, dimension.field, filters)
            return self._matched_metric_by_dimension(datasource_luid, primary_metric, dimension.field, filters)

        if filters:
            if len(metric_fields) > 1:
                return self._matched_multi_metric(datasource_luid, metric_fields, filters, pattern="multi_metric_with_filters")
            return self._matched_single_metric(datasource_luid, primary_metric, filters, pattern="single_metric_with_filters")

        if len(metric_fields) > 1:
            return self._matched_multi_metric(datasource_luid, metric_fields, filters, pattern="multi_metric")

        return self._matched_single_metric(datasource_luid, primary_metric, filters, pattern="single_metric")

    def _select_metrics(
        self,
        question: str,
        fields: Sequence[TableauMcpField],
    ) -> _MetricSelection:
        metrics = [field for field in fields if field.is_metric]
        exact = _explicit_exact_matches(question, metrics)
        if exact.hard_ambiguous:
            return _MetricSelection(hard_ambiguous=exact.hard_ambiguous, reason="multiple_exact_metric_matches")
        if exact.fields:
            return _MetricSelection(fields=exact.fields, reason="explicit_metric_matches")

        scored = _score_fields_detailed(question, metrics)
        if not scored:
            return _MetricSelection(reason="no_metric_match")
        best_score = scored[0][0]
        best_items = [item for item in scored if item[0] == best_score]
        best_fields = tuple(item[3] for item in best_items)
        best_match_type = str(best_items[0][1])
        if len(best_fields) > 1 and best_match_type in {"contains", "token", "alias"}:
            return _MetricSelection(hard_ambiguous=best_fields, reason="multiple_high_confidence_metric_matches")
        if best_match_type in {"contains", "token"}:
            return _MetricSelection(soft_ambiguous=best_fields, reason=f"soft_{best_match_type}_metric_match")
        if len(best_fields) > 1:
            return _MetricSelection(hard_ambiguous=best_fields, reason="metric_field_ambiguous")
        return _MetricSelection(fields=best_fields, reason="single_metric_match")

    def _select_metrics_from_phrases(
        self,
        phrases: Sequence[str],
        fields: Sequence[TableauMcpField],
    ) -> _MetricSelection:
        metric_fields = [field for field in fields if field.is_metric]
        selected: list[TableauMcpField] = []
        for phrase in phrases:
            selection = self._select_one_field_from_phrase(phrase, metric_fields)
            if selection.has_hard_ambiguity:
                return _MetricSelection(hard_ambiguous=selection.hard_ambiguous, reason="requested_metric_ambiguous")
            if selection.has_soft_ambiguity:
                return _MetricSelection(soft_ambiguous=selection.soft_ambiguous, reason="requested_metric_soft_ambiguous")
            if not selection.fields:
                return _MetricSelection(reason="requested_metric_not_found")
            selected.extend(selection.fields)
        return _MetricSelection(fields=tuple(_dedupe_fields(selected)), reason="requested_metric_matches")

    def _select_one_field_from_phrase(
        self,
        phrase: str,
        fields: Sequence[TableauMcpField],
    ) -> _MetricSelection:
        exact = _explicit_exact_matches(phrase, fields)
        if exact.hard_ambiguous or exact.fields:
            return exact
        scored = _score_fields_detailed(phrase, fields)
        if not scored:
            return _MetricSelection(reason="no_match")
        best_score = scored[0][0]
        best_items = [item for item in scored if item[0] == best_score]
        best_fields = tuple(item[3] for item in best_items)
        best_match_type = str(best_items[0][1])
        if len(best_fields) > 1:
            return _MetricSelection(hard_ambiguous=best_fields, reason="requested_field_ambiguous")
        if best_match_type in {"contains", "token"}:
            return _MetricSelection(soft_ambiguous=best_fields, reason="requested_field_soft_ambiguous")
        return _MetricSelection(fields=best_fields, reason="requested_field_match")

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

    def _select_requested_dimension(
        self,
        phrases: Sequence[str],
        fields: Sequence[TableauMcpField],
        *,
        role: FieldRole,
        excluded: set[str] | None = None,
    ) -> _FieldSelection:
        candidates = [
            field
            for field in fields
            if _field_matches_role(field, role) and _compact_text(field.caption) not in {_compact_text(value) for value in excluded or set()}
        ]
        selected: list[TableauMcpField] = []
        for phrase in phrases:
            selection = self._select_one_field_from_phrase(phrase, candidates)
            if selection.has_hard_ambiguity:
                return _FieldSelection(ambiguous=selection.hard_ambiguous, reason="requested_dimension_ambiguous")
            if selection.has_soft_ambiguity:
                return _FieldSelection(ambiguous=selection.soft_ambiguous, reason="requested_dimension_soft_ambiguous")
            selected.extend(selection.fields)
        selected = _dedupe_fields(selected)
        if len(selected) > 1:
            return _FieldSelection(reason="multi_dimension_unsupported")
        if selected:
            return _FieldSelection(field=selected[0], reason="requested_dimension_match")
        return _FieldSelection(reason="requested_dimension_not_found")

    def _select_requested_dimensions(
        self,
        phrases: Sequence[str],
        fields: Sequence[TableauMcpField],
        *,
        role: FieldRole,
        excluded: set[str] | None = None,
    ) -> _DimensionSelection:
        candidates = [
            field
            for field in fields
            if _field_matches_role(field, role) and _compact_text(field.caption) not in {_compact_text(value) for value in excluded or set()}
        ]
        selected: list[TableauMcpField] = []
        for phrase in phrases:
            selection = self._select_one_field_from_phrase(phrase, candidates)
            if selection.has_hard_ambiguity:
                return _DimensionSelection(ambiguous=selection.hard_ambiguous, reason="requested_dimension_ambiguous")
            if selection.has_soft_ambiguity:
                return _DimensionSelection(ambiguous=selection.soft_ambiguous, reason="requested_dimension_soft_ambiguous")
            selected.extend(selection.fields)
        selected = _dedupe_fields(selected)
        if selected:
            return _DimensionSelection(fields=tuple(selected), reason="requested_dimension_matches")
        return _DimensionSelection(reason="requested_dimension_not_found")

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

    def _extract_requested_filters(
        self,
        requested_filters: Sequence["_RequestedFilterInput"],
        fields: Sequence[TableauMcpField],
        *,
        excluded: set[str],
    ) -> list[dict[str, Any]]:
        filters: list[dict[str, Any]] = []
        seen: set[str] = set()
        candidates = [
            field
            for field in fields
            if _field_matches_role(field, "filter") and _compact_text(field.caption) not in {_compact_text(value) for value in excluded}
        ]
        for requested_filter in requested_filters:
            if not requested_filter.phrase or not requested_filter.values:
                continue
            selection = self._select_one_field_from_phrase(requested_filter.phrase, candidates)
            if selection.has_hard_ambiguity or selection.has_soft_ambiguity or not selection.fields:
                continue
            field = selection.fields[0]
            key = _compact_text(field.caption)
            if key in seen:
                continue
            filters.append(
                {
                    "field": {"fieldCaption": field.caption},
                    "filterType": "SET",
                    "values": list(requested_filter.values),
                }
            )
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

    def _matched_multi_metric_by_dimension(
        self,
        datasource_luid: str,
        metrics: Sequence[TableauMcpField],
        dimension: TableauMcpField,
        filters: list[dict[str, Any]],
    ) -> CompileResult:
        query_args = {
            "datasourceLuid": datasource_luid,
            "query": {
                "fields": [
                    {"fieldCaption": dimension.caption},
                    *[self._metric_field(metric) for metric in metrics],
                ],
                "filters": filters,
            },
            "limit": self.default_limit,
        }
        return CompileResult.matched(
            pattern="multi_metric_by_dimension",
            query_args=query_args,
            matched_fields={
                "metrics": [metric.to_payload() for metric in metrics],
                "dimension": dimension.to_payload(),
                "filters": filters,
            },
            confidence=0.86,
            reason="matched_multiple_metrics_and_dimension",
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

    def _matched_multi_metric_by_time(
        self,
        datasource_luid: str,
        metrics: Sequence[TableauMcpField],
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
                    *[self._metric_field(metric) for metric in metrics],
                ],
                "filters": filters,
            },
            "limit": self.default_limit,
        }
        return CompileResult.matched(
            pattern="multi_metric_by_time",
            query_args=query_args,
            matched_fields={"metrics": [metric.to_payload() for metric in metrics], "time": time.to_payload(), "filters": filters},
            confidence=0.84,
            reason="matched_multiple_metrics_and_time",
        )

    def _matched_metrics_by_dimensions(
        self,
        datasource_luid: str,
        metrics: Sequence[TableauMcpField],
        dimensions: Sequence[TableauMcpField],
        filters: list[dict[str, Any]],
        question: str,
    ) -> CompileResult:
        dimension_fields = [self._dimension_field(dimension, question) for dimension in dimensions]
        query_args = {
            "datasourceLuid": datasource_luid,
            "query": {
                "fields": [
                    *dimension_fields,
                    *[self._metric_field(metric) for metric in metrics],
                ],
                "filters": filters,
            },
            "limit": self.default_limit,
        }
        return CompileResult.matched(
            pattern="metrics_by_dimensions",
            query_args=query_args,
            matched_fields={
                "metrics": [metric.to_payload() for metric in metrics],
                "dimensions": [dimension.to_payload() for dimension in dimensions],
                "filters": filters,
            },
            confidence=0.84,
            reason="matched_metrics_and_dimensions",
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

    def _matched_multi_metric(
        self,
        datasource_luid: str,
        metrics: Sequence[TableauMcpField],
        filters: list[dict[str, Any]],
        *,
        pattern: str,
    ) -> CompileResult:
        query_args = {
            "datasourceLuid": datasource_luid,
            "query": {"fields": [self._metric_field(metric) for metric in metrics], "filters": filters},
            "limit": 1,
        }
        return CompileResult.matched(
            pattern=pattern,
            query_args=query_args,
            matched_fields={"metrics": [metric.to_payload() for metric in metrics], "filters": filters},
            confidence=0.8 if filters else 0.76,
            reason="matched_multiple_metrics_filters" if filters else "matched_multiple_metrics",
        )

    def _metric_field(self, metric: TableauMcpField) -> dict[str, Any]:
        field = {"fieldCaption": metric.caption}
        if not metric.is_calculation and not metric.is_aggregate_calculation:
            field["function"] = _metric_function(metric)
        return field

    def _dimension_field(self, dimension: TableauMcpField, question: str) -> dict[str, Any]:
        field = {"fieldCaption": dimension.caption}
        if dimension.is_time:
            field["function"] = _infer_time_grain(question)
            field["sortDirection"] = "ASC"
            field["sortPriority"] = 1
        return field

    def _field_ambiguity(
        self,
        role: FieldRole,
        fields: Sequence[TableauMcpField],
        *,
        ambiguity_level: AmbiguityLevel,
    ) -> CompileResult:
        candidates = [field.to_payload() for field in fields]
        advisory = _advisory(
            status="ambiguous",
            reason=f"{role}_field_ambiguous",
            ambiguous_metrics=[
                {
                    "phrase": "",
                    "ambiguity_level": ambiguity_level,
                    "candidates": candidates,
                }
            ]
            if role == "metric"
            else [],
            rejected_fast_path_reason=f"{role}_field_ambiguous",
        )
        return CompileResult.ambiguous(
            reason=f"{role}_field_ambiguous",
            clarification={
                "type": "field_ambiguity",
                "field_role": role,
                "message": "匹配到多个可能字段，请选择一个后继续。",
                "candidates": candidates,
            },
            ambiguity_level=ambiguity_level,
            advisory=advisory,
            confidence=0.0,
        )

    def _soft_metric_ambiguity(
        self,
        question: str,
        fields: Sequence[TableauMcpField],
        ambiguous: Sequence[TableauMcpField],
        reason: str,
    ) -> CompileResult:
        candidates = [field.to_payload() for field in ambiguous]
        advisory = self._advisory(
            status="ambiguous",
            reason=reason,
            fields=fields,
            question=question,
            ambiguous_metrics=[
                {
                    "phrase": "",
                    "ambiguity_level": "soft",
                    "candidates": candidates,
                }
            ],
            rejected_fast_path_reason=reason,
        )
        return CompileResult.ambiguous(
            reason=reason,
            clarification={
                "type": "field_ambiguity",
                "field_role": "metric",
                "message": "指标存在低置信候选，已交给 Tableau MCP Planner 继续判断。",
                "candidates": candidates,
            },
            ambiguity_level="soft",
            advisory=advisory,
            confidence=0.35,
        )

    def _advisory(
        self,
        *,
        status: CompileStatus,
        reason: str,
        fields: Sequence[TableauMcpField],
        question: str,
        matched_metrics: Sequence[TableauMcpField] | None = None,
        ambiguous_metrics: list[dict[str, Any]] | None = None,
        rejected_fast_path_reason: str | None,
    ) -> dict[str, Any]:
        return _advisory(
            status=status,
            reason=reason,
            matched_metrics=[
                {"phrase": field.caption, "fieldCaption": field.caption, "confidence": 1.0}
                for field in list(matched_metrics or [])
            ],
            ambiguous_metrics=ambiguous_metrics or [],
            candidate_dimensions=[
                {"fieldCaption": field.caption, "name": field.name, "confidence": confidence}
                for confidence, _match_type, field, _alias in _top_candidate_fields(question, fields, "dimension")
            ],
            candidate_filters=[
                {"fieldCaption": item["field"]["fieldCaption"], "filterType": item["filterType"], "values": item["values"]}
                for item in self._extract_filters(question, fields, excluded={field.caption for field in list(matched_metrics or [])})
            ],
            rejected_fast_path_reason=rejected_fast_path_reason,
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
        caption_key = _compact_text(caption)
        key = "|".join(part for part in (caption_key, _compact_text(_field_name(source))) if part)
        if not key or key in seen:
            continue
        if use_queryable_filter and caption_key not in queryable_keys:
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
    return [(score, field) for score, _match_type, _confidence, field, _alias in _score_fields_detailed(question, fields)]


def _score_fields_detailed(question: str, fields: Sequence[TableauMcpField]) -> list[tuple[int, str, float, TableauMcpField, str]]:
    question_compact = _compact_text(question)
    question_tokens = set(_tokens(question))
    scored: list[tuple[int, str, float, TableauMcpField, str]] = []
    for field in fields:
        scores: list[tuple[int, str, float, str]] = []
        for alias in field.aliases:
            alias_compact = _compact_text(alias)
            if not alias_compact:
                continue
            if _alias_has_standalone_mention(question, alias, fields):
                scores.append((1000 + len(alias_compact), "exact", 1.0, alias))
                continue
            if alias_compact and question_compact and question_compact in alias_compact:
                scores.append((350 + len(question_compact), "contains", 0.55, alias))
                continue
            alias_tokens = [token for token in _tokens(alias) if token not in _STOP_TOKENS and len(token) >= 3]
            overlap = [token for token in alias_tokens if token in question_tokens]
            if overlap:
                scores.append((100 + max(len(token) for token in overlap), "token", 0.45, alias))
        if scores:
            score, match_type, confidence, alias = max(scores, key=lambda item: item[0])
            scored.append((score, match_type, confidence, field, alias))
    scored.sort(key=lambda item: (-item[0], item[3].caption.casefold()))
    return scored


def _top_candidate_fields(
    question: str,
    fields: Sequence[TableauMcpField],
    role: FieldRole,
    *,
    limit: int = 5,
) -> list[tuple[float, str, TableauMcpField, str]]:
    candidates = [field for field in fields if _field_matches_role(field, role)]
    return [
        (confidence, match_type, field, alias)
        for _score, match_type, confidence, field, alias in _score_fields_detailed(question, candidates)[:limit]
    ]


def _explicit_exact_matches(question: str, fields: Sequence[TableauMcpField]) -> _MetricSelection:
    records: list[tuple[TableauMcpField, str, tuple[int, int]]] = []
    normalized = unicodedata.normalize("NFKC", question or "").casefold()
    all_spans: list[tuple[int, int, TableauMcpField, str]] = []
    for field in fields:
        for alias in field.aliases:
            alias_text = unicodedata.normalize("NFKC", alias or "").casefold().strip()
            if not alias_text:
                continue
            start = 0
            while True:
                index = normalized.find(alias_text, start)
                if index < 0:
                    break
                all_spans.append((index, index + len(alias_text), field, alias))
                start = index + max(1, len(alias_text))

    for start, end, field, alias in all_spans:
        if any(
            other_start <= start
            and end <= other_end
            and (other_start, other_end) != (start, end)
            and _compact_text(other_alias) != _compact_text(alias)
            for other_start, other_end, _other_field, other_alias in all_spans
        ):
            continue
        records.append((field, alias, (start, end)))

    if not records:
        return _MetricSelection()

    fields_by_alias: dict[str, list[TableauMcpField]] = {}
    for field, alias, _span in records:
        fields_by_alias.setdefault(_compact_text(alias), []).append(field)
    for alias_fields in fields_by_alias.values():
        unique = _dedupe_fields(alias_fields)
        if len(unique) > 1:
            return _MetricSelection(hard_ambiguous=tuple(unique), reason="multiple_exact_metric_matches")
    ordered_records = sorted(records, key=lambda item: (item[2][0], item[2][1]))
    return _MetricSelection(
        fields=tuple(_dedupe_fields([field for field, _alias, _span in ordered_records])),
        reason="explicit_metric_matches",
    )


def _dedupe_fields(fields: Sequence[TableauMcpField]) -> list[TableauMcpField]:
    seen: set[tuple[str, str]] = set()
    unique: list[TableauMcpField] = []
    for field in fields:
        key = (_compact_text(field.caption), _compact_text(field.name))
        if key in seen:
            continue
        seen.add(key)
        unique.append(field)
    return unique


def _current_turn_requested_inputs(
    analysis_context: Mapping[str, Any] | None,
    *,
    requested_metrics: Sequence[Any] | None,
    requested_dimensions: Sequence[Any] | None,
    requested_filters: Sequence[Any] | None,
) -> _RequestedFieldInputs:
    context = analysis_context or {}
    context_requested = context.get("requested_fields")
    if not isinstance(context_requested, Mapping):
        context_requested = context.get("current_turn_requested_fields")
    if not isinstance(context_requested, Mapping):
        context_requested = {}

    raw_metrics = requested_metrics if requested_metrics is not None else context.get("requested_metrics")
    raw_dimensions = requested_dimensions if requested_dimensions is not None else context.get("requested_dimensions")
    raw_filters = requested_filters if requested_filters is not None else context.get("requested_filters")

    if raw_metrics is None:
        raw_metrics = context_requested.get("metrics")
    if raw_dimensions is None:
        raw_dimensions = context_requested.get("dimensions")
    if raw_filters is None:
        raw_filters = context_requested.get("filters")

    return _RequestedFieldInputs(
        metrics=tuple(_requested_phrases(raw_metrics)),
        dimensions=tuple(_requested_phrases(raw_dimensions)),
        filters=tuple(_requested_filter_inputs(raw_filters)),
    )


def _requested_phrases(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, (str, Mapping)):
        values = [value]
    elif isinstance(value, Sequence):
        values = list(value)
    else:
        values = [value]
    phrases: list[str] = []
    seen: set[str] = set()
    for item in values:
        phrase = _requested_phrase(item)
        key = _compact_text(phrase)
        if not phrase or key in seen:
            continue
        phrases.append(phrase)
        seen.add(key)
    return phrases


def _requested_phrase(value: Any) -> str:
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, Mapping):
        field = value.get("field")
        if isinstance(field, Mapping):
            nested = _requested_phrase(field)
            if nested:
                return nested
        for key in ("fieldCaption", "field_caption", "caption", "display_name", "name", "field"):
            raw = value.get(key)
            if raw:
                return str(raw).strip()
    return str(value or "").strip()


def _requested_filter_inputs(value: Any) -> list[_RequestedFilterInput]:
    if value is None:
        return []
    if isinstance(value, (str, Mapping)):
        values = [value]
    elif isinstance(value, Sequence):
        values = list(value)
    else:
        values = [value]
    filters: list[_RequestedFilterInput] = []
    seen: set[str] = set()
    for item in values:
        phrase = _requested_phrase(item)
        filter_values = _requested_filter_values(item)
        key = f"{_compact_text(phrase)}|{'|'.join(_compact_text(filter_value) for filter_value in filter_values)}"
        if not phrase or key in seen:
            continue
        filters.append(_RequestedFilterInput(phrase=phrase, values=tuple(filter_values)))
        seen.add(key)
    return filters


def _requested_filter_values(value: Any) -> list[str]:
    if not isinstance(value, Mapping):
        return []
    raw_values = value.get("values")
    if raw_values is None:
        raw_values = value.get("value")
    if raw_values is None:
        return []
    if isinstance(raw_values, str):
        values = [raw_values]
    elif isinstance(raw_values, Sequence):
        values = [str(item) for item in raw_values if item is not None]
    else:
        values = [str(raw_values)]
    return [item.strip() for item in values if item.strip()]


def _alias_has_standalone_mention(question: str, alias: str, fields: Sequence[TableauMcpField]) -> bool:
    return any(field for field in _explicit_exact_matches(question, fields).fields if _compact_text(alias) in {_compact_text(value) for value in field.aliases})


def _has_unmatched_requested_terms(
    question: str,
    fields: Sequence[TableauMcpField],
    *,
    excluded: set[str],
) -> bool:
    if not re.search(r"\b(and|with)\b|[,，、/]|和|以及|及", question or "", flags=re.IGNORECASE):
        return False
    text = _normalize_text(question)
    aliases_to_remove: list[str] = []
    for field in fields:
        if field.caption in excluded or _alias_has_standalone_mention(question, field.caption, fields):
            for alias in field.aliases:
                alias_text = _normalize_text(alias)
                if alias_text:
                    aliases_to_remove.append(alias_text)
    for alias_text in sorted(set(aliases_to_remove), key=len, reverse=True):
        text = re.sub(re.escape(alias_text), " ", text, flags=re.IGNORECASE)
    tokens = [token for token in text.split(" ") if token and token not in _STOP_TOKENS]
    meaningful: list[str] = []
    for token in tokens:
        compact = _compact_text(token)
        if not compact or _is_question_filler(compact):
            continue
        if re.fullmatch(r"[\u4e00-\u9fff]+", compact) and all(filler in compact for filler in ("什么",)):
            continue
        meaningful.append(compact)
    return bool(meaningful)


def _is_question_filler(compact: str) -> bool:
    if compact in _QUESTION_FILLER_TOKENS:
        return True
    stripped = compact.strip("的")
    if stripped in _QUESTION_FILLER_TOKENS:
        return True
    return any(token in compact for token in ("什么", "多少", "样子", "情况", "如何"))


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
    return any(token in compact for token in ("趋势", "走势", "按年", "按月", "按季度", "按日", "逐年", "逐月", "每年", "每月", "每季度", "每日", "年度", "年份", "月份"))


def _infer_time_grain(question: str) -> str:
    normalized = _normalize_text(question)
    compact = _compact_text(question)
    if re.search(r"\bquarter|quarterly\b", normalized) or "季度" in compact:
        return "QUARTER"
    if re.search(r"\bmonth|monthly\b", normalized) or any(token in compact for token in ("按月", "逐月", "每月", "月份", "月度")):
        return "MONTH"
    if re.search(r"\bday|date|daily\b", normalized) or any(token in compact for token in ("按日", "逐日", "每日", "每天", "日期")):
        return "DAY"
    if re.search(r"\byear|yearly|annual\b", normalized) or any(token in compact for token in ("按年", "逐年", "每年", "年度", "年份")):
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


def _matched_metrics_from_fields(matched_fields: Mapping[str, Any] | None) -> list[dict[str, Any]]:
    if not isinstance(matched_fields, Mapping):
        return []
    raw_metrics = matched_fields.get("metrics")
    if isinstance(raw_metrics, list):
        return [
            {"phrase": str(item.get("fieldCaption") or item.get("name") or ""), "fieldCaption": item.get("fieldCaption"), "confidence": 1.0}
            for item in raw_metrics
            if isinstance(item, Mapping)
        ]
    metric = matched_fields.get("metric")
    if isinstance(metric, Mapping):
        return [{"phrase": str(metric.get("fieldCaption") or metric.get("name") or ""), "fieldCaption": metric.get("fieldCaption"), "confidence": 1.0}]
    return []


def _advisory(
    *,
    status: CompileStatus,
    reason: str,
    matched_metrics: list[dict[str, Any]] | None = None,
    matched_dimensions: list[dict[str, Any]] | None = None,
    ambiguous_metrics: list[dict[str, Any]] | None = None,
    ambiguous_dimensions: list[dict[str, Any]] | None = None,
    candidate_dimensions: list[dict[str, Any]] | None = None,
    candidate_filters: list[dict[str, Any]] | None = None,
    analysis_context_summary: dict[str, Any] | None = None,
    unresolved_references: bool | None = None,
    rejected_fast_path_reason: str | None,
) -> dict[str, Any]:
    return {
        "status": status,
        "reason": reason,
        "analysis_context_summary": dict(analysis_context_summary or {}),
        "unresolved_references": bool(unresolved_references) if unresolved_references is not None else False,
        "matched_metrics": list(matched_metrics or []),
        "matched_dimensions": list(matched_dimensions or []),
        "ambiguous_metrics": list(ambiguous_metrics or []),
        "ambiguous_dimensions": list(ambiguous_dimensions or []),
        "candidate_dimensions": list(candidate_dimensions or []),
        "candidate_filters": list(candidate_filters or []),
        "rejected_fast_path_reason": rejected_fast_path_reason,
    }


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

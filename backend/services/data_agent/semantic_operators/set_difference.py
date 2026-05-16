"""Set-difference operator for missing-record questions."""

from __future__ import annotations

from typing import Any, Mapping

from services.data_agent.query_plan import (
    OperatorResult,
    QueryPlanContext,
    QueryPlanStep,
    compact,
    field_name,
    first_dimension,
    normalize_result_table,
)
from services.data_agent.semantic_operators.base import BaseSemanticOperator, DataContinuityError
from services.data_agent.table_display import infer_table_display_schema


class SetDifferenceOperator(BaseSemanticOperator):
    name = "set_difference"
    version = "0.1.0"
    output_shape = "key_set"

    def match(self, ctx: QueryPlanContext) -> float:
        q = compact(ctx.question)
        if ctx.operator_hint == self.name:
            return 1.0
        if any(word in q for word in ("流失", "没有销售记录", "没有订单", "未购买", "未发生")):
            return 0.9 if ctx.dimensions else 0.65
        if "有" in q and "没有" in q:
            return 0.75
        return 0.0

    def build_steps(self, ctx: QueryPlanContext) -> list[QueryPlanStep]:
        entity = _target_dimension(ctx)
        universe_filter = (
            ctx.params.get("universe_filter")
            or ctx.params.get("universe_filters")
            or ctx.params.get("base_filter")
            or ctx.params.get("base_filters")
            or ctx.filters
        )
        occurred_filter = _occurred_filters(ctx, _as_filter_list(universe_filter))
        max_key_rows = int(ctx.params.get("max_key_rows") or 5000)
        return [
            QueryPlanStep(
                name="universe_keys",
                vizql_json={"fields": [{"fieldCaption": entity}], "filters": _as_filter_list(universe_filter)},
                result_shape="key_set",
                max_fetch_rows=max_key_rows,
                allow_key_set=True,
                internal_only=True,
                explain={"target_dimension": entity, "role": "universe"},
            ),
            QueryPlanStep(
                name="occurred_keys",
                vizql_json={"fields": [{"fieldCaption": entity}], "filters": occurred_filter},
                result_shape="key_set",
                max_fetch_rows=max_key_rows,
                allow_key_set=True,
                internal_only=True,
                explain={"target_dimension": entity, "role": "occurred"},
            ),
        ]

    def reduce(self, ctx: QueryPlanContext, step_results: dict[str, dict[str, Any]]) -> OperatorResult:
        entity = _target_dimension(ctx)
        return reduce_set_difference_result_sets(
            target_dimension=entity,
            universe_result=step_results.get("universe_keys") or step_results["base_keys"],
            occurred_result=step_results.get("occurred_keys") or step_results["compare_keys"],
            definition=str(ctx.params.get("definition") or "universe key set minus occurred key set"),
            sample_limit=_positive_int(ctx.params.get("sample_limit"), default=100, maximum=100),
        )


def reduce_set_difference_result_sets(
    *,
    target_dimension: str,
    universe_result: Mapping[str, Any],
    occurred_result: Mapping[str, Any],
    definition: str = "universe key set minus occurred key set",
    sample_limit: int = 100,
    universe_step_name: str = "universe_keys",
    occurred_step_name: str = "occurred_keys",
) -> OperatorResult:
    """Return the deterministic set difference from two MCP result tables.

    The only factual values used here are dimension values returned in the two
    MCP result sets. The caller controls how those result sets are queried.
    """

    entity = str(target_dimension or "").strip()
    base_fields, base_rows = normalize_result_table(dict(universe_result or {}))
    compare_fields, compare_rows = normalize_result_table(dict(occurred_result or {}))
    if not entity:
        entity = _first_returned_field_name(base_fields, compare_fields) or "dimension"

    base_idx = _field_index(base_fields, entity)
    compare_idx = _field_index(compare_fields, entity)
    if base_idx is None or compare_idx is None:
        raise DataContinuityError(
            "set_difference could not infer target dimension columns",
            detail={
                "target_dimension": entity,
                "universe_fields": [field_name(field) for field in base_fields],
                "occurred_fields": [field_name(field) for field in compare_fields],
            },
        )
    base_keys = _key_set(base_rows, base_idx)
    compare_keys = _key_set(compare_rows, compare_idx)
    diff = sorted(base_keys - compare_keys, key=lambda value: str(value))
    limit = _positive_int(sample_limit, default=100, maximum=100)
    sample = diff[:limit]
    fields = [entity]
    rows = [[value] for value in sample]
    return OperatorResult(
        fields=fields,
        rows=rows,
        summary=f"{definition}; count={len(diff)}; sample_rows={len(sample)}",
        intent=SetDifferenceOperator.name,
        confidence=0.95,
        result_shape="key_set",
        table_display=infer_table_display_schema(
            fields,
            rows,
            operator=SetDifferenceOperator.name,
            metric_names=[],
        ),
        explain={
            "operator": SetDifferenceOperator.name,
            "definition": definition,
            "universe_step": universe_step_name,
            "occurred_step": occurred_step_name,
            "visible_sample_limit": limit,
        },
        diagnostics={
            "universe_count": len(base_keys),
            "occurred_count": len(compare_keys),
            "difference_count": len(diff),
            "sampled": len(sample) < len(diff),
        },
    )


def build_set_difference_response_data(
    *,
    target_dimension: str,
    universe_result: Mapping[str, Any],
    occurred_result: Mapping[str, Any],
    datasource_name: str = "",
    datasource_luid: str = "",
    definition: str = "universe key set minus occurred key set",
    sample_limit: int = 100,
    fallback_detail: Mapping[str, Any] | None = None,
    mcp_steps: Mapping[str, Any] | None = None,
    chain_mode: str = "mcp_set_difference_fallback",
) -> dict[str, Any]:
    """Build one-column response_data for a QuerySpec-free MCP set difference."""

    result = reduce_set_difference_result_sets(
        target_dimension=target_dimension,
        universe_result=universe_result,
        occurred_result=occurred_result,
        definition=definition,
        sample_limit=sample_limit,
    )
    payload = result.to_tool_data(datasource_name=datasource_name)
    payload.update({
        "datasource_luid": datasource_luid,
        "operator": SetDifferenceOperator.name,
        "chain_mode": chain_mode,
    })
    if fallback_detail:
        payload["controlled_fallback"] = dict(fallback_detail)
        if fallback_detail.get("fallback_trace_event"):
            payload["fallback_trace_event"] = fallback_detail.get("fallback_trace_event")
    if mcp_steps:
        payload["mcp_steps"] = dict(mcp_steps)
    return payload


def _as_filter_list(value: Any) -> list[dict[str, Any]]:
    if value is None:
        return []
    if isinstance(value, list):
        return [item for item in value if isinstance(item, dict)]
    if isinstance(value, dict):
        return [value]
    return []


def _target_dimension(ctx: QueryPlanContext) -> str:
    dimension = ctx.params.get("target_dimension") or ctx.params.get("entity_field")
    if dimension:
        return str(dimension).strip()
    return first_dimension(ctx)


def _occurred_filters(ctx: QueryPlanContext, universe_filters: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if "occurred_filters" in ctx.params or "occurred_filter" in ctx.params:
        return _as_filter_list(ctx.params.get("occurred_filters") or ctx.params.get("occurred_filter"))
    extra = (
        ctx.params.get("exclude_filters")
        or ctx.params.get("exclude_filter")
        or ctx.params.get("compare_filters")
        or ctx.params.get("compare_filter")
        or []
    )
    return [*universe_filters, *_as_filter_list(extra)]


def _field_index(fields: list[Any], expected: str) -> int | None:
    expected_compact = compact(expected)
    for index, field in enumerate(fields):
        if compact(field_name(field)) == expected_compact:
            return index
    return None


def _key_set(rows: list[list[Any]], index: int) -> set[Any]:
    values: set[Any] = set()
    for row in rows:
        if len(row) <= index:
            continue
        value = row[index]
        if value is not None and str(value) != "":
            values.add(value)
    return values


def _first_returned_field_name(*field_lists: list[Any]) -> str:
    for fields in field_lists:
        for field in fields:
            name = field_name(field).strip()
            if name:
                return name
    return ""


def _positive_int(value: Any, *, default: int, maximum: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = default
    return min(max(parsed, 1), maximum)

"""Set-difference operator for churn / missing-record questions."""

from __future__ import annotations

from typing import Any

from services.data_agent.query_plan import (
    OperatorResult,
    QueryPlanContext,
    QueryPlanStep,
    compact,
    first_dimension,
    normalize_result_table,
)
from services.data_agent.semantic_operators.base import BaseSemanticOperator


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
        base_fields, base_rows = normalize_result_table(step_results.get("universe_keys") or step_results["base_keys"])
        compare_fields, compare_rows = normalize_result_table(step_results.get("occurred_keys") or step_results["compare_keys"])
        base_idx = _field_index(base_fields, entity)
        compare_idx = _field_index(compare_fields, entity)
        base_keys = _key_set(base_rows, base_idx)
        compare_keys = _key_set(compare_rows, compare_idx)
        diff = sorted(base_keys - compare_keys, key=lambda value: str(value))
        sample_limit = min(int(ctx.params.get("sample_limit") or 100), 100)
        sample = diff[:sample_limit]
        definition = ctx.params.get("definition") or "universe key set minus occurred key set"
        return OperatorResult(
            fields=[entity],
            rows=[[value] for value in sample],
            summary=f"{definition}; count={len(diff)}; sample_rows={len(sample)}",
            intent=self.name,
            confidence=0.95,
            result_shape="key_set",
            explain={
                "operator": self.name,
                "definition": definition,
                "universe_step": "universe_keys",
                "occurred_step": "occurred_keys",
                "visible_sample_limit": sample_limit,
            },
            diagnostics={
                "universe_count": len(base_keys),
                "occurred_count": len(compare_keys),
                "difference_count": len(diff),
                "sampled": len(sample) < len(diff),
            },
        )


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


def _field_index(fields: list[Any], expected: str) -> int:
    expected_compact = compact(expected)
    for index, field in enumerate(fields):
        if compact(field) == expected_compact:
            return index
    return 0


def _key_set(rows: list[list[Any]], index: int) -> set[Any]:
    values: set[Any] = set()
    for row in rows:
        if len(row) <= index:
            continue
        value = row[index]
        if value is not None and str(value) != "":
            values.add(value)
    return values

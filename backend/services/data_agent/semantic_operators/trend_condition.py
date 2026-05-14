"""Trend-condition operator for monotonic increase/decrease questions."""

from __future__ import annotations

from typing import Any

from services.data_agent.query_plan import (
    OperatorResult,
    QueryPlanContext,
    QueryPlanStep,
    build_field,
    compact,
    field_name,
    first_dimension,
    first_time_field,
    metric_agg,
    normalize_result_table,
    numeric_value,
)
from services.data_agent.semantic_operators.base import BaseSemanticOperator


class TrendConditionOperator(BaseSemanticOperator):
    name = "trend_condition"
    version = "0.1.0"
    output_shape = "operator_summary"

    def match(self, ctx: QueryPlanContext) -> float:
        q = compact(ctx.question)
        if ctx.operator_hint == self.name:
            return 1.0
        if any(word in q for word in ("持续增长", "一直在涨", "单调递增", "连续增长", "持续下降", "连续下降", "一直下降")):
            return 0.9 if ctx.metric and ctx.dimensions and ctx.time_field else 0.65
        return 0.0

    def build_steps(self, ctx: QueryPlanContext) -> list[QueryPlanStep]:
        time_field = first_time_field(ctx)
        dimension = _target_dimension(ctx)
        metric = metric_agg(ctx)
        period_function = ctx.params.get("period_function") or "YEAR"
        max_groups = int(ctx.params.get("max_groups") or 25)
        max_periods = int(ctx.params.get("max_periods") or 4)
        max_rows = min(100, max_groups * max_periods)
        return [
            QueryPlanStep(
                name="series_by_dimension",
                vizql_json={
                    "fields": [
                        build_field(time_field, period_function),
                        {"fieldCaption": dimension},
                        metric,
                    ],
                    "filters": ctx.filters,
                },
                result_shape="time_series",
                max_fetch_rows=max_rows + 1,
                max_visible_rows=100,
                explain={
                    "time_field": time_field,
                    "period_function": period_function,
                    "dimension": dimension,
                    "metric": ctx.metric,
                    "budget": {"max_groups": max_groups, "max_periods": max_periods},
                },
            )
        ]

    def reduce(self, ctx: QueryPlanContext, step_results: dict[str, dict[str, Any]]) -> OperatorResult:
        fields, rows = normalize_result_table(step_results["series_by_dimension"])
        field_names = [field_name(field) for field in fields]
        time_idx = _first_matching_index(field_names, ("YEAR", "QUARTER", "MONTH", "WEEK", "DAY", "年", "月", "季度"))
        metric_idx = _metric_index(field_names, ctx.metric)
        dimension = _target_dimension(ctx)
        dimension_idx = _field_index(field_names, dimension)
        if time_idx is None or metric_idx is None or dimension_idx is None:
            return OperatorResult(
                fields=["dimension", "condition_met", "periods", "first_value", "last_value", "delta_pct"],
                rows=[],
                summary="trend_condition could not infer time/dimension/metric columns",
                intent=self.name,
                confidence=0.4,
                diagnostics={"fields": field_names},
            )

        direction = _direction(ctx)
        expected_periods = _expected_periods(ctx, rows, time_idx)
        require_complete = _requires_complete_periods(ctx, expected_periods)
        series: dict[Any, list[tuple[Any, float]]] = {}
        for row in rows:
            if len(row) <= max(time_idx, metric_idx, dimension_idx):
                continue
            value = numeric_value(row[metric_idx])
            if value is None:
                continue
            series.setdefault(row[dimension_idx], []).append((row[time_idx], value))

        output_rows: list[list[Any]] = []
        detail: list[dict[str, Any]] = []
        for dimension, points in sorted(series.items(), key=lambda item: str(item[0])):
            ordered = sorted(points, key=lambda item: item[0])
            missing_periods = _missing_periods(ordered, expected_periods) if require_complete else []
            if missing_periods:
                if ctx.params.get("only_matches", True):
                    continue
                condition_met = False
                values = [value for _period, value in ordered]
            else:
                values = [value for _period, value in ordered]
                condition_met = _condition(values, direction)
            if ctx.params.get("only_matches", True) and not condition_met:
                continue
            first = values[0] if values else None
            last = values[-1] if values else None
            delta_pct = ((last - first) / abs(first)) if first not in (None, 0) and last is not None else None
            output_rows.append([dimension, condition_met, len(values), first, last, delta_pct])
            detail.append({
                "dimension": dimension,
                "points": [{"period": period, "value": value} for period, value in ordered],
                "missing_periods": missing_periods,
            })

        return OperatorResult(
            fields=["dimension", "condition_met", "periods", "first_value", "last_value", "delta_pct"],
            rows=output_rows[:100],
            summary=f"trend_condition direction={direction}; matches={len(output_rows)}",
            intent=self.name,
            confidence=0.92,
            result_shape="operator_summary",
            explain={
                "operator": self.name,
                "direction": direction,
                "strict": _strict(ctx),
                "target_dimension": dimension,
                "complete_periods": require_complete,
                "expected_periods": expected_periods,
                "series_step": "series_by_dimension",
            },
            diagnostics={"series": detail[:100], "input_rows": len(rows)},
        )


def _direction(ctx: QueryPlanContext) -> str:
    raw = str(ctx.params.get("direction") or "").strip().lower()
    if raw in {"increasing", "decreasing", "non_decreasing", "non_increasing"}:
        if raw == "increasing" and not _strict(ctx):
            return "non_decreasing"
        if raw == "decreasing" and not _strict(ctx):
            return "non_increasing"
        return raw
    q = compact(ctx.question)
    if any(word in q for word in ("下降", "减少", "降低", "下滑")):
        return "decreasing" if _strict(ctx) else "non_increasing"
    return "increasing" if _strict(ctx) else "non_decreasing"


def _strict(ctx: QueryPlanContext) -> bool:
    if "strict" in ctx.params:
        return bool(ctx.params["strict"])
    q = compact(ctx.question)
    if any(word in q for word in ("非严格", "不下降", "不减少", "不增长", "不增加")):
        return False
    return True


def _condition(values: list[float], direction: str) -> bool:
    if len(values) < 2:
        return False
    if direction == "non_decreasing":
        return all(curr >= prev for prev, curr in zip(values, values[1:]))
    if direction == "decreasing":
        return all(curr < prev for prev, curr in zip(values, values[1:]))
    if direction == "non_increasing":
        return all(curr <= prev for prev, curr in zip(values, values[1:]))
    return all(curr > prev for prev, curr in zip(values, values[1:]))


def _first_matching_index(names: list[str], needles: tuple[str, ...]) -> int | None:
    for index, name in enumerate(names):
        if any(needle in name for needle in needles):
            return index
    return None


def _metric_index(names: list[str], metric: str | None) -> int | None:
    if metric:
        metric_compact = compact(metric)
        for index, name in enumerate(names):
            if metric_compact in compact(name):
                return index
    return len(names) - 1 if names else None


def _target_dimension(ctx: QueryPlanContext) -> str:
    dimension = ctx.params.get("target_dimension") or ctx.params.get("dimension")
    if dimension:
        return str(dimension).strip()
    return first_dimension(ctx)


def _field_index(names: list[str], expected: str) -> int | None:
    expected_compact = compact(expected)
    for index, name in enumerate(names):
        if expected_compact and expected_compact in compact(name):
            return index
    return None


def _expected_periods(ctx: QueryPlanContext, rows: list[list[Any]], time_idx: int | None) -> list[Any]:
    raw = ctx.params.get("expected_periods", ctx.params.get("periods"))
    if isinstance(raw, list) and raw:
        return raw
    if time_idx is None:
        return []
    return sorted({row[time_idx] for row in rows if len(row) > time_idx}, key=lambda value: value)


def _requires_complete_periods(ctx: QueryPlanContext, expected_periods: list[Any]) -> bool:
    if "require_complete_periods" in ctx.params:
        return bool(ctx.params["require_complete_periods"])
    if "complete_periods" in ctx.params:
        return bool(ctx.params["complete_periods"])
    return bool(ctx.params.get("expected_periods") or ctx.params.get("periods")) and bool(expected_periods)


def _missing_periods(points: list[tuple[Any, float]], expected_periods: list[Any]) -> list[Any]:
    present = {period for period, _value in points}
    return [period for period in expected_periods if period not in present]

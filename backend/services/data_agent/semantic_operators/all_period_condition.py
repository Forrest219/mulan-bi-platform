"""All-period predicate operator, e.g. every year profitable/loss-making."""

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
from services.data_agent.semantic_operators.base import BaseSemanticOperator, DataContinuityError


class AllPeriodConditionOperator(BaseSemanticOperator):
    name = "all_period_condition"
    version = "0.1.0"
    output_shape = "operator_summary"

    def match(self, ctx: QueryPlanContext) -> float:
        q = compact(ctx.question)
        if ctx.operator_hint == self.name:
            return 1.0
        if any(word in q for word in ("一直亏损", "每年都亏", "每年都盈利", "一直盈利", "每个月都", "每年都")):
            return 0.9 if ctx.metric and ctx.dimensions and ctx.time_field else 0.65
        return 0.0

    def build_steps(self, ctx: QueryPlanContext) -> list[QueryPlanStep]:
        time_field = first_time_field(ctx)
        dimension = _target_dimension(ctx)
        metric = metric_agg(ctx)
        period_function = ctx.params.get("period_function") or "YEAR"
        return [
            QueryPlanStep(
                name="period_metric_by_dimension",
                vizql_json={
                    "fields": [
                        build_field(time_field, period_function),
                        {"fieldCaption": dimension},
                        metric,
                    ],
                    "filters": ctx.filters,
                },
                result_shape="time_series",
                max_fetch_rows=int(ctx.params.get("max_rows") or 101),
                max_visible_rows=100,
                explain={
                    "time_field": time_field,
                    "period_function": period_function,
                    "dimension": dimension,
                    "metric": ctx.metric,
                    "predicate": _predicate_spec(ctx),
                },
            )
        ]

    def reduce(self, ctx: QueryPlanContext, step_results: dict[str, dict[str, Any]]) -> OperatorResult:
        fields, rows = normalize_result_table(step_results["period_metric_by_dimension"])
        names = [field_name(field) for field in fields]
        time_idx = _time_index(names)
        metric_idx = _metric_index(names, ctx.metric)
        dimension = _target_dimension(ctx)
        dimension_idx = _field_index(names, dimension)
        predicate = _predicate_spec(ctx)
        if time_idx is None or metric_idx is None or dimension_idx is None:
            raise DataContinuityError(
                "all_period_condition could not infer time/dimension/metric columns",
                detail={"fields": names, "time_idx": time_idx, "metric_idx": metric_idx, "dimension_idx": dimension_idx},
            )

        grouped: dict[Any, list[tuple[Any, float]]] = {}
        for row in rows:
            if len(row) <= max(time_idx, metric_idx, dimension_idx):
                continue
            value = numeric_value(row[metric_idx])
            if value is None:
                continue
            grouped.setdefault(row[dimension_idx], []).append((row[time_idx], value))
        if rows and not grouped:
            raise DataContinuityError(
                "all_period_condition could not read any numeric metric values",
                detail={"fields": names, "input_rows": len(rows)},
            )

        output_rows: list[list[Any]] = []
        evidence: list[dict[str, Any]] = []
        min_periods = int(ctx.params.get("min_periods") or 2)
        expected_periods = _expected_periods(ctx, rows, time_idx)
        require_complete = _requires_complete_periods(ctx, expected_periods)
        if require_complete:
            _assert_global_period_coverage(rows, time_idx, expected_periods, operator=self.name)
        for dimension, points in sorted(grouped.items(), key=lambda item: str(item[0])):
            ordered = sorted(points, key=lambda item: item[0])
            missing_periods = _missing_periods(ordered, expected_periods) if require_complete else []
            failed = [{"period": period, "value": value} for period, value in ordered if not _passes(value, predicate)]
            condition_met = len(ordered) >= min_periods and not failed and not missing_periods
            if ctx.params.get("only_matches", True) and not condition_met:
                continue
            output_rows.append([dimension, condition_met, len(ordered), failed + [{"period": period, "missing": True} for period in missing_periods]])
            evidence.append({
                "dimension": dimension,
                "points": [{"period": period, "value": value} for period, value in ordered],
                "missing_periods": missing_periods,
            })

        return OperatorResult(
            fields=["dimension", "condition_met", "period_count", "failed_periods"],
            rows=output_rows[:100],
            summary=f"all_period_condition predicate={predicate}; matches={len(output_rows)}",
            intent=self.name,
            confidence=0.92,
            result_shape="operator_summary",
            explain={
                "operator": self.name,
                "predicate": predicate,
                "target_dimension": _target_dimension(ctx),
                "complete_periods": require_complete,
                "expected_periods": expected_periods,
                "series_step": "period_metric_by_dimension",
            },
            diagnostics={"series": evidence[:100], "input_rows": len(rows)},
        )


def _predicate_spec(ctx: QueryPlanContext) -> dict[str, Any]:
    if isinstance(ctx.params.get("predicate"), dict):
        return dict(ctx.params["predicate"])
    if isinstance(ctx.params.get("condition"), dict):
        return dict(ctx.params["condition"])
    q = compact(ctx.question)
    if any(word in q for word in ("亏损", "亏")):
        return {"op": "<", "value": 0}
    if any(word in q for word in ("盈利", "利润为正")):
        return {"op": ">", "value": 0}
    return {"op": str(ctx.params.get("op") or ">"), "value": ctx.params.get("threshold", 0)}


def _passes(value: float, predicate: dict[str, Any]) -> bool:
    threshold = float(predicate.get("value") or 0)
    op = predicate.get("op")
    if op == "<":
        return value < threshold
    if op == "<=":
        return value <= threshold
    if op == ">=":
        return value >= threshold
    if op == "==":
        return value == threshold
    return value > threshold


def _time_index(names: list[str]) -> int | None:
    for index, name in enumerate(names):
        if any(token in name for token in ("YEAR", "QUARTER", "MONTH", "WEEK", "DAY", "年", "月", "季度")):
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


def _assert_global_period_coverage(rows: list[list[Any]], time_idx: int, expected_periods: list[Any], *, operator: str) -> None:
    present = {row[time_idx] for row in rows if len(row) > time_idx}
    missing = [period for period in expected_periods if period not in present]
    if missing:
        raise DataContinuityError(
            f"{operator} result is missing required periods",
            detail={"expected_periods": expected_periods, "missing_periods": missing},
        )

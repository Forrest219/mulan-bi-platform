"""Aggregate evidence based root-cause contribution operator."""

from __future__ import annotations

from typing import Any

from services.data_agent.query_plan import (
    OperatorResult,
    QueryPlanContext,
    QueryPlanStep,
    compact,
    field_name,
    metric_agg,
    normalize_result_table,
    numeric_value,
)
from services.data_agent.semantic_operators.base import BaseSemanticOperator
from services.data_agent.table_display import infer_table_display_schema


class RootCauseOperator(BaseSemanticOperator):
    name = "root_cause"
    version = "0.1.0"
    output_shape = "operator_summary"

    def match(self, ctx: QueryPlanContext) -> float:
        q = compact(ctx.question)
        if ctx.operator_hint == self.name:
            return 1.0
        if any(word in q for word in ("为什么", "原因", "归因", "导致", "贡献")):
            return 0.85 if ctx.metric else 0.55
        return 0.0

    def build_steps(self, ctx: QueryPlanContext) -> list[QueryPlanStep]:
        if not _uses_baseline(ctx):
            return _build_breakdown_steps(ctx)

        current_filters = _as_filter_list(ctx.params.get("current_filter") or ctx.params.get("current_filters") or ctx.filters)
        baseline_filters = _as_filter_list(ctx.params.get("baseline_filter") or ctx.params.get("baseline_filters") or [])
        candidate_dimensions = _breakdown_dimensions(ctx)
        if not candidate_dimensions:
            raise ValueError("root_cause requires breakdown_dimensions or ctx.dimensions")

        steps = [
            QueryPlanStep(
                name="current_total",
                vizql_json={"fields": [metric_agg(ctx)], "filters": current_filters},
                result_shape="scalar",
                max_fetch_rows=1,
                max_visible_rows=1,
                explain={"role": "current_total", "metric": ctx.metric},
            ),
            QueryPlanStep(
                name="baseline_total",
                vizql_json={"fields": [metric_agg(ctx)], "filters": baseline_filters},
                result_shape="scalar",
                max_fetch_rows=1,
                max_visible_rows=1,
                explain={"role": "baseline_total", "metric": ctx.metric},
            ),
        ]
        top_k = min(int(ctx.params.get("top_k_per_dimension") or 20), 20)
        for dimension in candidate_dimensions[:5]:
            current_metric = metric_agg(ctx)
            current_metric["sortDirection"] = "ASC" if ctx.params.get("focus") == "loss" else "DESC"
            current_metric["sortPriority"] = 1
            steps.append(
                QueryPlanStep(
                    name=f"current_by_{dimension}",
                    vizql_json={"fields": [{"fieldCaption": dimension}, current_metric], "filters": current_filters},
                    result_shape="ranked_table",
                    max_fetch_rows=top_k,
                    max_visible_rows=top_k,
                    explain={"role": "current_segment", "dimension": dimension, "top_k": top_k},
                )
            )
            steps.append(
                QueryPlanStep(
                    name=f"baseline_by_{dimension}",
                    vizql_json={"fields": [{"fieldCaption": dimension}, metric_agg(ctx)], "filters": baseline_filters},
                    result_shape="aggregate_table",
                    max_fetch_rows=top_k + 1,
                    max_visible_rows=100,
                    explain={"role": "baseline_segment", "dimension": dimension, "top_k": top_k},
                )
            )
        return steps

    def reduce(self, ctx: QueryPlanContext, step_results: dict[str, dict[str, Any]]) -> OperatorResult:
        if "current_total" not in step_results and "baseline_total" not in step_results:
            return _reduce_breakdown_contributors(ctx, step_results)

        current_total = _first_numeric(normalize_result_table(step_results["current_total"])[1]) or 0.0
        baseline_total = _first_numeric(normalize_result_table(step_results["baseline_total"])[1]) or 0.0
        total_delta = current_total - baseline_total
        causes: list[dict[str, Any]] = []
        for dimension in _breakdown_dimensions(ctx)[:5]:
            current_result = step_results.get(f"current_by_{dimension}") or {}
            baseline_result = step_results.get(f"baseline_by_{dimension}") or {}
            causes.extend(_dimension_causes(dimension, ctx.metric, current_result, baseline_result, total_delta))

        causes.sort(key=lambda item: abs(item["delta_contribution"]), reverse=True)
        top_n = min(int(ctx.params.get("top_n") or 10), 20)
        rows = [
            [
                cause["dimension"],
                cause["segment"],
                cause["current_value"],
                cause["baseline_value"],
                cause["delta"],
                cause["delta_contribution"],
            ]
            for cause in causes[:top_n]
        ]
        output_fields = ["dimension", "segment", "current_value", "baseline_value", "delta", "delta_contribution"]
        return OperatorResult(
            fields=output_fields,
            rows=rows,
            summary=f"root_cause total_delta={total_delta}; causes={len(rows)}",
            intent=self.name,
            confidence=0.86 if rows else 0.5,
            result_shape="operator_summary",
            table_display=infer_table_display_schema(
                output_fields,
                rows,
                operator=self.name,
                metric_names=[ctx.metric] if ctx.metric else None,
            ),
            explain={
                "operator": self.name,
                "evidence_steps": list(step_results.keys()),
                "current_total": current_total,
                "baseline_total": baseline_total,
                "total_delta": total_delta,
            },
            diagnostics={"candidate_count": len(causes), "top_n": top_n},
        )


def _dimension_causes(
    dimension: str,
    metric: str | None,
    current_result: dict[str, Any],
    baseline_result: dict[str, Any],
    total_delta: float,
) -> list[dict[str, Any]]:
    current_fields, current_rows = normalize_result_table(current_result)
    baseline_fields, baseline_rows = normalize_result_table(baseline_result)
    current_map = _segment_metric_map(current_fields, current_rows, metric)
    baseline_map = _segment_metric_map(baseline_fields, baseline_rows, metric)
    segments = set(current_map) | set(baseline_map)
    causes = []
    for segment in segments:
        current_value = current_map.get(segment, 0.0)
        baseline_value = baseline_map.get(segment, 0.0)
        delta = current_value - baseline_value
        contribution = delta / total_delta if total_delta else 0.0
        causes.append(
            {
                "dimension": dimension,
                "segment": segment,
                "current_value": current_value,
                "baseline_value": baseline_value,
                "delta": delta,
                "delta_contribution": contribution,
            }
        )
    return causes


def _build_breakdown_steps(ctx: QueryPlanContext) -> list[QueryPlanStep]:
    dimensions = _breakdown_dimensions(ctx)
    if not dimensions:
        raise ValueError("root_cause requires breakdown_dimensions or ctx.dimensions")
    filters = _as_filter_list(ctx.params.get("filters") or ctx.filters)
    limit = min(int(ctx.params.get("limit") or ctx.params.get("top_n") or 10), 20)
    direction = _sort_direction(ctx)
    steps: list[QueryPlanStep] = []
    for dimension in dimensions[:5]:
        metric = metric_agg(ctx)
        metric["sortDirection"] = direction
        metric["sortPriority"] = 1
        steps.append(
            QueryPlanStep(
                name=f"breakdown_by_{dimension}",
                vizql_json={"fields": [{"fieldCaption": dimension}, metric], "filters": filters},
                result_shape="ranked_table",
                max_fetch_rows=limit,
                max_visible_rows=limit,
                explain={
                    "role": "breakdown_contributors",
                    "dimension": dimension,
                    "metric": ctx.metric,
                    "sort_direction": direction,
                    "limit": limit,
                },
            )
        )
    return steps


def _reduce_breakdown_contributors(ctx: QueryPlanContext, step_results: dict[str, dict[str, Any]]) -> OperatorResult:
    dimensions = _breakdown_dimensions(ctx)
    limit = min(int(ctx.params.get("limit") or ctx.params.get("top_n") or 10), 20)
    direction = _sort_direction(ctx)
    rows: list[list[Any]] = []
    evidence: dict[str, Any] = {}
    for dimension in dimensions[:5]:
        result = step_results.get(f"breakdown_by_{dimension}") or {}
        fields, input_rows = normalize_result_table(result)
        names = [field_name(field) for field in fields]
        dimension_idx = _field_index(names, dimension)
        metric_idx = _metric_index(names, ctx.metric)
        contributors: list[tuple[Any, float]] = []
        for row in input_rows:
            if dimension_idx is None or metric_idx is None or len(row) <= max(dimension_idx, metric_idx):
                continue
            value = numeric_value(row[metric_idx])
            if value is None:
                continue
            contributors.append((row[dimension_idx], value))
        contributors.sort(key=lambda item: item[1], reverse=direction == "DESC")
        total = sum(value for _segment, value in contributors)
        evidence[dimension] = {"total": total, "input_rows": len(input_rows)}
        for rank, (segment, value) in enumerate(contributors[:limit], start=1):
            rows.append([dimension, segment, value, _format_share(value / total) if total else None, rank])

    output_fields = ["分析维度", "维度取值", ctx.metric or "metric", "贡献占比", "排名"]
    return OperatorResult(
        fields=output_fields,
        rows=rows,
        summary=f"root_cause breakdown_dimensions={len(dimensions)}; contributors={len(rows)}",
        intent=RootCauseOperator.name,
        confidence=0.88 if rows else 0.5,
        result_shape="operator_summary",
        table_display=infer_table_display_schema(
            output_fields,
            rows,
            operator=RootCauseOperator.name,
            metric_names=[ctx.metric] if ctx.metric else None,
        ),
        explain={
            "operator": RootCauseOperator.name,
            "mode": "breakdown_contributors",
            "breakdown_dimensions": dimensions[:5],
            "sort_direction": direction,
            "limit": limit,
        },
        diagnostics=evidence,
    )


def _format_share(value: float | None) -> str | None:
    if value is None:
        return None
    return f"{value:.2%}"


def _segment_metric_map(fields: list[Any], rows: list[list[Any]], metric: str | None) -> dict[Any, float]:
    names = [field_name(field) for field in fields]
    metric_idx = _metric_index(names, metric)
    dimension_idx = 0
    result: dict[Any, float] = {}
    for row in rows:
        if len(row) <= max(dimension_idx, metric_idx):
            continue
        value = numeric_value(row[metric_idx])
        if value is not None:
            result[row[dimension_idx]] = value
    return result


def _metric_index(names: list[str], metric: str | None) -> int:
    if metric:
        metric_compact = compact(metric)
        for index, name in enumerate(names):
            if metric_compact in compact(name):
                return index
    return len(names) - 1


def _field_index(names: list[str], expected: str) -> int | None:
    expected_compact = compact(expected)
    for index, name in enumerate(names):
        if expected_compact and expected_compact in compact(name):
            return index
    return None


def _breakdown_dimensions(ctx: QueryPlanContext) -> list[str]:
    raw = ctx.params.get("breakdown_dimensions") or ctx.params.get("candidate_dimensions") or ctx.dimensions
    return [str(dimension).strip() for dimension in raw if str(dimension).strip()]


def _uses_baseline(ctx: QueryPlanContext) -> bool:
    return any(
        key in ctx.params
        for key in ("baseline_filter", "baseline_filters", "current_filter", "current_filters", "comparison_filter")
    )


def _sort_direction(ctx: QueryPlanContext) -> str:
    direction = str(ctx.params.get("sort_direction") or "").upper()
    if direction in {"ASC", "DESC"}:
        return direction
    if ctx.params.get("focus") == "loss":
        return "ASC"
    q = compact(ctx.question)
    return "ASC" if any(word in q for word in ("亏", "最低", "最少", "下降")) else "DESC"


def _first_numeric(rows: list[list[Any]]) -> float | None:
    for row in rows:
        for value in row:
            number = numeric_value(value)
            if number is not None:
                return number
    return None


def _as_filter_list(value: Any) -> list[dict[str, Any]]:
    if value is None:
        return []
    if isinstance(value, list):
        return [item for item in value if isinstance(item, dict)]
    if isinstance(value, dict):
        return [value]
    return []

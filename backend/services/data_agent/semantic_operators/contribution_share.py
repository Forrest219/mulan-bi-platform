"""Contribution-share operator with denominator pushed down as a total query."""

from __future__ import annotations

from typing import Any

from services.data_agent.query_plan import (
    OperatorResult,
    QueryPlanContext,
    QueryPlanStep,
    compact,
    field_name,
    first_dimension,
    metric_agg,
    normalize_result_table,
    numeric_value,
)
from services.data_agent.semantic_operators.base import BaseSemanticOperator
from services.data_agent.table_display import infer_table_display_schema


class ContributionShareOperator(BaseSemanticOperator):
    name = "contribution_share"
    version = "0.1.0"
    output_shape = "aggregate_table"

    def match(self, ctx: QueryPlanContext) -> float:
        q = compact(ctx.question)
        if ctx.operator_hint == self.name:
            return 1.0
        if any(word in q for word in ("占比", "贡献率", "贡献占比", "份额")):
            return 0.9 if ctx.metric and ctx.dimensions else 0.65
        return 0.0

    def build_steps(self, ctx: QueryPlanContext) -> list[QueryPlanStep]:
        dimension = first_dimension(ctx)
        metric = metric_agg(ctx)
        top_n = int(ctx.params.get("top_n") or _extract_top_n(ctx.question) or 0)
        if top_n:
            metric["sortDirection"] = "DESC"
            metric["sortPriority"] = 1
        group_limit = min(top_n or int(ctx.params.get("max_groups") or 100), 100)
        return [
            QueryPlanStep(
                name="group_metric",
                vizql_json={
                    "fields": [{"fieldCaption": dimension}, metric],
                    "filters": ctx.filters,
                },
                result_shape="ranked_table" if top_n else "aggregate_table",
                max_fetch_rows=group_limit + 1,
                max_visible_rows=100,
                explain={"dimension": dimension, "metric": ctx.metric, "top_n": top_n or None},
            ),
            QueryPlanStep(
                name="total_metric",
                vizql_json={"fields": [metric_agg(ctx)], "filters": ctx.filters},
                result_shape="scalar",
                max_fetch_rows=1,
                max_visible_rows=1,
                explain={"metric": ctx.metric, "denominator": "same filters, no group dimension"},
            ),
        ]

    def reduce(self, ctx: QueryPlanContext, step_results: dict[str, dict[str, Any]]) -> OperatorResult:
        group_fields, group_rows = normalize_result_table(step_results["group_metric"])
        total_fields, total_rows = normalize_result_table(step_results["total_metric"])
        group_names = [field_name(field) for field in group_fields]
        dimension_idx = 0
        metric_idx = _metric_index(group_names, ctx.metric)
        total = _first_numeric(total_rows) or 0.0
        rows: list[list[Any]] = []
        for row in group_rows:
            if len(row) <= max(dimension_idx, metric_idx):
                continue
            value = numeric_value(row[metric_idx])
            if value is None:
                continue
            share = _format_share(value / total) if total else None
            rows.append([row[dimension_idx], value, share])

        top_n = int(ctx.params.get("top_n") or _extract_top_n(ctx.question) or 0)
        output_fields = [
            group_names[dimension_idx] if group_names else "dimension",
            ctx.metric or "metric",
            _share_label(ctx),
        ]
        return OperatorResult(
            fields=output_fields,
            rows=rows[:100],
            summary=f"contribution_share rows={len(rows)}; denominator_step=total_metric",
            intent=self.name,
            confidence=0.94,
            result_shape="aggregate_table",
            table_display=infer_table_display_schema(
                output_fields,
                rows[:100],
                operator=self.name,
                metric_names=[ctx.metric] if ctx.metric else None,
            ),
            explain={
                "operator": self.name,
                "group_step": "group_metric",
                "denominator_step": "total_metric",
                "denominator_fields": [field_name(field) for field in total_fields],
                "top_n": top_n or None,
            },
            diagnostics={"denominator": total, "input_group_rows": len(group_rows)},
        )


def _metric_index(names: list[str], metric: str | None) -> int:
    if metric:
        metric_compact = compact(metric)
        for index, name in enumerate(names):
            if metric_compact in compact(name):
                return index
    return len(names) - 1


def _first_numeric(rows: list[list[Any]]) -> float | None:
    for row in rows:
        for value in row:
            number = numeric_value(value)
            if number is not None:
                return number
    return None


def _extract_top_n(question: str) -> int | None:
    import re

    match = re.search(r"(?:top|TOP|Top)\s*(\d+)", question)
    if match:
        return int(match.group(1))
    match = re.search(r"前\s*(\d+)", question)
    if match:
        return int(match.group(1))
    return None


def _share_label(ctx: QueryPlanContext) -> str:
    return f"{ctx.metric}占比" if ctx.metric else "占比"


def _format_share(value: float | None) -> str | None:
    if value is None:
        return None
    return f"{value:.2%}"

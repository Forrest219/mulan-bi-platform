"""TopN/BottomN ranking operator."""

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


class RankingOperator(BaseSemanticOperator):
    name = "ranking"
    version = "0.1.0"
    output_shape = "ranked_table"

    def match(self, ctx: QueryPlanContext) -> float:
        q = compact(ctx.question)
        if ctx.operator_hint in {self.name, "top_n", "bottom_n"}:
            return 1.0
        if any(word in q for word in ("top", "前", "最高", "最大", "最低", "最差", "bottom")):
            return 0.88 if ctx.metric and ctx.dimensions else 0.6
        return 0.0

    def build_steps(self, ctx: QueryPlanContext) -> list[QueryPlanStep]:
        dimension = first_dimension(ctx)
        n = min(int(ctx.params.get("n") or _extract_n(ctx.question) or 10), 100)
        direction = _sort_direction(ctx)
        metric = metric_agg(ctx)
        metric["sortDirection"] = direction
        metric["sortPriority"] = 1
        include_share = ctx.params.get("include_share", ctx.params.get("share", True))
        steps = [
            QueryPlanStep(
                name="ranked_groups",
                vizql_json={
                    "fields": [{"fieldCaption": dimension}, metric],
                    "filters": ctx.filters,
                },
                result_shape="ranked_table",
                max_fetch_rows=n,
                max_visible_rows=n,
                explain={"dimension": dimension, "metric": ctx.metric, "n": n, "sort_direction": direction},
            )
        ]
        if include_share:
            steps.append(
                QueryPlanStep(
                    name="total_metric",
                    vizql_json={"fields": [metric_agg(ctx)], "filters": ctx.filters},
                    result_shape="scalar",
                    max_fetch_rows=1,
                    max_visible_rows=1,
                    explain={"metric": ctx.metric, "denominator": "same filters, no group dimension"},
                )
            )
        return steps

    def reduce(self, ctx: QueryPlanContext, step_results: dict[str, dict[str, Any]]) -> OperatorResult:
        fields, rows = normalize_result_table(step_results["ranked_groups"])
        n = min(int(ctx.params.get("n") or _extract_n(ctx.question) or 10), 100)
        direction = _sort_direction(ctx)
        names = [field_name(field) for field in fields]
        total = _first_numeric(normalize_result_table(step_results.get("total_metric") or {})[1])
        output_rows = [list(row) for row in rows[:n]]
        if total is not None:
            metric_idx = _metric_index(names, ctx.metric)
            for row in output_rows:
                value = numeric_value(row[metric_idx]) if len(row) > metric_idx else None
                row.append(_format_share(value / total) if total and value is not None else None)
        output_fields = [*names, *([_share_label(ctx)] if total is not None else [])]
        return OperatorResult(
            fields=output_fields,
            rows=output_rows,
            summary=f"ranking n={n}; sort_direction={direction}; pushed_down=true",
            intent="bottom_n" if direction == "ASC" else "top_n",
            confidence=0.94,
            result_shape="ranked_table",
            table_display=infer_table_display_schema(
                output_fields,
                output_rows,
                operator=self.name,
                metric_names=[ctx.metric] if ctx.metric else None,
            ),
            explain={"operator": self.name, "step": "ranked_groups", "n": n, "sort_direction": direction},
            diagnostics={"input_rows": len(rows), "denominator": total},
        )


def _sort_direction(ctx: QueryPlanContext) -> str:
    direction = str(ctx.params.get("sort_direction") or "").upper()
    if direction in {"ASC", "DESC"}:
        return direction
    q = compact(ctx.question)
    if any(word in q for word in ("最低", "最少", "最差", "bottom", "后")):
        return "ASC"
    return "DESC"


def _extract_n(question: str) -> int | None:
    import re

    match = re.search(r"(?:top|TOP|Top|bottom|Bottom|BOTTOM)\s*(\d+)", question)
    if match:
        return int(match.group(1))
    match = re.search(r"(?:前|后|最低|最高|最差|最大|最少)\s*(\d+)", question)
    if match:
        return int(match.group(1))
    return None


def _metric_index(names: list[str], metric: str | None) -> int:
    if metric:
        metric_compact = compact(metric)
        for index, name in enumerate(names):
            if metric_compact in compact(name):
                return index
    return len(names) - 1


def _first_numeric(rows: list[list[Any]]) -> float | None:
    from services.data_agent.query_plan import numeric_value

    for row in rows:
        for value in row:
            number = numeric_value(value)
            if number is not None:
                return number
    return None


def _share_label(ctx: QueryPlanContext) -> str:
    return f"{ctx.metric}占比" if ctx.metric else "占比"


def _format_share(value: float | None) -> str | None:
    if value is None:
        return None
    return f"{value:.2%}"

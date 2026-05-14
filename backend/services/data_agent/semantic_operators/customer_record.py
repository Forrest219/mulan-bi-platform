"""Customer/entity record operator for period-level cooperation history."""

from __future__ import annotations

from typing import Any

from services.data_agent.query_plan import (
    OperatorResult,
    QueryPlanContext,
    QueryPlanStep,
    build_field,
    compact,
    field_name,
    first_time_field,
    normalize_result_table,
    numeric_value,
)
from services.data_agent.semantic_operators.base import BaseSemanticOperator


class CustomerRecordOperator(BaseSemanticOperator):
    name = "customer_record"
    version = "0.1.0"
    output_shape = "time_series"

    def match(self, ctx: QueryPlanContext) -> float:
        q = compact(ctx.question)
        if ctx.operator_hint == self.name:
            return 1.0
        if any(word in q for word in ("合作", "记录", "最近", "还有")):
            return 0.88 if _entity_field(ctx) and _entity_values(ctx) and ctx.time_field else 0.55
        return 0.0

    def build_steps(self, ctx: QueryPlanContext) -> list[QueryPlanStep]:
        entity_field = _entity_field(ctx)
        entity_values = _entity_values(ctx)
        if not entity_field or not entity_values:
            raise ValueError("customer_record requires entity_field and entity_value")

        time_field = first_time_field(ctx)
        period_function = str(ctx.params.get("period_function") or ctx.params.get("grain") or "YEAR").upper()
        metrics = _metric_fields(ctx)
        if not metrics:
            raise ValueError("customer_record requires at least one metric")

        filters = list(ctx.filters) + [_entity_filter(entity_field, entity_values)]
        return [
            QueryPlanStep(
                name="entity_period_metrics",
                vizql_json={
                    "fields": [build_field(time_field, period_function), *metrics],
                    "filters": filters,
                },
                result_shape="time_series",
                max_fetch_rows=min(int(ctx.params.get("max_periods") or 100), 500),
                max_visible_rows=100,
                explain={
                    "entity_field": entity_field,
                    "entity_values": entity_values,
                    "time_field": time_field,
                    "period_function": period_function,
                    "metrics": [field["fieldCaption"] for field in metrics],
                },
            )
        ]

    def reduce(self, ctx: QueryPlanContext, step_results: dict[str, dict[str, Any]]) -> OperatorResult:
        fields, rows = normalize_result_table(step_results["entity_period_metrics"])
        names = [field_name(field) for field in fields]
        period_idx = _period_index(names)
        metric_indices = [idx for idx in range(len(names)) if idx != period_idx]
        if period_idx is None or not metric_indices:
            return OperatorResult(
                fields=["period"],
                rows=[],
                summary="customer_record could not infer period/metric columns",
                intent=self.name,
                confidence=0.4,
                result_shape="time_series",
                diagnostics={"fields": names},
            )

        annual_records: list[list[Any]] = []
        for row in rows:
            if len(row) <= period_idx:
                continue
            record = [row[period_idx]]
            for metric_idx in metric_indices:
                record.append(numeric_value(row[metric_idx]) if len(row) > metric_idx else None)
            annual_records.append(record)

        annual_records.sort(key=lambda row: row[0])
        active_records = [row for row in annual_records if any(_is_active_metric(value) for value in row[1:])]
        last_record = active_records[-1] if active_records else (annual_records[-1] if annual_records else None)
        last_period = last_record[0] if last_record else None
        metric_names = [names[idx] for idx in metric_indices]

        return OperatorResult(
            fields=["period", *metric_names],
            rows=annual_records[:100],
            summary=f"customer_record periods={len(annual_records)}; last_period={last_period}",
            intent=self.name,
            confidence=0.93 if annual_records else 0.55,
            result_shape="time_series",
            explain={
                "operator": self.name,
                "entity_field": _entity_field(ctx),
                "entity_values": _entity_values(ctx),
                "last_record_period": last_period,
                "record_count": len(annual_records),
            },
            diagnostics={
                "input_rows": len(rows),
                "active_record_count": len(active_records),
                "last_record": last_record,
            },
        )


def _entity_field(ctx: QueryPlanContext) -> str | None:
    value = ctx.params.get("entity_field") or ctx.params.get("target_dimension")
    if value:
        return str(value).strip()
    return ctx.dimensions[0] if ctx.dimensions else None


def _entity_values(ctx: QueryPlanContext) -> list[Any]:
    value = ctx.params.get("entity_value", ctx.params.get("entity_values"))
    if value is None:
        return []
    if isinstance(value, list):
        return [item for item in value if item not in (None, "")]
    return [value]


def _metric_fields(ctx: QueryPlanContext) -> list[dict[str, Any]]:
    raw_metrics = ctx.params.get("metrics") or ([ctx.metric] if ctx.metric else [])
    fields: list[dict[str, Any]] = []
    for metric in raw_metrics:
        if isinstance(metric, dict):
            caption = str(metric.get("fieldCaption") or metric.get("field") or "").strip()
            if not caption:
                continue
            fields.append(
                build_field(
                    caption,
                    str(metric.get("function") or metric.get("aggregation") or "SUM").upper(),
                    fieldAlias=metric.get("fieldAlias"),
                )
            )
        elif metric:
            fields.append(build_field(str(metric).strip(), "SUM"))
    return fields


def _entity_filter(entity_field: str, entity_values: list[Any]) -> dict[str, Any]:
    return {
        "field": {"fieldCaption": entity_field},
        "filterType": "SET",
        "values": entity_values,
    }


def _period_index(names: list[str]) -> int | None:
    for index, name in enumerate(names):
        if any(token in name for token in ("YEAR", "QUARTER", "MONTH", "WEEK", "DAY", "年", "月", "季度")):
            return index
    return 0 if names else None


def _is_active_metric(value: Any) -> bool:
    number = numeric_value(value)
    return number is not None and number != 0

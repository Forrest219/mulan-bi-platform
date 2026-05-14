"""Pushdown guardrail for controlled Data Agent query execution."""

from __future__ import annotations

from typing import Any

from services.data_agent.query_plan import (
    ANALYSIS_INTENTS,
    QueryExecutionPolicy,
    QueryPlanContext,
    QueryPlanStep,
    has_aggregate_field,
    has_time_bucket_field,
    make_pushdown_fallback,
    normalize_result_table,
    sorted_field,
    PushdownGuardrailError,
)


class PushdownGuardrail:
    """Validates that analysis queries are pushed down and bounded.

    Intended wiring:
    - call validate_plan(step, ctx) before execute_query()
    - pass step.mcp_limit() as Tableau MCP limit
    - call validate_result(step, result, ctx=ctx) before emitting rows/history
    """

    def __init__(self, policy: QueryExecutionPolicy | None = None):
        self.policy = policy or QueryExecutionPolicy()

    def validate_plan(self, step: QueryPlanStep, ctx: QueryPlanContext) -> None:
        if step.max_visible_rows > self.policy.max_visible_rows and not step.internal_only:
            raise PushdownGuardrailError(
                make_pushdown_fallback(
                    code="PUSHDOWN_RESULT_TOO_WIDE",
                    message="分析结果展示行数超过 100 行预算",
                    ctx=ctx,
                    fallback_type="too_wide",
                    detail={"step": step.name, "max_visible_rows": step.max_visible_rows},
                )
            )

        if ctx.intent in ANALYSIS_INTENTS and step.result_shape == "detail_table" and not self.policy.allow_detail_scan:
            raise PushdownGuardrailError(
                make_pushdown_fallback(
                    code="PUSHDOWN_UNSAFE_DETAIL_SCAN",
                    message="分析类问题禁止执行明细扫描",
                    ctx=ctx,
                    detail={"step": step.name, "shape": step.result_shape},
                )
            )

        if step.result_shape == "key_set":
            if not step.allow_key_set:
                raise PushdownGuardrailError(
                    make_pushdown_fallback(
                        code="PUSHDOWN_UNSAFE_DETAIL_SCAN",
                        message="key-set 查询必须显式声明 allow_key_set",
                        ctx=ctx,
                        detail={"step": step.name},
                    )
                )
            self._validate_key_set_step(step, ctx)
            return

        if step.result_shape in {"aggregate_table", "ranked_table", "time_series", "scalar", "operator_summary"}:
            if not has_aggregate_field(step.vizql_json):
                raise PushdownGuardrailError(
                    make_pushdown_fallback(
                        code="PUSHDOWN_REQUIRED",
                        message="分析类查询必须包含聚合字段",
                        ctx=ctx,
                        detail={"step": step.name, "vizql_json": step.vizql_json},
                    )
                )

        if step.result_shape == "ranked_table":
            sort = sorted_field(step.vizql_json)
            if not sort:
                raise PushdownGuardrailError(
                    make_pushdown_fallback(
                        code="PUSHDOWN_REQUIRED",
                        message="TopN/BottomN 必须把排序字段下推到 VizQL",
                        ctx=ctx,
                        detail={"step": step.name},
                    )
                )
            if step.mcp_limit() > self.policy.max_visible_rows + 1:
                raise PushdownGuardrailError(
                    make_pushdown_fallback(
                        code="PUSHDOWN_RESULT_TOO_WIDE",
                        message="TopN/BottomN 的查询 limit 超过展示预算",
                        ctx=ctx,
                        fallback_type="too_wide",
                        detail={"step": step.name, "limit": step.mcp_limit()},
                    )
                )

        if step.result_shape == "time_series" and not has_time_bucket_field(step.vizql_json):
            raise PushdownGuardrailError(
                make_pushdown_fallback(
                    code="PUSHDOWN_REQUIRED",
                    message="趋势/全周期条件查询必须包含时间桶字段",
                    ctx=ctx,
                    detail={"step": step.name, "vizql_json": step.vizql_json},
                )
            )

    def validate_result(
        self,
        step: QueryPlanStep,
        result: dict[str, Any],
        *,
        ctx: QueryPlanContext | None = None,
        before_emit: bool = False,
    ) -> None:
        _fields, rows = normalize_result_table(result)
        row_count = len(rows)

        if step.result_shape == "key_set" and step.internal_only:
            if row_count > self.policy.max_key_rows:
                raise PushdownGuardrailError(
                    make_pushdown_fallback(
                        code="PUSHDOWN_RESULT_TOO_WIDE",
                        message="内部 key-set 查询超过基数上限",
                        ctx=ctx,
                        fallback_type="too_wide",
                        detail={"step": step.name, "row_count": row_count, "max_key_rows": self.policy.max_key_rows},
                    )
                )
            return

        if row_count > step.max_visible_rows:
            raise PushdownGuardrailError(
                make_pushdown_fallback(
                    code="PUSHDOWN_RESULT_TOO_WIDE",
                    message="查询返回超过 100 行，不能交给 LLM 或 UI 截断后继续回答",
                    ctx=ctx,
                    fallback_type="too_wide",
                    detail={
                        "step": step.name,
                        "row_count": row_count,
                        "max_visible_rows": step.max_visible_rows,
                        "before_emit": before_emit,
                    },
                )
            )

    def fallback_tool_data(self, error: PushdownGuardrailError) -> dict[str, Any]:
        fallback = error.fallback.to_dict()
        return {
            "fields": [],
            "rows": [],
            "intent": "pushdown_fallback",
            "confidence": 1.0,
            "fallback": fallback,
            "error_code": fallback["error_code"],
            "fallback_type": fallback["fallback_type"],
            "explain": {"pushdown_guardrail": fallback},
        }

    def _validate_key_set_step(self, step: QueryPlanStep, ctx: QueryPlanContext) -> None:
        fields = step.vizql_json.get("fields") or []
        if len(fields) != 1:
            raise PushdownGuardrailError(
                make_pushdown_fallback(
                    code="PUSHDOWN_UNSAFE_DETAIL_SCAN",
                    message="key-set 查询只能返回一个实体 key 字段",
                    ctx=ctx,
                    detail={"step": step.name, "fields": fields},
                )
            )
        if step.max_fetch_rows > self.policy.max_key_rows:
            raise PushdownGuardrailError(
                make_pushdown_fallback(
                    code="PUSHDOWN_RESULT_TOO_WIDE",
                    message="key-set 查询 fetch rows 超过内部上限",
                    ctx=ctx,
                    fallback_type="too_wide",
                    detail={"step": step.name, "max_fetch_rows": step.max_fetch_rows},
                )
            )

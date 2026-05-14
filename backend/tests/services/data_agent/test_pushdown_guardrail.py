import pytest

from services.data_agent.pushdown_guardrail import PushdownGuardrail
from services.data_agent.query_plan import (
    PushdownGuardrailError,
    QueryPlanContext,
    QueryPlanStep,
)


@pytest.fixture
def ctx():
    return QueryPlanContext(
        question="各省份销售额是多少？",
        datasource_luid="ds1",
        datasource_name="订单",
        connection_id=1,
        fields=["省/自治区", "销售额", "订单日期"],
        intent="analysis",
        metric="销售额",
        dimensions=["省/自治区"],
        time_field="订单日期",
        trace_id="trace-1",
    )


def test_validate_plan_accepts_aggregate_vizql(ctx):
    guardrail = PushdownGuardrail()
    step = QueryPlanStep(
        name="aggregate_by_province",
        vizql_json={
            "fields": [
                {"fieldCaption": "省/自治区"},
                {"fieldCaption": "销售额", "function": "SUM"},
            ],
            "filters": [],
        },
        result_shape="aggregate_table",
    )

    guardrail.validate_plan(step, ctx)


def test_validate_plan_rejects_analysis_dimension_only_detail_like_vizql(ctx):
    guardrail = PushdownGuardrail()
    step = QueryPlanStep(
        name="dimension_only",
        vizql_json={"fields": [{"fieldCaption": "省/自治区"}], "filters": []},
        result_shape="aggregate_table",
    )

    with pytest.raises(PushdownGuardrailError) as exc:
        guardrail.validate_plan(step, ctx)

    assert exc.value.fallback.error_code == "PUSHDOWN_REQUIRED"


def test_validate_plan_rejects_detail_scan_for_analysis(ctx):
    guardrail = PushdownGuardrail()
    step = QueryPlanStep(
        name="raw_rows",
        vizql_json={
            "fields": [
                {"fieldCaption": "订单ID"},
                {"fieldCaption": "客户名称"},
                {"fieldCaption": "销售额"},
            ],
            "filters": [],
        },
        result_shape="detail_table",
    )

    with pytest.raises(PushdownGuardrailError) as exc:
        guardrail.validate_plan(step, ctx)

    assert exc.value.fallback.error_code == "PUSHDOWN_UNSAFE_DETAIL_SCAN"


def test_validate_plan_requires_sort_for_ranking(ctx):
    guardrail = PushdownGuardrail()
    step = QueryPlanStep(
        name="top_customers",
        vizql_json={
            "fields": [
                {"fieldCaption": "客户名称"},
                {"fieldCaption": "销售额", "function": "SUM"},
            ],
            "filters": [],
        },
        result_shape="ranked_table",
    )

    with pytest.raises(PushdownGuardrailError) as exc:
        guardrail.validate_plan(step, ctx)

    assert exc.value.fallback.error_code == "PUSHDOWN_REQUIRED"


def test_validate_plan_accepts_key_set_when_explicitly_internal(ctx):
    guardrail = PushdownGuardrail()
    step = QueryPlanStep(
        name="base_keys",
        vizql_json={"fields": [{"fieldCaption": "客户ID"}], "filters": []},
        result_shape="key_set",
        allow_key_set=True,
        internal_only=True,
        max_fetch_rows=5000,
    )

    guardrail.validate_plan(step, ctx)


def test_validate_result_rejects_101_row_sentinel(ctx):
    guardrail = PushdownGuardrail()
    step = QueryPlanStep(
        name="aggregate_by_province",
        vizql_json={
            "fields": [
                {"fieldCaption": "省/自治区"},
                {"fieldCaption": "销售额", "function": "SUM"},
            ],
        },
        result_shape="aggregate_table",
        max_visible_rows=100,
    )
    result = {"fields": ["省/自治区", "SUM(销售额)"], "rows": [[f"P{i}", i] for i in range(101)]}

    with pytest.raises(PushdownGuardrailError) as exc:
        guardrail.validate_result(step, result, ctx=ctx, before_emit=True)

    assert exc.value.fallback.error_code == "PUSHDOWN_RESULT_TOO_WIDE"
    assert exc.value.fallback.detail["row_count"] == 101


def test_validate_result_allows_internal_key_set_under_cap(ctx):
    guardrail = PushdownGuardrail()
    step = QueryPlanStep(
        name="base_keys",
        vizql_json={"fields": [{"fieldCaption": "客户ID"}]},
        result_shape="key_set",
        allow_key_set=True,
        internal_only=True,
        max_fetch_rows=5000,
    )
    result = {"fields": ["客户ID"], "rows": [[f"C{i}"] for i in range(120)]}

    guardrail.validate_result(step, result, ctx=ctx)

import pytest

from services.data_agent.result_guardrail import (
    DETAIL_SCAN_BLOCKED,
    RESULT_FIELD_MISSING,
    ResultGuardrailInput,
    evaluate_result_guardrail,
)

pytestmark = pytest.mark.skip_db


def _payload(**kwargs):
    base = ResultGuardrailInput(
        question="top customers",
        chain_mode="mcp_host",
        fallback_triggered=False,
        fallback_reason=None,
        semantic_operator="aggregate",
        context_snapshot={},
        tool_name="query-datasource",
        safe_args={},
        result={"fields": ["Customer", "Sales"], "rows": [["a", 1]], "metadata": {}},
        thresholds={"max_detail_rows": 200},
    )
    for k, v in kwargs.items():
        setattr(base, k, v)
    return base


def test_detail_scan_blocks_when_rows_exceed_threshold():
    payload = _payload(result={"fields": ["Customer"], "rows": [[i] for i in range(201)], "metadata": {}})
    out = evaluate_result_guardrail(payload)
    assert out.decision == "block"
    assert out.semantic_status == "semantic_fail"
    assert out.error_code == DETAIL_SCAN_BLOCKED


def test_truncated_result_blocks_for_aggregate_question():
    payload = _payload(result={"fields": ["Customer"], "rows": [[1]], "metadata": {"truncated_by_guardrail": True}})
    out = evaluate_result_guardrail(payload)
    assert out.decision == "block"
    assert out.error_code == DETAIL_SCAN_BLOCKED


def test_trend_condition_blocks_detail_scan():
    payload = _payload(
        semantic_operator="trend_condition",
        result={"fields": ["Year", "Sales"], "rows": [[i, i] for i in range(201)], "metadata": {}},
    )
    out = evaluate_result_guardrail(payload)
    assert out.decision == "block"
    assert out.error_code == DETAIL_SCAN_BLOCKED


def test_missing_required_field_enters_semantic_fail_review():
    payload = _payload(thresholds={"max_detail_rows": 200, "required_fields": ["Profit"]})
    out = evaluate_result_guardrail(payload)
    assert out.decision == "review"
    assert out.semantic_status == "semantic_fail"
    assert out.error_code == RESULT_FIELD_MISSING


def test_fallback_defaults_to_needs_review():
    payload = _payload(fallback_triggered=True, fallback_reason="queryspec_mcp_fallback")
    out = evaluate_result_guardrail(payload)
    assert out.decision == "review"
    assert out.semantic_status == "needs_review"
    assert out.error_code is None

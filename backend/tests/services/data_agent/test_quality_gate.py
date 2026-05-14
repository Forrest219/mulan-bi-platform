"""Draft tests for services.data_agent.quality_gate."""

import uuid

import pytest

from services.data_agent.analysis_context import AnalysisContext
from services.data_agent.quality_gate import evaluate_quality_gate, standard_gate_fallback


pytestmark = pytest.mark.skip_db


def _context(**overrides):
    query_plan = {
        "metrics": [{"name": "销售额", "field_caption": "销售额", "aggregation": "SUM"}],
        "dimensions": [{"name": "客户名称", "field_caption": "客户名称"}],
        "filters": [],
        "limit": 10,
        "order_by": [{"metric": "销售额", "direction": "desc"}],
    }
    query_plan.update(overrides.pop("query_plan", {}))
    return AnalysisContext.new(
        conversation_id=str(uuid.uuid4()),
        run_id=str(uuid.uuid4()),
        trace_id="t-gate",
        turn_no=1,
        scope={
            "tenant_id": None,
            "user_id": 7,
            "role": "analyst",
            "connection_id": overrides.pop("connection_id", 12),
            "connection_type": "tableau",
            "datasource_luid": "ds-luid",
            "datasource_name": "订单+ (示例 - 超市)",
        },
        analysis_type=overrides.pop("analysis_type", "ranking"),
        confidence=0.9,
        query_plan=query_plan,
    )


def test_quality_gate_passes_numeric_set_ranking_route_performance_checks():
    context = _context()
    result = evaluate_quality_gate(
        context=context,
        response_data={
            "fields": ["客户名称", "销售额"],
            "rows": [["客户A", 100.0], ["客户B", 90.0]],
        },
        baseline={
            "expected_plan": {"metrics": ["销售额"]},
            "result_shape": {"required_fields": ["客户名称", "销售额"], "max_rows": 10},
            "rows": [["客户A", 100.0], ["客户B", 90.0]],
            "tolerances": {"numeric_rel": 0.001, "row_set": "exact"},
        },
        execution_time_ms=1200,
        expected_connection_id=12,
    )

    assert result.gate_status == "pass"
    assert {check.check_type for check in result.checks} >= {"numeric", "set", "route", "performance"}


def test_quality_gate_blocks_missing_dimension_from_response():
    context = _context()
    result = evaluate_quality_gate(
        context=context,
        response_data={"fields": ["销售额"], "rows": [[100.0]]},
        expected_connection_id=12,
    )

    assert result.gate_status == "block"
    assert any(blocker["code"] == "no_unrequested_dimension_drop" for blocker in result.blockers)


def test_quality_gate_blocks_more_than_100_visible_rows():
    context = _context(query_plan={"limit": None})
    result = evaluate_quality_gate(
        context=context,
        response_data={"fields": ["客户名称", "销售额"], "rows": [[f"客户{i}", i] for i in range(101)]},
        expected_connection_id=12,
    )

    assert result.gate_status == "block"
    assert any(blocker["code"] == "max_visible_rows" for blocker in result.blockers)


def test_quality_gate_blocks_wrong_connection_route():
    context = _context(connection_id=99)
    result = evaluate_quality_gate(
        context=context,
        response_data={"fields": ["客户名称", "销售额"], "rows": [["客户A", 100.0]]},
        expected_connection_id=12,
    )

    assert result.gate_status == "block"
    assert any(blocker["code"] == "target_connection" for blocker in result.blockers)


def test_quality_gate_blocks_baseline_numeric_mismatch():
    context = _context()
    result = evaluate_quality_gate(
        context=context,
        response_data={"fields": ["客户名称", "销售额"], "rows": [["客户A", 80.0]]},
        baseline={
            "result_shape": {"required_fields": ["客户名称", "销售额"], "max_rows": 10},
            "rows": [["客户A", 100.0]],
            "tolerances": {"numeric_rel": 0.001, "row_set": "exact"},
        },
        expected_connection_id=12,
    )

    assert result.gate_status == "block"
    assert any(blocker["code"] in {"baseline_row_set", "baseline_numeric_tolerance"} for blocker in result.blockers)


def test_standard_gate_fallback_is_structured():
    context = _context()
    result = evaluate_quality_gate(
        context=context,
        response_data={"fields": ["销售额"], "rows": [[100.0]]},
        expected_connection_id=12,
    )

    fallback = standard_gate_fallback(result, trace_id="t-gate")

    assert fallback["fallback_type"] == "quality_gate_blocked"
    assert fallback["trace_id"] == "t-gate"
    assert fallback["quality_gate"]["gate_status"] == "block"

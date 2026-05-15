"""Draft tests for services.data_agent.quality_gate."""

import json
import uuid

import pytest

from services.data_agent.analysis_context import AnalysisContext
from services.data_agent.mcp_baseline_comparator import load_snapshot
from services.data_agent.quality_gate import (
    DEFAULT_CASES_PATH,
    DEFAULT_SNAPSHOT_PATH,
    build_canary_quality_report,
    evaluate_quality_gate,
    standard_gate_fallback,
)


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


def _guardrail_event():
    return {
        "type": "tool_result",
        "tool": "mcp_args_guardrail",
        "result": {"event": "MCP_ARGS_GUARDRAIL_PASS"},
    }


def _tableau_event():
    return {"type": "tool_result", "tool": "tableau_mcp", "result": {"success": True}}


def _snapshot_response_data(snapshot_case):
    if "tables" in snapshot_case:
        return {"tables": snapshot_case["tables"]}
    return {"fields": snapshot_case["fields"], "rows": snapshot_case["rows"]}


def _run_artifact(response_data):
    artifact = {
        "events": [_guardrail_event(), _tableau_event()],
        "done": {
            "response_type": "table",
            "tools_used": ["tableau_mcp"],
            "queryspec_metrics": {
                "queryspec_main_path_success": True,
                "queryspec_fallback_triggered": False,
            },
            "response_data": response_data,
        },
    }
    if "fields" in response_data and "rows" in response_data:
        artifact["table_data"] = {"fields": response_data["fields"], "rows": response_data["rows"]}
    return artifact


def test_canary_quality_report_passes_compliant_first_cases(tmp_path):
    snapshot = load_snapshot(DEFAULT_SNAPSHOT_PATH)
    runs = {
        "mulan": {
            "Q1": _run_artifact(_snapshot_response_data(snapshot["cases"]["batch2.q1_overall_kpis"])),
            "Q6": _run_artifact(_snapshot_response_data(snapshot["cases"]["batch2.q6_top10_customers"])),
            "Q10": _run_artifact(_snapshot_response_data(snapshot["cases"]["batch2.q10_loss_root_cause_liaoning_fujian_2024"])),
        }
    }
    runs_path = tmp_path / "runs.json"
    report_path = tmp_path / "report.json"
    runs_path.write_text(json.dumps(runs, ensure_ascii=False), encoding="utf-8")

    report = build_canary_quality_report(
        runs_path=runs_path,
        cases_path=DEFAULT_CASES_PATH,
        snapshot_path=DEFAULT_SNAPSHOT_PATH,
        report_path=report_path,
    )

    assert report["status"] == "pass"
    assert report_path.exists()
    assert report["metrics"]["queryspec_main_path_success_rate"] == 1


def test_canary_quality_report_fails_ui_table_mismatch(tmp_path):
    snapshot = load_snapshot(DEFAULT_SNAPSHOT_PATH)
    response_data = _snapshot_response_data(snapshot["cases"]["batch2.q1_overall_kpis"])
    artifact = _run_artifact(response_data)
    artifact["table_data"] = {"fields": response_data["fields"], "rows": [[0, 0, 0, 0, 0]]}
    runs_path = tmp_path / "runs.json"
    runs_path.write_text(json.dumps({"mulan": {"Q1": artifact}}, ensure_ascii=False), encoding="utf-8")

    report = build_canary_quality_report(
        runs_path=runs_path,
        cases_path=DEFAULT_CASES_PATH,
        snapshot_path=DEFAULT_SNAPSHOT_PATH,
        case_ids=["batch2.q1_overall_kpis"],
    )

    assert report["status"] == "block"
    assert report["cases"][0]["failure_layer"] == "ui_table_mismatch"

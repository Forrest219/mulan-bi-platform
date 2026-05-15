"""Tests for MCP snapshot baseline comparator."""

import uuid
from pathlib import Path

import pytest

from services.data_agent.analysis_context import AnalysisContext
from services.data_agent.mcp_baseline_comparator import (
    FAILURE_CONTRACT,
    FAILURE_GUARDRAIL,
    FAILURE_MCP_FAILURE,
    FAILURE_NO_MCP,
    FAILURE_NUMERIC,
    FAILURE_ORDER,
    FAILURE_ROW_COUNT,
    FAILURE_FIELD,
    FAILURE_SILENT_FALLBACK,
    BaselineCase,
    compare_case_to_run_artifact,
    compare_case_to_snapshot,
    load_cases,
    load_snapshot,
)


pytestmark = pytest.mark.skip_db


FIXTURE_DIR = Path(__file__).parents[2] / "fixtures" / "data_agent" / "baseline"
SNAPSHOT_PATH = FIXTURE_DIR / "mcp_snapshots" / "superstore_2026_05_13.json"


def _context_for_case(case: BaselineCase) -> AnalysisContext:
    expected_plan = case.baseline.get("expected_plan") or {}
    return AnalysisContext.new(
        conversation_id=str(uuid.uuid4()),
        run_id=str(uuid.uuid4()),
        trace_id="t-baseline",
        turn_no=1,
        scope={
            "user_id": 7,
            "role": "analyst",
            "connection_id": 12,
            "connection_type": "tableau",
            "datasource_luid": "ds-luid",
        },
        query_plan={
            "metrics": [{"name": item, "field_caption": item} for item in expected_plan.get("metrics") or ["value"]],
            "dimensions": [{"name": item, "field_caption": item} for item in expected_plan.get("dimensions") or []],
        },
    )


def _generic_case() -> BaselineCase:
    return BaselineCase.from_dict({
        "id": "batch2.generic",
        "group": "batch2",
        "question": "generic comparator case",
        "connection_fixture": "generic",
        "expected_patch": {},
        "baseline": {
            "result_shape": {
                "required_fields": ["dim", "value", "share"],
                "row_count": 2,
                "max_rows": 2,
            },
            "tolerances": {"numeric_rel": 0.001, "row_set": "exact"},
            "identity_fields": ["dim"],
            "numeric_fields": ["value", "share"],
            "order": {
                "field": "value",
                "direction": "desc",
                "top_n": 2,
                "identity_fields": ["dim"],
            },
            "derived_metrics": {"required_fields": ["share"]},
        },
    })


def _generic_snapshot() -> dict:
    return {
        "snapshot_id": "generic_snapshot",
        "cases": {
            "batch2.generic": {
                "fields": ["dim", "value", "share"],
                "rows": [["a", 100.0, "60%"], ["b", 50.0, "40%"]],
                "result_shape": {
                    "required_fields": ["dim", "value", "share"],
                    "row_count": 2,
                    "max_rows": 2,
                },
                "tolerances": {"numeric_rel": 0.001, "row_set": "exact"},
                "identity_fields": ["dim"],
                "numeric_fields": ["value", "share"],
                "order": {
                    "field": "value",
                    "direction": "desc",
                    "top_n": 2,
                    "identity_fields": ["dim"],
                },
                "derived_metrics": {"required_fields": ["share"]},
            }
        },
    }


def _guardrail_event() -> dict:
    return {
        "type": "tool_result",
        "tool": "mcp_args_guardrail",
        "result": {"event": "MCP_ARGS_GUARDRAIL_PASS"},
    }


def test_reviewed_q1_q6_q10_snapshots_pass_self_check():
    cases = {case.id: case for case in load_cases(FIXTURE_DIR / "batch2_cases.yaml")}
    snapshot = load_snapshot(SNAPSHOT_PATH)

    for case_id in [
        "batch2.q1_overall_kpis",
        "batch2.q2_followup_metric_trend",
        "batch2.q4_continue_split_each_year",
        "batch2.q5_subcategories_without_sales_2025",
        "batch2.q6_top10_customers",
        "batch2.q7_customer_dengbao_history",
        "batch2.q8_subcategory_profit_continuous_growth",
        "batch2.q9_provinces_always_loss",
        "batch2.q10_loss_root_cause_liaoning_fujian_2024",
    ]:
        case = cases[case_id]
        snapshot_case = snapshot["cases"][case_id]
        response_data = (
            {"tables": snapshot_case["tables"]}
            if "tables" in snapshot_case
            else {"fields": snapshot_case["fields"], "rows": snapshot_case["rows"]}
        )

        comparison = compare_case_to_snapshot(
            case=case,
            context=_context_for_case(case),
            response_data=response_data,
            snapshot=snapshot,
        )

        assert comparison.status == "pass", comparison.to_report_item()
        assert comparison.failure_layer == "pass"


def test_comparator_detects_field_row_order_and_numeric_mismatches():
    case = _generic_case()
    snapshot = _generic_snapshot()
    context = _context_for_case(case)

    field_result = compare_case_to_snapshot(
        case=case,
        context=context,
        response_data={"fields": ["dim", "value"], "rows": [["a", 100.0], ["b", 50.0]]},
        snapshot=snapshot,
    )
    assert field_result.failure_layer == FAILURE_FIELD
    assert any(check.name == "baseline_required_fields" for check in field_result.checks)

    row_result = compare_case_to_snapshot(
        case=case,
        context=context,
        response_data={"fields": ["dim", "value", "share"], "rows": [["a", 100.0, "60%"]]},
        snapshot=snapshot,
    )
    assert row_result.failure_layer == FAILURE_ROW_COUNT
    assert any(check.name == "baseline_row_count" for check in row_result.checks)

    order_result = compare_case_to_snapshot(
        case=case,
        context=context,
        response_data={"fields": ["dim", "value", "share"], "rows": [["b", 50.0, "40%"], ["a", 100.0, "60%"]]},
        snapshot=snapshot,
    )
    assert order_result.failure_layer == FAILURE_ORDER
    assert any(check.name == "baseline_topn_order" for check in order_result.checks)

    numeric_result = compare_case_to_snapshot(
        case=case,
        context=context,
        response_data={"fields": ["dim", "value", "share"], "rows": [["a", 80.0, "60%"], ["b", 50.0, "40%"]]},
        snapshot=snapshot,
    )
    assert numeric_result.failure_layer == FAILURE_NUMERIC
    assert any(check.name == "baseline_numeric_tolerance" for check in numeric_result.checks)


def test_run_artifact_failure_layers_are_classified():
    case = _generic_case()
    snapshot = _generic_snapshot()
    context = _context_for_case(case)

    no_mcp = compare_case_to_run_artifact(
        case=case,
        context=context,
        run_artifact={"events": []},
        snapshot=snapshot,
    )
    assert no_mcp.failure_layer == FAILURE_NO_MCP

    mcp_failure = compare_case_to_run_artifact(
        case=case,
        context=context,
        run_artifact={"events": [{"tool": "tableau_mcp"}], "error": {"message": "failed"}},
        snapshot=snapshot,
    )
    assert mcp_failure.failure_layer == FAILURE_MCP_FAILURE

    contract_failure = compare_case_to_run_artifact(
        case=case,
        context=context,
        run_artifact={"done": {"response_type": "text", "tools_used": ["tableau_mcp"]}},
        snapshot=snapshot,
    )
    assert contract_failure.failure_layer == FAILURE_CONTRACT

    numeric_mismatch = compare_case_to_run_artifact(
        case=case,
        context=context,
        run_artifact={
            "events": [_guardrail_event()],
            "done": {
                "response_type": "table",
                "tools_used": ["tableau_mcp"],
                "response_data": {
                    "fields": ["dim", "value", "share"],
                    "rows": [["a", 80.0, "60%"], ["b", 50.0, "40%"]],
                },
            }
        },
        snapshot=snapshot,
    )
    assert numeric_mismatch.failure_layer == FAILURE_NUMERIC

    missing_guardrail = compare_case_to_run_artifact(
        case=case,
        context=context,
        run_artifact={
            "done": {
                "response_type": "table",
                "tools_used": ["tableau_mcp"],
                "response_data": {
                    "fields": ["dim", "value", "share"],
                    "rows": [["a", 100.0, "60%"], ["b", 50.0, "40%"]],
                },
            }
        },
        snapshot=snapshot,
    )
    assert missing_guardrail.failure_layer == FAILURE_GUARDRAIL

    silent_fallback = compare_case_to_run_artifact(
        case=case,
        context=context,
        run_artifact={
            "events": [_guardrail_event()],
            "done": {
                "response_type": "table",
                "tools_used": ["tableau_mcp"],
                "response_data": {
                    "fields": ["dim", "value", "share"],
                    "rows": [["a", 100.0, "60%"], ["b", 50.0, "40%"]],
                    "fallback_chain_mode": "queryspec_mcp_fallback",
                },
            }
        },
        snapshot=snapshot,
    )
    assert silent_fallback.failure_layer == FAILURE_SILENT_FALLBACK

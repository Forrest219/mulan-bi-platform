import pytest

from services.data_agent.tableau_mcp_telemetry import (
    FALLBACK_ALERT_BLOCKED,
    FALLBACK_ALERT_LEAKED,
    FALLBACK_ALERT_LEAKED_SUCCESS,
    FALLBACK_ALERT_NONE,
    FALLBACK_SEVERITY_ERROR,
    FALLBACK_SEVERITY_HIGH_PRIORITY_ERROR,
    FALLBACK_SEVERITY_NONE,
    FALLBACK_SEVERITY_WARNING,
    build_compiler_unsupported_planner_reason_payload,
    build_fallback_audit_payload,
    build_strict_trace_payload,
    classify_fallback_audit,
    response_looks_successful,
)

pytestmark = pytest.mark.skip_db


def test_strict_trace_payload_includes_required_fallback_audit_fields():
    payload = build_strict_trace_payload(
        actual_entry="mcp_proxy_main",
        fallback_attempted=True,
        fallback_blocked=True,
        fallback_target="schema_inventory",
        fallback_blocked_reason="known_tableau_mcp_scene",
    )

    trace = payload["trace"]
    assert trace["mainline_convergence_strict"] is True
    assert trace["expected_entry"] == "mcp_proxy_main"
    assert trace["actual_entry"] == "mcp_proxy_main"
    assert trace["fallback_attempted"] is True
    assert trace["fallback_blocked"] is True
    assert trace["fallback_target"] == "schema_inventory"
    assert trace["fallback_blocked_reason"] == "known_tableau_mcp_scene"
    assert trace["hidden_fallback_error"] is None


def test_fallback_blocked_is_warning_telemetry():
    payload = build_fallback_audit_payload(
        fallback_attempted=True,
        fallback_blocked=True,
        fallback_target="queryspec_fallback",
        fallback_blocked_reason="tableau_mcp_strict_chain",
    )

    audit = payload["fallback_audit"]
    assert audit["kind"] == FALLBACK_ALERT_BLOCKED
    assert audit["severity"] == FALLBACK_SEVERITY_WARNING
    assert audit["log_level"] == "warning"
    assert audit["telemetry_event"] == "tableau_mcp_fallback_blocked"
    assert audit["requires_blocking"] is False


def test_fallback_leak_is_error():
    payload = build_strict_trace_payload(
        actual_entry="schema_inventory",
        fallback_attempted=True,
        fallback_blocked=False,
        fallback_target="schema_inventory",
        hidden_fallback_error={"route": "schema_inventory", "reason": "legacy_answer"},
    )

    audit = classify_fallback_audit(payload)
    assert audit["kind"] == FALLBACK_ALERT_LEAKED
    assert audit["severity"] == FALLBACK_SEVERITY_ERROR
    assert audit["log_level"] == "error"
    assert audit["telemetry_event"] == "tableau_mcp_fallback_leaked"
    assert audit["requires_blocking"] is True
    assert audit["hidden_fallback_error"]["route"] == "schema_inventory"


def test_fallback_leak_returning_success_is_high_priority_error():
    payload = build_strict_trace_payload(
        actual_entry="mcp_first_main",
        fallback_attempted=True,
        fallback_blocked=False,
        fallback_target="mcp_first_main.py",
        hidden_fallback_error="legacy route returned success",
    )

    audit = classify_fallback_audit(payload, response_success=True)
    assert audit["kind"] == FALLBACK_ALERT_LEAKED_SUCCESS
    assert audit["severity"] == FALLBACK_SEVERITY_HIGH_PRIORITY_ERROR
    assert audit["log_level"] == "error"
    assert audit["telemetry_event"] == "tableau_mcp_fallback_leaked_success"
    assert audit["requires_blocking"] is True


def test_fallback_not_attempted_has_no_alert():
    audit = classify_fallback_audit(build_strict_trace_payload())

    assert audit["kind"] == FALLBACK_ALERT_NONE
    assert audit["severity"] == FALLBACK_SEVERITY_NONE
    assert audit["log_level"] == "info"
    assert audit["requires_blocking"] is False


def test_compiler_unsupported_reason_payload_explains_planner_handoff():
    payload = build_compiler_unsupported_planner_reason_payload(
        compiler_reason="requires_multi_step_analysis",
        planner_reason="planner_can_select_mcp_tool",
        compile_ms=12,
        detail={"pattern": "unsupported_complex_question", "field_count": 8},
    )

    assert payload["compiler"] == {
        "status": "unsupported",
        "reason": "requires_multi_step_analysis",
        "ms": 12,
    }
    assert payload["planner"]["status"] == "pending"
    assert payload["planner"]["entry"] == "tableau_mcp_llm_planner"
    assert payload["planner"]["reason"] == "planner_can_select_mcp_tool"
    assert payload["planner"]["handoff_reason"] == "requires_multi_step_analysis"
    assert payload["explainability"]["event"] == "compiler_unsupported_entered_planner"
    assert payload["explainability"]["reason"] == "requires_multi_step_analysis"
    assert payload["explainability"]["detail"]["pattern"] == "unsupported_complex_question"


def test_response_success_detector_supports_fallback_leaked_success_audit():
    assert response_looks_successful({"response_type": "query_result", "rows": []}) is True
    assert response_looks_successful({"fields": ["Sales"], "rows": [[1]]}) is True
    assert response_looks_successful({"structured_error": {"code": "MCP_FAILED"}}) is False

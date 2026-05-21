"""Telemetry helpers for the Tableau MCP controlled chain.

The helpers in this module are intentionally side-effect free.  Callers can
attach the returned payloads to run metadata, explainability events, or logs
without coupling the main chain to a tracing backend.
"""

from __future__ import annotations

from typing import Any, Mapping


TABLEAU_MCP_EXPECTED_ENTRY = "mcp_proxy_main"
TABLEAU_MCP_STRICT_TRACE_KEY = "mainline_convergence_strict"

FALLBACK_ALERT_NONE = "none"
FALLBACK_ALERT_BLOCKED = "blocked"
FALLBACK_ALERT_LEAKED = "leaked"
FALLBACK_ALERT_LEAKED_SUCCESS = "leaked_success"

FALLBACK_SEVERITY_NONE = "none"
FALLBACK_SEVERITY_WARNING = "warning"
FALLBACK_SEVERITY_ERROR = "error"
FALLBACK_SEVERITY_HIGH_PRIORITY_ERROR = "high_priority_error"

_SUCCESS_RESPONSE_TYPES = {
    "query_result",
    "asset_metadata",
    "asset_candidates",
    "text",
    "table",
    "number",
    "chart_spec",
}


def build_strict_trace_payload(
    *,
    actual_entry: str = TABLEAU_MCP_EXPECTED_ENTRY,
    expected_entry: str = TABLEAU_MCP_EXPECTED_ENTRY,
    fallback_attempted: bool = False,
    fallback_blocked: bool = False,
    fallback_target: str | None = None,
    fallback_blocked_reason: str | None = None,
    hidden_fallback_error: str | Mapping[str, Any] | None = None,
    extra_trace: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Return the mandatory strict trace payload for Tableau MCP runs."""

    trace: dict[str, Any] = {
        TABLEAU_MCP_STRICT_TRACE_KEY: True,
        "expected_entry": expected_entry,
        "actual_entry": actual_entry,
        "fallback_attempted": bool(fallback_attempted),
        "fallback_blocked": bool(fallback_blocked),
        "fallback_target": fallback_target,
        "fallback_blocked_reason": fallback_blocked_reason,
        "hidden_fallback_error": _json_safe_value(hidden_fallback_error),
    }
    if extra_trace:
        trace.update({str(key): _json_safe_value(value) for key, value in extra_trace.items()})
        trace[TABLEAU_MCP_STRICT_TRACE_KEY] = True
        trace["expected_entry"] = expected_entry
        trace["actual_entry"] = actual_entry
    return {"trace": trace}


def build_fallback_audit_payload(
    *,
    actual_entry: str = TABLEAU_MCP_EXPECTED_ENTRY,
    expected_entry: str = TABLEAU_MCP_EXPECTED_ENTRY,
    fallback_attempted: bool,
    fallback_blocked: bool,
    fallback_target: str | None,
    fallback_blocked_reason: str | None = None,
    hidden_fallback_error: str | Mapping[str, Any] | None = None,
    response_success: bool | None = None,
    extra_trace: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Return strict trace data plus the fallback audit classification."""

    payload = build_strict_trace_payload(
        actual_entry=actual_entry,
        expected_entry=expected_entry,
        fallback_attempted=fallback_attempted,
        fallback_blocked=fallback_blocked,
        fallback_target=fallback_target,
        fallback_blocked_reason=fallback_blocked_reason,
        hidden_fallback_error=hidden_fallback_error,
        extra_trace=extra_trace,
    )
    payload["fallback_audit"] = classify_fallback_audit(payload, response_success=response_success)
    return payload


def classify_fallback_audit(
    payload: Mapping[str, Any] | None = None,
    *,
    response_success: bool | None = None,
) -> dict[str, Any]:
    """Classify fallback state into the alert levels required by TDE-40/41."""

    trace = _trace_from_payload(payload)
    fallback_attempted = bool(trace.get("fallback_attempted"))
    fallback_blocked = bool(trace.get("fallback_blocked"))
    fallback_target = _optional_str(trace.get("fallback_target"))
    hidden_fallback_error = trace.get("hidden_fallback_error")

    leaked = fallback_attempted and not fallback_blocked
    leaked_success = leaked and bool(response_success)

    if leaked_success:
        return {
            "kind": FALLBACK_ALERT_LEAKED_SUCCESS,
            "severity": FALLBACK_SEVERITY_HIGH_PRIORITY_ERROR,
            "log_level": "error",
            "telemetry_event": "tableau_mcp_fallback_leaked_success",
            "requires_blocking": True,
            "fallback_target": fallback_target,
            "hidden_fallback_error": hidden_fallback_error,
        }
    if leaked:
        return {
            "kind": FALLBACK_ALERT_LEAKED,
            "severity": FALLBACK_SEVERITY_ERROR,
            "log_level": "error",
            "telemetry_event": "tableau_mcp_fallback_leaked",
            "requires_blocking": True,
            "fallback_target": fallback_target,
            "hidden_fallback_error": hidden_fallback_error,
        }
    if fallback_attempted and fallback_blocked:
        return {
            "kind": FALLBACK_ALERT_BLOCKED,
            "severity": FALLBACK_SEVERITY_WARNING,
            "log_level": "warning",
            "telemetry_event": "tableau_mcp_fallback_blocked",
            "requires_blocking": False,
            "fallback_target": fallback_target,
            "fallback_blocked_reason": _optional_str(trace.get("fallback_blocked_reason")),
        }
    return {
        "kind": FALLBACK_ALERT_NONE,
        "severity": FALLBACK_SEVERITY_NONE,
        "log_level": "info",
        "telemetry_event": "tableau_mcp_fallback_not_attempted",
        "requires_blocking": False,
        "fallback_target": fallback_target,
    }


def build_compiler_unsupported_planner_reason_payload(
    *,
    compiler_reason: str | None,
    planner_reason: str | None = None,
    compiler_status: str = "unsupported",
    planner_status: str = "pending",
    compile_ms: int | None = None,
    planner_ms: int | None = None,
    planner_entry: str = "tableau_mcp_llm_planner",
    detail: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Explain why deterministic compile handed the run to Planner."""

    payload: dict[str, Any] = {
        "compiler": {
            "status": compiler_status,
            "reason": compiler_reason,
        },
        "planner": {
            "status": planner_status,
            "entry": planner_entry,
            "reason": planner_reason or "compiler_unsupported",
            "handoff_reason": compiler_reason,
        },
        "explainability": {
            "event": "compiler_unsupported_entered_planner",
            "reason": compiler_reason,
        },
    }
    if compile_ms is not None:
        payload["compiler"]["ms"] = max(0, int(compile_ms))
    if planner_ms is not None:
        payload["planner"]["ms"] = max(0, int(planner_ms))
    if detail:
        payload["explainability"]["detail"] = {str(key): _json_safe_value(value) for key, value in detail.items()}
    return payload


def response_looks_successful(response_payload: Mapping[str, Any] | None) -> bool:
    """Best-effort success detector for fallback leak audits."""

    if not response_payload:
        return False
    if response_payload.get("success") is True:
        return True
    if response_payload.get("error") or response_payload.get("structured_error"):
        return False
    response_type = response_payload.get("response_type")
    if isinstance(response_type, str) and response_type in _SUCCESS_RESPONSE_TYPES:
        return True
    rows = response_payload.get("rows")
    fields = response_payload.get("fields")
    return isinstance(rows, list) and isinstance(fields, list)


def _trace_from_payload(payload: Mapping[str, Any] | None) -> Mapping[str, Any]:
    if not payload:
        return {}
    trace = payload.get("trace")
    if isinstance(trace, Mapping):
        return trace
    return payload


def _optional_str(value: Any) -> str | None:
    if value is None:
        return None
    return str(value)


def _json_safe_value(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, Mapping):
        return {str(key): _json_safe_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_json_safe_value(item) for item in value]
    return str(value)

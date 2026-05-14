"""Quality Gate and baseline comparison result model for Data Agent P0.

Draft target:
    backend/services/data_agent/quality_gate.py
"""

from __future__ import annotations

import math
import time
from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping, Optional

from services.data_agent.analysis_context import AnalysisContext, field_caption, normalize_query_plan, names_for


GATE_PASS = "pass"
GATE_WARN = "warn"
GATE_FALLBACK = "fallback"
GATE_BLOCK = "block"

CHECK_NUMERIC = "numeric"
CHECK_SET = "set"
CHECK_RANKING = "ranking"
CHECK_ROUTE = "route"
CHECK_PERFORMANCE = "performance"


@dataclass(slots=True)
class GateCheck:
    name: str
    status: str
    check_type: str
    message: str = ""
    details: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "status": self.status,
            "check_type": self.check_type,
            "message": self.message,
            "details": self.details,
        }


@dataclass(slots=True)
class QualityGateResult:
    gate_status: str
    checks: list[GateCheck]
    gate_level: str = "blocking"
    warnings: list[dict[str, Any]] = field(default_factory=list)
    blockers: list[dict[str, Any]] = field(default_factory=list)
    started_at: float = field(default_factory=time.time)
    completed_at: Optional[float] = None

    def to_dict(self) -> dict[str, Any]:
        completed_at = self.completed_at if self.completed_at is not None else time.time()
        return {
            "gate_status": self.gate_status,
            "gate_level": self.gate_level,
            "checks": [check.to_dict() for check in self.checks],
            "warnings": self.warnings,
            "blockers": self.blockers,
            "execution_time_ms": max(0, int((completed_at - self.started_at) * 1000)),
        }


def evaluate_quality_gate(
    *,
    context: AnalysisContext | Mapping[str, Any],
    response_data: Optional[Mapping[str, Any]],
    baseline: Optional[Mapping[str, Any]] = None,
    execution_time_ms: Optional[int] = None,
    expected_connection_id: Optional[int] = None,
    max_visible_rows: int = 100,
) -> QualityGateResult:
    """Evaluate P0 blocking checks before emitting a successful done event."""
    ctx = context if isinstance(context, AnalysisContext) else AnalysisContext.from_payload(context)
    plan = normalize_query_plan(ctx.query_plan)
    response = dict(response_data or {})
    checks: list[GateCheck] = []

    checks.extend(_check_route(ctx, expected_connection_id))
    checks.extend(_check_required_plan_parts(plan, response))
    checks.extend(_check_row_budget(response, max_visible_rows))
    checks.extend(_check_unresolved_terms(ctx))
    if execution_time_ms is not None:
        checks.append(_check_performance(execution_time_ms))
    if baseline:
        checks.extend(compare_to_baseline(plan=plan, response_data=response, baseline=baseline))

    blockers = [
        {"code": check.name, "message": check.message, "details": check.details}
        for check in checks
        if check.status == GATE_BLOCK
    ]
    warnings = [
        {"code": check.name, "message": check.message, "details": check.details}
        for check in checks
        if check.status == GATE_WARN
    ]
    status = GATE_BLOCK if blockers else (GATE_WARN if warnings else GATE_PASS)
    result = QualityGateResult(gate_status=status, checks=checks, warnings=warnings, blockers=blockers)
    result.completed_at = time.time()
    return result


def standard_gate_fallback(result: QualityGateResult, *, trace_id: str) -> dict[str, Any]:
    """User-facing fallback/error payload for gate blockers."""
    blocker = result.blockers[0] if result.blockers else {"code": "quality_gate_blocked", "message": "质量检查未通过"}
    return {
        "fallback_type": "quality_gate_blocked",
        "error_code": blocker["code"],
        "user_hint": _hint_for_blocker(blocker["code"]),
        "message": blocker["message"],
        "trace_id": trace_id,
        "quality_gate": result.to_dict(),
    }


def compare_to_baseline(
    *,
    plan: Mapping[str, Any],
    response_data: Mapping[str, Any],
    baseline: Mapping[str, Any],
) -> list[GateCheck]:
    checks: list[GateCheck] = []
    result_shape = baseline.get("result_shape") or {}
    tolerances = baseline.get("tolerances") or {}
    expected_plan = baseline.get("expected_plan") or {}

    required_metrics = set(expected_plan.get("metrics") or [])
    if required_metrics:
        actual_metrics = set(names_for(plan.get("metrics") or []))
        missing = required_metrics - actual_metrics
        checks.append(GateCheck(
            name="baseline_required_metrics",
            status=GATE_BLOCK if missing else GATE_PASS,
            check_type=CHECK_SET,
            message=f"missing baseline metrics: {sorted(missing)}" if missing else "required metrics match",
            details={"expected": sorted(required_metrics), "actual": sorted(actual_metrics)},
        ))

    required_fields = list(result_shape.get("required_fields") or [])
    if required_fields:
        fields = _field_names(response_data.get("fields") or [])
        missing = [field for field in required_fields if field not in fields]
        checks.append(GateCheck(
            name="baseline_required_fields",
            status=GATE_BLOCK if missing else GATE_PASS,
            check_type=CHECK_SET,
            message=f"missing response fields: {missing}" if missing else "required fields match",
            details={"expected": required_fields, "actual": fields},
        ))

    max_rows = result_shape.get("max_rows")
    if max_rows is not None:
        row_count = len(response_data.get("rows") or [])
        checks.append(GateCheck(
            name="baseline_max_rows",
            status=GATE_BLOCK if row_count > int(max_rows) else GATE_PASS,
            check_type=CHECK_PERFORMANCE,
            message=f"row_count {row_count} exceeds baseline max_rows {max_rows}" if row_count > int(max_rows) else "row budget matches",
            details={"row_count": row_count, "max_rows": int(max_rows)},
        ))

    baseline_rows = baseline.get("rows")
    if baseline_rows is not None:
        checks.extend(_compare_rows(response_data, baseline_rows, tolerances))
    return checks


def _check_route(ctx: AnalysisContext, expected_connection_id: Optional[int]) -> list[GateCheck]:
    checks = []
    actual_connection_id = ctx.scope.get("connection_id")
    if expected_connection_id is not None:
        checks.append(GateCheck(
            name="target_connection",
            status=GATE_BLOCK if actual_connection_id != expected_connection_id else GATE_PASS,
            check_type=CHECK_ROUTE,
            message="response used unexpected connection" if actual_connection_id != expected_connection_id else "connection matches",
            details={"expected_connection_id": expected_connection_id, "actual_connection_id": actual_connection_id},
        ))
    if not actual_connection_id:
        checks.append(GateCheck(
            name="connection_required",
            status=GATE_BLOCK,
            check_type=CHECK_ROUTE,
            message="data_question requires a verified Tableau connection_id",
        ))
    return checks


def _check_required_plan_parts(plan: Mapping[str, Any], response: Mapping[str, Any]) -> list[GateCheck]:
    checks: list[GateCheck] = []
    metrics = names_for(plan.get("metrics") or [])
    response_fields = _field_names(response.get("fields") or [])
    if not metrics:
        checks.append(GateCheck(
            name="required_metric_resolved",
            status=GATE_BLOCK,
            check_type=CHECK_SET,
            message="data query has no resolved metric",
        ))
    else:
        checks.append(GateCheck("required_metric_resolved", GATE_PASS, CHECK_SET, "metric resolved", {"metrics": metrics}))

    missing_dimensions = [
        dim for dim in names_for(plan.get("dimensions") or [])
        if response_fields and dim not in response_fields
    ]
    checks.append(GateCheck(
        name="no_unrequested_dimension_drop",
        status=GATE_BLOCK if missing_dimensions else GATE_PASS,
        check_type=CHECK_SET,
        message=f"requested dimensions missing from response: {missing_dimensions}" if missing_dimensions else "requested dimensions present",
        details={"response_fields": response_fields, "missing_dimensions": missing_dimensions},
    ))

    time_spec = plan.get("time")
    if time_spec and not any(field_caption(f) == field_caption(time_spec) for f in plan.get("filters") or []):
        checks.append(GateCheck(
            name="time_filter_bound",
            status=GATE_WARN,
            check_type=CHECK_SET,
            message="time spec exists but no matching filter was found; verify VizQL builder binds it",
            details={"time": time_spec, "filters": plan.get("filters") or []},
        ))
    return checks


def _check_row_budget(response: Mapping[str, Any], max_visible_rows: int) -> list[GateCheck]:
    rows = response.get("rows") or []
    row_count = len(rows)
    return [GateCheck(
        name="max_visible_rows",
        status=GATE_BLOCK if row_count > max_visible_rows else GATE_PASS,
        check_type=CHECK_PERFORMANCE,
        message=f"visible rows {row_count} exceeds max {max_visible_rows}" if row_count > max_visible_rows else "visible row budget respected",
        details={"row_count": row_count, "max_visible_rows": max_visible_rows},
    )]


def _check_unresolved_terms(ctx: AnalysisContext) -> list[GateCheck]:
    unresolved = list((ctx.semantic_resolution or {}).get("unresolved_terms") or [])
    return [GateCheck(
        name="no_unresolved_terms",
        status=GATE_BLOCK if unresolved else GATE_PASS,
        check_type=CHECK_SET,
        message=f"unresolved terms remain: {unresolved}" if unresolved else "all terms resolved",
        details={"unresolved_terms": unresolved},
    )]


def _check_performance(execution_time_ms: int) -> GateCheck:
    if execution_time_ms <= 15_000:
        status = GATE_PASS
    elif execution_time_ms <= 50_000:
        status = GATE_WARN
    else:
        status = GATE_BLOCK
    return GateCheck(
        name="latency_budget",
        status=status,
        check_type=CHECK_PERFORMANCE,
        message=f"execution_time_ms={execution_time_ms}",
        details={"warn_ms": 15_000, "block_ms": 50_000, "execution_time_ms": execution_time_ms},
    )


def _compare_rows(response: Mapping[str, Any], baseline_rows: Iterable[Iterable[Any]], tolerances: Mapping[str, Any]) -> list[GateCheck]:
    actual_rows = [list(row) for row in response.get("rows") or []]
    expected_rows = [list(row) for row in baseline_rows]
    checks: list[GateCheck] = []
    row_set_mode = tolerances.get("row_set", "exact")
    if row_set_mode == "exact":
        actual_set = {tuple(row) for row in actual_rows}
        expected_set = {tuple(row) for row in expected_rows}
        missing = expected_set - actual_set
        extra = actual_set - expected_set
        checks.append(GateCheck(
            name="baseline_row_set",
            status=GATE_BLOCK if missing or extra else GATE_PASS,
            check_type=CHECK_SET,
            message="baseline row set mismatch" if missing or extra else "row set matches",
            details={"missing": [list(row) for row in missing], "extra": [list(row) for row in extra]},
        ))

    numeric_rel = float(tolerances.get("numeric_rel") or 0.0)
    if numeric_rel and actual_rows and expected_rows:
        failures = []
        for r_idx, (actual, expected) in enumerate(zip(actual_rows, expected_rows)):
            for c_idx, (actual_value, expected_value) in enumerate(zip(actual, expected)):
                if _is_number(actual_value) and _is_number(expected_value):
                    if not _within_rel_tolerance(float(actual_value), float(expected_value), numeric_rel):
                        failures.append({"row": r_idx, "col": c_idx, "actual": actual_value, "expected": expected_value})
        checks.append(GateCheck(
            name="baseline_numeric_tolerance",
            status=GATE_BLOCK if failures else GATE_PASS,
            check_type=CHECK_NUMERIC,
            message="numeric values exceed tolerance" if failures else "numeric values within tolerance",
            details={"numeric_rel": numeric_rel, "failures": failures},
        ))
    return checks


def _field_names(fields: Iterable[Any]) -> list[str]:
    return [field_caption(field if isinstance(field, Mapping) else {"name": field}) for field in fields]


def _is_number(value: Any) -> bool:
    try:
        float(str(value).replace(",", "").replace("%", ""))
        return True
    except (TypeError, ValueError):
        return False


def _within_rel_tolerance(actual: float, expected: float, rel: float) -> bool:
    if math.isclose(actual, expected, rel_tol=rel, abs_tol=rel):
        return True
    denom = max(abs(expected), 1.0)
    return abs(actual - expected) / denom <= rel


def _hint_for_blocker(code: str) -> str:
    hints = {
        "required_metric_resolved": "请明确要看的指标，例如销售额、利润或客户数。",
        "no_unrequested_dimension_drop": "结果缺少用户要求的拆分维度，请缩小问题或换一个维度重试。",
        "max_visible_rows": "结果行数超过当前安全上限，请增加筛选条件或改成 TopN/聚合问题。",
        "target_connection": "当前数据连接与问题上下文不一致，请重新选择数据源后再问。",
        "connection_required": "请先选择一个可用的 Tableau 数据连接。",
        "baseline_required_fields": "结果结构与基线口径不一致，本次不输出成功答案。",
        "baseline_row_set": "结果集合与 MCP 基线不一致，本次不输出成功答案。",
    }
    return hints.get(code, "质量检查未通过，本次不输出可能误导的答案。")

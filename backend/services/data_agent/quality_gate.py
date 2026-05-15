"""Quality Gate and baseline comparison result model for Data Agent P0.

Draft target:
    backend/services/data_agent/quality_gate.py
"""

from __future__ import annotations

import argparse
import json
import math
import re
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping, Optional, Sequence

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

FIRST_CANARY_CASE_IDS = (
    "batch2.q1_overall_kpis",
    "batch2.q6_top10_customers",
    "batch2.q10_loss_root_cause_liaoning_fujian_2024",
)
EXTENDED_CANARY_CASE_IDS = (
    "batch2.q1_overall_kpis",
    "batch2.q4_continue_split_each_year",
    "batch2.q6_top10_customers",
    "batch2.q8_subcategory_profit_continuous_growth",
    "batch2.q10_loss_root_cause_liaoning_fujian_2024",
)
QUALITY_REPORT_SCHEMA_VERSION = "mcp_accuracy_quality_report.v1"
QUERY_SPEC_SUCCESS_RATE_THRESHOLD = 0.8
DEFAULT_BASELINE_DIR = Path(__file__).resolve().parents[2] / "tests" / "fixtures" / "data_agent" / "baseline"
DEFAULT_CASES_PATH = DEFAULT_BASELINE_DIR / "batch2_cases.yaml"
DEFAULT_SNAPSHOT_PATH = DEFAULT_BASELINE_DIR / "mcp_snapshots" / "superstore_2026_05_13.json"
DEFAULT_GATE_COMMAND = (
    "cd backend && .venv/bin/python -m services.data_agent.quality_gate "
    "--runs ../inbox/20260515-13-abtest-raw.json "
    "--report ../tmp/mcp_acc_06_quality_report.json"
)

FAILURE_GUARDRAIL = "guardrail_missing"
FAILURE_SILENT_FALLBACK = "silent_fallback"
FAILURE_RESPONSE_DATA = "response_data_empty"
FAILURE_UI_TABLE = "ui_table_mismatch"


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
        "required_metric_resolved": "请明确要看的指标。",
        "no_unrequested_dimension_drop": "结果缺少用户要求的拆分维度，请缩小问题或换一个维度重试。",
        "max_visible_rows": "结果行数超过当前安全上限，请增加筛选条件或改成 TopN/聚合问题。",
        "target_connection": "当前数据连接与问题上下文不一致，请重新选择数据源后再问。",
        "connection_required": "请先选择一个可用的 Tableau 数据连接。",
        "baseline_required_fields": "结果结构与基线口径不一致，本次不输出成功答案。",
        "baseline_row_set": "结果集合与 MCP 基线不一致，本次不输出成功答案。",
    }
    return hints.get(code, "质量检查未通过，本次不输出可能误导的答案。")


def build_canary_quality_report(
    *,
    runs_path: str | Path,
    cases_path: str | Path = DEFAULT_CASES_PATH,
    snapshot_path: str | Path = DEFAULT_SNAPSHOT_PATH,
    case_ids: Sequence[str] | None = None,
    case_set: str = "first",
    report_path: str | Path | None = None,
) -> dict[str, Any]:
    from services.data_agent.mcp_baseline_comparator import (
        compare_case_to_run_artifact,
        load_cases,
        load_snapshot,
    )

    runs = _load_json(runs_path)
    cases = load_cases(cases_path)
    snapshot = load_snapshot(snapshot_path)
    selected_cases = _select_cases(cases, case_ids=case_ids, case_set=case_set)
    case_items: list[dict[str, Any]] = []

    for case in selected_cases:
        artifact = _artifact_for_case(runs, case.id) or {}
        comparison = compare_case_to_run_artifact(
            case=case,
            context=_context_for_case(case, snapshot),
            run_artifact=artifact,
            snapshot=snapshot,
        )
        ui_checks = _ui_table_checks(artifact)
        checks = [*comparison.checks, *ui_checks]
        status = GATE_BLOCK if any(check.status == GATE_BLOCK for check in checks) else (
            GATE_WARN if any(check.status == GATE_WARN for check in checks) else GATE_PASS
        )
        failure_layer = _case_failure_layer(comparison.failure_layer, ui_checks, status)
        response_data = _extract_response_data_from_artifact(artifact) or {}
        case_items.append({
            "case_id": case.id,
            "question_id": _question_key_for_case(case.id),
            "status": status,
            "failure_layer": failure_layer,
            "checks": [check.to_dict() for check in checks],
            "queryspec_metrics": _artifact_queryspec_metrics(artifact),
            "mcp_baseline": _baseline_summary(snapshot, case.id),
            "mulan_response_data": _table_summary(response_data),
            "ui_table_data": _table_summary(_extract_ui_table_data(artifact) or {}),
        })

    metrics = _quality_report_metrics(case_items)
    blockers = [
        {
            "code": "queryspec_success_rate",
            "message": "QuerySpec main-path success rate is below threshold",
            "details": metrics,
        }
    ] if metrics["queryspec_main_path_success_rate"] < metrics["queryspec_success_rate_threshold"] else []
    status = GATE_BLOCK if blockers or any(item["status"] == GATE_BLOCK for item in case_items) else (
        GATE_WARN if any(item["status"] == GATE_WARN for item in case_items) else GATE_PASS
    )
    report = {
        "schema_version": QUALITY_REPORT_SCHEMA_VERSION,
        "source_plan": "inbox/20260515-15-mulan-mcp-accuracy-repair-plan.md",
        "snapshot_id": snapshot.get("snapshot_id"),
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "status": status,
        "case_set": case_set,
        "cases": case_items,
        "metrics": metrics,
        "blockers": blockers,
        "failure_categories": [
            FAILURE_GUARDRAIL,
            FAILURE_SILENT_FALLBACK,
            FAILURE_RESPONSE_DATA,
            FAILURE_UI_TABLE,
        ],
        "command": DEFAULT_GATE_COMMAND,
    }
    if report_path:
        output = Path(report_path)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report


def _select_cases(cases: Sequence[Any], *, case_ids: Sequence[str] | None, case_set: str) -> list[Any]:
    by_id = {case.id: case for case in cases}
    if case_ids:
        ids = list(case_ids)
    elif case_set == "extended":
        ids = list(EXTENDED_CANARY_CASE_IDS)
    elif case_set == "all":
        ids = [case.id for case in cases if case.id.startswith("batch2.")]
    else:
        ids = list(FIRST_CANARY_CASE_IDS)
    missing = [case_id for case_id in ids if case_id not in by_id]
    if missing:
        raise ValueError(f"unknown baseline case ids: {missing}")
    return [by_id[case_id] for case_id in ids]


def _load_json(path: str | Path) -> dict[str, Any]:
    with Path(path).open("r", encoding="utf-8") as fh:
        payload = json.load(fh)
    if not isinstance(payload, Mapping):
        raise ValueError("runs artifact must be a JSON object")
    return dict(payload)


def _artifact_for_case(runs: Mapping[str, Any], case_id: str) -> Optional[Mapping[str, Any]]:
    if isinstance(runs.get(case_id), Mapping):
        return runs[case_id]
    cases = runs.get("cases")
    if isinstance(cases, Mapping) and isinstance(cases.get(case_id), Mapping):
        return cases[case_id]
    question_key = _question_key_for_case(case_id)
    mulan = runs.get("mulan")
    if isinstance(mulan, Mapping) and isinstance(mulan.get(question_key), Mapping):
        return mulan[question_key]
    if isinstance(runs.get(question_key), Mapping):
        return runs[question_key]
    return None


def _question_key_for_case(case_id: str) -> str:
    match = re.search(r"\.q(\d+)", case_id)
    return f"Q{match.group(1)}" if match else case_id


def _context_for_case(case: Any, snapshot: Mapping[str, Any]) -> AnalysisContext:
    expected_plan = dict((case.baseline or {}).get("expected_plan") or {})
    return AnalysisContext.new(
        conversation_id=f"quality-{case.id}",
        run_id=f"quality-{case.id}",
        trace_id=f"quality-{case.id}",
        turn_no=1,
        scope={
            "connection_id": snapshot.get("connection_id"),
            "connection_type": "tableau",
            "datasource_luid": snapshot.get("datasource_luid"),
        },
        query_plan={
            "metrics": [{"name": item, "field_caption": item} for item in expected_plan.get("metrics") or []],
            "dimensions": [{"name": item, "field_caption": item} for item in expected_plan.get("dimensions") or []],
        },
    )


def _ui_table_checks(run_artifact: Mapping[str, Any]) -> list[GateCheck]:
    ui_table = _extract_ui_table_data(run_artifact)
    response_data = _extract_response_data_from_artifact(run_artifact)
    if not _is_table(response_data):
        return []
    if ui_table is None:
        return [GateCheck(
            name="ui_table_data_capture",
            status=GATE_WARN,
            check_type=CHECK_SET,
            message="UI table_data capture is not present",
        )]
    matches = _field_names(response_data.get("fields") or []) == _field_names(ui_table.get("fields") or []) and list(
        response_data.get("rows") or []
    ) == list(ui_table.get("rows") or [])
    return [GateCheck(
        name="ui_table_data_match",
        status=GATE_PASS if matches else GATE_BLOCK,
        check_type=CHECK_SET,
        message="UI table_data matches response_data" if matches else "UI table_data differs from response_data",
        details={
            "response_data": _table_summary(response_data),
            "ui_table_data": _table_summary(ui_table),
        },
    )]


def _extract_response_data_from_artifact(run_artifact: Mapping[str, Any]) -> Optional[Mapping[str, Any]]:
    response_data = run_artifact.get("response_data")
    if isinstance(response_data, Mapping):
        return response_data
    done = run_artifact.get("done")
    if isinstance(done, Mapping) and isinstance(done.get("response_data"), Mapping):
        return done["response_data"]
    return None


def _extract_ui_table_data(run_artifact: Mapping[str, Any]) -> Optional[Mapping[str, Any]]:
    for key in ("ui_table_data", "table_data"):
        value = run_artifact.get(key)
        if _is_table(value):
            return value
    for event in run_artifact.get("events") or []:
        if not isinstance(event, Mapping):
            continue
        if event.get("type") != "table_data":
            continue
        for key in ("content", "data", "payload"):
            value = event.get(key)
            if _is_table(value):
                return value
        if _is_table(event):
            return event
    return None


def _artifact_queryspec_metrics(run_artifact: Mapping[str, Any]) -> dict[str, Any]:
    output = {
        "queryspec_main_path_success": None,
        "queryspec_fallback_triggered": None,
    }
    for item in _walk_mappings(run_artifact):
        for key in output:
            if key in item and isinstance(item[key], bool):
                output[key] = item[key]
    tokens = _event_tokens(run_artifact)
    if output["queryspec_fallback_triggered"] is None and "FALLBACK_TRIGGERED" in tokens:
        output["queryspec_fallback_triggered"] = True
    return output


def _quality_report_metrics(case_items: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    total = len(case_items)
    success_count = 0
    fallback_count = 0
    missing_metrics = 0
    for item in case_items:
        metrics = item.get("queryspec_metrics") if isinstance(item.get("queryspec_metrics"), Mapping) else {}
        if metrics.get("queryspec_main_path_success") is True:
            success_count += 1
        elif metrics.get("queryspec_main_path_success") is None:
            missing_metrics += 1
        if metrics.get("queryspec_fallback_triggered") is True:
            fallback_count += 1
    denominator = total or 1
    return {
        "case_count": total,
        "queryspec_main_path_success_count": success_count,
        "queryspec_main_path_success_rate": success_count / denominator,
        "fallback_count": fallback_count,
        "fallback_rate": fallback_count / denominator,
        "missing_trace_metrics_count": missing_metrics,
        "queryspec_success_rate_threshold": QUERY_SPEC_SUCCESS_RATE_THRESHOLD,
    }


def _baseline_summary(snapshot: Mapping[str, Any], case_id: str) -> dict[str, Any]:
    case = (snapshot.get("cases") or {}).get(case_id) if isinstance(snapshot.get("cases"), Mapping) else None
    if not isinstance(case, Mapping):
        return {}
    if _is_table(case):
        return _table_summary(case)
    tables = case.get("tables")
    if isinstance(tables, Mapping):
        return {
            "tables": {
                name: _table_summary(table)
                for name, table in tables.items()
                if isinstance(table, Mapping)
            }
        }
    return {}


def _table_summary(table: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(table, Mapping):
        return {}
    rows = list(table.get("rows") or [])
    return {
        "fields": _field_names(table.get("fields") or []),
        "row_count": len(rows),
    }


def _case_failure_layer(comparison_layer: str, ui_checks: Sequence[GateCheck], status: str) -> str:
    if status == GATE_PASS:
        return "pass"
    if any(check.status == GATE_BLOCK for check in ui_checks):
        return FAILURE_UI_TABLE
    return comparison_layer


def _event_tokens(value: Any) -> set[str]:
    tokens: set[str] = set()
    for item in _walk_mappings(value):
        for key in ("event", "type", "tool", "fallback_type"):
            token = item.get(key)
            if token:
                tokens.add(str(token))
    return tokens


def _walk_mappings(value: Any) -> Iterable[Mapping[str, Any]]:
    if isinstance(value, Mapping):
        yield value
        for child in value.values():
            yield from _walk_mappings(child)
    elif isinstance(value, list):
        for child in value:
            yield from _walk_mappings(child)


def _is_table(value: Any) -> bool:
    return isinstance(value, Mapping) and isinstance(value.get("fields"), list) and isinstance(value.get("rows"), list)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run offline MCP accuracy canary quality gate.")
    parser.add_argument("--runs", required=True)
    parser.add_argument("--cases", default=str(DEFAULT_CASES_PATH))
    parser.add_argument("--snapshot", default=str(DEFAULT_SNAPSHOT_PATH))
    parser.add_argument("--report", required=True)
    parser.add_argument("--case-set", choices=("first", "extended", "all"), default="first")
    parser.add_argument("--case-id", action="append", dest="case_ids")
    args = parser.parse_args(argv)
    report = build_canary_quality_report(
        runs_path=args.runs,
        cases_path=args.cases,
        snapshot_path=args.snapshot,
        case_ids=args.case_ids,
        case_set=args.case_set,
        report_path=args.report,
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["status"] == GATE_PASS else 1


if __name__ == "__main__":
    raise SystemExit(main())

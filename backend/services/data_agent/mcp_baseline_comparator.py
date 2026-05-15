"""Offline MCP baseline comparator utilities.

CI should run snapshot comparison only. Live MCP recording/comparison must be
guarded by explicit env vars so PR runs do not require Tableau credentials.
"""

from __future__ import annotations

import json
import math
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Mapping, Optional

from services.data_agent.analysis_context import AnalysisContext
from services.data_agent.quality_gate import (
    CHECK_NUMERIC,
    CHECK_PERFORMANCE,
    CHECK_RANKING,
    CHECK_ROUTE,
    CHECK_SET,
    FAILURE_GUARDRAIL,
    FAILURE_SILENT_FALLBACK,
    GATE_BLOCK,
    GATE_PASS,
    GATE_WARN,
    GateCheck,
    QualityGateResult,
    compare_to_baseline,
)


FAILURE_PASS = "pass"
FAILURE_NO_MCP = "no_mcp"
FAILURE_MCP_FAILURE = "mcp_failure"
FAILURE_CONTRACT = "contract_failure"
FAILURE_FIELD = "field_mismatch"
FAILURE_ROW_COUNT = "row_count_mismatch"
FAILURE_ORDER = "order_mismatch"
FAILURE_ROW_SET = "row_mismatch"
FAILURE_NUMERIC = "numeric_mismatch"
FAILURE_DERIVED = "derived_metric_mismatch"
FAILURE_UNKNOWN = "comparison_mismatch"

_TABLE_KEYS = frozenset({"fields", "rows"})


@dataclass(slots=True)
class BaselineCase:
    id: str
    group: str
    question: str
    connection_fixture: str
    previous_context: Optional[dict[str, Any]]
    expected_patch: dict[str, Any]
    baseline: dict[str, Any]
    expected_gate: str = "pass"
    tags: list[str] = field(default_factory=list)

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "BaselineCase":
        return cls(
            id=str(payload["id"]),
            group=str(payload.get("group") or "uncategorized"),
            question=str(payload["question"]),
            connection_fixture=str(payload.get("connection_fixture") or ""),
            previous_context=payload.get("previous_context"),
            expected_patch=dict(payload.get("expected_patch") or {}),
            baseline=dict(payload.get("baseline") or {}),
            expected_gate=str(payload.get("expected_gate") or "pass"),
            tags=list(payload.get("tags") or []),
        )


@dataclass(slots=True)
class BaselineComparison:
    case_id: str
    status: str
    checks: list[GateCheck]
    snapshot_id: Optional[str] = None
    failure_layer: str = FAILURE_PASS

    def to_quality_gate(self) -> QualityGateResult:
        blockers = [
            {"code": check.name, "message": check.message, "details": check.details}
            for check in self.checks
            if check.status == "block"
        ]
        warnings = [
            {"code": check.name, "message": check.message, "details": check.details}
            for check in self.checks
            if check.status == "warn"
        ]
        return QualityGateResult(
            gate_status=self.status,
            checks=self.checks,
            warnings=warnings,
            blockers=blockers,
        )

    def to_report_item(self) -> dict[str, Any]:
        return {
            "case_id": self.case_id,
            "status": self.status,
            "failure_layer": self.failure_layer,
            "snapshot_id": self.snapshot_id,
            "checks": [check.to_dict() for check in self.checks],
        }


def load_cases(path: str | Path) -> list[BaselineCase]:
    """Load YAML case files.

    PyYAML is already common in pytest stacks, but this import is local so the
    production app does not need it unless tests/evals call the loader.
    """
    import yaml

    with Path(path).open("r", encoding="utf-8") as fh:
        payload = yaml.safe_load(fh) or []
    return [BaselineCase.from_dict(item) for item in payload]


def load_snapshot(path: str | Path) -> dict[str, Any]:
    with Path(path).open("r", encoding="utf-8") as fh:
        return json.load(fh)


def compare_case_to_snapshot(
    *,
    case: BaselineCase,
    context: AnalysisContext | Mapping[str, Any],
    response_data: Mapping[str, Any],
    snapshot: Mapping[str, Any],
) -> BaselineComparison:
    ctx = context if isinstance(context, AnalysisContext) else AnalysisContext.from_payload(context)
    snapshot_case = (snapshot.get("cases") or {}).get(case.id, {})
    checks: list[GateCheck] = []

    expected_plan = (case.baseline or {}).get("expected_plan")
    if expected_plan:
        checks.extend(compare_to_baseline(plan=ctx.query_plan, response_data={}, baseline={"expected_plan": expected_plan}))

    for table_name, expected_table, table_spec in _iter_expected_tables(case.baseline, snapshot_case):
        actual_table = _table_from_response(response_data, table_name)
        if not _is_table(actual_table):
            checks.append(GateCheck(
                name=_check_name(table_name, "baseline_table_contract"),
                status=GATE_BLOCK,
                check_type=CHECK_SET,
                message="missing table fields/rows contract",
                details={"table": table_name},
            ))
            continue
        checks.extend(_compare_table(table_name, actual_table, expected_table, table_spec))

    status = "block" if any(check.status == "block" for check in checks) else (
        "warn" if any(check.status == "warn" for check in checks) else "pass"
    )
    return BaselineComparison(
        case_id=case.id,
        status=status,
        checks=checks,
        snapshot_id=str(snapshot.get("snapshot_id") or "") or None,
        failure_layer=_classify_from_checks(checks),
    )


def compare_case_to_run_artifact(
    *,
    case: BaselineCase,
    context: AnalysisContext | Mapping[str, Any],
    run_artifact: Mapping[str, Any],
    snapshot: Mapping[str, Any],
) -> BaselineComparison:
    """Compare a recorded Mulan run artifact with the reviewed MCP snapshot.

    The run artifact may be a raw SSE capture, a compact test fixture, or a
    saved quality report item. Numeric comparison always uses structured
    response_data/table rows, never answer text.
    """
    preflight_checks = _artifact_preflight_checks(run_artifact)
    response_data = _extract_response_data(run_artifact)
    if any(check.status == GATE_BLOCK for check in preflight_checks):
        return _comparison_from_checks(
            case_id=case.id,
            snapshot_id=str(snapshot.get("snapshot_id") or "") or None,
            checks=preflight_checks,
            failure_layer=_classify_artifact_failure(run_artifact, preflight_checks),
        )

    comparison = compare_case_to_snapshot(
        case=case,
        context=context,
        response_data=response_data or {},
        snapshot=snapshot,
    )
    checks = [*preflight_checks, *comparison.checks]
    return _comparison_from_checks(
        case_id=case.id,
        snapshot_id=comparison.snapshot_id,
        checks=checks,
        failure_layer=_classify_artifact_failure(run_artifact, checks),
    )


def _comparison_from_checks(
    *,
    case_id: str,
    snapshot_id: Optional[str],
    checks: list[GateCheck],
    failure_layer: str,
) -> BaselineComparison:
    status = GATE_BLOCK if any(check.status == GATE_BLOCK for check in checks) else (
        GATE_WARN if any(check.status == GATE_WARN for check in checks) else GATE_PASS
    )
    return BaselineComparison(
        case_id=case_id,
        status=status,
        checks=checks,
        snapshot_id=snapshot_id,
        failure_layer=failure_layer if status != GATE_PASS else FAILURE_PASS,
    )


def _iter_expected_tables(
    case_baseline: Mapping[str, Any],
    snapshot_case: Mapping[str, Any],
) -> Iterable[tuple[Optional[str], Mapping[str, Any], Mapping[str, Any]]]:
    snapshot_tables = snapshot_case.get("tables")
    case_tables = case_baseline.get("tables") or {}
    if isinstance(snapshot_tables, Mapping):
        for table_name, table in snapshot_tables.items():
            if not isinstance(table, Mapping):
                continue
            yield str(table_name), table, _merge_table_spec(table, case_tables.get(table_name) or {})
        return

    expected_table = snapshot_case if snapshot_case else case_baseline
    yield None, expected_table, _merge_table_spec(expected_table, case_baseline)


def _merge_table_spec(base: Mapping[str, Any], override: Mapping[str, Any]) -> dict[str, Any]:
    merged: dict[str, Any] = {}
    for source in (base, override):
        for key in (
            "result_shape",
            "tolerances",
            "order",
            "field_aliases",
            "derived_metrics",
            "identity_fields",
            "numeric_fields",
        ):
            value = source.get(key)
            if isinstance(value, Mapping) and isinstance(merged.get(key), Mapping):
                merged[key] = {**merged[key], **value}
            elif value is not None:
                merged[key] = value
    return merged


def _compare_table(
    table_name: Optional[str],
    actual_table: Mapping[str, Any],
    expected_table: Mapping[str, Any],
    spec: Mapping[str, Any],
) -> list[GateCheck]:
    checks: list[GateCheck] = []
    actual_fields = _field_names(actual_table.get("fields") or [])
    expected_fields = _field_names(expected_table.get("fields") or [])
    actual_rows = [list(row) for row in actual_table.get("rows") or []]
    expected_rows = [list(row) for row in expected_table.get("rows") or []]
    aliases = spec.get("field_aliases") or {}
    shape = spec.get("result_shape") or {}

    required_fields = list(shape.get("required_fields") or expected_fields)
    missing_fields = [field for field in required_fields if _field_index(actual_fields, field, aliases) is None]
    checks.append(GateCheck(
        name=_check_name(table_name, "baseline_required_fields"),
        status=GATE_BLOCK if missing_fields else GATE_PASS,
        check_type=CHECK_SET,
        message="missing response fields" if missing_fields else "required fields match",
        details={"table": table_name, "missing": missing_fields, "expected": required_fields, "actual": actual_fields},
    ))

    row_count = shape.get("row_count", shape.get("expected_rows"))
    if row_count is not None:
        expected_count = int(row_count)
        checks.append(GateCheck(
            name=_check_name(table_name, "baseline_row_count"),
            status=GATE_BLOCK if len(actual_rows) != expected_count else GATE_PASS,
            check_type=CHECK_PERFORMANCE,
            message="row count mismatch" if len(actual_rows) != expected_count else "row count matches",
            details={"table": table_name, "expected": expected_count, "actual": len(actual_rows)},
        ))

    max_rows = shape.get("max_rows")
    if max_rows is not None:
        max_count = int(max_rows)
        checks.append(GateCheck(
            name=_check_name(table_name, "baseline_max_rows"),
            status=GATE_BLOCK if len(actual_rows) > max_count else GATE_PASS,
            check_type=CHECK_PERFORMANCE,
            message="row count exceeds maximum" if len(actual_rows) > max_count else "row budget matches",
            details={"table": table_name, "max_rows": max_count, "actual": len(actual_rows)},
        ))

    checks.extend(_compare_derived_fields(table_name, actual_fields, aliases, spec))
    checks.extend(_compare_order(table_name, actual_fields, actual_rows, expected_fields, expected_rows, aliases, spec))
    checks.extend(_compare_row_identity(table_name, actual_fields, actual_rows, expected_fields, expected_rows, aliases, spec))
    checks.extend(_compare_numeric_values(table_name, actual_fields, actual_rows, expected_fields, expected_rows, aliases, spec))
    return checks


def _compare_derived_fields(
    table_name: Optional[str],
    actual_fields: list[str],
    aliases: Mapping[str, Any],
    spec: Mapping[str, Any],
) -> list[GateCheck]:
    derived = spec.get("derived_metrics") or []
    if isinstance(derived, Mapping):
        required = list(derived.get("required_fields") or [])
    else:
        required = [str(item.get("field") if isinstance(item, Mapping) else item) for item in derived]
    required = [field for field in required if field]
    if not required:
        return []
    missing = [field for field in required if _field_index(actual_fields, field, aliases) is None]
    return [GateCheck(
        name=_check_name(table_name, "baseline_derived_metrics"),
        status=GATE_BLOCK if missing else GATE_PASS,
        check_type=CHECK_SET,
        message="missing derived metric fields" if missing else "derived metric fields match",
        details={"table": table_name, "missing": missing, "expected": required},
    )]


def _compare_order(
    table_name: Optional[str],
    actual_fields: list[str],
    actual_rows: list[list[Any]],
    expected_fields: list[str],
    expected_rows: list[list[Any]],
    aliases: Mapping[str, Any],
    spec: Mapping[str, Any],
) -> list[GateCheck]:
    order = spec.get("order") or {}
    order_field = order.get("field") or order.get("by")
    if not order_field:
        return []
    actual_idx = _field_index(actual_fields, str(order_field), aliases)
    if actual_idx is None:
        return [GateCheck(
            name=_check_name(table_name, "baseline_topn_order"),
            status=GATE_BLOCK,
            check_type=CHECK_RANKING,
            message="order field missing",
            details={"table": table_name, "order_field": order_field, "actual_fields": actual_fields},
        )]

    top_n = int(order.get("top_n") or order.get("limit") or len(actual_rows))
    direction = str(order.get("direction") or "desc").lower()
    ordered_values = [_comparable_value(row[actual_idx] if actual_idx < len(row) else None) for row in actual_rows[:top_n]]
    monotonic = _is_monotonic(ordered_values, direction)
    identity_fields = list(order.get("identity_fields") or spec.get("identity_fields") or [])
    sequence_matches = True
    expected_sequence: list[Any] = []
    actual_sequence: list[Any] = []
    if identity_fields and expected_rows:
        actual_sequence = _row_id_sequence(actual_fields, actual_rows[:top_n], identity_fields, aliases)
        expected_sequence = _row_id_sequence(expected_fields, expected_rows[:top_n], identity_fields, aliases)
        sequence_matches = actual_sequence == expected_sequence

    passed = monotonic and sequence_matches
    return [GateCheck(
        name=_check_name(table_name, "baseline_topn_order"),
        status=GATE_BLOCK if not passed else GATE_PASS,
        check_type=CHECK_RANKING,
        message="Top N order mismatch" if not passed else "Top N order matches",
        details={
            "table": table_name,
            "order_field": order_field,
            "direction": direction,
            "top_n": top_n,
            "monotonic": monotonic,
            "expected_sequence": expected_sequence,
            "actual_sequence": actual_sequence,
        },
    )]


def _compare_row_identity(
    table_name: Optional[str],
    actual_fields: list[str],
    actual_rows: list[list[Any]],
    expected_fields: list[str],
    expected_rows: list[list[Any]],
    aliases: Mapping[str, Any],
    spec: Mapping[str, Any],
) -> list[GateCheck]:
    tolerances = spec.get("tolerances") or {}
    if tolerances.get("row_set") != "exact":
        return []
    identity_fields = list(spec.get("identity_fields") or [])
    if identity_fields:
        actual_ids = set(_row_id_sequence(actual_fields, actual_rows, identity_fields, aliases))
        expected_ids = set(_row_id_sequence(expected_fields, expected_rows, identity_fields, aliases))
        missing = expected_ids - actual_ids
        extra = actual_ids - expected_ids
    else:
        actual_ids = {_canonical_row(row) for row in actual_rows}
        expected_ids = {_canonical_row(row) for row in expected_rows}
        missing = expected_ids - actual_ids
        extra = actual_ids - expected_ids
    return [GateCheck(
        name=_check_name(table_name, "baseline_row_set"),
        status=GATE_BLOCK if missing or extra else GATE_PASS,
        check_type=CHECK_SET,
        message="baseline row set mismatch" if missing or extra else "row set matches",
        details={
            "table": table_name,
            "missing": [list(item) if isinstance(item, tuple) else item for item in sorted(missing, key=str)],
            "extra": [list(item) if isinstance(item, tuple) else item for item in sorted(extra, key=str)],
        },
    )]


def _compare_numeric_values(
    table_name: Optional[str],
    actual_fields: list[str],
    actual_rows: list[list[Any]],
    expected_fields: list[str],
    expected_rows: list[list[Any]],
    aliases: Mapping[str, Any],
    spec: Mapping[str, Any],
) -> list[GateCheck]:
    tolerances = spec.get("tolerances") or {}
    numeric_rel = float(tolerances.get("numeric_rel") or 0.0)
    numeric_abs = float(tolerances.get("numeric_abs") or 0.0)
    if not (numeric_rel or numeric_abs) or not actual_rows or not expected_rows:
        return []

    identity_fields = list(spec.get("identity_fields") or [])
    expected_pairs = _align_rows(actual_fields, actual_rows, expected_fields, expected_rows, identity_fields, aliases)
    configured_numeric_fields = list(spec.get("numeric_fields") or [])
    candidate_fields = configured_numeric_fields or expected_fields
    failures = []
    for row_ref, actual, expected in expected_pairs:
        for field in candidate_fields:
            actual_idx = _field_index(actual_fields, field, aliases)
            expected_idx = _field_index(expected_fields, field, aliases)
            if actual_idx is None or expected_idx is None:
                continue
            actual_num = _to_number(actual[actual_idx] if actual_idx < len(actual) else None)
            expected_num = _to_number(expected[expected_idx] if expected_idx < len(expected) else None)
            if actual_num is None or expected_num is None:
                continue
            if not _within_tolerance(actual_num, expected_num, numeric_rel, numeric_abs):
                failures.append({
                    "row": row_ref,
                    "field": field,
                    "actual": actual[actual_idx] if actual_idx < len(actual) else None,
                    "expected": expected[expected_idx] if expected_idx < len(expected) else None,
                })
    return [GateCheck(
        name=_check_name(table_name, "baseline_numeric_tolerance"),
        status=GATE_BLOCK if failures else GATE_PASS,
        check_type=CHECK_NUMERIC,
        message="numeric values exceed tolerance" if failures else "numeric values within tolerance",
        details={"table": table_name, "numeric_rel": numeric_rel, "numeric_abs": numeric_abs, "failures": failures},
    )]


def _align_rows(
    actual_fields: list[str],
    actual_rows: list[list[Any]],
    expected_fields: list[str],
    expected_rows: list[list[Any]],
    identity_fields: list[str],
    aliases: Mapping[str, Any],
) -> list[tuple[Any, list[Any], list[Any]]]:
    if not identity_fields:
        return [(idx, actual, expected) for idx, (actual, expected) in enumerate(zip(actual_rows, expected_rows))]

    actual_by_id = {
        row_id: row
        for row_id, row in zip(
            _row_id_sequence(actual_fields, actual_rows, identity_fields, aliases),
            actual_rows,
        )
    }
    aligned = []
    for row_id, expected in zip(_row_id_sequence(expected_fields, expected_rows, identity_fields, aliases), expected_rows):
        actual = actual_by_id.get(row_id)
        if actual is not None:
            aligned.append((list(row_id), actual, expected))
    return aligned


def _artifact_preflight_checks(run_artifact: Mapping[str, Any]) -> list[GateCheck]:
    checks: list[GateCheck] = []
    tools = _tools_used(run_artifact)
    saw_mcp = "tableau_mcp" in tools
    response_data = _extract_response_data(run_artifact)
    artifact_error = run_artifact.get("error")
    done = run_artifact.get("done") if isinstance(run_artifact.get("done"), Mapping) else {}
    tokens = _event_tokens(run_artifact)

    checks.append(GateCheck(
        name="baseline_mcp_execution",
        status=GATE_PASS if saw_mcp else GATE_BLOCK,
        check_type=CHECK_ROUTE,
        message="MCP execution observed" if saw_mcp else "MCP execution was not observed",
        details={"tools_used": sorted(tools)},
    ))
    if saw_mcp and artifact_error and not response_data:
        checks.append(GateCheck(
            name="baseline_mcp_result",
            status=GATE_BLOCK,
            check_type=CHECK_ROUTE,
            message="MCP execution did not produce response data",
            details={"error": artifact_error},
        ))
    if saw_mcp and not _has_table_contract(response_data):
        checks.append(GateCheck(
            name="baseline_response_contract",
            status=GATE_BLOCK,
            check_type=CHECK_SET,
            message="table response_data contract is missing",
            details={"response_type": done.get("response_type") or run_artifact.get("response_type")},
        ))
    if saw_mcp:
        guardrail_pass = _has_guardrail_pass(run_artifact)
        checks.append(GateCheck(
            name="baseline_guardrail_trace",
            status=GATE_PASS if guardrail_pass else GATE_BLOCK,
            check_type=CHECK_ROUTE,
            message="Guardrail pass trace observed" if guardrail_pass else "MCP execution is missing Guardrail pass trace",
            details={"expected_event": "MCP_ARGS_GUARDRAIL_PASS"},
        ))
    if _fallback_observed(run_artifact):
        fallback_trace = "FALLBACK_TRIGGERED" in tokens or "WARN" in tokens
        checks.append(GateCheck(
            name="baseline_fallback_trace",
            status=GATE_PASS if fallback_trace else GATE_BLOCK,
            check_type=CHECK_ROUTE,
            message="fallback trace observed" if fallback_trace else "fallback occurred without FALLBACK_TRIGGERED/WARN trace",
            details={"expected_event": ["FALLBACK_TRIGGERED", "WARN"]},
        ))
    return checks


def _extract_response_data(run_artifact: Mapping[str, Any]) -> Optional[Mapping[str, Any]]:
    response_data = run_artifact.get("response_data")
    if isinstance(response_data, Mapping):
        return response_data
    done = run_artifact.get("done")
    if isinstance(done, Mapping) and isinstance(done.get("response_data"), Mapping):
        return done["response_data"]
    return None


def _tools_used(run_artifact: Mapping[str, Any]) -> set[str]:
    tools = set(str(tool) for tool in (run_artifact.get("tools_used") or []) if tool)
    done = run_artifact.get("done")
    if isinstance(done, Mapping):
        tools.update(str(tool) for tool in (done.get("tools_used") or []) if tool)
    for event in run_artifact.get("events") or []:
        if not isinstance(event, Mapping):
            continue
        tool = event.get("tool") or event.get("name")
        if tool:
            tools.add(str(tool))
    return tools


def _has_guardrail_pass(run_artifact: Mapping[str, Any]) -> bool:
    for item in _walk_mappings(run_artifact):
        if item.get("event") == "MCP_ARGS_GUARDRAIL_PASS":
            return True
        guardrail = item.get("mcp_args_guardrail")
        if isinstance(guardrail, Mapping) and guardrail.get("decision") in {"allow", "repair"}:
            return True
    return False


def _fallback_observed(run_artifact: Mapping[str, Any]) -> bool:
    for item in _walk_mappings(run_artifact):
        if item.get("fallback_chain_mode") or item.get("queryspec_fallback"):
            return True
        if item.get("fallback_type"):
            return True
        fallback = item.get("fallback")
        if isinstance(fallback, Mapping) and fallback.get("occurred") is True:
            return True
    return False


def _event_tokens(run_artifact: Mapping[str, Any]) -> set[str]:
    tokens: set[str] = set()
    for item in _walk_mappings(run_artifact):
        for key in ("event", "type", "tool"):
            value = item.get(key)
            if value:
                tokens.add(str(value))
    return tokens


def _walk_mappings(value: Any) -> Iterable[Mapping[str, Any]]:
    if isinstance(value, Mapping):
        yield value
        for child in value.values():
            yield from _walk_mappings(child)
    elif isinstance(value, list):
        for child in value:
            yield from _walk_mappings(child)


def _has_table_contract(value: Any) -> bool:
    if not isinstance(value, Mapping):
        return False
    if _is_table(value):
        return True
    tables = value.get("tables")
    if isinstance(tables, Mapping):
        return any(_is_table(table) for table in tables.values() if isinstance(table, Mapping))
    return any(_is_table(item) for item in value.values() if isinstance(item, Mapping))


def _is_table(value: Any) -> bool:
    return isinstance(value, Mapping) and _TABLE_KEYS.issubset(value.keys()) and isinstance(value.get("rows"), list)


def _table_from_response(response_data: Mapping[str, Any], table_name: Optional[str]) -> Optional[Mapping[str, Any]]:
    if table_name is None and _is_table(response_data):
        return response_data
    tables = response_data.get("tables") if isinstance(response_data, Mapping) else None
    if table_name is not None and isinstance(tables, Mapping) and _is_table(tables.get(table_name)):
        return tables[table_name]
    if table_name is not None and _is_table(response_data.get(table_name)):
        return response_data[table_name]
    if table_name is None and isinstance(tables, Mapping) and len(tables) == 1:
        only_table = next(iter(tables.values()))
        if _is_table(only_table):
            return only_table
    return None


def _field_names(fields: Iterable[Any]) -> list[str]:
    from services.data_agent.analysis_context import field_caption

    return [field_caption(field if isinstance(field, Mapping) else {"name": field}) for field in fields]


def _field_index(fields: list[str], expected: str, aliases: Mapping[str, Any]) -> Optional[int]:
    candidates = [expected, *list(aliases.get(expected) or [])]
    for candidate in candidates:
        if candidate in fields:
            return fields.index(candidate)
    return None


def _row_id_sequence(
    fields: list[str],
    rows: list[list[Any]],
    identity_fields: list[str],
    aliases: Mapping[str, Any],
) -> list[tuple[Any, ...]]:
    indexes = [_field_index(fields, field, aliases) for field in identity_fields]
    return [
        tuple(row[idx] if idx is not None and idx < len(row) else None for idx in indexes)
        for row in rows
    ]


def _canonical_row(row: list[Any]) -> str:
    return json.dumps(row, ensure_ascii=False, sort_keys=True, default=str)


def _comparable_value(value: Any) -> Any:
    number = _to_number(value)
    return number if number is not None else value


def _is_monotonic(values: list[Any], direction: str) -> bool:
    if len(values) < 2:
        return True
    if direction == "asc":
        return all(left <= right for left, right in zip(values, values[1:]))
    return all(left >= right for left, right in zip(values, values[1:]))


def _to_number(value: Any) -> Optional[float]:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        number = float(value)
        return number if math.isfinite(number) else None
    if isinstance(value, str):
        stripped = value.strip().replace(",", "")
        is_percent = stripped.endswith("%")
        if is_percent:
            stripped = stripped[:-1].strip()
        try:
            number = float(stripped)
        except ValueError:
            return None
        if is_percent:
            number /= 100.0
        return number if math.isfinite(number) else None
    return None


def _within_tolerance(actual: float, expected: float, rel: float, abs_tol: float) -> bool:
    if math.isclose(actual, expected, rel_tol=rel, abs_tol=abs_tol):
        return True
    denom = max(abs(expected), 1.0)
    return abs(actual - expected) / denom <= rel or abs(actual - expected) <= abs_tol


def _check_name(table_name: Optional[str], name: str) -> str:
    return f"{table_name}.{name}" if table_name else name


def _classify_from_checks(checks: Iterable[GateCheck]) -> str:
    blocked = [check for check in checks if check.status == GATE_BLOCK]
    if not blocked:
        return FAILURE_PASS
    for check in blocked:
        if check.name.endswith("baseline_table_contract"):
            return FAILURE_CONTRACT
    for check in blocked:
        if check.name.endswith("baseline_required_fields"):
            return FAILURE_FIELD
    for check in blocked:
        if check.name.endswith("baseline_row_count") or check.name.endswith("baseline_max_rows"):
            return FAILURE_ROW_COUNT
    for check in blocked:
        if check.name.endswith("baseline_derived_metrics"):
            return FAILURE_DERIVED
    for check in blocked:
        if check.name.endswith("baseline_numeric_tolerance"):
            return FAILURE_NUMERIC
    for check in blocked:
        if check.name.endswith("baseline_topn_order"):
            return FAILURE_ORDER
    for check in blocked:
        if check.name.endswith("baseline_row_set"):
            return FAILURE_ROW_SET
    return FAILURE_UNKNOWN


def _classify_artifact_failure(run_artifact: Mapping[str, Any], checks: Iterable[GateCheck]) -> str:
    blocked_names = {check.name for check in checks if check.status == GATE_BLOCK}
    if "baseline_mcp_execution" in blocked_names:
        return FAILURE_NO_MCP
    if "baseline_mcp_result" in blocked_names:
        return FAILURE_MCP_FAILURE
    if "baseline_response_contract" in blocked_names:
        return FAILURE_CONTRACT
    if "baseline_guardrail_trace" in blocked_names:
        return FAILURE_GUARDRAIL
    if "baseline_fallback_trace" in blocked_names:
        return FAILURE_SILENT_FALLBACK
    return _classify_from_checks(checks)


def live_mcp_enabled() -> bool:
    return os.getenv("MULAN_BASELINE_MCP_LIVE") == "1"


async def record_live_mcp_snapshot(
    *,
    cases: Iterable[BaselineCase],
    mcp_execute: Any,
    output_path: str | Path,
    snapshot_id: str,
    datasource_luid: str,
    connection_id: int,
) -> dict[str, Any]:
    """Record live MCP results using a caller-supplied executor.

    The comparator deliberately receives `mcp_execute` as a dependency so this
    module does not import Tableau clients at module import time.
    """
    if not live_mcp_enabled():
        raise RuntimeError("live MCP baseline recording requires MULAN_BASELINE_MCP_LIVE=1")

    snapshot: dict[str, Any] = {
        "snapshot_id": snapshot_id,
        "datasource_luid": datasource_luid,
        "connection_id": connection_id,
        "cases": {},
    }
    for case in cases:
        executable = case.baseline.get("executable") or {}
        if not executable:
            raise ValueError(f"case {case.id} has no baseline.executable")
        result = await mcp_execute(
            datasource_luid=datasource_luid,
            connection_id=connection_id,
            vizql_json=executable.get("vizql_json"),
            limit=executable.get("limit", 1000),
        )
        snapshot["cases"][case.id] = {
            "fields": result.get("fields") or [],
            "rows": result.get("rows") or [],
            "result_shape": case.baseline.get("result_shape") or {},
            "tolerances": case.baseline.get("tolerances") or {},
        }

    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2), encoding="utf-8")
    return snapshot

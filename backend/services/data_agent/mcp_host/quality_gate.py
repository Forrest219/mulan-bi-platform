"""Quality gate for MCP Host Q1-Q4 baseline comparison.

The gate compares live Mulan artifacts with the reviewed direct MCP baseline
stored in ``inbox/20260515-13-abtest-raw.json``. It deliberately compares by
QID and tabular artifact shape only; it does not encode business fields,
metrics, formulas, filters, or question mappings.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


GATE_PASS = "pass"
GATE_BLOCK = "block"

DEFAULT_QIDS = ("Q1", "Q2", "Q3", "Q4")
DEFAULT_BASELINE_PATH = Path(__file__).resolve().parents[4] / "inbox" / "20260515-13-abtest-raw.json"
DEFAULT_LIVE_ARTIFACT_PATH = (
    Path(__file__).resolve().parents[4] / "inbox" / "20260516-02-mulan-mcp-host-q1-q4-trace.json"
)

NUMERIC_REL_TOLERANCE = 1e-6
NUMERIC_ABS_TOLERANCE = 1e-6
_TABLE_KEYS = frozenset({"fields", "rows"})
_MCP_EVIDENCE_MARKERS = (
    "mcp",
    "query-datasource",
    "get-datasource-metadata",
    "tools/call",
)
_FORBIDDEN_QUERYSPEC_MARKERS = (
    "llm_queryspec",
    "llm_queryspec_repair",
    "queryspec_fallback",
    "qs_llm_invalid",
    "query_plan_rejected",
    "planning_skill_loader",
    "llm_mcp_args",
    "queryspec",
    "query_spec",
)


@dataclass(slots=True)
class MCPHostGateCheck:
    qid: str
    name: str
    status: str
    message: str
    details: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "qid": self.qid,
            "name": self.name,
            "status": self.status,
            "message": self.message,
            "details": self.details,
        }


@dataclass(slots=True)
class MCPHostCaseResult:
    qid: str
    status: str
    checks: list[MCPHostGateCheck]

    def to_dict(self) -> dict[str, Any]:
        return {
            "qid": self.qid,
            "status": self.status,
            "checks": [check.to_dict() for check in self.checks],
        }


@dataclass(slots=True)
class MCPHostQualityGateResult:
    status: str
    cases: list[MCPHostCaseResult]
    baseline_path: str | None = None
    live_artifact_path: str | None = None
    generated_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    @property
    def checks(self) -> list[MCPHostGateCheck]:
        return [check for case in self.cases for check in case.checks]

    def to_dict(self) -> dict[str, Any]:
        blocked = [check for check in self.checks if check.status == GATE_BLOCK]
        return {
            "schema_version": "mcp_host_quality_gate.v1",
            "status": self.status,
            "generated_at": self.generated_at,
            "baseline_path": self.baseline_path,
            "live_artifact_path": self.live_artifact_path,
            "qids": [case.qid for case in self.cases],
            "cases": [case.to_dict() for case in self.cases],
            "metrics": {
                "case_count": len(self.cases),
                "passed_count": sum(1 for case in self.cases if case.status == GATE_PASS),
                "blocked_count": sum(1 for case in self.cases if case.status == GATE_BLOCK),
                "blocker_count": len(blocked),
            },
            "blockers": [check.to_dict() for check in blocked],
            "rules": [
                "Q1-Q4 live artifacts must be present.",
                "Each live artifact must include MCP-backed response_data.",
                "Each live artifact must be free of forbidden QuerySpec markers.",
                "Each live response_data table must be no weaker than the direct MCP baseline table for the same QID.",
            ],
        }


def evaluate_mcp_host_quality_gate_from_files(
    *,
    runs_path: str | Path = DEFAULT_LIVE_ARTIFACT_PATH,
    baseline_path: str | Path = DEFAULT_BASELINE_PATH,
    report_path: str | Path | None = None,
    qids: Sequence[str] = DEFAULT_QIDS,
) -> MCPHostQualityGateResult:
    baseline = _load_json(baseline_path)
    runs = _load_json(runs_path)
    result = evaluate_mcp_host_quality_gate(
        live_artifacts=runs,
        baseline_artifacts=baseline,
        qids=qids,
        baseline_path=str(baseline_path),
        live_artifact_path=str(runs_path),
    )
    if report_path is not None:
        output = Path(report_path)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(result.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
    return result


def evaluate_mcp_host_quality_gate(
    *,
    live_artifacts: Mapping[str, Any],
    baseline_artifacts: Mapping[str, Any],
    qids: Sequence[str] = DEFAULT_QIDS,
    baseline_path: str | None = None,
    live_artifact_path: str | None = None,
) -> MCPHostQualityGateResult:
    cases = [
        _evaluate_qid(
            qid=str(qid),
            live_artifacts=live_artifacts,
            baseline_artifacts=baseline_artifacts,
        )
        for qid in qids
    ]
    status = GATE_BLOCK if any(case.status == GATE_BLOCK for case in cases) else GATE_PASS
    return MCPHostQualityGateResult(
        status=status,
        cases=cases,
        baseline_path=baseline_path,
        live_artifact_path=live_artifact_path,
    )


def _evaluate_qid(
    *,
    qid: str,
    live_artifacts: Mapping[str, Any],
    baseline_artifacts: Mapping[str, Any],
) -> MCPHostCaseResult:
    checks: list[MCPHostGateCheck] = []
    live_artifact = _artifact_for_qid(live_artifacts, qid)
    baseline_artifact = _baseline_artifact_for_qid(baseline_artifacts, qid)

    if live_artifact is None:
        checks.append(_check(qid, "live_artifact_present", GATE_BLOCK, "live artifact is missing"))
        return _case_result(qid, checks)
    checks.append(_check(qid, "live_artifact_present", GATE_PASS, "live artifact is present"))

    if baseline_artifact is None:
        checks.append(_check(qid, "direct_mcp_baseline_present", GATE_BLOCK, "direct MCP baseline is missing"))
        return _case_result(qid, checks)
    checks.append(_check(qid, "direct_mcp_baseline_present", GATE_PASS, "direct MCP baseline is present"))

    response_data = _extract_response_data(live_artifact)
    response_table = _select_table(response_data)
    has_response_table = response_table is not None
    has_mcp_evidence = _has_mcp_evidence(live_artifact)
    checks.append(
        _check(
            qid,
            "mcp_backed_response_data",
            GATE_PASS if has_response_table and has_mcp_evidence else GATE_BLOCK,
            "MCP-backed response_data is present"
            if has_response_table and has_mcp_evidence
            else "MCP-backed response_data is missing",
            {
                "has_response_table": has_response_table,
                "has_mcp_evidence": has_mcp_evidence,
            },
        )
    )

    forbidden = _find_forbidden_markers(live_artifact)
    checks.append(
        _check(
            qid,
            "forbidden_queryspec_markers_absent",
            GATE_BLOCK if forbidden else GATE_PASS,
            "forbidden QuerySpec markers found" if forbidden else "forbidden QuerySpec markers absent",
            {"markers": forbidden},
        )
    )

    baseline_table = _select_table(_baseline_payload(baseline_artifact))
    if baseline_table is None:
        checks.append(_check(qid, "direct_mcp_baseline_table", GATE_BLOCK, "direct MCP baseline table is missing"))
    elif response_data is not None:
        response_table = _select_table(response_data, required_fields=_field_names(baseline_table.get("fields") or []))
        if response_table is not None:
            checks.extend(_compare_tables(qid=qid, actual=response_table, expected=baseline_table))
        elif has_response_table:
            checks.append(
                _check(
                    qid,
                    "baseline_required_fields",
                    GATE_BLOCK,
                    "no response_data table contains all baseline fields",
                    {"expected": _field_names(baseline_table.get("fields") or [])},
                )
            )

    weaker = any(
        check.status == GATE_BLOCK
        for check in checks
        if check.name
        in {
            "mcp_backed_response_data",
            "direct_mcp_baseline_table",
            "baseline_required_fields",
            "baseline_row_count",
            "baseline_rows",
        }
    )
    checks.append(
        _check(
            qid,
            "correctness_not_weaker_than_direct_mcp",
            GATE_BLOCK if weaker else GATE_PASS,
            "live response_data is weaker than the direct MCP baseline"
            if weaker
            else "live response_data is not weaker than the direct MCP baseline",
        )
    )
    return _case_result(qid, checks)


def _compare_tables(
    *,
    qid: str,
    actual: Mapping[str, Any],
    expected: Mapping[str, Any],
) -> list[MCPHostGateCheck]:
    actual_fields = _field_names(actual.get("fields") or [])
    expected_fields = _field_names(expected.get("fields") or [])
    missing_fields = [field for field in expected_fields if field not in actual_fields]
    checks = [
        _check(
            qid,
            "baseline_required_fields",
            GATE_BLOCK if missing_fields else GATE_PASS,
            "baseline fields are missing" if missing_fields else "baseline fields are present",
            {
                "missing": missing_fields,
                "expected": expected_fields,
                "actual": actual_fields,
            },
        )
    ]
    if missing_fields:
        return checks

    actual_rows = _project_rows(actual.get("rows") or [], actual_fields, expected_fields)
    expected_rows = [list(row) for row in expected.get("rows") or []]
    checks.append(
        _check(
            qid,
            "baseline_row_count",
            GATE_BLOCK if len(actual_rows) != len(expected_rows) else GATE_PASS,
            "row count differs from direct MCP baseline" if len(actual_rows) != len(expected_rows) else "row count matches",
            {"expected": len(expected_rows), "actual": len(actual_rows)},
        )
    )

    missing_rows, extra_rows = _row_multiset_delta(actual_rows, expected_rows)
    checks.append(
        _check(
            qid,
            "baseline_rows",
            GATE_BLOCK if missing_rows or extra_rows else GATE_PASS,
            "rows differ from direct MCP baseline" if missing_rows or extra_rows else "rows match direct MCP baseline",
            {
                "missing": missing_rows[:10],
                "extra": extra_rows[:10],
                "missing_count": len(missing_rows),
                "extra_count": len(extra_rows),
                "numeric_rel_tolerance": NUMERIC_REL_TOLERANCE,
                "numeric_abs_tolerance": NUMERIC_ABS_TOLERANCE,
            },
        )
    )
    return checks


def _case_result(qid: str, checks: list[MCPHostGateCheck]) -> MCPHostCaseResult:
    status = GATE_BLOCK if any(check.status == GATE_BLOCK for check in checks) else GATE_PASS
    return MCPHostCaseResult(qid=qid, status=status, checks=checks)


def _check(
    qid: str,
    name: str,
    status: str,
    message: str,
    details: Mapping[str, Any] | None = None,
) -> MCPHostGateCheck:
    return MCPHostGateCheck(qid=qid, name=name, status=status, message=message, details=dict(details or {}))


def _load_json(path: str | Path) -> dict[str, Any]:
    with Path(path).open("r", encoding="utf-8") as fh:
        payload = json.load(fh)
    if not isinstance(payload, Mapping):
        raise ValueError(f"artifact must be a JSON object: {path}")
    return dict(payload)


def _artifact_for_qid(payload: Mapping[str, Any], qid: str) -> Mapping[str, Any] | None:
    direct = payload.get(qid)
    if isinstance(direct, Mapping):
        return direct
    for key in ("mulan", "runs", "cases", "artifacts", "results"):
        container = payload.get(key)
        if isinstance(container, Mapping) and isinstance(container.get(qid), Mapping):
            return container[qid]
        if isinstance(container, list):
            for item in container:
                if not isinstance(item, Mapping):
                    continue
                item_id = item.get("qid") or item.get("question_id") or item.get("id") or item.get("case_id")
                if str(item_id) == qid:
                    return item
    return None


def _baseline_artifact_for_qid(payload: Mapping[str, Any], qid: str) -> Mapping[str, Any] | None:
    mcp = payload.get("mcp")
    if isinstance(mcp, Mapping) and isinstance(mcp.get(qid), Mapping):
        return mcp[qid]
    return _artifact_for_qid(payload, qid)


def _baseline_payload(artifact: Mapping[str, Any]) -> Any:
    data = artifact.get("data")
    return data if data is not None else artifact


def _extract_response_data(artifact: Mapping[str, Any]) -> Mapping[str, Any] | None:
    for candidate in _response_data_candidates(artifact):
        table = _select_table(candidate)
        if table is not None:
            if isinstance(candidate, Mapping):
                return candidate
            return table
    return None


def _response_data_candidates(artifact: Mapping[str, Any]) -> Iterable[Any]:
    for key in ("response_data", "responseData"):
        if key in artifact:
            yield artifact[key]
    for parent_key in ("done", "result", "payload", "content", "data"):
        parent = artifact.get(parent_key)
        if isinstance(parent, Mapping):
            for key in ("response_data", "responseData"):
                if key in parent:
                    yield parent[key]
            if _select_table(parent) is not None:
                yield parent
    if _select_table(artifact) is not None:
        yield artifact
    events = artifact.get("events")
    if isinstance(events, list):
        for event in reversed(events):
            if not isinstance(event, Mapping):
                continue
            for key in ("response_data", "responseData", "table_data", "data", "payload", "result"):
                value = event.get(key)
                if _select_table(value) is not None:
                    yield value


def _select_table(value: Any, required_fields: Sequence[str] | None = None) -> Mapping[str, Any] | None:
    tables = list(_iter_tables(value))
    if not tables:
        return None
    if required_fields:
        required = set(required_fields)
        for table in tables:
            if required.issubset(set(_field_names(table.get("fields") or []))):
                return table
    return tables[0]


def _iter_tables(value: Any) -> Iterable[Mapping[str, Any]]:
    table = _coerce_table(value)
    if table is not None:
        yield table
        return
    if not isinstance(value, Mapping):
        return
    tables = value.get("tables")
    if isinstance(tables, Mapping):
        for item in tables.values():
            yield from _iter_tables(item)
    for key in ("data", "result", "payload", "content"):
        child = value.get(key)
        if child is not value:
            yield from _iter_tables(child)


def _coerce_table(value: Any) -> Mapping[str, Any] | None:
    if not isinstance(value, Mapping):
        return None
    if _TABLE_KEYS.issubset(value.keys()) and isinstance(value.get("rows"), list):
        return {"fields": list(value.get("fields") or []), "rows": [list(row) for row in value.get("rows") or []]}
    rows = value.get("data")
    fields = value.get("fields") or value.get("columns")
    if isinstance(rows, list) and rows and all(isinstance(row, Mapping) for row in rows):
        field_names = _field_names(fields or list(rows[0].keys()))
        return {
            "fields": field_names,
            "rows": [[row.get(field) for field in field_names] for row in rows],
        }
    if isinstance(rows, list) and isinstance(fields, list):
        return {"fields": list(fields), "rows": [list(row) for row in rows]}
    return None


def _field_names(fields: Iterable[Any]) -> list[str]:
    names: list[str] = []
    for field in fields:
        if isinstance(field, Mapping):
            value = (
                field.get("name")
                or field.get("field")
                or field.get("field_name")
                or field.get("caption")
                or field.get("field_caption")
                or field.get("label")
                or field.get("id")
            )
        else:
            value = field
        names.append(str(value))
    return names


def _project_rows(rows: Iterable[Sequence[Any]], actual_fields: Sequence[str], expected_fields: Sequence[str]) -> list[list[Any]]:
    indexes = [actual_fields.index(field) for field in expected_fields]
    projected = []
    for row in rows:
        row_values = list(row)
        projected.append([row_values[index] if index < len(row_values) else None for index in indexes])
    return projected


def _row_multiset_delta(actual_rows: list[list[Any]], expected_rows: list[list[Any]]) -> tuple[list[list[Any]], list[list[Any]]]:
    unmatched_actual = [list(row) for row in actual_rows]
    missing: list[list[Any]] = []
    for expected in expected_rows:
        match_idx = next((idx for idx, actual in enumerate(unmatched_actual) if _rows_match(actual, expected)), None)
        if match_idx is None:
            missing.append(list(expected))
        else:
            unmatched_actual.pop(match_idx)
    return missing, unmatched_actual


def _rows_match(actual: Sequence[Any], expected: Sequence[Any]) -> bool:
    if len(actual) != len(expected):
        return False
    return all(_values_match(left, right) for left, right in zip(actual, expected))


def _values_match(actual: Any, expected: Any) -> bool:
    actual_number = _to_number(actual)
    expected_number = _to_number(expected)
    if actual_number is not None and expected_number is not None:
        return math.isclose(
            actual_number,
            expected_number,
            rel_tol=NUMERIC_REL_TOLERANCE,
            abs_tol=NUMERIC_ABS_TOLERANCE,
        )
    return actual == expected


def _to_number(value: Any) -> float | None:
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


def _has_mcp_evidence(artifact: Mapping[str, Any]) -> bool:
    for item in _walk(artifact):
        if isinstance(item, Mapping):
            if item.get("mcp_backed") is True:
                return True
            tools = item.get("tools_used")
            if isinstance(tools, list) and any(_contains_mcp_marker(tool) for tool in tools):
                return True
            for key in ("tool", "name", "event", "type", "route", "source", "method"):
                value = item.get(key)
                if _contains_mcp_marker(value):
                    return True
        elif _contains_mcp_marker(item):
            return True
    return False


def _contains_mcp_marker(value: Any) -> bool:
    if not isinstance(value, str):
        return False
    lowered = value.lower()
    return any(marker in lowered for marker in _MCP_EVIDENCE_MARKERS)


def _find_forbidden_markers(artifact: Mapping[str, Any]) -> list[dict[str, str]]:
    matches: list[dict[str, str]] = []
    for path, value in _walk_with_path(artifact):
        if not isinstance(value, str):
            continue
        lowered = value.lower()
        for marker in _FORBIDDEN_QUERYSPEC_MARKERS:
            if marker in lowered:
                matches.append({"marker": marker, "path": path, "value": value[:160]})
                break
        if len(matches) >= 20:
            break
    return matches


def _walk(value: Any) -> Iterable[Any]:
    yield value
    if isinstance(value, Mapping):
        for key, child in value.items():
            yield key
            yield from _walk(child)
    elif isinstance(value, list):
        for child in value:
            yield from _walk(child)


def _walk_with_path(value: Any, path: str = "$") -> Iterable[tuple[str, Any]]:
    yield path, value
    if isinstance(value, Mapping):
        for key, child in value.items():
            key_text = str(key)
            yield f"{path}.{key_text}", key_text
            yield from _walk_with_path(child, f"{path}.{key_text}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            yield from _walk_with_path(child, f"{path}[{index}]")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Evaluate MCP Host Q1-Q4 quality gate.")
    parser.add_argument("--runs", default=str(DEFAULT_LIVE_ARTIFACT_PATH), help="Live Mulan MCP Host artifact JSON path.")
    parser.add_argument(
        "--baseline",
        default=str(DEFAULT_BASELINE_PATH),
        help="Baseline artifact JSON path. Defaults to inbox/20260515-13-abtest-raw.json.",
    )
    parser.add_argument("--report", help="Optional report JSON output path.")
    parser.add_argument("--qid", action="append", dest="qids", help="QID to include. May be repeated.")
    args = parser.parse_args(argv)

    result = evaluate_mcp_host_quality_gate_from_files(
        runs_path=args.runs,
        baseline_path=args.baseline,
        report_path=args.report,
        qids=tuple(args.qids or DEFAULT_QIDS),
    )
    print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2))
    return 0 if result.status == GATE_PASS else 2


if __name__ == "__main__":
    sys.exit(main())

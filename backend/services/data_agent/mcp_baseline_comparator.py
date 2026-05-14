"""MCP baseline comparator draft.

Draft target:
    backend/services/data_agent/mcp_baseline_comparator.py

CI should run snapshot comparison only. Live MCP recording/comparison must be
guarded by explicit env vars so PR runs do not require Tableau credentials.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Mapping, Optional

from services.data_agent.analysis_context import AnalysisContext
from services.data_agent.quality_gate import GateCheck, QualityGateResult, compare_to_baseline


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
    baseline = dict(case.baseline)
    if snapshot_case:
        baseline["rows"] = snapshot_case.get("rows")
        baseline.setdefault("result_shape", snapshot_case.get("result_shape") or {})
        baseline.setdefault("tolerances", snapshot_case.get("tolerances") or {})
    checks = compare_to_baseline(plan=ctx.query_plan, response_data=response_data, baseline=baseline)
    status = "block" if any(check.status == "block" for check in checks) else (
        "warn" if any(check.status == "warn" for check in checks) else "pass"
    )
    return BaselineComparison(
        case_id=case.id,
        status=status,
        checks=checks,
        snapshot_id=str(snapshot.get("snapshot_id") or "") or None,
    )


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

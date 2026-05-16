"""Tests for MCP Host Q1-Q4 quality gate."""

import json

import pytest

from services.data_agent.mcp_host.quality_gate import (
    DEFAULT_BASELINE_PATH,
    GATE_BLOCK,
    GATE_PASS,
    evaluate_mcp_host_quality_gate,
    evaluate_mcp_host_quality_gate_from_files,
)


pytestmark = pytest.mark.skip_db


QIDS = ("Q1", "Q2", "Q3", "Q4")


def _table(qid: str, value: float = 10.0) -> dict:
    return {
        "fields": ["group_key", "value"],
        "rows": [[qid, value]],
    }


def _baseline() -> dict:
    return {
        "mcp": {
            qid: {
                "duration": 1.0,
                "row_count": 1,
                "data": _table(qid),
            }
            for qid in QIDS
        }
    }


def _live_artifact(qid: str, table: dict | None = None) -> dict:
    return {
        "events": [
            {"type": "mcp_host_tool_call", "tool": "query-datasource"},
            {"type": "mcp_host_tool_result", "tool": "query-datasource", "status": "ok"},
        ],
        "done": {
            "response_data": table or _table(qid),
            "tools_used": ["query-datasource"],
        },
    }


def _live() -> dict:
    return {"mulan": {qid: _live_artifact(qid) for qid in QIDS}}


def _check(result, qid: str, name: str):
    case = next(item for item in result.cases if item.qid == qid)
    return next(item for item in case.checks if item.name == name)


def test_mcp_host_gate_passes_when_live_artifacts_match_direct_mcp_baseline(tmp_path):
    baseline_path = tmp_path / "baseline.json"
    runs_path = tmp_path / "runs.json"
    report_path = tmp_path / "report.json"
    baseline_path.write_text(json.dumps(_baseline()), encoding="utf-8")
    runs_path.write_text(json.dumps(_live()), encoding="utf-8")

    result = evaluate_mcp_host_quality_gate_from_files(
        runs_path=runs_path,
        baseline_path=baseline_path,
        report_path=report_path,
    )

    assert result.status == GATE_PASS
    assert all(case.status == GATE_PASS for case in result.cases)
    assert report_path.exists()
    assert json.loads(report_path.read_text())["metrics"]["passed_count"] == 4


def test_mcp_host_gate_blocks_when_live_response_is_weaker_than_direct_mcp_baseline():
    live = _live()
    live["mulan"]["Q2"] = _live_artifact("Q2", table=_table("Q2", value=9.0))

    result = evaluate_mcp_host_quality_gate(live_artifacts=live, baseline_artifacts=_baseline())

    assert result.status == GATE_BLOCK
    assert _check(result, "Q2", "baseline_rows").status == GATE_BLOCK
    assert _check(result, "Q2", "correctness_not_weaker_than_direct_mcp").status == GATE_BLOCK


def test_mcp_host_gate_blocks_for_forbidden_queryspec_markers():
    live = _live()
    live["mulan"]["Q3"]["events"].append({"type": "tool_call", "tool": "llm_queryspec"})

    result = evaluate_mcp_host_quality_gate(live_artifacts=live, baseline_artifacts=_baseline())

    assert result.status == GATE_BLOCK
    check = _check(result, "Q3", "forbidden_queryspec_markers_absent")
    assert check.status == GATE_BLOCK
    assert check.details["markers"][0]["marker"] == "llm_queryspec"


def test_mcp_host_gate_blocks_when_response_data_is_not_mcp_backed():
    live = _live()
    live["mulan"]["Q4"] = {"done": {"response_data": _table("Q4")}, "events": []}

    result = evaluate_mcp_host_quality_gate(live_artifacts=live, baseline_artifacts=_baseline())

    assert result.status == GATE_BLOCK
    assert _check(result, "Q4", "mcp_backed_response_data").status == GATE_BLOCK
    assert _check(result, "Q4", "correctness_not_weaker_than_direct_mcp").status == GATE_BLOCK


def test_default_baseline_path_points_to_abtest_raw_artifact():
    assert DEFAULT_BASELINE_PATH.as_posix().endswith("inbox/20260515-13-abtest-raw.json")

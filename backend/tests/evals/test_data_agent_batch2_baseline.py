"""Draft eval harness for batch2 MCP baseline.

This is intentionally a skeleton. In CI it should run snapshot-only checks
against recorded response_data fixtures. Live MCP compare/record must require:
    MULAN_BASELINE_MCP_LIVE=1
    MULAN_BASELINE_CONNECTION_ID=...
    MULAN_BASELINE_SNAPSHOT_DATE=...
"""

import os
from pathlib import Path

import pytest

from services.data_agent.mcp_baseline_comparator import load_cases, load_snapshot


pytestmark = pytest.mark.skip_db


FIXTURE_DIR = Path(__file__).parents[1] / "fixtures" / "data_agent" / "baseline"


@pytest.mark.parametrize("case", load_cases(FIXTURE_DIR / "batch2_cases.yaml"))
def test_batch2_case_contract_shape(case):
    assert case.id.startswith("batch2.")
    assert case.question
    assert case.expected_patch.get("patch_type")
    assert case.expected_gate in {"pass", "warn", "block", "fallback"}


def test_live_mcp_options_are_explicit():
    if os.getenv("MULAN_BASELINE_MCP_LIVE") != "1":
        pytest.skip("live MCP baseline is manual/nightly only")

    assert os.getenv("MULAN_BASELINE_CONNECTION_ID")
    assert os.getenv("MULAN_BASELINE_SNAPSHOT_DATE")


def test_snapshot_fixture_loads():
    snapshot = load_snapshot(FIXTURE_DIR / "mcp_snapshots" / "superstore_2026_05_13.json")

    assert snapshot["snapshot_id"] == "superstore_2026_05_13"
    assert "cases" in snapshot

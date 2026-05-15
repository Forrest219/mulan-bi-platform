"""Draft eval harness for batch2 MCP baseline.

This is intentionally a skeleton. In CI it should run snapshot-only checks
against recorded response_data fixtures. Live MCP compare/record must require:
    MULAN_BASELINE_MCP_LIVE=1
    MULAN_BASELINE_CONNECTION_ID=...
    MULAN_BASELINE_SNAPSHOT_DATE=...
"""

import os
import json
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
    assert snapshot["review_status"] == "reviewed"
    assert {
        "batch2.q1_overall_kpis",
        "batch2.q2_followup_metric_trend",
        "batch2.q4_continue_split_each_year",
        "batch2.q5_subcategories_without_sales_2025",
        "batch2.q6_top10_customers",
        "batch2.q7_customer_dengbao_history",
        "batch2.q8_subcategory_profit_continuous_growth",
        "batch2.q9_provinces_always_loss",
        "batch2.q10_loss_root_cause_liaoning_fujian_2024",
    }.issubset(snapshot["cases"])


def test_quality_report_template_loads():
    template = json.loads((FIXTURE_DIR / "quality_report_template.json").read_text(encoding="utf-8"))

    assert template["schema_version"] == "mcp_accuracy_quality_report.v1"
    assert template["snapshot_id"] == "superstore_2026_05_13"
    assert {case["case_id"] for case in template["cases"]} == {
        "batch2.q1_overall_kpis",
        "batch2.q2_followup_metric_trend",
        "batch2.q4_continue_split_each_year",
        "batch2.q5_subcategories_without_sales_2025",
        "batch2.q6_top10_customers",
        "batch2.q7_customer_dengbao_history",
        "batch2.q8_subcategory_profit_continuous_growth",
        "batch2.q9_provinces_always_loss",
        "batch2.q10_loss_root_cause_liaoning_fujian_2024",
    }

from pathlib import Path

import pytest
import yaml

from services.data_agent.result_guardrail import ResultGuardrailInput, evaluate_result_guardrail

pytestmark = pytest.mark.skip_db


FIXTURE = Path(__file__).resolve().parents[2] / "fixtures" / "data_agent_golden_set" / "batch2_q0_q10.yaml"


def _load_cases():
    with FIXTURE.open("r", encoding="utf-8") as fh:
        return yaml.safe_load(fh) or []


def test_golden_set_fixture_has_q0_to_q10_and_p0_contract():
    cases = _load_cases()
    ids = [case["id"] for case in cases]
    assert ids == [f"Q{i}" for i in range(11)]

    p0_ids = [case["id"] for case in cases if case.get("priority") == "P0"]
    assert set(p0_ids) == {"Q2", "Q4", "Q5", "Q8", "Q9", "Q10"}


def test_golden_set_harness_marks_unverified_fallback_as_needs_review():
    out = evaluate_result_guardrail(
        ResultGuardrailInput(
            question="test",
            chain_mode="mcp_host",
            fallback_triggered=True,
            fallback_reason="queryspec_mcp_fallback",
            semantic_operator="aggregate",
            context_snapshot={},
            tool_name="query-datasource",
            safe_args={},
            result={"fields": ["Metric A"], "rows": [[1]], "metadata": {}},
            thresholds={"max_detail_rows": 200},
        )
    )
    assert out.semantic_status == "needs_review"
    assert out.decision == "review"

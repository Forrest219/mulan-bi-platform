"""Draft tests for services.data_agent.analysis_context."""

import uuid

import pytest

from services.data_agent.analysis_context import (
    ANALYSIS_CONTEXT_VERSION,
    AnalysisContext,
    build_response_data_with_context,
    load_latest_analysis_context,
)


pytestmark = pytest.mark.skip_db


def _context() -> AnalysisContext:
    return AnalysisContext.new(
        conversation_id=str(uuid.uuid4()),
        run_id=str(uuid.uuid4()),
        trace_id="t-context",
        turn_no=1,
        scope={
            "tenant_id": None,
            "user_id": 7,
            "role": "analyst",
            "connection_id": 12,
            "connection_name": "Tableau Server",
            "connection_type": "tableau",
            "datasource_luid": "ds-luid",
            "datasource_name": "订单+ (示例 - 超市)",
        },
        analysis_type="lookup",
        confidence=0.91,
        query_plan={
            "subject": "销售表现",
            "metrics": [{"name": "销售额", "field_caption": "净额", "aggregation": "SUM"}],
            "dimensions": [{"name": "类别", "field_caption": "类别"}],
            "filters": [],
        },
    )


class _Message:
    def __init__(self, role, response_data):
        self.role = role
        self.response_data = response_data


class _SessionMgr:
    def __init__(self, messages):
        self.messages = messages

    def get_conversation_messages(self, **kwargs):
        return self.messages


def test_analysis_context_round_trips_with_stable_hash():
    context = _context()

    payload = context.to_dict()
    restored = AnalysisContext.from_payload(payload)

    assert payload["schema_version"] == ANALYSIS_CONTEXT_VERSION
    assert restored.to_dict()["context_hash"] == payload["context_hash"]
    assert restored.query_plan["metrics"][0]["name"] == "销售额"


def test_build_response_data_embeds_context_patch_and_gate():
    context = _context()
    response_data = build_response_data_with_context(
        {"fields": ["类别", "销售额"], "rows": [["家具", 100]]},
        analysis_context=context,
        query_plan_patch={"patch_type": "add_dimension"},
        quality_gate={"gate_status": "pass"},
    )

    assert response_data["analysis_context"]["context_hash"] == context.hash
    assert response_data["query_plan_patch"]["patch_type"] == "add_dimension"
    assert response_data["quality_gate"]["gate_status"] == "pass"


def test_load_latest_analysis_context_uses_latest_assistant_message():
    old_context = _context()
    new_context = _context()
    new_context.turn_no = 2
    mgr = _SessionMgr([
        _Message("assistant", {"analysis_context": old_context.to_dict()}),
        _Message("user", None),
        _Message("assistant", {"analysis_context": new_context.to_dict()}),
    ])

    loaded = load_latest_analysis_context(
        mgr,
        conversation_id=uuid.UUID(new_context.conversation_id),
        user_id=7,
    )

    assert loaded.turn_no == 2
    assert loaded.hash == new_context.hash

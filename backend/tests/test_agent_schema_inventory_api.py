import json
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

from app.core.database import get_db
from app.core.dependencies import get_current_user
from services.data_agent.deterministic import DeterministicRouteResult
from services.data_agent.models import AgentConversationMessage, BiAgentRun, BiAgentStep
from services.skills.models import AgentSkill, AgentSkillVersion


def _parse_sse(response):
    events = []
    for line in response.text.splitlines():
        if line.startswith("data: "):
            events.append(json.loads(line[len("data: "):]))
    return events


def _business_events(events):
    return [
        event
        for event in events
        if event.get("type") not in {"intent_classifier", "route_decision", "explainability"}
    ]


def _override_db(db_session):
    def _get_db():
        yield db_session

    return _get_db


def _current_user():
    return {"id": 1001, "role": "analyst", "tenant_id": None}


def _create_skill_version(db_session) -> uuid.UUID:
    skill = AgentSkill(
        skill_key=f"schema-test-{uuid.uuid4()}",
        name="Schema Test",
        category="data",
        is_enabled=True,
    )
    db_session.add(skill)
    db_session.flush()
    version = AgentSkillVersion(
        skill_id=skill.id,
        version_number="v1",
        description="schema tool",
        input_schema={"type": "object", "properties": {}},
        is_active=True,
    )
    db_session.add(version)
    db_session.commit()
    return version.id


async def _fake_create_engine_with_skills(_db):
    return object(), object()


def test_schema_inventory_stream_uses_deterministic_route_and_persists_observability(db_session):
    from app.main import app

    skill_version_id = _create_skill_version(db_session)
    result = DeterministicRouteResult(
        answer="## 当前连接 数据源清单\n\n共 1 个资产，展示 1 个，省略 0 个。",
        response_data={"total_count": 1, "assets": [{"name": "Orders"}]},
        tools_used=["schema"],
        response_type="schema_inventory",
        steps_count=1,
        tool_name="schema",
        tool_params={},
        tool_result_summary="total=1, shown=1, omitted=0",
        skill_version_id=str(skill_version_id),
    )

    async def _fail_run_agent(**_kwargs):
        raise AssertionError("ReAct should not run for schema inventory")
        yield

    app.dependency_overrides[get_current_user] = _current_user
    app.dependency_overrides[get_db] = _override_db(db_session)
    try:
        with (
            patch("app.api.agent.create_engine_with_skills", _fake_create_engine_with_skills),
            patch(
                "app.api.agent.get_active_skill_version",
                return_value={
                    "is_configured": True,
                    "is_enabled": True,
                    "version_id": str(skill_version_id),
                },
            ),
            patch("app.api.agent.run_schema_inventory_route", new=AsyncMock(return_value=result)) as route_mock,
            patch("app.api.agent.run_agent", _fail_run_agent),
            patch("app.api.agent.log_nlq_query"),
        ):
            client = TestClient(app, raise_server_exceptions=True)
            response = client.post("/api/agent/stream", json={"question": "有哪些数据源"})
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    events = _parse_sse(response)
    core_events = _business_events(events)
    event_types = [event["type"] for event in core_events]
    assert event_types == ["metadata", "thinking", "tool_call", "tool_result", "token", "done"]
    assert core_events[2] == {"type": "tool_call", "tool": "schema", "params": {}}
    token_answer = "".join(event["content"] for event in core_events if event["type"] == "token")
    done = core_events[-1]
    assert done["answer"] == token_answer
    assert done["response_type"] == "schema_inventory"
    assert done["response_data"] == result.response_data
    assert done["tools_used"] == ["schema"]
    assert done["steps_count"] == 1
    route_mock.assert_awaited_once()
    assert route_mock.await_args.kwargs["active_skill_version"]["version_id"] == str(skill_version_id)

    run_id = uuid.UUID(done["run_id"])
    run = db_session.query(BiAgentRun).filter(BiAgentRun.id == run_id).one()
    assert run.status == "completed"
    assert run.response_type == "schema_inventory"
    assert run.tools_used == ["schema"]

    steps = (
        db_session.query(BiAgentStep)
        .filter(BiAgentStep.run_id == run_id)
        .order_by(BiAgentStep.step_number)
        .all()
    )
    assert [step.step_type for step in steps] == ["thinking", "tool_call", "tool_result", "answer"]
    assert steps[1].tool_name == "schema"
    assert steps[1].tool_params == {}
    assert steps[1].skill_version_id == skill_version_id

    assistant = (
        db_session.query(AgentConversationMessage)
        .filter(AgentConversationMessage.role == "assistant")
        .order_by(AgentConversationMessage.id.desc())
        .first()
    )
    assert assistant.response_type == "schema_inventory"
    assert assistant.response_data == result.response_data
    assert assistant.tools_used == ["schema"]
    assert assistant.steps_count == 1

    app.dependency_overrides[get_current_user] = _current_user
    app.dependency_overrides[get_db] = _override_db(db_session)
    try:
        messages_response = client.get(f"/api/agent/conversations/{core_events[0]['conversation_id']}/messages")
        assert messages_response.status_code == 200
        assistant_messages = [m for m in messages_response.json() if m["role"] == "assistant"]
        assert assistant_messages[-1]["run_id"] == str(run_id)
    finally:
        app.dependency_overrides.clear()


def test_schema_inventory_disabled_returns_business_error_without_fallback(db_session):
    from app.main import app

    async def _fail_run_agent(**_kwargs):
        raise AssertionError("ReAct should not run when schema tool is disabled")
        yield

    app.dependency_overrides[get_current_user] = _current_user
    app.dependency_overrides[get_db] = _override_db(db_session)
    try:
        with (
            patch("app.api.agent.create_engine_with_skills", _fake_create_engine_with_skills),
            patch(
                "app.api.agent.get_active_skill_version",
                return_value={"is_configured": True, "is_enabled": False, "version_id": None},
            ),
            patch("app.api.agent.run_schema_inventory_route", new=AsyncMock()) as route_mock,
            patch("app.api.agent.run_agent", _fail_run_agent),
            patch("app.api.agent.log_nlq_query"),
        ):
            client = TestClient(app, raise_server_exceptions=True)
            response = client.post("/api/agent/stream", json={"question": "有哪些数据源"})
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    events = _parse_sse(response)
    core_events = _business_events(events)
    assert [event["type"] for event in core_events] == ["metadata", "error"]
    assert core_events[-1]["error_code"] == "AGENT_003"
    assert "schema 工具已禁用" in core_events[-1]["message"]
    route_mock.assert_not_awaited()


def test_non_inventory_question_keeps_existing_react_path(db_session):
    from app.main import app

    async def _fake_run_agent(**_kwargs):
        yield SimpleNamespace(
            type="metadata",
            content={"conversation_id": str(uuid.uuid4()), "run_id": str(uuid.uuid4())},
        )
        yield SimpleNamespace(
            type="done",
            content={
                "answer": "ReAct answer",
                "trace_id": "trace-react",
                "run_id": str(uuid.uuid4()),
                "tools_used": [],
                "response_type": "text",
                "response_data": None,
                "steps_count": 0,
                "execution_time_ms": 1,
            },
        )

    app.dependency_overrides[get_current_user] = _current_user
    app.dependency_overrides[get_db] = _override_db(db_session)
    try:
        with (
            patch("app.api.agent.create_engine_with_skills", _fake_create_engine_with_skills),
            patch("app.api.agent.run_agent", _fake_run_agent),
            patch("app.api.agent.run_schema_inventory_route", new=AsyncMock()) as route_mock,
            patch("app.api.agent.log_nlq_query"),
        ):
            client = TestClient(app, raise_server_exceptions=True)
            response = client.post("/api/agent/stream", json={"question": "分析一下本月销售额"})
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    events = _parse_sse(response)
    core_events = _business_events(events)
    assert core_events[0]["type"] == "metadata"
    assert core_events[-1]["type"] == "done"
    assert all(event["type"] == "token" for event in core_events[1:-1])
    assert "".join(event["content"] for event in core_events[1:-1]) == "ReAct answer"
    assert core_events[-1]["answer"] == "ReAct answer"
    route_mock.assert_not_awaited()

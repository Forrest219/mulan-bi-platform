import json
import uuid
from contextlib import contextmanager

from fastapi.testclient import TestClient
from sqlalchemy import text

from app.core.database import get_db
from app.core.dependencies import get_current_user
from services.data_agent.models import AgentConversationMessage, BiAgentRun


FALLBACK_QUESTION = "???"
FALLBACK_ERROR_CODE = "ROUTER_CLARIFY_REQUIRED"


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


async def _fake_create_engine_with_skills(_db):
    return object(), object()


def _ensure_message_feedback_table(db_session):
    db_session.execute(
        text(
            """
            CREATE TABLE IF NOT EXISTS message_feedback (
                id SERIAL PRIMARY KEY,
                user_id INTEGER NOT NULL,
                username VARCHAR(128),
                conversation_id VARCHAR(128),
                message_index INTEGER,
                question TEXT,
                answer_summary VARCHAR(100),
                rating VARCHAR(4) NOT NULL,
                created_at TIMESTAMP
            )
            """
        )
    )
    db_session.commit()


@contextmanager
def _agent_test_client(db_session):
    from app.main import app

    app.dependency_overrides[get_current_user] = _current_user
    app.dependency_overrides[get_db] = _override_db(db_session)
    client = TestClient(app, raise_server_exceptions=True)
    try:
        yield client
    finally:
        client.close()
        app.dependency_overrides.clear()


def _post_fallback_stream(client):
    return client.post(
        "/api/agent/stream",
        json={"question": FALLBACK_QUESTION},
    )


def _latest_conversation_id(db_session):
    user_message = (
        db_session.query(AgentConversationMessage)
        .filter(AgentConversationMessage.role == "user")
        .order_by(AgentConversationMessage.id.desc())
        .first()
    )
    assert user_message is not None
    return user_message.conversation_id


def test_router_clarify_fallback_persists_message_and_monitor_run(db_session, monkeypatch):
    from app.api.agent_admin import list_agent_runs

    monkeypatch.setattr(
        "app.api.agent.create_engine_with_skills",
        _fake_create_engine_with_skills,
    )
    monkeypatch.setattr("app.api.agent.log_nlq_query", lambda **_kwargs: None)

    with _agent_test_client(db_session) as client:
        response = _post_fallback_stream(client)

        assert response.status_code == 200
        events = _business_events(_parse_sse(response))
        assert events[-1]["type"] == "done"
        done = events[-1]
        assert done["response_type"] == "fallback"
        assert done["response_data"]["fallback_type"] == "clarification_required"
        assert done["response_data"]["error_code"] == FALLBACK_ERROR_CODE
        assert done["answer"]
        assert done["answer"] == (
            "我还不能确定你是想查看数据资产，还是查询业务数据。\n\n"
            "请选择：查看数据资产/字段结构，或查询业务数据/指标。"
        )

        run_id = uuid.UUID(done["run_id"])
        run = db_session.query(BiAgentRun).filter(BiAgentRun.id == run_id).one()
        assert run.status == "completed"
        assert run.response_type == "fallback"
        assert run.error_code == FALLBACK_ERROR_CODE
        assert run.tools_used == []

        conversation_id = run.conversation_id
        messages_response = client.get(f"/api/agent/conversations/{conversation_id}/messages")
        assert messages_response.status_code == 200
        assistant_messages = [m for m in messages_response.json() if m["role"] == "assistant"]
        assert assistant_messages
        assert assistant_messages[-1]["content"] == done["answer"]
        assert assistant_messages[-1]["response_type"] == "fallback"
        assert assistant_messages[-1]["response_data"]["error_code"] == FALLBACK_ERROR_CODE
        assert assistant_messages[-1]["run_id"] == str(run_id)

    _ensure_message_feedback_table(db_session)
    monitor = list_agent_runs(
        db=db_session,
        _user={"id": 1, "role": "admin"},
        limit=20,
        offset=0,
        status=None,
        run_id=str(run_id),
    )
    assert monitor.total == 1
    assert monitor.items[0].id == str(run_id)
    assert monitor.items[0].status == "completed"


def test_fallback_error_code_contract_allows_router_clarify_required():
    assert len(FALLBACK_ERROR_CODE) == 23
    assert BiAgentRun.error_code.type.length >= 128


def test_telemetry_failure_does_not_drop_fallback_assistant_message(db_session, monkeypatch):
    monkeypatch.setattr(
        "app.api.agent.create_engine_with_skills",
        _fake_create_engine_with_skills,
    )
    monkeypatch.setattr("app.api.agent.log_nlq_query", lambda **_kwargs: None)

    original_add = db_session.add

    def add_with_telemetry_failure(instance, *args, **kwargs):
        if isinstance(instance, BiAgentRun):
            raise RuntimeError("simulated telemetry insert failure")
        return original_add(instance, *args, **kwargs)

    monkeypatch.setattr(db_session, "add", add_with_telemetry_failure)

    with _agent_test_client(db_session) as client:
        response = _post_fallback_stream(client)
        assert response.status_code == 200
        events = _business_events(_parse_sse(response))
        assert events[-1]["type"] == "done"
        done = events[-1]
        assert done["response_data"]["error_code"] == FALLBACK_ERROR_CODE

        conversation_id = _latest_conversation_id(db_session)
        messages_response = client.get(f"/api/agent/conversations/{conversation_id}/messages")
        assert messages_response.status_code == 200
        assistant_messages = [m for m in messages_response.json() if m["role"] == "assistant"]
        assert assistant_messages
        assert assistant_messages[-1]["content"] == done["answer"]
        assert assistant_messages[-1]["response_data"]["error_code"] == FALLBACK_ERROR_CODE


def test_assistant_message_failure_returns_error_not_done(db_session, monkeypatch):
    import app.api.agent as agent_api

    monkeypatch.setattr(
        "app.api.agent.create_engine_with_skills",
        _fake_create_engine_with_skills,
    )
    monkeypatch.setattr("app.api.agent.log_nlq_query", lambda **_kwargs: None)

    original_persist_message = agent_api.SessionManager.persist_message

    def persist_message_with_assistant_failure(self, *args, **kwargs):
        role = kwargs.get("role") if "role" in kwargs else args[1]
        if role == "assistant":
            raise RuntimeError("simulated assistant message insert failure")
        return original_persist_message(self, *args, **kwargs)

    monkeypatch.setattr(
        agent_api.SessionManager,
        "persist_message",
        persist_message_with_assistant_failure,
    )

    with _agent_test_client(db_session) as client:
        response = _post_fallback_stream(client)

    assert response.status_code == 200
    events = _business_events(_parse_sse(response))
    assert events
    assert all(event["type"] != "done" for event in events)
    assert events[-1]["type"] == "error"
    assert events[-1]["error_code"] == "AGENT_PERSISTENCE_FAILED"

    conversation_id = _latest_conversation_id(db_session)
    assistant_count = (
        db_session.query(AgentConversationMessage)
        .filter(
            AgentConversationMessage.conversation_id == conversation_id,
            AgentConversationMessage.role == "assistant",
        )
        .count()
    )
    assert assistant_count == 0

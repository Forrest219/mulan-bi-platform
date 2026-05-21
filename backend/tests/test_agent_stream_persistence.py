import json
import uuid

from fastapi.testclient import TestClient

from app.core.database import get_db
from app.core.dependencies import get_current_user
from app.api import agent as agent_api
from services.data_agent.fallback import make_clarification_fallback
from services.data_agent.router_guardrail import classify_homepage_question
from services.data_agent.session import AgentSession


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


class _TelemetryFailDb:
    def __init__(self):
        self.rollbacks = 0

    def add(self, _obj):
        pass

    def flush(self):
        raise RuntimeError("telemetry down")

    def rollback(self):
        self.rollbacks += 1


class _CapturingSessionManager:
    def __init__(self):
        self.messages = []

    def persist_message(self, **kwargs):
        self.messages.append(kwargs)


def test_standard_fallback_telemetry_failure_still_persists_assistant(caplog):
    session = AgentSession(conversation_id=uuid.uuid4(), user_id=1001)
    db = _TelemetryFailDb()
    session_mgr = _CapturingSessionManager()
    fallback = make_clarification_fallback(
        trace_id="trace-fallback-telemetry",
        route_decision=classify_homepage_question("帮我查一下"),
    )
    caplog.set_level("ERROR", logger="app.api.agent")

    agent_api._write_standard_fallback_run(
        db=db,
        run_id=uuid.uuid4(),
        session=session,
        session_mgr=session_mgr,
        current_user={"id": 1001},
        question="帮我查一下",
        connection_id=None,
        fallback=fallback,
        execution_time_ms=12,
    )

    assert db.rollbacks == 1
    assert session_mgr.messages[-1]["role"] == "assistant"
    assert session_mgr.messages[-1]["response_type"] == "fallback"
    telemetry_logs = [
        record
        for record in caplog.records
        if record.message == "Agent fallback telemetry persistence failed"
    ]
    assert telemetry_logs
    assert telemetry_logs[-1].conversation_id == str(session.conversation_id)
    assert telemetry_logs[-1].trace_id == "trace-fallback-telemetry"
    assert telemetry_logs[-1].error_code == "ROUTER_CLARIFY_REQUIRED"


def test_clarification_fallback_assistant_persistence_failure_returns_error_without_done(
    db_session,
    monkeypatch,
):
    from app.main import app

    original_persist_message = agent_api.SessionManager.persist_message

    def _fail_assistant_persist(self, *args, **kwargs):
        if kwargs.get("role") == "assistant":
            raise RuntimeError("assistant store down")
        return original_persist_message(self, *args, **kwargs)

    monkeypatch.setattr(agent_api, "create_engine_with_skills", _fake_create_engine_with_skills)
    monkeypatch.setattr(agent_api.SessionManager, "persist_message", _fail_assistant_persist)

    app.dependency_overrides[get_current_user] = _current_user
    app.dependency_overrides[get_db] = _override_db(db_session)
    try:
        client = TestClient(app, raise_server_exceptions=True)
        response = client.post("/api/agent/stream", json={"question": "帮我查一下"})
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    core_events = _business_events(_parse_sse(response))
    assert core_events[-1]["type"] == "error"
    assert core_events[-1]["error_code"] == "AGENT_PERSISTENCE_FAILED"
    assert core_events[-1]["retryable"] is True
    assert all(event["type"] != "done" for event in core_events)

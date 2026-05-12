import json
import uuid
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api import help_agent
from app.core.dependencies import get_current_user


pytestmark = pytest.mark.skip_db


class _Result:
    def __init__(self, rows):
        self._rows = [SimpleNamespace(_mapping=row) for row in rows]

    def all(self):
        return self._rows

    def first(self):
        return self._rows[0] if self._rows else None


class _FakeDB:
    def __init__(self, responses):
        self.responses = list(responses)
        self.statements = []
        self.committed = False

    def execute(self, statement, params=None):
        self.statements.append((str(statement), params or {}))
        rows = self.responses.pop(0) if self.responses else []
        return _Result(rows)

    def commit(self):
        self.committed = True

    def rollback(self):
        pass


def _client_with_user(app, user):
    app.dependency_overrides[get_current_user] = lambda: user
    return TestClient(app, raise_server_exceptions=False)


def _make_app():
    app = FastAPI()
    app.include_router(help_agent.router)
    return app


def test_help_agent_stream_consumes_mock_service(monkeypatch):
    class MockHelpAgentService:
        async def stream(self, request, user):
            assert request["question"] == "这个 run 为什么失败？"
            assert user["id"] == 7
            yield {"type": "metadata", "conversation_id": str(uuid.uuid4()), "run_id": str(uuid.uuid4())}
            yield {"type": "diagnostic_progress", "step_key": "diagnose_agent_run:1", "status": "completed"}
            yield {"type": "done", "answer": "截至当前快照，诊断完成。", "response_type": "help"}

    monkeypatch.setattr(help_agent, "HelpAgentService", MockHelpAgentService)
    app = _make_app()
    client = _client_with_user(app, {"id": 7, "username": "u7", "role": "user"})
    try:
        with client.stream(
            "POST",
            "/api/help-agent/stream",
            json={"question": "这个 run 为什么失败？"},
        ) as resp:
            body = resp.read().decode("utf-8")
        assert resp.status_code == 200
        events = [
            json.loads(line.removeprefix("data: "))
            for line in body.splitlines()
            if line.startswith("data: ")
        ]
        assert [event["type"] for event in events] == ["metadata", "diagnostic_progress", "done"]
    finally:
        app.dependency_overrides.clear()


def test_help_agent_conversations_query_help_tables_only():
    now = datetime(2026, 5, 13, tzinfo=timezone.utc)
    fake_db = _FakeDB([
        [{
            "id": str(uuid.uuid4()),
            "title": "诊断会话",
            "status": "active",
            "last_page_path": "/agents/agent-monitor",
            "message_count": 2,
            "created_at": now,
            "updated_at": now,
        }]
    ])
    app = _make_app()
    app.dependency_overrides[get_current_user] = lambda: {"id": 9, "username": "u9", "role": "user"}
    app.dependency_overrides[help_agent.get_db] = lambda: fake_db
    try:
        client = TestClient(app, raise_server_exceptions=False)
        resp = client.get("/api/help-agent/conversations")
        assert resp.status_code == 200
        assert resp.json()[0]["message_count"] == 2
        sql = fake_db.statements[0][0]
        assert "help_agent_conversations" in sql
        assert "help_agent_messages" in sql
        assert " FROM agent_conversations" not in sql
        assert " JOIN agent_conversation_messages" not in sql
    finally:
        app.dependency_overrides.clear()


def test_help_agent_messages_forbidden_for_non_owner():
    conversation_id = str(uuid.uuid4())
    fake_db = _FakeDB([[{"user_id": 99}]])
    app = _make_app()
    app.dependency_overrides[get_current_user] = lambda: {"id": 9, "username": "u9", "role": "user"}
    app.dependency_overrides[help_agent.get_db] = lambda: fake_db
    try:
        client = TestClient(app, raise_server_exceptions=False)
        resp = client.get(f"/api/help-agent/conversations/{conversation_id}/messages")
        assert resp.status_code == 403
        assert resp.json()["detail"]["error_code"] == "HLP_003"
    finally:
        app.dependency_overrides.clear()

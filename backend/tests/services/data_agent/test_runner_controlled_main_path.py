import uuid

import pytest

from services.data_agent.intent_classifier import classify_intent
from services.data_agent.models import BiAgentRun, BiAgentStep
from services.data_agent.response import AgentEvent
from services.data_agent.runner import run_agent
from services.data_agent.session import AgentSession
from services.data_agent.tool_base import ToolContext


pytestmark = pytest.mark.skip_db


class _FakeDb:
    def __init__(self):
        self.added = []
        self.updates = []

    def add(self, obj):
        self.added.append(obj)

    def commit(self):
        pass

    def refresh(self, obj):
        if isinstance(obj, BiAgentRun) and obj.id is None:
            obj.id = uuid.uuid4()

    def query(self, model):
        return _FakeQuery(self)


class _FakeQuery:
    def __init__(self, db):
        self.db = db

    def filter(self, *args):
        return self

    def update(self, values, synchronize_session=False):
        self.db.updates.append(values)
        return 1


class _NoEngineFallback:
    async def run(self, *args, **kwargs):
        raise AssertionError("data intents must not enter ReAct when controlled main path is enforced")
        yield AgentEvent(type="answer", content="unreachable")


class _FakeSessionManager:
    def __init__(self):
        self.messages = []

    def persist_message(self, **kwargs):
        self.messages.append(kwargs)

    def get_conversation_messages(self, **kwargs):
        return []


@pytest.mark.asyncio
async def test_data_intent_returns_guarded_error_instead_of_schema_fallback(monkeypatch):
    monkeypatch.setattr("services.data_agent.runner.is_direct_query", lambda question: False)

    db = _FakeDb()
    session_mgr = _FakeSessionManager()
    session = AgentSession(conversation_id=uuid.uuid4(), user_id=7)
    context = ToolContext(
        session_id=str(session.conversation_id),
        user_id=7,
        connection_id=2,
        connection_type="tableau",
        trace_id="t-controlled",
    )
    intent_result = classify_intent("按收入列出排名最高的产品", connection_type="tableau")

    events = [
        event
        async for event in run_agent(
            engine=_NoEngineFallback(),
            context=context,
            session_mgr=session_mgr,
            session=session,
            question="按收入列出排名最高的产品",
            trace_id="t-controlled",
            current_user={"id": 7},
            db=db,
            connection_id=2,
            intent_result=intent_result,
            enforce_controlled_data_path=True,
        )
    ]

    assert [event.type for event in events] == ["metadata", "thinking", "error"]
    error_payload = events[-1].content
    assert error_payload["fallback_type"] == "query_plan_unavailable"
    assert error_payload["intent_classifier"]["intent"] == "ranking"
    assert error_payload["controlled_chain"]["status"] == "failed"
    assert "schema" not in error_payload.get("tools_used", [])
    assert not session_mgr.messages

    intent_steps = [
        obj
        for obj in db.added
        if isinstance(obj, BiAgentStep) and obj.tool_name == "intent_classifier"
    ]
    assert len(intent_steps) == 1
    assert '"intent": "ranking"' in intent_steps[0].content
    assert db.updates[-1][BiAgentRun.response_type] == "fallback"


@pytest.mark.asyncio
async def test_controlled_transient_failure_records_tools_without_chat_message(monkeypatch):
    async def _fake_controlled_path(**kwargs):
        yield AgentEvent(type="thinking", content="受控链路")
        yield AgentEvent(type="tool_call", content={"tool": "tableau_mcp", "params": {"operator": "aggregate"}})
        yield AgentEvent(
            type="tool_result",
            content={
                "tool": "tableau_mcp",
                "result": {"success": False, "error": "read ECONNRESET", "data": {"error": "read ECONNRESET"}},
            },
        )
        yield AgentEvent(
            type="error",
            content={
                "error_code": "mcp_execution_failed",
                "message": "Tableau MCP 查询失败，本次不输出结论。",
                "fallback_type": "query_plan_unavailable",
            },
        )

    monkeypatch.setattr("services.data_agent.runner.run_mcp_first_main_path", _fake_controlled_path)

    db = _FakeDb()
    session_mgr = _FakeSessionManager()
    session = AgentSession(conversation_id=uuid.uuid4(), user_id=7)
    context = ToolContext(
        session_id=str(session.conversation_id),
        user_id=7,
        connection_id=2,
        connection_type="tableau",
        trace_id="t-controlled",
    )

    events = [
        event
        async for event in run_agent(
            engine=_NoEngineFallback(),
            context=context,
            session_mgr=session_mgr,
            session=session,
            question="整体销售额是多少",
            trace_id="t-controlled",
            current_user={"id": 7},
            db=db,
            connection_id=2,
            intent_result=classify_intent("整体销售额是多少", connection_type="tableau"),
            enforce_controlled_data_path=True,
        )
    ]

    assert events[-1].type == "error"
    assert db.updates[-1][BiAgentRun.status] == "failed"
    assert db.updates[-1][BiAgentRun.tools_used] == ["tableau_mcp"]
    assert db.updates[-1][BiAgentRun.steps_count] == 1
    assert not session_mgr.messages


@pytest.mark.asyncio
async def test_unknown_intent_can_continue_existing_runner_path(monkeypatch):
    monkeypatch.setattr("services.data_agent.runner.is_direct_query", lambda question: False)

    class _AnswerEngine:
        async def run(self, query, context, session=None, **kwargs):
            yield AgentEvent(type="answer", content="ok")

    db = _FakeDb()
    session_mgr = _FakeSessionManager()
    session = AgentSession(conversation_id=uuid.uuid4(), user_id=7)
    context = ToolContext(session_id=str(session.conversation_id), user_id=7, trace_id="t-unknown")

    events = [
        event
        async for event in run_agent(
            engine=_AnswerEngine(),
            context=context,
            session_mgr=session_mgr,
            session=session,
            question="你好",
            trace_id="t-unknown",
            current_user={"id": 7},
            db=db,
            enforce_controlled_data_path=True,
        )
    ]

    assert [event.type for event in events] == ["metadata", "done"]
    assert session_mgr.messages[0]["content"] == "ok"


@pytest.mark.asyncio
async def test_controlled_path_defaults_to_legacy_queryspec(monkeypatch):
    monkeypatch.delenv("DATA_AGENT_CHAIN_MODE", raising=False)
    monkeypatch.delenv("DATA_AGENT_MCP_PROXY_ENABLED", raising=False)

    async def _legacy_path(**kwargs):
        yield AgentEvent(type="thinking", content="legacy")
        yield AgentEvent(type="answer", content="legacy answer")

    async def _proxy_path(**kwargs):
        raise AssertionError("default chain mode must not enter mcp_proxy")

    monkeypatch.setattr("services.data_agent.runner.run_mcp_first_main_path", _legacy_path)
    monkeypatch.setattr("services.data_agent.runner.run_mcp_proxy_main_path", _proxy_path)

    db = _FakeDb()
    session_mgr = _FakeSessionManager()
    session = AgentSession(conversation_id=uuid.uuid4(), user_id=7)
    context = ToolContext(session_id=str(session.conversation_id), user_id=7, connection_id=2, trace_id="t-default")

    events = [
        event
        async for event in run_agent(
            engine=_NoEngineFallback(),
            context=context,
            session_mgr=session_mgr,
            session=session,
            question="整体销售额是多少",
            trace_id="t-default",
            current_user={"id": 7},
            db=db,
            connection_id=2,
            intent_result=classify_intent("整体销售额是多少", connection_type="tableau"),
            enforce_controlled_data_path=True,
        )
    ]

    assert [event.type for event in events] == ["metadata", "thinking", "done"]
    assert events[1].content == "legacy"
    assert events[-1].content["answer"] == "legacy answer"


@pytest.mark.asyncio
async def test_controlled_table_success_emits_shared_table_data_and_done_response(monkeypatch):
    async def _controlled_path(**kwargs):
        response_data = {
            "fields": ["region", "sales"],
            "rows": [["east", 100]],
            "table_display": {
                "columns": [
                    {"key": "region", "label": "Region", "align": "left", "format": "plain"},
                    {"key": "sales", "label": "Sales", "align": "right", "format": "number"},
                ]
            },
        }
        yield AgentEvent(type="tool_call", content={"tool": "tableau_mcp", "params": {}})
        yield AgentEvent(type="tool_result", content={"tool": "tableau_mcp", "result": {"data": response_data}})
        yield AgentEvent(type="answer", content="query complete")

    monkeypatch.setattr("services.data_agent.runner.run_mcp_first_main_path", _controlled_path)

    db = _FakeDb()
    session_mgr = _FakeSessionManager()
    session = AgentSession(conversation_id=uuid.uuid4(), user_id=7)
    context = ToolContext(session_id=str(session.conversation_id), user_id=7, connection_id=2, trace_id="t-table")

    events = [
        event
        async for event in run_agent(
            engine=_NoEngineFallback(),
            context=context,
            session_mgr=session_mgr,
            session=session,
            question="show sales by region",
            trace_id="t-table",
            current_user={"id": 7},
            db=db,
            connection_id=2,
            intent_result=classify_intent("show sales by region", connection_type="tableau"),
            enforce_controlled_data_path=True,
        )
    ]

    table_event = next(event for event in events if event.type == "table_data")
    done = events[-1].content

    assert done["response_type"] == "table"
    assert done["response_data"]["fields"] == ["region", "sales"]
    assert done["response_data"]["rows"] == [["east", 100]]
    assert done["response_data"]["table_display"]["columns"][1]["label"] == "Sales"
    assert table_event.content == {"type": "table_data", **done["response_data"]}
    assert session_mgr.messages[0]["response_data"] == done["response_data"]
    assert db.updates[-1][BiAgentRun.response_type] == "table"


@pytest.mark.asyncio
async def test_controlled_path_uses_mcp_proxy_only_when_mode_and_flag_enabled(monkeypatch):
    monkeypatch.setenv("DATA_AGENT_CHAIN_MODE", "mcp_proxy")
    monkeypatch.setenv("DATA_AGENT_MCP_PROXY_ENABLED", "true")

    async def _legacy_path(**kwargs):
        raise AssertionError("mcp_proxy mode with enabled flag must not enter legacy")

    async def _proxy_path(**kwargs):
        yield AgentEvent(type="thinking", content="proxy")
        yield AgentEvent(type="answer", content="proxy answer")

    monkeypatch.setattr("services.data_agent.runner.run_mcp_first_main_path", _legacy_path)
    monkeypatch.setattr("services.data_agent.runner.run_mcp_proxy_main_path", _proxy_path)

    db = _FakeDb()
    session_mgr = _FakeSessionManager()
    session = AgentSession(conversation_id=uuid.uuid4(), user_id=7)
    context = ToolContext(session_id=str(session.conversation_id), user_id=7, connection_id=2, trace_id="t-proxy")

    events = [
        event
        async for event in run_agent(
            engine=_NoEngineFallback(),
            context=context,
            session_mgr=session_mgr,
            session=session,
            question="整体销售额是多少",
            trace_id="t-proxy",
            current_user={"id": 7},
            db=db,
            connection_id=2,
            intent_result=classify_intent("整体销售额是多少", connection_type="tableau"),
            enforce_controlled_data_path=True,
        )
    ]

    assert [event.type for event in events] == ["metadata", "thinking", "done"]
    assert events[1].content == "proxy"
    assert events[-1].content["answer"] == "proxy answer"


@pytest.mark.asyncio
async def test_controlled_path_invalid_chain_mode_falls_back_with_clear_event(monkeypatch):
    monkeypatch.setenv("DATA_AGENT_CHAIN_MODE", "experimental")
    monkeypatch.setenv("DATA_AGENT_MCP_PROXY_ENABLED", "true")

    async def _legacy_path(**kwargs):
        yield AgentEvent(type="thinking", content="legacy")
        yield AgentEvent(type="answer", content="legacy answer")

    async def _proxy_path(**kwargs):
        raise AssertionError("invalid chain mode must not enter mcp_proxy")

    monkeypatch.setattr("services.data_agent.runner.run_mcp_first_main_path", _legacy_path)
    monkeypatch.setattr("services.data_agent.runner.run_mcp_proxy_main_path", _proxy_path)

    db = _FakeDb()
    session_mgr = _FakeSessionManager()
    session = AgentSession(conversation_id=uuid.uuid4(), user_id=7)
    context = ToolContext(session_id=str(session.conversation_id), user_id=7, connection_id=2, trace_id="t-invalid")

    events = [
        event
        async for event in run_agent(
            engine=_NoEngineFallback(),
            context=context,
            session_mgr=session_mgr,
            session=session,
            question="整体销售额是多少",
            trace_id="t-invalid",
            current_user={"id": 7},
            db=db,
            connection_id=2,
            intent_result=classify_intent("整体销售额是多少", connection_type="tableau"),
            enforce_controlled_data_path=True,
        )
    ]

    assert [event.type for event in events] == ["metadata", "thinking", "thinking", "done"]
    assert "DATA_AGENT_CHAIN_MODE=experimental" in events[1].content
    assert events[2].content == "legacy"
    assert events[-1].content["answer"] == "legacy answer"

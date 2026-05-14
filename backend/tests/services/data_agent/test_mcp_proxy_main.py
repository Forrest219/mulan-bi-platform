import json
import uuid

import pytest

from services.data_agent import mcp_proxy_main
from services.data_agent.intent_classifier import IntentClassification, classify_intent
from services.data_agent.models import BiAgentRun
from services.data_agent.response import AgentEvent
from services.data_agent.runner import run_agent
from services.data_agent.session import AgentSession
from services.data_agent.tool_base import ToolContext

pytestmark = pytest.mark.skip_db


class _FakeLLM:
    def __init__(self, payload):
        self.payload = payload

    async def complete(self, *, prompt, system=None, timeout=None, purpose=None):
        assert purpose == "data_agent_mcp_proxy_args"
        assert "QuerySpec" in system
        return {"content": json.dumps(self.payload, ensure_ascii=False)}


def _intent(intent: str = "aggregate") -> IntentClassification:
    return IntentClassification(intent=intent, confidence=0.9, route_reason="test")


def _context() -> ToolContext:
    return ToolContext(session_id="s1", user_id=7, connection_id=2, trace_id="trace-proxy")


def _patch_datasource(monkeypatch, fields=None):
    monkeypatch.setattr(
        mcp_proxy_main,
        "_resolve_datasource",
        lambda question, context, datasource_name_hint: {"name": "测试数据源", "luid": "ds-1", "asset_id": 1},
    )
    monkeypatch.setattr(
        mcp_proxy_main,
        "_queryable_fields",
        lambda ds_info, connection_id=None: fields or ["省份", "销售额", "订单日期"],
    )


@pytest.mark.asyncio
async def test_mcp_proxy_allows_llm_args_and_executes_mcp(monkeypatch):
    _patch_datasource(monkeypatch)

    async def _fake_execute(args, context):
        assert args == {
            "datasourceLuid": "ds-1",
            "query": {"fields": [{"fieldCaption": "销售额", "function": "SUM"}], "filters": []},
            "limit": 50,
        }
        return {"fields": ["SUM(销售额)"], "rows": [[100]]}

    monkeypatch.setattr(mcp_proxy_main, "_execute_query_datasource_args", _fake_execute)

    events = [
        event
        async for event in mcp_proxy_main.run_mcp_proxy_main_path(
            question="总销售额是多少？",
            context=_context(),
            intent_result=_intent(),
            llm_service=_FakeLLM(
                {
                    "datasourceLuid": "ds-1",
                    "query": {"fields": [{"fieldCaption": "销售额", "function": "SUM"}], "filters": []},
                    "limit": 50,
                }
            ),
        )
    ]

    tool_names = [
        event.content["tool"]
        for event in events
        if event.type in {"tool_call", "tool_result"} and isinstance(event.content, dict)
    ]
    assert "llm_mcp_args" in tool_names
    assert "mcp_args_guardrail" in tool_names
    assert "tableau_mcp" in tool_names
    assert "llm_queryspec" not in tool_names
    assert "queryspec_validator" not in tool_names

    guardrail_result = next(
        event.content["result"]["data"]
        for event in events
        if event.type == "tool_result" and event.content.get("tool") == "mcp_args_guardrail"
    )
    assert guardrail_result["decision"] == "allow"

    mcp_result = next(
        event.content["result"]["data"]
        for event in events
        if event.type == "tool_result" and event.content.get("tool") == "tableau_mcp"
    )
    assert mcp_result["chain_mode"] == "mcp_proxy"
    assert mcp_result["guardrail_decision"] == "allow"
    assert mcp_result["fields"] == ["SUM(销售额)"]
    assert mcp_result["rows"] == [[100]]
    assert mcp_result["table_display"]["columns"][0]["semantic_type"] == "metric"
    assert events[-1].type == "answer"


@pytest.mark.asyncio
async def test_mcp_proxy_repairs_limit_and_records_trace(monkeypatch):
    _patch_datasource(monkeypatch)
    executed_args = {}

    async def _fake_execute(args, context):
        executed_args.update(args)
        return {"fields": ["省份", "SUM(销售额)"], "rows": [["华东", 100]]}

    monkeypatch.setattr(mcp_proxy_main, "_execute_query_datasource_args", _fake_execute)

    events = [
        event
        async for event in mcp_proxy_main.run_mcp_proxy_main_path(
            question="按省份看销售额",
            context=_context(),
            intent_result=_intent(),
            llm_service=_FakeLLM(
                {
                    "datasourceLuid": "ds-1",
                    "query": {
                        "fields": [{"fieldCaption": "省份"}, {"fieldCaption": "销售额", "function": "SUM"}],
                        "filters": [],
                    },
                }
            ),
        )
    ]

    assert executed_args["limit"] == 100
    mcp_result = next(
        event.content["result"]["data"]
        for event in events
        if event.type == "tool_result" and event.content.get("tool") == "tableau_mcp"
    )
    assert mcp_result["guardrail_decision"] == "repair"
    assert mcp_result["guardrail_repairs"][0]["type"] == "limit_default"


@pytest.mark.asyncio
async def test_mcp_proxy_reject_does_not_enter_queryspec_or_mcp(monkeypatch):
    _patch_datasource(monkeypatch)

    async def _unexpected_execute(args, context):
        raise AssertionError("guardrail reject must not execute MCP")

    monkeypatch.setattr(mcp_proxy_main, "_execute_query_datasource_args", _unexpected_execute)

    events = [
        event
        async for event in mcp_proxy_main.run_mcp_proxy_main_path(
            question="按不存在字段看销售额",
            context=_context(),
            intent_result=_intent(),
            llm_service=_FakeLLM(
                {
                    "datasourceLuid": "ds-1",
                    "query": {
                        "fields": [{"fieldCaption": "不存在字段"}, {"fieldCaption": "销售额", "function": "SUM"}],
                        "filters": [],
                    },
                    "limit": 20,
                }
            ),
        )
    ]

    error = events[-1]
    assert error.type == "error"
    assert error.content["fallback_type"] == "guardrail_rejected"
    assert error.content["error_code"] == "MCP_ARGS_UNKNOWN_FIELD"
    assert error.content["controlled_chain"]["detail"]["chain_mode"] == "mcp_proxy"
    assert error.content["controlled_chain"]["detail"]["guardrail_decision"] == "reject"

    tool_names = [
        event.content["tool"]
        for event in events
        if event.type in {"tool_call", "tool_result"} and isinstance(event.content, dict)
    ]
    assert "tableau_mcp" not in tool_names
    assert "queryspec_fallback" not in tool_names
    assert "llm_queryspec" not in tool_names


class _FakeDb:
    def __init__(self):
        self.added = []
        self.updates = []

    def add(self, obj):
        self.added.append(obj)

    def commit(self):
        pass

    def refresh(self, obj):
        if getattr(obj, "id", None) is None:
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


class _FakeSessionManager:
    def __init__(self):
        self.messages = []

    def persist_message(self, **kwargs):
        self.messages.append(kwargs)

    def get_conversation_messages(self, **kwargs):
        return []


class _NoEngine:
    async def run(self, *args, **kwargs):
        raise AssertionError("controlled path should handle data intents")
        yield AgentEvent(type="answer", content="unreachable")


@pytest.mark.asyncio
async def test_runner_keeps_legacy_path_when_mcp_proxy_flag_is_off(monkeypatch):
    monkeypatch.setenv("DATA_AGENT_CHAIN_MODE", "mcp_proxy")
    monkeypatch.delenv("DATA_AGENT_MCP_PROXY_ENABLED", raising=False)

    async def _legacy_path(**kwargs):
        yield AgentEvent(type="thinking", content="legacy")
        yield AgentEvent(type="answer", content="legacy answer")

    async def _proxy_path(**kwargs):
        raise AssertionError("DATA_AGENT_MCP_PROXY_ENABLED=false must not enter mcp_proxy")

    monkeypatch.setattr("services.data_agent.runner.run_mcp_first_main_path", _legacy_path)
    monkeypatch.setattr("services.data_agent.runner.run_mcp_proxy_main_path", _proxy_path)

    db = _FakeDb()
    session_mgr = _FakeSessionManager()
    session = AgentSession(conversation_id=uuid.uuid4(), user_id=7)
    context = ToolContext(session_id=str(session.conversation_id), user_id=7, connection_id=2, trace_id="t-legacy")

    events = [
        event
        async for event in run_agent(
            engine=_NoEngine(),
            context=context,
            session_mgr=session_mgr,
            session=session,
            question="整体销售额是多少",
            trace_id="t-legacy",
            current_user={"id": 7},
            db=db,
            connection_id=2,
            intent_result=classify_intent("整体销售额是多少", connection_type="tableau"),
            enforce_controlled_data_path=True,
        )
    ]

    assert [event.type for event in events] == ["metadata", "thinking", "thinking", "done"]
    assert "DATA_AGENT_MCP_PROXY_ENABLED" in events[1].content
    assert events[-1].content["answer"] == "legacy answer"
    assert db.updates[-1][BiAgentRun.status] == "completed"

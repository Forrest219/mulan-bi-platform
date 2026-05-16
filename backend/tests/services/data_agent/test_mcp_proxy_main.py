import json
import uuid

import pytest

from services.data_agent import mcp_first_main, mcp_proxy_main
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
        self.calls = []

    async def complete(self, *, prompt, system=None, timeout=None, purpose=None):
        assert purpose == "data_agent_mcp_proxy_args"
        assert "QuerySpec" in system
        self.calls.append({"prompt": prompt, "system": system, "timeout": timeout, "purpose": purpose})
        return {"content": json.dumps(self.payload, ensure_ascii=False)}


def _intent(intent: str = "aggregate") -> IntentClassification:
    return IntentClassification(intent=intent, confidence=0.9, route_reason="test")


def _context() -> ToolContext:
    context = ToolContext(session_id="s1", user_id=7, connection_id=2, trace_id="trace-proxy")
    context.datasource_luid = "ds-1"
    context.datasource_name = "测试数据源"
    return context


def _tool_names(events):
    return [
        event.content["tool"]
        for event in events
        if event.type in {"tool_call", "tool_result"} and isinstance(event.content, dict)
    ]


class _FakeHostCatalog:
    async def list_tools(self):
        return {
            "tools": [
                {
                    "name": "get-datasource-metadata",
                    "inputSchema": {
                        "type": "object",
                        "required": ["datasourceLuid"],
                        "properties": {"datasourceLuid": {"type": "string"}},
                    },
                },
                {
                    "name": "query-datasource",
                    "inputSchema": {
                        "type": "object",
                        "required": ["datasourceLuid", "query"],
                        "properties": {"datasourceLuid": {"type": "string"}, "query": {"type": "object"}},
                    },
                },
            ]
        }


class _FakeHostExecutor:
    def __init__(self, *, query_result=None, query_error=None):
        self.calls = []
        self.query_result = query_result or {"fields": ["Metric A"], "rows": [[100]]}
        self.query_error = query_error

    async def execute_tool(self, tool_name, arguments, context):
        self.calls.append({"tool_name": tool_name, "arguments": dict(arguments), "context": context})
        if tool_name == "get-datasource-metadata":
            return {"fields": [{"name": "Metric A", "dataType": "REAL"}]}
        if self.query_error:
            return self.query_error
        return self.query_result


class _FakeHostPlanner:
    def __init__(self, actions=None):
        self.actions = list(actions or [_query_tool_call(), {"action": "final", "answer": "Use response_data only."}])
        self.calls = []

    async def plan(self, **kwargs):
        self.calls.append(kwargs)
        if not self.actions:
            raise AssertionError("unexpected extra MCP Host planner call")
        return self.actions.pop(0)


def _query_tool_call():
    return {
        "action": "tool_call",
        "tool_call": {
            "tool": "query-datasource",
            "arguments": {
                "datasourceLuid": "ds-1",
                "query": {"fields": [{"fieldCaption": "Metric A", "function": "SUM"}], "filters": []},
                "limit": 50,
            },
        },
    }


def _patch_host(monkeypatch, *, query_result=None, query_error=None, actions=None):
    executor = _FakeHostExecutor(query_result=query_result, query_error=query_error)
    planner = _FakeHostPlanner(actions=actions)
    catalog = _FakeHostCatalog()

    async def _load_components(**kwargs):
        return mcp_first_main._McpHostComponents(catalog=catalog, executor=executor, planner=planner)

    monkeypatch.setattr(mcp_first_main, "_load_mcp_host_components", _load_components)
    return executor, planner


def _forbidden_main_path_markers():
    return {
        "mcp_nl_tool_discovery",
        "tableau_mcp_nl",
        "llm_mcp_args",
        "mcp_args_guardrail",
        "llm_queryspec",
        "llm_queryspec_repair",
        "queryspec_fallback",
        "queryspec_validator",
        "mcp_main_queryspec_fallback",
        "queryspec_mcp_fallback",
    }


@pytest.mark.asyncio
async def test_mcp_proxy_calls_mcp_host_loop_without_llm_args(monkeypatch):
    executor, planner = _patch_host(monkeypatch)

    events = [
        event
        async for event in mcp_proxy_main.run_mcp_proxy_main_path(
            question="overall Metric A",
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

    tool_names = _tool_names(events)
    assert "mcp_host_catalog" in tool_names
    assert "mcp_host_planner" in tool_names
    assert "tableau_mcp" in tool_names
    assert "mcp_host_final_response" in tool_names
    assert _forbidden_main_path_markers().isdisjoint(tool_names)
    assert [call["tool_name"] for call in executor.calls] == ["get-datasource-metadata", "query-datasource"]
    assert planner.calls[0]["previous_response_data"] is None

    response_data = next(
        event.content["result"]["data"]
        for event in events
        if event.type == "tool_result" and event.content.get("tool") == "mcp_host_final_response"
    )
    assert response_data["chain_mode"] == "mcp_proxy"
    assert response_data["mcp_host"] is True
    assert response_data["fields"] == ["Metric A"]
    assert response_data["rows"] == [[100]]
    assert response_data["table_display"]["columns"][0]["semantic_type"] == "metric"
    assert events[-1].type == "answer"


@pytest.mark.asyncio
async def test_mcp_proxy_mcp_error_returns_structured_error_without_queryspec(monkeypatch):
    _patch_host(
        monkeypatch,
        query_error={"success": False, "error_code": "MCP_UPSTREAM_ERROR", "error": "upstream unavailable"},
    )

    events = [
        event
        async for event in mcp_proxy_main.run_mcp_proxy_main_path(
            question="Metric A by Dimension A",
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

    tool_names = _tool_names(events)
    assert "tableau_mcp" in tool_names
    assert _forbidden_main_path_markers().isdisjoint(tool_names)
    assert events[-1].type == "error"
    assert events[-1].content["error_code"] == "MCP_UPSTREAM_ERROR"


@pytest.mark.asyncio
async def test_mcp_proxy_followup_context_is_passed_to_host_not_used_to_construct_fields(monkeypatch):
    executor, planner = _patch_host(
        monkeypatch,
        query_result={
            "fields": ["Dimension A", "Year A", "Metric A", "Metric B"],
            "rows": [["x", 2025, 10, 4]],
        },
    )
    llm = _FakeLLM(
        {
            "datasourceLuid": "ds-1",
            "query": {
                "fields": [
                    {"fieldCaption": "日期字段", "function": "YEAR"},
                    {"fieldCaption": "指标一", "function": "SUM"},
                ],
                "filters": [],
            },
            "limit": 100,
        }
    )

    events = [
        event
        async for event in mcp_proxy_main.run_mcp_proxy_main_path(
            question="continue by year",
            context=_context(),
            intent_result=_intent(),
            analysis_context={
                "datasource_name": "测试数据源",
                "response_data": {"fields": ["Metric A"], "rows": [[100]]},
            },
            llm_service=llm,
        )
    ]

    assert executor.calls[1]["tool_name"] == "query-datasource"
    assert executor.calls[1]["arguments"] == _query_tool_call()["tool_call"]["arguments"]
    assert planner.calls[0]["previous_response_data"] == {"fields": ["Metric A"], "rows": [[100]]}
    assert events[-1].type == "answer"
    assert llm.calls == []


@pytest.mark.asyncio
async def test_mcp_proxy_q1_like_question_enters_host_not_llm_or_queryspec(monkeypatch):
    _patch_host(monkeypatch)

    events = [
        event
        async for event in mcp_proxy_main.run_mcp_proxy_main_path(
            question="Metric A by Dimension A",
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

    tool_names = _tool_names(events)
    assert {"mcp_host_catalog", "mcp_host_planner", "tableau_mcp", "mcp_host_final_response"}.issubset(set(tool_names))
    assert _forbidden_main_path_markers().isdisjoint(tool_names)
    assert events[-1].type == "answer"


@pytest.mark.asyncio
async def test_mcp_proxy_blocks_detail_scan_result_before_renderer(monkeypatch):
    _patch_host(
        monkeypatch,
        query_result={"fields": ["Customer", "Sales"], "rows": [[f"c{i}", i] for i in range(250)]},
    )

    events = [
        event
        async for event in mcp_proxy_main.run_mcp_proxy_main_path(
            question="top customers by sales",
            context=_context(),
            intent_result=_intent(),
            llm_service=_FakeLLM({}),
        )
    ]

    assert events[-1].type == "error"
    assert events[-1].content["error_code"] == "DETAIL_SCAN_BLOCKED"


@pytest.mark.asyncio
async def test_mcp_proxy_requires_explicit_datasource(monkeypatch):
    async def _unexpected_components(**kwargs):
        raise AssertionError("Host runtime must not load without an explicit datasource")

    monkeypatch.setattr(mcp_first_main, "_load_mcp_host_components", _unexpected_components)

    events = [
        event
        async for event in mcp_proxy_main.run_mcp_proxy_main_path(
            question="整体销售额和利润率是多少",
            context=ToolContext(session_id="s1", user_id=7, connection_id=2, trace_id="trace-proxy"),
            intent_result=_intent(),
            llm_service=_FakeLLM(
                {
                    "datasourceLuid": "ds-1",
                    "query": {"fields": ["销售额", "利润率"], "filters": []},
                    "limit": 20,
                }
            ),
        )
    ]

    error = events[-1]
    assert error.type == "error"
    assert error.content["error_code"] == "MCP_EXPLICIT_DATASOURCE_REQUIRED"
    tool_names = _tool_names(events)
    assert "mcp_host_catalog" not in tool_names
    assert "llm_mcp_args" not in tool_names



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

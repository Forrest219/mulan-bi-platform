"""Data Agent runner observability regressions."""

import asyncio
import uuid

import pytest

from services.data_agent.models import BiAgentRun, BiAgentStep
from services.data_agent.response import AgentEvent
from services.data_agent.runner import resolve_recent_query_context, run_agent
from services.data_agent.session import AgentSession
from services.data_agent.tool_base import ToolContext


pytestmark = pytest.mark.skip_db


class _FakeDb:
    def __init__(self):
        self.added = []
        self.commits = 0
        self.updates = []

    def add(self, obj):
        self.added.append(obj)

    def commit(self):
        self.commits += 1

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


class _FakeEngine:
    async def run(self, query, context, session=None, **kwargs):
        yield AgentEvent(
            type="tool_result",
            content={
                "tool": "schema",
                "result": {
                    "success": False,
                    "error": "Tableau asset fields are unavailable",
                    "data": {"fields": {}},
                },
            },
        )
        yield AgentEvent(type="answer", content="无法读取字段。")


class _CapturingEngine:
    def __init__(self):
        self.kwargs = None

    async def run(self, query, context, session=None, **kwargs):
        self.kwargs = kwargs
        yield AgentEvent(type="answer", content="ok")


class _ErrorEngine:
    async def run(self, query, context, session=None, **kwargs):
        yield AgentEvent(
            type="error",
            content={
                "error_code": "AGENT_001",
                "message": "查询超时",
                "fallback_type": "query_timeout",
                "user_hint": "请缩小时间范围后重试。",
            },
        )


class _BlockingEngine:
    async def run(self, query, context, session=None, **kwargs):
        await asyncio.sleep(3600)
        yield AgentEvent(type="answer", content="late")


class _UnexpectedEngine:
    async def run(self, query, context, session=None, **kwargs):
        raise AssertionError("engine should not be called for previous-result transforms")


class _FakeMessage:
    def __init__(self, role="assistant", tools_used=None, content="", response_data=None, response_type=None):
        self.role = role
        self.tools_used = tools_used or ["schema"]
        self.content = content or "数据资产 **orders-订单明细表** 返回了 **16 个字段**："
        self.response_data = response_data
        self.response_type = response_type


class _FakeSessionManager:
    def __init__(self, messages=None):
        self.messages = []
        self._stored_messages = messages or [_FakeMessage()]

    def persist_message(self, **kwargs):
        self.messages.append(kwargs)

    def get_conversation_messages(self, **kwargs):
        return self._stored_messages


@pytest.mark.asyncio
async def test_failed_tool_result_persists_error_summary(monkeypatch):
    """回归：失败 tool_result 的错误摘要应写入 bi_agent_steps.tool_result_summary。"""
    monkeypatch.setattr("services.data_agent.runner.is_direct_query", lambda question: False)

    db = _FakeDb()
    session_mgr = _FakeSessionManager()
    session = AgentSession(conversation_id=uuid.uuid4(), user_id=7)
    context = ToolContext(
        session_id=str(session.conversation_id),
        user_id=7,
        connection_id=1,
        trace_id="t-runner",
    )

    events = [
        event
        async for event in run_agent(
            engine=_FakeEngine(),
            context=context,
            session_mgr=session_mgr,
            session=session,
            question="字段有哪些？",
            trace_id="t-runner",
            current_user={"id": 7},
            db=db,
            connection_id=1,
        )
    ]

    tool_result_steps = [
        obj
        for obj in db.added
        if isinstance(obj, BiAgentStep) and obj.step_type == "tool_result"
    ]

    assert [event.type for event in events] == ["metadata", "tool_result", "done"]
    assert len(tool_result_steps) == 1
    assert tool_result_steps[0].tool_name == "schema"
    assert tool_result_steps[0].tool_result_summary == "Tableau asset fields are unavailable"
    assert db.updates[-1][BiAgentRun.status] == "completed"


@pytest.mark.asyncio
async def test_error_event_persists_assistant_history_message(monkeypatch):
    """回归：错误事件也必须落成 assistant 历史消息，刷新后可见。"""
    monkeypatch.setattr("services.data_agent.runner.is_direct_query", lambda question: False)
    monkeypatch.setattr("services.data_agent.runner.persist_structured_error", lambda *args, **kwargs: None)

    db = _FakeDb()
    session_mgr = _FakeSessionManager()
    session = AgentSession(conversation_id=uuid.uuid4(), user_id=7)
    context = ToolContext(
        session_id=str(session.conversation_id),
        user_id=7,
        connection_id=1,
        connection_name="Tableau",
        trace_id="t-error",
    )

    events = [
        event
        async for event in run_agent(
            engine=_ErrorEngine(),
            context=context,
            session_mgr=session_mgr,
            session=session,
            question="会超时的问题",
            trace_id="t-error",
            current_user={"id": 7},
            db=db,
            connection_id=1,
        )
    ]

    assert [event.type for event in events] == ["metadata", "error"]
    assert db.updates[-1][BiAgentRun.status] == "failed"
    assert db.updates[-1][BiAgentRun.response_type] == "fallback"
    assert len(session_mgr.messages) == 1
    message = session_mgr.messages[0]
    assert message["role"] == "assistant"
    assert message["content"] == "查询超时"
    assert message["response_type"] == "fallback"
    assert message["response_data"]["error_code"] == "AGENT_001"
    assert message["trace_id"] == "t-error"
    assert message["sources_count"] == 1
    assert message["top_sources"] == ["Tableau"]


@pytest.mark.asyncio
async def test_cancelled_stream_marks_run_failed_and_persists_message(monkeypatch):
    """回归：客户端断开后 run 不应长期停留在 running。"""
    monkeypatch.setattr("services.data_agent.runner.is_direct_query", lambda question: False)

    db = _FakeDb()
    session_mgr = _FakeSessionManager()
    session = AgentSession(conversation_id=uuid.uuid4(), user_id=7)
    context = ToolContext(
        session_id=str(session.conversation_id),
        user_id=7,
        connection_id=1,
        connection_name="Tableau",
        trace_id="t-cancel",
    )

    stream = run_agent(
        engine=_BlockingEngine(),
        context=context,
        session_mgr=session_mgr,
        session=session,
        question="一个会被取消的问题",
        trace_id="t-cancel",
        current_user={"id": 7},
        db=db,
        connection_id=1,
    )

    first = await stream.__anext__()
    assert first.type == "metadata"

    pending = asyncio.create_task(stream.__anext__())
    await asyncio.sleep(0)
    pending.cancel()
    with pytest.raises(asyncio.CancelledError):
        await pending

    assert db.updates[-1][BiAgentRun.status] == "failed"
    assert db.updates[-1][BiAgentRun.error_code] == "AGENT_CANCELLED"
    assert db.updates[-1][BiAgentRun.response_type] == "error"
    assert session_mgr.messages[-1]["role"] == "assistant"
    assert session_mgr.messages[-1]["response_data"]["error_type"] == "client_disconnected"


@pytest.mark.asyncio
async def test_previous_query_result_transform_skips_planner_and_persists_query_result(monkeypatch):
    """追问增加派生列时，应基于上一条结果表变换，不进入 LLM/MCP planner。"""
    previous_response = {
        "fields": ["Period", "Revenue"],
        "rows": [["2026-01", 100.0], ["2026-02", 125.0], ["2026-03", 150.0]],
        "col_types": ["string", "numeric"],
        "table_display": {
            "columns": [
                {"key": "Period", "label": "Period", "semantic_type": "period", "value_type": "date", "format": "date"},
                {"key": "Revenue", "label": "Revenue", "semantic_type": "metric", "value_type": "number", "format": "number"},
            ],
        },
    }
    session_mgr = _FakeSessionManager(messages=[
        _FakeMessage(
            role="assistant",
            tools_used=["tableau_mcp"],
            response_type="query_result",
            response_data=previous_response,
        )
    ])
    db = _FakeDb()
    session = AgentSession(conversation_id=uuid.uuid4(), user_id=7)
    context = ToolContext(
        session_id=str(session.conversation_id),
        user_id=7,
        connection_id=1,
        connection_name="Tableau",
        trace_id="t-transform",
    )

    events = [
        event
        async for event in run_agent(
            engine=_UnexpectedEngine(),
            context=context,
            session_mgr=session_mgr,
            session=session,
            question="增加一列环比金额、环比金额变化率",
            trace_id="t-transform",
            current_user={"id": 7},
            db=db,
            connection_id=1,
        )
    ]

    assert [event.type for event in events] == ["metadata", "tool_call", "tool_result", "table_data", "done"]
    assert events[1].content["tool"] == "previous_result_transform"
    assert db.updates[-1][BiAgentRun.status] == "completed"
    assert db.updates[-1][BiAgentRun.response_type] == "query_result"
    assert session_mgr.messages[-1]["response_type"] == "query_result"
    data = session_mgr.messages[-1]["response_data"]
    assert data["source"] == "previous_result_transform"
    assert data["fields"] == ["Period", "Revenue", "环比金额", "环比金额变化率"]
    assert data["rows"][1] == ["2026-02", 125.0, 25.0, 0.25]
    assert data["table_display"]["columns"][-1]["format"] == "percent"


@pytest.mark.asyncio
async def test_direct_query_followup_uses_recent_schema_asset_as_datasource(monkeypatch):
    """追问问数时应继承上轮 schema 查到的数据资产。"""
    monkeypatch.setattr("services.data_agent.runner.is_direct_query", lambda question: True)

    db = _FakeDb()
    session_mgr = _FakeSessionManager()
    session = AgentSession(conversation_id=uuid.uuid4(), user_id=7)
    context = ToolContext(
        session_id=str(session.conversation_id),
        user_id=7,
        connection_id=2,
        trace_id="t-runner",
    )
    engine = _CapturingEngine()

    events = [
        event
        async for event in run_agent(
            engine=engine,
            context=context,
            session_mgr=session_mgr,
            session=session,
            question="过去四年的销售额、利润趋势如何？",
            trace_id="t-runner",
            current_user={"id": 7},
            db=db,
            connection_id=2,
        )
    ]

    assert [event.type for event in events] == ["metadata", "done"]
    assert engine.kwargs["force_first_tool"] == "query"
    assert engine.kwargs["force_first_params"] == {
        "question": "过去四年的销售额、利润趋势如何？",
        "datasource_name": "orders-订单明细表",
    }


@pytest.mark.asyncio
async def test_direct_query_followup_uses_recent_query_datasource_and_metrics(monkeypatch):
    """含“这个指标”的追问应继承上一轮 query 的数据源和指标上下文。"""
    monkeypatch.setattr("services.data_agent.runner.is_direct_query", lambda question: True)

    previous_query_message = _FakeMessage(
        tools_used=["query"],
        response_data={
            "datasource_name": "订单+ (示例 - 超市)",
            "fields": ["SUM(销售额)", "SUM(利润)", "COUNTD(客户名称)"],
        },
    )
    db = _FakeDb()
    session_mgr = _FakeSessionManager(messages=[previous_query_message])
    session = AgentSession(conversation_id=uuid.uuid4(), user_id=7)
    context = ToolContext(
        session_id=str(session.conversation_id),
        user_id=7,
        connection_id=2,
        trace_id="t-runner",
    )
    engine = _CapturingEngine()

    events = [
        event
        async for event in run_agent(
            engine=engine,
            context=context,
            session_mgr=session_mgr,
            session=session,
            question="这个指标过去几年的趋势是什么样子",
            trace_id="t-runner",
            current_user={"id": 7},
            db=db,
            connection_id=2,
        )
    ]

    assert [event.type for event in events] == ["metadata", "done"]
    assert engine.kwargs["force_first_tool"] == "query"
    assert engine.kwargs["force_first_params"] == {
        "question": "销售额、利润、客户名称 这个指标过去几年的趋势是什么样子",
        "datasource_name": "订单+ (示例 - 超市)",
    }


def test_recent_query_context_inherits_schema_inventory_datasource():
    """schema_inventory 命中的单数据源应成为后续问数的显式数据源上下文。"""
    previous_schema_message = _FakeMessage(
        tools_used=["schema"],
        response_data={
            "mode": "fields",
            "matched_asset": {
                "asset_id": 422,
                "name": "订单+ (示例 - 超市)",
                "tableau_id": "f4290485-26d3-428f-aa8d-ccc33862a411",
            },
            "fields": [{"display_name": "销售额"}, {"display_name": "利润"}],
        },
    )
    session_mgr = _FakeSessionManager(messages=[previous_schema_message])
    session = AgentSession(conversation_id=uuid.uuid4(), user_id=7)

    context = resolve_recent_query_context(session_mgr, session, user_id=7)

    assert context["datasource_luid"] == "f4290485-26d3-428f-aa8d-ccc33862a411"
    assert context["tableau_datasource_luid"] == "f4290485-26d3-428f-aa8d-ccc33862a411"
    assert context["datasource_name"] == "订单+ (示例 - 超市)"
    assert context["selected_datasource"] == {
        "luid": "f4290485-26d3-428f-aa8d-ccc33862a411",
        "datasource_luid": "f4290485-26d3-428f-aa8d-ccc33862a411",
        "tableau_datasource_luid": "f4290485-26d3-428f-aa8d-ccc33862a411",
        "name": "订单+ (示例 - 超市)",
        "datasource_name": "订单+ (示例 - 超市)",
        "asset_id": 422,
        "connection_id": None,
    }

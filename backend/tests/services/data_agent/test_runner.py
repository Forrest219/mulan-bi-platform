"""Data Agent runner observability regressions."""

import uuid

import pytest

from services.data_agent.models import BiAgentRun, BiAgentStep
from services.data_agent.response import AgentEvent
from services.data_agent.runner import run_agent
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


class _FakeMessage:
    def __init__(self, role="assistant", tools_used=None, content="", response_data=None):
        self.role = role
        self.tools_used = tools_used or ["schema"]
        self.content = content or "数据资产 **orders-订单明细表** 返回了 **16 个字段**："
        self.response_data = response_data


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

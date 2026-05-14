import uuid

import pytest

from services.data_agent.models import BiAgentRun
from services.data_agent.response import AgentEvent
from services.data_agent.router_guardrail import classify_homepage_question
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


class _CapturingEngine:
    def __init__(self):
        self.kwargs = None

    async def run(self, query, context, session=None, **kwargs):
        self.kwargs = kwargs
        yield AgentEvent(type="answer", content="ok")


class _FakeSessionManager:
    def __init__(self):
        self.messages = []

    def persist_message(self, **kwargs):
        self.messages.append(kwargs)

    def get_conversation_messages(self, **kwargs):
        return []


@pytest.mark.asyncio
async def test_data_question_route_forces_query_even_when_keyword_fast_path_misses(monkeypatch):
    monkeypatch.setattr("services.data_agent.runner.is_direct_query", lambda question: False)

    db = _FakeDb()
    session_mgr = _FakeSessionManager()
    session = AgentSession(conversation_id=uuid.uuid4(), user_id=7)
    context = ToolContext(session_id=str(session.conversation_id), user_id=7, connection_id=2, trace_id="t-runner")
    engine = _CapturingEngine()
    decision = classify_homepage_question("辽宁、福建 2024 巨亏原因是什么？")

    events = [
        event
        async for event in run_agent(
            engine=engine,
            context=context,
            session_mgr=session_mgr,
            session=session,
            question="辽宁、福建 2024 巨亏原因是什么？",
            trace_id="t-runner",
            current_user={"id": 7},
            db=db,
            connection_id=2,
            route_decision=decision,
        )
    ]

    assert [event.type for event in events] == ["metadata", "done"]
    assert engine.kwargs["route_decision"] == decision
    assert engine.kwargs["force_first_tool"] == "query"
    params = engine.kwargs["force_first_params"]
    assert params["question"] == "辽宁、福建 2024 巨亏原因是什么？"
    assert params["analysis_intent"] == "root_cause"
    assert params["target_metric"] == {"fieldCaption": "利润", "function": "SUM"}
    assert params["breakdown_dimensions"] == ["类别", "子类别", "客户名称"]
    assert params["filters"][0]["values"] == ["辽宁", "福建"]

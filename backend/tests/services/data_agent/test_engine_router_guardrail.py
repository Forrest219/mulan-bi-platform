import pytest
from unittest.mock import AsyncMock, MagicMock

from services.data_agent.engine import ReActEngine
from services.data_agent.router_guardrail import classify_homepage_question
from services.data_agent.tool_base import BaseTool, ToolContext, ToolRegistry, ToolResult


class _SchemaTool(BaseTool):
    name = "schema"
    description = "schema"
    parameters_schema = {"type": "object"}

    def __init__(self):
        self.called = 0

    async def execute(self, params, context):
        self.called += 1
        return ToolResult(success=True, data={"tables": [{"name": "assets"}]})


class _FailingQueryTool(BaseTool):
    name = "query"
    description = "query"
    parameters_schema = {"type": "object"}

    async def execute(self, params, context):
        return ToolResult(success=False, error="[NLQ_007] MCP 查询超时")


@pytest.fixture
def context():
    return ToolContext(session_id="s1", user_id=1, connection_id=1, trace_id="t1")


@pytest.mark.asyncio
async def test_data_question_blocks_llm_selected_schema_tool(context):
    schema = _SchemaTool()
    reg = ToolRegistry()
    reg.register(schema)
    llm = MagicMock()
    llm.complete = AsyncMock(
        return_value={
            "action": "tool_call",
            "tool_name": "schema",
            "tool_params": {},
            "reasoning": "wrong tool",
        }
    )
    engine = ReActEngine(registry=reg, llm_service=llm, max_steps=3)
    decision = classify_homepage_question("2024 年销售额是多少？")

    events = [e async for e in engine.run("2024 年销售额是多少？", context, route_decision=decision)]

    assert [e.type for e in events] == ["thinking", "error"]
    assert events[-1].content["error_code"] == "ROUTER_GUARDRAIL_BLOCKED"
    assert events[-1].content["fallback_type"] == "router_guardrail_blocked"
    assert schema.called == 0


@pytest.mark.asyncio
async def test_data_question_query_failure_returns_fallback_without_second_llm(context):
    reg = ToolRegistry()
    reg.register(_FailingQueryTool())
    llm = MagicMock()
    llm.complete = AsyncMock(
        return_value={
            "action": "final_answer",
            "answer": "不应该二次调用 LLM",
            "reasoning": "unexpected",
        }
    )
    engine = ReActEngine(registry=reg, llm_service=llm, max_steps=3)
    decision = classify_homepage_question("过去四年的销售额、利润趋势如何？")

    events = [
        e
        async for e in engine.run(
            "过去四年的销售额、利润趋势如何？",
            context,
            route_decision=decision,
            force_first_tool="query",
            force_first_params={"question": "过去四年的销售额、利润趋势如何？"},
        )
    ]

    assert [e.type for e in events] == ["tool_call", "tool_result", "error"]
    assert events[-1].content["fallback_type"] == "query_timeout"
    assert events[-1].content["tools_used"] == ["query"]
    assert llm.complete.call_count == 0


@pytest.mark.asyncio
async def test_asset_question_schema_rendering_still_allowed(context):
    schema = _SchemaTool()
    reg = ToolRegistry()
    reg.register(schema)
    llm = MagicMock()
    llm.complete = AsyncMock(
        return_value={
            "action": "tool_call",
            "tool_name": "schema",
            "tool_params": {},
            "reasoning": "asset inventory",
        }
    )
    engine = ReActEngine(registry=reg, llm_service=llm, max_steps=1)
    decision = classify_homepage_question("当前连接有哪些数据源？")

    events = [e async for e in engine.run("当前连接有哪些数据源？", context, route_decision=decision)]

    assert [e.type for e in events] == ["thinking", "tool_call", "tool_result", "answer"]
    assert schema.called == 1

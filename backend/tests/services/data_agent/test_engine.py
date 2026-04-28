"""
Data Agent Engine 单元测试

测试 ReActEngine 的核心推理循环、max_steps 熔断、错误处理等。
"""

import pytest
from unittest.mock import AsyncMock, MagicMock

from services.data_agent.engine import ReActEngine
from services.data_agent.tool_base import ToolRegistry, ToolResult, ToolContext, BaseTool
from services.data_agent.response import AgentEvent


class MockQueryTool(BaseTool):
    """Mock query tool for testing"""
    name = "query"
    description = "查询数据"
    parameters_schema = {"type": "object"}

    async def execute(self, params, context):
        return ToolResult(success=True, data={"answer": "Q4 销售额为 3200 万元", "type": "number"})


class MockMetricsTool(BaseTool):
    """Mock metrics tool for testing"""
    name = "metrics"
    description = "查询指标"
    parameters_schema = {"type": "object"}

    async def execute(self, params, context):
        return ToolResult(success=True, data={"metrics": [{"name": "销售额"}], "total": 1})


@pytest.fixture
def mock_registry():
    """创建带有 mock 工具的注册表"""
    reg = ToolRegistry()
    reg.register(MockQueryTool())
    reg.register(MockMetricsTool())
    return reg


@pytest.fixture
def mock_llm():
    """创建 mock LLM 服务"""
    llm = MagicMock()
    llm.complete = AsyncMock(return_value={
        "action": "tool_call",
        "tool_name": "query",
        "tool_params": {"question": "Q4 销售额"},
        "reasoning": "用户询问销售数据，需要使用查询工具",
    })
    return llm


@pytest.fixture
def tool_context():
    """创建测试用 ToolContext"""
    return ToolContext(
        session_id="s1",
        user_id=1,
        connection_id=1,
        trace_id="t1",
    )


# =============================================================================
# TC-ENGINE-001: 直接回答场景（无需调工具）
# =============================================================================
@pytest.mark.asyncio
async def test_tc_engine_001_direct_answer(mock_registry, mock_llm, tool_context):
    """TC-ENGINE-001: 闲聊场景，直接回答，不调工具"""
    engine = ReActEngine(registry=mock_registry, llm_service=mock_llm, max_steps=10)

    # Mock LLM 直接返回 final_answer
    mock_llm.complete = AsyncMock(return_value={
        "action": "final_answer",
        "answer": "你好，请问有什么可以帮您？",
        "reasoning": "闲聊问题，直接回答",
    })

    events = [e async for e in engine.run("你好", tool_context)]

    # 验证
    assert len(events) >= 2
    assert events[0].type == "thinking"
    assert events[-1].type in ("answer", "done")

    # LLM 应只被调用一次（无需工具调用）
    assert mock_llm.complete.call_count == 1


# =============================================================================
# TC-ENGINE-002: 单步工具调用
# =============================================================================
@pytest.mark.asyncio
async def test_tc_engine_002_single_tool_call(mock_registry, mock_llm, tool_context):
    """TC-ENGINE-002: 单步工具调用场景"""
    engine = ReActEngine(registry=mock_registry, llm_service=mock_llm, max_steps=10)

    # Mock LLM 返回工具调用 -> 然后直接回答
    mock_llm.complete = AsyncMock(side_effect=[
        {
            "action": "tool_call",
            "tool_name": "query",
            "tool_params": {"question": "Q4 销售额"},
            "reasoning": "需要查询数据",
        },
        {
            "action": "final_answer",
            "answer": "Q4 销售额为 3200 万元",
            "reasoning": "已获取数据",
        },
    ])

    events = [e async for e in engine.run("Q4 销售额", tool_context)]
    event_types = [e.type for e in events]

    # 验证事件流
    assert "thinking" in event_types
    assert "tool_call" in event_types
    assert "tool_result" in event_types
    assert "answer" in event_types

    # 工具应只被调用一次
    tool_calls = [e for e in events if e.type == "tool_call"]
    assert len(tool_calls) == 1


# =============================================================================
# TC-ENGINE-003: max_steps 熔断
# =============================================================================
@pytest.mark.asyncio
async def test_tc_engine_003_max_steps_capped(mock_registry, mock_llm, tool_context):
    """TC-ENGINE-003: max_steps 熔断，限制推理步数"""
    engine = ReActEngine(registry=mock_registry, llm_service=mock_llm, max_steps=3)

    # Mock LLM 永远返回需要继续推理
    mock_llm.complete = AsyncMock(side_effect=[
        {"action": "tool_call", "tool_name": "query", "tool_params": {}, "reasoning": "step1"},
        {"action": "tool_call", "tool_name": "query", "tool_params": {}, "reasoning": "step2"},
        {"action": "tool_call", "tool_name": "query", "tool_params": {}, "reasoning": "step3"},
        {"action": "tool_call", "tool_name": "query", "tool_params": {}, "reasoning": "step4"},  # 不应执行
    ])

    events = [e async for e in engine.run("分析趋势", tool_context)]

    # 验证 max_steps=3 限制了工具调用次数
    tool_calls = [e for e in events if e.type == "tool_call"]
    assert len(tool_calls) == 3

    # 最终应达到 max_steps 并返回 answer
    final_events = [e for e in events if e.type == "answer"]
    assert len(final_events) >= 1

    # LLM 应恰好被调用 3 次
    assert mock_llm.complete.call_count == 3


# =============================================================================
# TC-ENGINE-004: 工具不存在
# =============================================================================
@pytest.mark.asyncio
async def test_tc_engine_004_tool_not_found(mock_registry, mock_llm, tool_context):
    """TC-ENGINE-004: LLM 返回不存在的工具名"""
    engine = ReActEngine(registry=mock_registry, llm_service=mock_llm, max_steps=10)

    mock_llm.complete = AsyncMock(return_value={
        "action": "tool_call",
        "tool_name": "nonexistent_tool",
        "tool_params": {},
        "reasoning": "需要调用一个不存在的工具",
    })

    events = [e async for e in engine.run("分析数据", tool_context)]
    event_types = [e.type for e in events]

    # 应该有 thinking 和 error 事件
    assert "thinking" in event_types
    assert "error" in event_types


# =============================================================================
# TC-ENGINE-005: LLM 服务异常
# =============================================================================
@pytest.mark.asyncio
async def test_tc_engine_005_llm_error(mock_registry, mock_llm, tool_context):
    """TC-ENGINE-005: LLM 服务抛出异常"""
    engine = ReActEngine(registry=mock_registry, llm_service=mock_llm, max_steps=10)

    mock_llm.complete = AsyncMock(side_effect=Exception("LLM 服务不可用"))

    events = [e async for e in engine.run("分析数据", tool_context)]
    event_types = [e.type for e in events]

    # 应该有 thinking 和 error 事件
    assert "thinking" in event_types
    assert "error" in event_types


# =============================================================================
# TC-ENGINE-006: 工具执行超时
# =============================================================================
@pytest.mark.asyncio
async def test_tc_engine_006_tool_timeout(mock_registry, mock_llm, tool_context):
    """TC-ENGINE-006: 工具执行超时"""
    engine = ReActEngine(registry=mock_registry, llm_service=mock_llm, max_steps=10, step_timeout=0.1)

    # 创建一个会超时的工具
    async def slow_execute(params, context):
        import asyncio
        await asyncio.sleep(10)  # 模拟慢查询
        return ToolResult(success=True, data={})

    class SlowTool(BaseTool):
        name = "slow_query"
        description = "慢查询"
        parameters_schema = {"type": "object"}
        execute = slow_execute

    reg = ToolRegistry()
    reg.register(SlowTool())
    engine.registry = reg

    mock_llm.complete = AsyncMock(side_effect=[
        {"action": "tool_call", "tool_name": "slow_query", "tool_params": {}, "reasoning": "需要慢查询"},
    ])

    events = [e async for e in engine.run("分析数据", tool_context)]
    event_types = [e.type for e in events]

    # 应该有 tool_call 和 error（超时）
    assert "tool_call" in event_types
    assert "error" in event_types


# =============================================================================
# TC-ENGINE-007: 空问题处理
# =============================================================================
@pytest.mark.asyncio
async def test_tc_engine_007_empty_query(mock_registry, mock_llm, tool_context):
    """TC-ENGINE-007: 空问题应直接返回"""
    engine = ReActEngine(registry=mock_registry, llm_service=mock_llm, max_steps=10)

    mock_llm.complete = AsyncMock(return_value={
        "action": "final_answer",
        "answer": "请提供有效的问题",
        "reasoning": "问题为空",
    })

    events = [e async for e in engine.run("", tool_context)]
    event_types = [e.type for e in events]

    # 应有 thinking 和 answer
    assert "thinking" in event_types
    assert "answer" in event_types


# =============================================================================
# TC-ENGINE-008: 历史消息截断
# =============================================================================
@pytest.mark.asyncio
async def test_tc_engine_008_history_truncation(mock_registry, mock_llm, tool_context):
    """TC-ENGINE-008: 长历史应被截断"""
    engine = ReActEngine(registry=mock_registry, llm_service=mock_llm, max_steps=10)

    # Mock session with long history
    mock_session = MagicMock()
    long_history = []
    for i in range(20):
        long_history.append(MagicMock(role="user", content=f"这是第{i}条用户消息" * 50))
    mock_session.get_messages = MagicMock(return_value=long_history)

    mock_llm.complete = AsyncMock(return_value={
        "action": "final_answer",
        "answer": "已了解",
        "reasoning": "处理长历史",
    })

    events = [e async for e in engine.run("继续分析", tool_context, session=mock_session)]

    # 应正常返回
    assert len(events) >= 2


# =============================================================================
# TC-ENGINE-009: 非 JSON LLM 响应
# =============================================================================
@pytest.mark.asyncio
async def test_tc_engine_009_non_json_response(mock_registry, mock_llm, tool_context):
    """TC-ENGINE-009: LLM 返回非 JSON 响应"""
    engine = ReActEngine(registry=mock_registry, llm_service=mock_llm, max_steps=10)

    mock_llm.complete = AsyncMock(return_value={
        "content": "这不是 JSON 格式的响应",  # 不是结构化响应
        # 没有 action 字段
    })

    events = [e async for e in engine.run("分析数据", tool_context)]
    event_types = [e.type for e in events]

    # 应有 thinking 和 answer（fallback 到文本解析）
    assert "thinking" in event_types
    assert "answer" in event_types


# =============================================================================
# TC-ENGINE-010: 多工具协同
# =============================================================================
@pytest.mark.asyncio
async def test_tc_engine_010_multi_tool_collaboration(mock_registry, mock_llm, tool_context):
    """TC-ENGINE-010: 多工具协同场景"""
    engine = ReActEngine(registry=mock_registry, llm_service=mock_llm, max_steps=10)

    call_count = [0]

    async def query_execute(params, context):
        call_count[0] += 1
        return ToolResult(success=True, data={"answer": "销售额数据"})

    async def metrics_execute(params, context):
        call_count[0] += 1
        return ToolResult(success=True, data={"metrics": []})

    class QueryTool(BaseTool):
        name = "query"
        description = "查询"
        parameters_schema = {"type": "object"}
        execute = query_execute

    class MetricsTool(BaseTool):
        name = "metrics"
        description = "指标"
        parameters_schema = {"type": "object"}
        execute = metrics_execute

    reg = ToolRegistry()
    reg.register(QueryTool())
    reg.register(MetricsTool())
    engine.registry = reg

    # 模拟: query -> metrics -> final_answer
    mock_llm.complete = AsyncMock(side_effect=[
        {"action": "tool_call", "tool_name": "query", "tool_params": {}, "reasoning": "查询数据"},
        {"action": "tool_call", "tool_name": "metrics", "tool_params": {}, "reasoning": "查询指标"},
        {"action": "final_answer", "answer": "分析完成", "reasoning": "已获取足够信息"},
    ])

    events = [e async for e in engine.run("分析销售数据", tool_context)]
    event_types = [e.type for e in events]

    # 验证两个工具都被调用
    tool_calls = [e for e in events if e.type == "tool_call"]
    assert len(tool_calls) == 2
    assert tool_calls[0].content.get("tool") == "query"
    assert tool_calls[1].content.get("tool") == "metrics"

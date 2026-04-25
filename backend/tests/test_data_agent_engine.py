"""
Data Agent 引擎单元测试 — TC-ENG-001 ~ TC-ENG-005, TC-REG-001 ~ TC-REG-004

参考：docs/specs/36-data-agent-architecture-test-cases.md
"""

import asyncio
import pytest
import time
from typing import Any, Dict, List, Optional, Union
from unittest.mock import AsyncMock, MagicMock

from services.data_agent.tool_base import BaseTool, ToolContext, ToolResult, ToolRegistry
from services.data_agent.response import AgentEvent, AgentResponse
from services.data_agent.engine import ReActEngine
from services.data_agent.prompts import build_react_system_prompt


# =============================================================================
# Mock 工具（用于 Engine 测试）
# =============================================================================

class MockTool(BaseTool):
    """可配置的 Mock 工具"""

    def __init__(
        self,
        name: str = "mock",
        description: str = "Mock tool",
        parameters_schema: dict = None,
        execute_result: ToolResult = None,
        execute_exception: Exception = None,
        execute_sleep: float = 0,
    ):
        self.name = name
        self.description = description
        self.parameters_schema = parameters_schema or {
            "type": "object",
            "properties": {"question": {"type": "string"}},
            "required": ["question"],
        }
        self._execute_result = execute_result
        self._execute_exception = execute_exception
        self._execute_sleep = execute_sleep

    async def execute(self, params: dict, context: ToolContext) -> ToolResult:
        if self._execute_sleep > 0:
            await asyncio.sleep(self._execute_sleep)
        if self._execute_exception:
            raise self._execute_exception
        return self._execute_result or ToolResult(success=True, data={"result": "mock"})


class MockLLMService:
    """Mock LLM 服务"""

    def __init__(self, responses: Union[List[dict], dict] = None):
        """
        Args:
            responses: 如果是 list，按顺序返回；如果是 dict，每次返回相同响应
        """
        if responses is None:
            responses = {"error": "LLM 未配置"}
        self._responses = responses
        self._call_count = 0

    async def complete(self, prompt: str, system: str = None, timeout: int = 15, purpose: str = "default") -> dict:
        self._call_count += 1
        if isinstance(self._responses, list):
            if self._call_count <= len(self._responses):
                return self._responses[self._call_count - 1]
            return self._responses[-1]
        return self._responses


# =============================================================================
# TC-ENG: ReAct Engine 单元测试
# =============================================================================

class TestReActEngine:
    """ReAct Engine 测试用例 TC-ENG-001 ~ TC-ENG-005"""

    @pytest.fixture
    def empty_registry(self):
        """空注册表（0个工具）"""
        return ToolRegistry()

    @pytest.fixture
    def query_tool_registry(self):
        """注册了 MockQueryTool 的注册表"""
        registry = ToolRegistry()
        tool = MockTool(
            name="query",
            description="查询数据",
            execute_result=ToolResult(success=True, data={"value": 3200}),
        )
        registry.register(tool)
        return registry

    @pytest.mark.asyncio
    async def test_tc_eng_001_direct_answer_no_tools(self, empty_registry):
        """TC-ENG-001: 单步直接回答（闲聊场景）"""
        # LLM 返回 final_answer（闲聊）
        llm = MockLLMService({
            "content": '{"action": "final_answer", "answer": "你好！有什么可以帮助你的？", "reasoning": "这是一个问候语，直接回答"}'
        })

        engine = ReActEngine(registry=empty_registry, llm_service=llm)
        context = ToolContext(session_id="s1", user_id=1, connection_id=1, trace_id="t1")

        events = []
        async for event in engine.run("你好", context):
            events.append(event)

        # 验证事件序列
        assert len(events) >= 1
        answer_events = [e for e in events if e.type == "answer"]
        assert len(answer_events) == 1
        assert "你好" in answer_events[0].content

        # 不应有 tool_call
        tool_call_events = [e for e in events if e.type == "tool_call"]
        assert len(tool_call_events) == 0

    @pytest.mark.asyncio
    async def test_tc_eng_002_single_tool_call(self, query_tool_registry):
        """TC-ENG-002: 单工具调用（查询场景）"""
        llm = MockLLMService([
            {
                "content": '{"action": "tool_call", "tool_name": "query", "tool_params": {"question": "Q4 销售额"}, "reasoning": "需要查询数据"}'
            },
            {
                "content": '{"action": "final_answer", "answer": "Q4 销售额为 3200 万元。", "reasoning": "已获取数据"}'
            },
        ])

        engine = ReActEngine(registry=query_tool_registry, llm_service=llm)
        context = ToolContext(session_id="s1", user_id=1, connection_id=1, trace_id="t1")

        events = []
        async for event in engine.run("Q4 销售额是多少", context):
            events.append(event)

        # 验证事件序列
        event_types = [e.type for e in events]

        # 必须有 thinking
        assert "thinking" in event_types

        # 必须有 tool_call
        assert "tool_call" in event_types

        # 必须有 tool_result
        assert "tool_result" in event_types

        # 必须有 answer
        answer_events = [e for e in events if e.type == "answer"]
        assert len(answer_events) == 1

        # tools_used 验证
        # （从 tool_result 事件中提取）

    @pytest.mark.asyncio
    async def test_tc_eng_003_max_steps_breaker(self, query_tool_registry):
        """TC-ENG-003: max_steps 熔断"""
        # LLM 始终返回需要继续推理的结果
        llm = MockLLMService({
            "content": '{"action": "tool_call", "tool_name": "query", "tool_params": {"question": "分析趋势"}, "reasoning": "需要更多数据"}'
        })

        engine = ReActEngine(registry=query_tool_registry, llm_service=llm, max_steps=3)
        context = ToolContext(session_id="s1", user_id=1, connection_id=1, trace_id="t1")

        events = []
        async for event in engine.run("分析一下趋势", context):
            events.append(event)

        event_types = [e.type for e in events]

        # 恰好 3 步（3 个 tool_call）
        tool_call_count = event_types.count("tool_call")
        assert tool_call_count == 3

        # 最后事件是 answer
        assert events[-1].type == "answer"
        assert "最大推理步数" in events[-1].content

        # 不抛异常

    @pytest.mark.asyncio
    async def test_tc_eng_004_tool_failure_with_retry(self):
        """TC-ENG-004: 工具执行失败，重试 1 次后仍失败"""
        registry = ToolRegistry()
        tool = MockTool(
            name="query",
            description="查询数据",
            execute_exception=RuntimeError("数据库连接失败"),
        )
        registry.register(tool)

        llm = MockLLMService({
            "content": '{"action": "tool_call", "tool_name": "query", "tool_params": {"question": "查询"}, "reasoning": "需要查询数据"}'
        })

        engine = ReActEngine(registry=registry, llm_service=llm, max_tool_retries=1)
        context = ToolContext(session_id="s1", user_id=1, connection_id=1, trace_id="t1")

        events = []
        async for event in engine.run("查询数据", context):
            events.append(event)

        event_types = [e.type for e in events]

        # 应该有 error 事件（工具失败）
        error_events = [e for e in events if e.type == "error"]
        assert len(error_events) >= 1

        # 不暴露内部异常信息
        for e in error_events:
            content = e.content if isinstance(e.content, dict) else {}
            error_msg = content.get("message", "") if isinstance(content, dict) else str(e.content)
            assert "数据库连接失败" not in error_msg
            assert "RuntimeError" not in error_msg

    @pytest.mark.asyncio
    async def test_tc_eng_005_step_timeout(self):
        """TC-ENG-005: step_timeout 超时"""
        registry = ToolRegistry()
        tool = MockTool(
            name="slow",
            description="慢工具",
            execute_sleep=40,  # 40 秒
        )
        registry.register(tool)

        llm = MockLLMService({
            "content": '{"action": "tool_call", "tool_name": "slow", "tool_params": {}, "reasoning": "需要调用慢工具"}'
        })

        engine = ReActEngine(registry=registry, llm_service=llm, step_timeout=1, total_timeout=5)
        context = ToolContext(session_id="s1", user_id=1, connection_id=1, trace_id="t1")

        events = []
        async for event in engine.run("查询", context):
            events.append(event)

        # 应该收到 error 事件
        error_events = [e for e in events if e.type == "error"]
        assert len(error_events) >= 1

        # 错误码应该是 AGENT_001
        first_error = error_events[0].content
        if isinstance(first_error, dict):
            assert first_error.get("error_code") == "AGENT_001"


# =============================================================================
# TC-REG: ToolRegistry 单元测试
# =============================================================================

class TestToolRegistry:
    """ToolRegistry 测试用例 TC-REG-001 ~ TC-REG-004"""

    def test_tc_reg_001_register_and_get(self):
        """TC-REG-001: 注册 + 获取工具"""
        registry = ToolRegistry()
        tool = MockTool(name="query", description="查询")
        registry.register(tool)

        retrieved = registry.get("query")
        assert retrieved is tool
        assert retrieved.name == "query"

    def test_tc_reg_002_get_nonexistent(self):
        """TC-REG-002: 获取不存在的工具"""
        registry = ToolRegistry()

        with pytest.raises(KeyError):
            registry.get("nonexistent")

    def test_tc_reg_003_duplicate_registration(self):
        """TC-REG-003: 重复注册同名工具"""
        registry = ToolRegistry()
        tool1 = MockTool(name="query", description="查询1")
        tool2 = MockTool(name="query", description="查询2")

        registry.register(tool1)

        with pytest.raises(ValueError) as exc_info:
            registry.register(tool2)
        assert "query" in str(exc_info.value)

    def test_tc_reg_004_get_tool_descriptions_format(self):
        """TC-REG-004: get_tool_descriptions 格式"""
        registry = ToolRegistry()

        tool1 = MockTool(
            name="query",
            description="查询数据",
            parameters_schema={
                "type": "object",
                "properties": {"question": {"type": "string", "description": "问题"}},
                "required": ["question"],
            },
        )
        tool2 = MockTool(
            name="schema",
            description="获取schema",
            parameters_schema={
                "type": "object",
                "properties": {"connection_id": {"type": "integer"}},
            },
        )

        registry.register(tool1)
        registry.register(tool2)

        descriptions = registry.get_tool_descriptions()

        assert len(descriptions) == 2
        # 验证格式
        for desc in descriptions:
            assert "name" in desc
            assert "description" in desc
            assert "parameters_schema" in desc

        names = {d["name"] for d in descriptions}
        assert "query" in names
        assert "schema" in names


# =============================================================================
# prompts.py 单元测试
# =============================================================================

class TestPrompts:
    """prompts.py 单元测试"""

    def test_build_react_system_prompt_empty(self):
        """无工具时的 system prompt"""
        prompt = build_react_system_prompt([])
        assert "Data Agent" in prompt
        assert "（暂无注册工具）" in prompt

    def test_build_react_system_prompt_with_tools(self):
        """有工具时的 system prompt"""
        tool_descriptions = [
            {
                "name": "query",
                "description": "查询数据",
                "parameters_schema": {
                    "type": "object",
                    "properties": {
                        "question": {
                            "type": "string",
                            "description": "用户问题",
                        }
                    },
                    "required": ["question"],
                },
            }
        ]
        prompt = build_react_system_prompt(tool_descriptions)
        assert "query" in prompt
        assert "查询数据" in prompt
        assert "question" in prompt


# =============================================================================
# BaseTool 子类测试
# =============================================================================

class TestBaseTool:
    """BaseTool 抽象类行为测试"""

    def test_tool_context_dataclass(self):
        """ToolContext 数据类"""
        ctx = ToolContext(session_id="s1", user_id=1, connection_id=1, trace_id="t1")
        assert ctx.session_id == "s1"
        assert ctx.user_id == 1
        assert ctx.connection_id == 1
        assert ctx.trace_id == "t1"

        # 可选字段
        ctx2 = ToolContext(session_id="s2", user_id=2)
        assert ctx2.connection_id is None
        assert ctx2.trace_id == ""

    def test_tool_result_dataclass(self):
        """ToolResult 数据类"""
        result = ToolResult(success=True, data={"value": 100}, execution_time_ms=50)
        assert result.success is True
        assert result.data == {"value": 100}
        assert result.error is None
        assert result.execution_time_ms == 50

        result2 = ToolResult(success=False, error="查询失败")
        assert result2.success is False
        assert result2.error == "查询失败"


# =============================================================================
# AgentResponse + AgentEvent 单元测试
# =============================================================================

class TestResponse:
    """AgentResponse + AgentEvent 单元测试"""

    def test_agent_response_fields(self):
        """AgentResponse 字段"""
        resp = AgentResponse(
            answer="销售额为 3200 万",
            type="number",
            data={"value": 32000000, "unit": "元"},
            trace_id="t-xxx",
            confidence=0.95,
            tools_used=["query"],
            steps_count=2,
            session_id="s-xxx",
        )
        assert resp.answer == "销售额为 3200 万"
        assert resp.type == "number"
        assert resp.tools_used == ["query"]
        assert resp.steps_count == 2

    def test_agent_event_fields(self):
        """AgentEvent 字段"""
        import time
        before = time.time()
        event = AgentEvent(type="thinking", content="正在分析...")
        after = time.time()

        assert event.type == "thinking"
        assert event.content == "正在分析..."
        assert before <= event.timestamp <= after

    def test_agent_event_types(self):
        """AgentEvent 支持的类型"""
        valid_types = ["thinking", "tool_call", "tool_result", "answer", "error", "metadata"]
        for t in valid_types:
            event = AgentEvent(type=t, content="test")
            assert event.type == t
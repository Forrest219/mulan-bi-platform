"""
CausationTool 单元测试 — stub 实现验证
"""

import pytest

from services.data_agent.tools.causation_tool import CausationTool
from services.data_agent.tool_base import ToolContext, ToolResult


class TestCausationTool:
    """CausationTool 测试用例"""

    @pytest.fixture
    def tool(self):
        return CausationTool()

    @pytest.fixture
    def context(self):
        return ToolContext(
            session_id="s1", user_id=1, connection_id=None, trace_id="t1"
        )

    # =============================================================================
    # TC-CAUSATION-001: 正常调用返回 stub 结果
    # =============================================================================
    @pytest.mark.asyncio
    async def test_tc_causation_001_stub_result(self, tool, context):
        """TC-CAUSATION-001: 正常参数返回结构化 stub 结果"""
        result = await tool.execute(
            {"metric_name": "销售额", "direction": "decrease"},
            context,
        )

        assert result.success is True
        assert result.data["status"] == "completed"
        assert result.data["metric_name"] == "销售额"
        assert result.data["direction"] == "decrease"
        assert result.data["time_range"] == "last_30d"
        assert result.data["anomaly_confirmed"] is True

    # =============================================================================
    # TC-CAUSATION-002: 缺少 metric_name
    # =============================================================================
    @pytest.mark.asyncio
    async def test_tc_causation_002_missing_metric_name(self, tool, context):
        """TC-CAUSATION-002: 缺少 metric_name 返回错误"""
        result = await tool.execute(
            {"direction": "increase"},
            context,
        )

        assert result.success is False
        assert "metric_name" in result.error

    # =============================================================================
    # TC-CAUSATION-003: 缺少 direction
    # =============================================================================
    @pytest.mark.asyncio
    async def test_tc_causation_003_missing_direction(self, tool, context):
        """TC-CAUSATION-003: 缺少 direction 返回错误"""
        result = await tool.execute(
            {"metric_name": "销售额"},
            context,
        )

        assert result.success is False
        assert "direction" in result.error

    # =============================================================================
    # TC-CAUSATION-004: direction 值非法
    # =============================================================================
    @pytest.mark.asyncio
    async def test_tc_causation_004_invalid_direction(self, tool, context):
        """TC-CAUSATION-004: direction 不在 enum 范围内"""
        result = await tool.execute(
            {"metric_name": "销售额", "direction": "sideways"},
            context,
        )

        assert result.success is False
        assert "increase" in result.error
        assert "decrease" in result.error

    # =============================================================================
    # TC-CAUSATION-005: 可选参数透传
    # =============================================================================
    @pytest.mark.asyncio
    async def test_tc_causation_005_optional_params(self, tool, context):
        """TC-CAUSATION-005: connection_id 和 time_range 正确透传"""
        result = await tool.execute(
            {
                "metric_name": "订单数",
                "direction": "increase",
                "connection_id": 42,
                "time_range": "last_30d",
            },
            context,
        )

        assert result.success is True
        assert result.success is True
        assert result.data["metric_name"] == "订单数"
        assert result.data["connection_id"] == 42
        assert result.data["time_range"] == "last_30d"

    # =============================================================================
    # TC-CAUSATION-006: context.connection_id 作为默认值
    # =============================================================================
    @pytest.mark.asyncio
    async def test_tc_causation_006_context_connection_id(self, tool):
        """TC-CAUSATION-006: 未传 connection_id 时使用 context.connection_id"""
        context = ToolContext(
            session_id="s1", user_id=1, connection_id=7, trace_id="t1"
        )

        result = await tool.execute(
            {"metric_name": "销售额", "direction": "decrease"},
            context,
        )

        assert result.success is True
        assert result.success is True
        assert result.data["connection_id"] == 7

    # =============================================================================
    # TC-CAUSATION-007: 工具元数据正确
    # =============================================================================
    def test_tc_causation_007_tool_metadata(self, tool):
        """TC-CAUSATION-007: name, description, parameters_schema 正确"""
        assert tool.name == "causation"
        assert "归因" in tool.description
        assert "metric_name" in tool.parameters_schema["properties"]
        assert "direction" in tool.parameters_schema["properties"]
        assert tool.parameters_schema["required"] == ["metric_name", "direction"]

    # =============================================================================
    # TC-CAUSATION-008: 空字符串 metric_name 视为缺失
    # =============================================================================
    @pytest.mark.asyncio
    async def test_tc_causation_008_empty_metric_name(self, tool, context):
        """TC-CAUSATION-008: 空字符串 metric_name 返回错误"""
        result = await tool.execute(
            {"metric_name": "", "direction": "increase"},
            context,
        )

        assert result.success is False
        assert "metric_name" in result.error

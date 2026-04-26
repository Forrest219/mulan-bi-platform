"""
FunnelAnalysisTool 单元测试
"""

import pytest

from services.data_agent.tools.funnel_analysis_tool import FunnelAnalysisTool
from services.data_agent.tool_base import ToolContext


class TestFunnelAnalysisTool:
    """FunnelAnalysisTool 测试用例"""

    @pytest.fixture
    def tool(self):
        return FunnelAnalysisTool()

    @pytest.fixture
    def context(self):
        return ToolContext(
            session_id="s1", user_id=1, connection_id=1, trace_id="t1"
        )

    # =============================================================================
    # TC-FUNNEL-001: 基本漏斗分析
    # =============================================================================
    @pytest.mark.asyncio
    async def test_tc_funnel_001_basic_analysis(self, tool, context):
        """TC-FUNNEL-001: 正常参数返回漏斗分析结果"""
        result = await tool.execute(
            {
                "funnel_name": "用户购买漏斗",
                "funnel_steps": [
                    {"step_name": "访问", "event_name": "page_view"},
                    {"step_name": "加购", "event_name": "add_to_cart"},
                    {"step_name": "下单", "event_name": "place_order"},
                    {"step_name": "支付", "event_name": "payment"},
                ],
                "time_range": {"start": "2026-01-01", "end": "2026-03-31"},
            },
            context,
        )

        assert result.success is True
        assert result.data["funnel_name"] == "用户购买漏斗"
        assert "step_details" in result.data
        assert "overall_conversion_rate" in result.data
        assert "step_conversion_rates" in result.data

    # =============================================================================
    # TC-FUNNEL-002: 缺少 funnel_name
    # =============================================================================
    @pytest.mark.asyncio
    async def test_tc_funnel_002_missing_funnel_name(self, tool, context):
        """TC-FUNNEL-002: 缺少 funnel_name 返回错误"""
        result = await tool.execute(
            {
                "funnel_steps": [
                    {"step_name": "访问"},
                    {"step_name": "下单"},
                ],
                "time_range": {"start": "2026-01-01", "end": "2026-03-31"},
            },
            context,
        )

        assert result.success is False
        assert "funnel_name" in result.error

    # =============================================================================
    # TC-FUNNEL-003: 少于2个步骤
    # =============================================================================
    @pytest.mark.asyncio
    async def test_tc_funnel_003_single_step(self, tool, context):
        """TC-FUNNEL-003: 只有1个步骤返回错误"""
        result = await tool.execute(
            {
                "funnel_name": "单步漏斗",
                "funnel_steps": [{"step_name": "访问"}],
                "time_range": {"start": "2026-01-01", "end": "2026-03-31"},
            },
            context,
        )

        assert result.success is False
        assert "2个步骤" in result.error

    # =============================================================================
    # TC-FUNNEL-004: 缺少 time_range
    # =============================================================================
    @pytest.mark.asyncio
    async def test_tc_funnel_004_missing_time_range(self, tool, context):
        """TC-FUNNEL-004: 缺少 time_range 返回错误"""
        result = await tool.execute(
            {
                "funnel_name": "测试漏斗",
                "funnel_steps": [
                    {"step_name": "访问"},
                    {"step_name": "下单"},
                ],
            },
            context,
        )

        assert result.success is False
        assert "time_range" in result.error

    # =============================================================================
    # TC-FUNNEL-005: 周期对比
    # =============================================================================
    @pytest.mark.asyncio
    async def test_tc_funnel_005_with_comparison(self, tool, context):
        """TC-FUNNEL-005: 启用周期对比"""
        result = await tool.execute(
            {
                "funnel_name": "用户购买漏斗",
                "funnel_steps": [
                    {"step_name": "访问"},
                    {"step_name": "下单"},
                ],
                "time_range": {"start": "2026-01-01", "end": "2026-03-31"},
                "compare_with_previous": True,
            },
            context,
        )

        assert result.success is True
        assert result.data["comparison"] is not None

    # =============================================================================
    # TC-FUNNEL-006: 工具元数据正确
    # =============================================================================
    def test_tc_funnel_006_tool_metadata(self, tool):
        """TC-FUNNEL-006: name, description, parameters_schema 正确"""
        assert tool.name == "funnel_analysis"
        assert "漏斗" in tool.description
        assert "funnel_name" in tool.parameters_schema["properties"]
        assert "funnel_steps" in tool.parameters_schema["properties"]
        assert "time_range" in tool.parameters_schema["properties"]

    # =============================================================================
    # TC-FUNNEL-007: 瓶颈识别
    # =============================================================================
    @pytest.mark.asyncio
    async def test_tc_funnel_007_bottleneck_detection(self, tool, context):
        """TC-FUNNEL-007: 返回瓶颈步骤"""
        result = await tool.execute(
            {
                "funnel_name": "用户购买漏斗",
                "funnel_steps": [
                    {"step_name": "访问"},
                    {"step_name": "下单"},
                ],
                "time_range": {"start": "2026-01-01", "end": "2026-03-31"},
            },
            context,
        )

        assert result.success is True
        assert "bottleneck_steps" in result.data

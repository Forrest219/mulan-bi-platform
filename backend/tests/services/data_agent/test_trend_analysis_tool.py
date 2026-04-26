"""
TrendAnalysisTool 单元测试
"""

import pytest

from services.data_agent.tools.trend_analysis_tool import TrendAnalysisTool
from services.data_agent.tool_base import ToolContext


class TestTrendAnalysisTool:
    """TrendAnalysisTool 测试用例"""

    @pytest.fixture
    def tool(self):
        return TrendAnalysisTool()

    @pytest.fixture
    def context(self):
        return ToolContext(
            session_id="s1", user_id=1, connection_id=1, trace_id="t1"
        )

    # =============================================================================
    # TC-TREND-001: 基本趋势分析
    # =============================================================================
    @pytest.mark.asyncio
    async def test_tc_trend_001_basic_analysis(self, tool, context):
        """TC-TREND-001: 正常参数返回趋势分析结果"""
        result = await tool.execute(
            {
                "metric": "gmv",
                "time_range": {"start": "2026-01-01", "end": "2026-03-31"},
                "granularity": "day",
            },
            context,
        )

        assert result.success is True
        assert result.data["metric"] == "gmv"
        assert "trend_direction" in result.data
        assert "slope" in result.data

    # =============================================================================
    # TC-TREND-002: 缺少 metric
    # =============================================================================
    @pytest.mark.asyncio
    async def test_tc_trend_002_missing_metric(self, tool, context):
        """TC-TREND-002: 缺少 metric 返回错误"""
        result = await tool.execute(
            {
                "time_range": {"start": "2026-01-01", "end": "2026-03-31"},
            },
            context,
        )

        assert result.success is False
        assert "metric" in result.error

    # =============================================================================
    # TC-TREND-003: 缺少 time_range
    # =============================================================================
    @pytest.mark.asyncio
    async def test_tc_trend_003_missing_time_range(self, tool, context):
        """TC-TREND-003: 缺少 time_range 返回错误"""
        result = await tool.execute(
            {
                "metric": "gmv",
            },
            context,
        )

        assert result.success is False
        assert "time_range" in result.error

    # =============================================================================
    # TC-TREND-004: 移动平均模式
    # =============================================================================
    @pytest.mark.asyncio
    async def test_tc_trend_004_moving_average(self, tool, context):
        """TC-TREND-004: 移动平均模式返回移动平均数据"""
        result = await tool.execute(
            {
                "metric": "gmv",
                "time_range": {"start": "2026-01-01", "end": "2026-03-31"},
                "analysis_mode": "moving_average",
                "window_size": 7,
            },
            context,
        )

        assert result.success is True
        assert result.data["analysis_mode"] == "moving_average"
        assert "moving_average" in result.data

    # =============================================================================
    # TC-TREND-005: 季节性分析
    # =============================================================================
    @pytest.mark.asyncio
    async def test_tc_trend_005_seasonal_analysis(self, tool, context):
        """TC-TREND-005: 季节性分析返回季节性模式"""
        result = await tool.execute(
            {
                "metric": "gmv",
                "time_range": {"start": "2026-01-01", "end": "2026-03-31"},
                "analysis_mode": "seasonal",
            },
            context,
        )

        assert result.success is True
        assert result.data["analysis_mode"] == "seasonal"
        assert "seasonal_pattern" in result.data

    # =============================================================================
    # TC-TREND-006: 工具元数据正确
    # =============================================================================
    def test_tc_trend_006_tool_metadata(self, tool):
        """TC-TREND-006: name, description, parameters_schema 正确"""
        assert tool.name == "trend_analysis"
        assert "趋势" in tool.description
        assert "metric" in tool.parameters_schema["properties"]
        assert "time_range" in tool.parameters_schema["properties"]
        assert "granularity" in tool.parameters_schema["properties"]

    # =============================================================================
    # TC-TREND-007: 拐点识别
    # =============================================================================
    @pytest.mark.asyncio
    async def test_tc_trend_007_inflection_points(self, tool, context):
        """TC-TREND-007: 返回拐点信息"""
        result = await tool.execute(
            {
                "metric": "gmv",
                "time_range": {"start": "2026-01-01", "end": "2026-03-31"},
            },
            context,
        )

        assert result.success is True
        assert "inflection_points" in result.data

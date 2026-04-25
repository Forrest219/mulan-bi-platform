"""
ChartTool 单元测试 — stub 实现验证
"""

import pytest

from services.data_agent.tools.chart_tool import ChartTool
from services.data_agent.tool_base import ToolContext, ToolResult


class TestChartTool:
    """ChartTool 测试用例"""

    @pytest.fixture
    def tool(self):
        return ChartTool()

    @pytest.fixture
    def context(self):
        return ToolContext(
            session_id="s1", user_id=1, connection_id=None, trace_id="t1"
        )

    @pytest.fixture
    def sample_data(self):
        return {
            "fields": ["month", "sales"],
            "rows": [
                ["2024-01", 100],
                ["2024-02", 150],
            ],
        }

    # =============================================================================
    # TC-CHART-001: 正常调用返回 stub 结果
    # =============================================================================
    @pytest.mark.asyncio
    async def test_tc_chart_001_stub_result(self, tool, context, sample_data):
        """TC-CHART-001: 正常参数返回结构化 stub 结果"""
        result = await tool.execute(
            {
                "chart_type": "bar",
                "data": sample_data,
                "title": "月度销售",
                "x_field": "month",
                "y_field": "sales",
            },
            context,
        )

        assert result.success is True
        assert result.data["status"] == "not_implemented"
        assert result.data["message"] == "图表生成功能开发中"
        assert result.data["chart_type"] == "bar"
        assert result.data["title"] == "月度销售"
        assert result.data["x_field"] == "month"
        assert result.data["y_field"] == "sales"

    # =============================================================================
    # TC-CHART-002: 缺少 chart_type
    # =============================================================================
    @pytest.mark.asyncio
    async def test_tc_chart_002_missing_chart_type(self, tool, context, sample_data):
        """TC-CHART-002: 缺少 chart_type 返回错误"""
        result = await tool.execute(
            {"data": sample_data},
            context,
        )

        assert result.success is False
        assert "chart_type" in result.error

    # =============================================================================
    # TC-CHART-003: 缺少 data
    # =============================================================================
    @pytest.mark.asyncio
    async def test_tc_chart_003_missing_data(self, tool, context):
        """TC-CHART-003: 缺少 data 返回错误"""
        result = await tool.execute(
            {"chart_type": "line"},
            context,
        )

        assert result.success is False
        assert "data" in result.error

    # =============================================================================
    # TC-CHART-004: chart_type 非法值
    # =============================================================================
    @pytest.mark.asyncio
    async def test_tc_chart_004_invalid_chart_type(self, tool, context, sample_data):
        """TC-CHART-004: chart_type 不在 enum 范围内"""
        result = await tool.execute(
            {"chart_type": "radar", "data": sample_data},
            context,
        )

        assert result.success is False
        assert "chart_type" in result.error

    # =============================================================================
    # TC-CHART-005: 所有合法 chart_type 均可通过
    # =============================================================================
    @pytest.mark.asyncio
    @pytest.mark.parametrize("chart_type", ["bar", "line", "pie", "scatter", "table"])
    async def test_tc_chart_005_all_valid_chart_types(self, tool, context, sample_data, chart_type):
        """TC-CHART-005: 所有合法 chart_type 均返回成功"""
        result = await tool.execute(
            {"chart_type": chart_type, "data": sample_data},
            context,
        )

        assert result.success is True
        assert result.data["chart_type"] == chart_type

    # =============================================================================
    # TC-CHART-006: 可选参数缺省
    # =============================================================================
    @pytest.mark.asyncio
    async def test_tc_chart_006_minimal_params(self, tool, context, sample_data):
        """TC-CHART-006: 只传必填参数，可选参数使用默认值"""
        result = await tool.execute(
            {"chart_type": "pie", "data": sample_data},
            context,
        )

        assert result.success is True
        assert result.data["title"] == ""
        assert result.data["x_field"] == ""
        assert result.data["y_field"] == ""

    # =============================================================================
    # TC-CHART-007: 工具元数据正确
    # =============================================================================
    def test_tc_chart_007_tool_metadata(self, tool):
        """TC-CHART-007: name, description, parameters_schema 正确"""
        assert tool.name == "chart"
        assert "图表" in tool.description
        assert "chart_type" in tool.parameters_schema["properties"]
        assert "data" in tool.parameters_schema["properties"]
        assert set(tool.parameters_schema["required"]) == {"chart_type", "data"}

    # =============================================================================
    # TC-CHART-008: 空字符串 chart_type 视为缺失
    # =============================================================================
    @pytest.mark.asyncio
    async def test_tc_chart_008_empty_chart_type(self, tool, context, sample_data):
        """TC-CHART-008: 空字符串 chart_type 返回错误"""
        result = await tool.execute(
            {"chart_type": "", "data": sample_data},
            context,
        )

        assert result.success is False
        assert "chart_type" in result.error

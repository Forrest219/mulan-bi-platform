"""
ChartTool 单元测试 — Viz Agent 集成版契约验证
"""

import pytest

from services.data_agent.tools.chart_tool import ChartTool, VALID_CHART_TYPES
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
    # TC-CHART-001: 正常调用返回规格卡片结果
    # =============================================================================
    @pytest.mark.asyncio
    async def test_tc_chart_001_card_result(self, tool, context, sample_data):
        """TC-CHART-001: 显式图表类型和字段返回结构化规格卡片"""
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
        assert result.data["output_mode"] == "card"
        assert result.data["chart_type"] == "bar"
        assert result.data["field_mapping"]["x"] == "month"
        assert result.data["field_mapping"]["y"] == "sales"
        assert result.data["tableau_mark_type"] == "Bar"
        assert "spec_card" in result.data

    # =============================================================================
    # TC-CHART-002: 缺少 schema/data
    # =============================================================================
    @pytest.mark.asyncio
    async def test_tc_chart_002_missing_chart_type(self, tool, context, sample_data):
        """TC-CHART-002: schema 和 data 同时缺失返回错误"""
        result = await tool.execute(
            {"chart_type": "bar"},
            context,
        )

        assert result.success is False
        assert "schema" in result.error
        assert "data" in result.error

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
    @pytest.mark.parametrize("chart_type", VALID_CHART_TYPES)
    async def test_tc_chart_005_all_valid_chart_types(self, tool, context, sample_data, chart_type):
        """TC-CHART-005: 所有合法 chart_type 均返回成功"""
        result = await tool.execute(
            {
                "chart_type": chart_type,
                "data": sample_data,
                "x_field": "month",
                "y_field": "sales",
            },
            context,
        )

        assert result.success is True
        assert result.data["chart_type"] == chart_type

    # =============================================================================
    # TC-CHART-006: 可选参数缺省
    # =============================================================================
    @pytest.mark.asyncio
    async def test_tc_chart_006_minimal_params(self, tool, context, sample_data):
        """TC-CHART-006: 未指定 chart_type 时使用 Viz Agent 推荐"""
        async def fake_recommend(schema, user_intent, connection_id):
            return {
                "rank": 1,
                "chart_type": "line",
                "confidence": 0.9,
                "reason": "趋势字段推荐折线图",
                "field_mapping": {"x": "month", "y": "sales"},
                "tableau_mark_type": "Line",
                "suggested_title": "月度销售趋势",
            }

        tool._call_viz_agent_recommend = fake_recommend
        result = await tool.execute(
            {"data": sample_data},
            context,
        )

        assert result.success is True
        assert result.data["chart_type"] == "line"
        assert result.data["field_mapping"]["x"] == "month"
        assert result.data["field_mapping"]["y"] == "sales"

    # =============================================================================
    # TC-CHART-007: 工具元数据正确
    # =============================================================================
    def test_tc_chart_007_tool_metadata(self, tool):
        """TC-CHART-007: name, description, parameters_schema 正确"""
        assert tool.name == "chart"
        assert "图表" in tool.description
        assert "chart_type" in tool.parameters_schema["properties"]
        assert "data" in tool.parameters_schema["properties"]
        assert tool.parameters_schema["required"] == []

    # =============================================================================
    # TC-CHART-008: 空字符串 chart_type 视为缺失
    # =============================================================================
    @pytest.mark.asyncio
    async def test_tc_chart_008_empty_chart_type(self, tool, context, sample_data):
        """TC-CHART-008: 空字符串 chart_type 视为未指定并使用推荐器"""
        async def fake_recommend(schema, user_intent, connection_id):
            return {
                "rank": 1,
                "chart_type": "bar",
                "confidence": 0.8,
                "reason": "默认推荐柱状图",
                "field_mapping": {"x": "month", "y": "sales"},
                "tableau_mark_type": "Bar",
                "suggested_title": "月度销售",
            }

        tool._call_viz_agent_recommend = fake_recommend
        result = await tool.execute(
            {"chart_type": "", "data": sample_data},
            context,
        )

        assert result.success is True
        assert result.data["chart_type"] == "bar"

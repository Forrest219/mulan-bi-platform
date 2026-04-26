"""
RootCauseAnalysisTool 单元测试
"""

import pytest

from services.data_agent.tools.root_cause_analysis_tool import RootCauseAnalysisTool
from services.data_agent.tool_base import ToolContext


class TestRootCauseAnalysisTool:
    """RootCauseAnalysisTool 测试用例"""

    @pytest.fixture
    def tool(self):
        return RootCauseAnalysisTool()

    @pytest.fixture
    def context(self):
        return ToolContext(
            session_id="s1", user_id=1, connection_id=1, trace_id="t1"
        )

    # =============================================================================
    # TC-RCA-001: 基本根因分析
    # =============================================================================
    @pytest.mark.asyncio
    async def test_tc_rca_001_basic_analysis(self, tool, context):
        """TC-RCA-001: 正常参数返回根因分析结果"""
        result = await tool.execute(
            {
                "problem_statement": "GMV 连续两周下降",
                "problem_metric": "gmv",
                "direction": "decrease",
            },
            context,
        )

        assert result.success is True
        assert result.data["problem_metric"] == "gmv"
        assert result.data["direction"] == "decrease"
        assert "five_why_analysis" in result.data
        assert "fishbone_analysis" in result.data
        assert "root_causes" in result.data

    # =============================================================================
    # TC-RCA-002: 缺少 problem_statement
    # =============================================================================
    @pytest.mark.asyncio
    async def test_tc_rca_002_missing_problem_statement(self, tool, context):
        """TC-RCA-002: 缺少 problem_statement 返回错误"""
        result = await tool.execute(
            {
                "problem_metric": "gmv",
                "direction": "decrease",
            },
            context,
        )

        assert result.success is False
        assert "problem_statement" in result.error

    # =============================================================================
    # TC-RCA-003: 缺少 problem_metric
    # =============================================================================
    @pytest.mark.asyncio
    async def test_tc_rca_003_missing_problem_metric(self, tool, context):
        """TC-RCA-003: 缺少 problem_metric 返回错误"""
        result = await tool.execute(
            {
                "problem_statement": "GMV 下降",
                "direction": "decrease",
            },
            context,
        )

        assert result.success is False
        assert "problem_metric" in result.error

    # =============================================================================
    # TC-RCA-004: 非法 direction
    # =============================================================================
    @pytest.mark.asyncio
    async def test_tc_rca_004_invalid_direction(self, tool, context):
        """TC-RCA-004: direction 不在 enum 范围内"""
        result = await tool.execute(
            {
                "problem_statement": "GMV 下降",
                "problem_metric": "gmv",
                "direction": "sideways",
            },
            context,
        )

        assert result.success is False
        assert "increase" in result.error
        assert "decrease" in result.error

    # =============================================================================
    # TC-RCA-005: 增长方向分析
    # =============================================================================
    @pytest.mark.asyncio
    async def test_tc_rca_005_increase_direction(self, tool, context):
        """TC-RCA-005: direction=increase 正常工作"""
        result = await tool.execute(
            {
                "problem_statement": "订单数异常增长",
                "problem_metric": "order_count",
                "direction": "increase",
            },
            context,
        )

        assert result.success is True
        assert result.data["direction"] == "increase"

    # =============================================================================
    # TC-RCA-006: 工具元数据正确
    # =============================================================================
    def test_tc_rca_006_tool_metadata(self, tool):
        """TC-RCA-006: name, description, parameters_schema 正确"""
        assert tool.name == "root_cause_analysis"
        assert "根因" in tool.description
        assert "problem_statement" in tool.parameters_schema["properties"]
        assert "problem_metric" in tool.parameters_schema["properties"]
        assert "direction" in tool.parameters_schema["properties"]
        assert "analysis_depth" in tool.parameters_schema["properties"]

    # =============================================================================
    # TC-RCA-007: 影响因子返回
    # =============================================================================
    @pytest.mark.asyncio
    async def test_tc_rca_007_impact_factors(self, tool, context):
        """TC-RCA-007: 返回影响因子"""
        result = await tool.execute(
            {
                "problem_statement": "GMV 下降",
                "problem_metric": "gmv",
                "direction": "decrease",
            },
            context,
        )

        assert result.success is True
        assert "impact_factors" in result.data
        assert "confidence" in result.data

    # =============================================================================
    # TC-RCA-008: 鱼骨图分析
    # =============================================================================
    @pytest.mark.asyncio
    async def test_tc_rca_008_fishbone_analysis(self, tool, context):
        """TC-RCA-008: 返回鱼骨图分析"""
        result = await tool.execute(
            {
                "problem_statement": "GMV 下降",
                "problem_metric": "gmv",
                "direction": "decrease",
                "root_cause_categories": ["people", "process", "technology"],
            },
            context,
        )

        assert result.success is True
        fishbone = result.data["fishbone_analysis"]
        assert "categories" in fishbone

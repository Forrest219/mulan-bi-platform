"""
CohortAnalysisTool 单元测试
"""

import pytest

from services.data_agent.tools.cohort_analysis_tool import CohortAnalysisTool
from services.data_agent.tool_base import ToolContext


class TestCohortAnalysisTool:
    """CohortAnalysisTool 测试用例"""

    @pytest.fixture
    def tool(self):
        return CohortAnalysisTool()

    @pytest.fixture
    def context(self):
        return ToolContext(
            session_id="s1", user_id=1, connection_id=1, trace_id="t1"
        )

    # =============================================================================
    # TC-COHORT-001: 基本队列分析
    # =============================================================================
    @pytest.mark.asyncio
    async def test_tc_cohort_001_basic_analysis(self, tool, context):
        """TC-COHORT-001: 正常参数返回队列分析结果"""
        result = await tool.execute(
            {
                "cohort_type": "time",
                "time_range": {"start": "2026-01-01", "end": "2026-06-30"},
            },
            context,
        )

        assert result.success is True
        assert result.data["cohort_type"] == "time"
        assert "cohorts" in result.data
        assert len(result.data["cohorts"]) > 0

    # =============================================================================
    # TC-COHORT-002: 缺少 cohort_type
    # =============================================================================
    @pytest.mark.asyncio
    async def test_tc_cohort_002_missing_cohort_type(self, tool, context):
        """TC-COHORT-002: 缺少 cohort_type 返回错误"""
        result = await tool.execute(
            {
                "time_range": {"start": "2026-01-01", "end": "2026-06-30"},
            },
            context,
        )

        assert result.success is False
        assert "cohort_type" in result.error

    # =============================================================================
    # TC-COHORT-003: 缺少 time_range
    # =============================================================================
    @pytest.mark.asyncio
    async def test_tc_cohort_003_missing_time_range(self, tool, context):
        """TC-COHORT-003: 缺少 time_range 返回错误"""
        result = await tool.execute(
            {
                "cohort_type": "time",
            },
            context,
        )

        assert result.success is False
        assert "time_range" in result.error

    # =============================================================================
    # TC-COHORT-004: 渠道队列分析
    # =============================================================================
    @pytest.mark.asyncio
    async def test_tc_cohort_004_channel_cohort(self, tool, context):
        """TC-COHORT-004: 渠道队列类型"""
        result = await tool.execute(
            {
                "cohort_type": "channel",
                "time_range": {"start": "2026-01-01", "end": "2026-06-30"},
            },
            context,
        )

        assert result.success is True
        assert result.data["cohort_type"] == "channel"

    # =============================================================================
    # TC-COHORT-005: 工具元数据正确
    # =============================================================================
    def test_tc_cohort_005_tool_metadata(self, tool):
        """TC-COHORT-005: name, description, parameters_schema 正确"""
        assert tool.name == "cohort_analysis"
        assert "队列" in tool.description
        assert "cohort_type" in tool.parameters_schema["properties"]
        assert "time_range" in tool.parameters_schema["properties"]
        assert "num_periods" in tool.parameters_schema["properties"]

    # =============================================================================
    # TC-COHORT-006: 留存曲线返回
    # =============================================================================
    @pytest.mark.asyncio
    async def test_tc_cohort_006_retention_curve(self, tool, context):
        """TC-COHORT-006: 返回留存曲线"""
        result = await tool.execute(
            {
                "cohort_type": "time",
                "time_range": {"start": "2026-01-01", "end": "2026-06-30"},
            },
            context,
        )

        assert result.success is True
        assert "retention_curve" in result.data

    # =============================================================================
    # TC-COHORT-007: 队列对比
    # =============================================================================
    @pytest.mark.asyncio
    async def test_tc_cohort_007_cohort_comparison(self, tool, context):
        """TC-COHORT-007: 返回队列对比信息"""
        result = await tool.execute(
            {
                "cohort_type": "time",
                "time_range": {"start": "2026-01-01", "end": "2026-06-30"},
                "num_periods": 6,
            },
            context,
        )

        assert result.success is True
        assert "cohort_comparison" in result.data

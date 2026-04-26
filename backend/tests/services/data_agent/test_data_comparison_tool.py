"""
DataComparisonTool 单元测试
"""

import pytest

from services.data_agent.tools.data_comparison_tool import DataComparisonTool
from services.data_agent.tool_base import ToolContext


class TestDataComparisonTool:
    """DataComparisonTool 测试用例"""

    @pytest.fixture
    def tool(self):
        return DataComparisonTool()

    @pytest.fixture
    def context(self):
        return ToolContext(
            session_id="s1", user_id=1, connection_id=1, trace_id="t1"
        )

    # =============================================================================
    # TC-COMPARE-001: 基本比较
    # =============================================================================
    @pytest.mark.asyncio
    async def test_tc_compare_001_basic_comparison(self, tool, context):
        """TC-COMPARE-001: 正常参数返回比较结果"""
        result = await tool.execute(
            {
                "dataset_a": {
                    "metric": "gmv",
                    "time_range": {"start": "2026-01-01", "end": "2026-03-31"},
                },
                "dataset_b": {
                    "metric": "gmv",
                    "time_range": {"start": "2025-01-01", "end": "2025-03-31"},
                },
                "comparison_type": "temporal",
            },
            context,
        )

        assert result.success is True
        assert result.data["comparison_type"] == "temporal"
        assert "differences" in result.data
        assert "similarities" in result.data
        assert "statistical_significance" in result.data

    # =============================================================================
    # TC-COMPARE-002: 缺少 dataset_a
    # =============================================================================
    @pytest.mark.asyncio
    async def test_tc_compare_002_missing_dataset_a(self, tool, context):
        """TC-COMPARE-002: 缺少 dataset_a 返回错误"""
        result = await tool.execute(
            {
                "dataset_b": {"metric": "gmv"},
            },
            context,
        )

        assert result.success is False
        assert "dataset_a" in result.error

    # =============================================================================
    # TC-COMPARE-003: 缺少 dataset_b
    # =============================================================================
    @pytest.mark.asyncio
    async def test_tc_compare_003_missing_dataset_b(self, tool, context):
        """TC-COMPARE-003: 缺少 dataset_b 返回错误"""
        result = await tool.execute(
            {
                "dataset_a": {"metric": "gmv"},
            },
            context,
        )

        assert result.success is False
        assert "dataset_b" in result.error

    # =============================================================================
    # TC-COMPARE-004: 横截面比较
    # =============================================================================
    @pytest.mark.asyncio
    async def test_tc_compare_004_cross_sectional(self, tool, context):
        """TC-COMPARE-004: 横截面比较正常工作"""
        result = await tool.execute(
            {
                "dataset_a": {
                    "metric": "gmv",
                    "dimension": "华北",
                },
                "dataset_b": {
                    "metric": "gmv",
                    "dimension": "华南",
                },
                "comparison_type": "cross_sectional",
            },
            context,
        )

        assert result.success is True
        assert result.data["comparison_type"] == "cross_sectional"

    # =============================================================================
    # TC-COMPARE-005: 工具元数据正确
    # =============================================================================
    def test_tc_compare_005_tool_metadata(self, tool):
        """TC-COMPARE-005: name, description, parameters_schema 正确"""
        assert tool.name == "data_comparison"
        assert "比较" in tool.description
        assert "dataset_a" in tool.parameters_schema["properties"]
        assert "dataset_b" in tool.parameters_schema["properties"]
        assert "comparison_type" in tool.parameters_schema["properties"]

    # =============================================================================
    # TC-COMPARE-006: 统计显著性返回
    # =============================================================================
    @pytest.mark.asyncio
    async def test_tc_compare_006_statistical_significance(self, tool, context):
        """TC-COMPARE-006: 返回统计显著性信息"""
        result = await tool.execute(
            {
                "dataset_a": {"metric": "gmv"},
                "dataset_b": {"metric": "gmv"},
            },
            context,
        )

        assert result.success is True
        sig = result.data["statistical_significance"]
        assert "p_value" in sig
        assert "significant" in sig

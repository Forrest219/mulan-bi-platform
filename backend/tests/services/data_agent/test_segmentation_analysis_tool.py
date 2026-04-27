"""
SegmentationAnalysisTool 单元测试
"""

import pytest

from services.data_agent.tools.segmentation_analysis_tool import SegmentationAnalysisTool
from services.data_agent.tool_base import ToolContext


class TestSegmentationAnalysisTool:
    """SegmentationAnalysisTool 测试用例"""

    @pytest.fixture
    def tool(self):
        return SegmentationAnalysisTool()

    @pytest.fixture
    def context(self):
        return ToolContext(
            session_id="s1", user_id=1, connection_id=1, trace_id="t1"
        )

    # =============================================================================
    # TC-SEGM-001: 基本分群分析
    # =============================================================================
    @pytest.mark.asyncio
    async def test_tc_segm_001_basic_analysis(self, tool, context):
        """TC-SEGM-001: 正常参数返回分群结果"""
        result = await tool.execute(
            {
                "entity_type": "user",
                "segmentation_dimensions": ["activity_level", "purchase_frequency"],
                "time_range": {"start": "2026-01-01", "end": "2026-03-31"},
            },
            context,
        )

        assert result.success is True
        assert result.data["entity_type"] == "user"
        assert "segments" in result.data
        assert len(result.data["segments"]) > 0

    # =============================================================================
    # TC-SEGM-002: 缺少 segmentation_dimensions
    # =============================================================================
    @pytest.mark.asyncio
    async def test_tc_segm_002_missing_dimensions(self, tool, context):
        """TC-SEGM-002: 缺少 segmentation_dimensions 返回错误"""
        result = await tool.execute(
            {
                "entity_type": "user",
                "time_range": {"start": "2026-01-01", "end": "2026-03-31"},
            },
            context,
        )

        assert result.success is False
        assert "segmentation_dimensions" in result.error

    # =============================================================================
    # TC-SEGM-003: 缺少 time_range
    # =============================================================================
    @pytest.mark.asyncio
    async def test_tc_segm_003_missing_time_range(self, tool, context):
        """TC-SEGM-003: 缺少 time_range 返回错误"""
        result = await tool.execute(
            {
                "entity_type": "user",
                "segmentation_dimensions": ["activity_level"],
            },
            context,
        )

        assert result.success is False
        assert "time_range" in result.error

    # =============================================================================
    # TC-SEGM-004: 指定分群数量
    # =============================================================================
    @pytest.mark.asyncio
    async def test_tc_segm_004_custom_num_segments(self, tool, context):
        """TC-SEGM-004: 指定分群数量"""
        result = await tool.execute(
            {
                "entity_type": "customer",
                "segmentation_dimensions": ["engagement_score"],
                "time_range": {"start": "2026-01-01", "end": "2026-03-31"},
                "num_segments": 5,
            },
            context,
        )

        assert result.success is True
        assert result.data["num_segments"] == 5

    # =============================================================================
    # TC-SEGM-005: 工具元数据正确
    # =============================================================================
    def test_tc_segm_005_tool_metadata(self, tool):
        """TC-SEGM-005: name, description, parameters_schema 正确"""
        assert tool.name == "segmentation_analysis"
        assert "分群" in tool.description
        assert "entity_type" in tool.parameters_schema["properties"]
        assert "segmentation_dimensions" in tool.parameters_schema["properties"]
        assert "time_range" in tool.parameters_schema["properties"]

    # =============================================================================
    # TC-SEGM-006: 分群摘要返回
    # =============================================================================
    @pytest.mark.asyncio
    async def test_tc_segm_006_segment_summary(self, tool, context):
        """TC-SEGM-006: 返回分群摘要"""
        result = await tool.execute(
            {
                "entity_type": "user",
                "segmentation_dimensions": ["activity"],
                "time_range": {"start": "2026-01-01", "end": "2026-03-31"},
            },
            context,
        )

        assert result.success is True
        assert "segment_summary" in result.data
        assert "total_entities" in result.data["segment_summary"]

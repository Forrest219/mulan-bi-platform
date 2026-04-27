"""
ProactiveInsightTool 单元测试
"""

import pytest

from services.data_agent.tools.proactive_insight_tool import ProactiveInsightTool
from services.data_agent.tool_base import ToolContext


class TestProactiveInsightTool:
    """ProactiveInsightTool 测试用例"""

    @pytest.fixture
    def tool(self):
        return ProactiveInsightTool()

    @pytest.fixture
    def context(self):
        return ToolContext(
            session_id="s1", user_id=1, connection_id=1, trace_id="t1"
        )

    # =============================================================================
    # TC-PROACTIVE-001: 全量扫描
    # =============================================================================
    @pytest.mark.asyncio
    async def test_tc_proactive_001_full_scan(self, tool, context):
        """TC-PROACTIVE-001: 全量扫描返回检测结果"""
        result = await tool.execute(
            {
                "scan_type": "full",
                "metrics": ["gmv", "order_count"],
            },
            context,
        )

        assert result.success is True
        assert result.data["scan_type"] == "full"
        assert "detections" in result.data
        assert "insights_generated" in result.data

    # =============================================================================
    # TC-PROACTIVE-002: 增量扫描
    # =============================================================================
    @pytest.mark.asyncio
    async def test_tc_proactive_002_incremental_scan(self, tool, context):
        """TC-PROACTIVE-002: 增量扫描正常工作"""
        result = await tool.execute(
            {
                "scan_type": "incremental",
                "metrics": ["gmv"],
            },
            context,
        )

        assert result.success is True
        assert result.data["scan_type"] == "incremental"

    # =============================================================================
    # TC-PROACTIVE-003: 触发式扫描
    # =============================================================================
    @pytest.mark.asyncio
    async def test_tc_proactive_003_triggered_scan(self, tool, context):
        """TC-PROACTIVE-003: 触发式扫描正常工作"""
        result = await tool.execute(
            {
                "scan_type": "triggered",
                "metrics": ["gmv"],
            },
            context,
        )

        assert result.success is True
        assert result.data["scan_type"] == "triggered"

    # =============================================================================
    # TC-PROACTIVE-004: 空 metrics 扫描全部
    # =============================================================================
    @pytest.mark.asyncio
    async def test_tc_proactive_004_scan_all_metrics(self, tool, context):
        """TC-PROACTIVE-004: 不指定 metrics 时扫描全部"""
        result = await tool.execute(
            {"scan_type": "incremental"},
            context,
        )

        assert result.success is True
        assert result.data["metrics_scanned"] > 0

    # =============================================================================
    # TC-PROACTIVE-005: 工具元数据正确
    # =============================================================================
    def test_tc_proactive_005_tool_metadata(self, tool):
        """TC-PROACTIVE-005: name, description, parameters_schema 正确"""
        assert tool.name == "proactive_insight"
        assert "主动" in tool.description or "洞察" in tool.description
        assert "scan_type" in tool.parameters_schema["properties"]
        assert "metrics" in tool.parameters_schema["properties"]

    # =============================================================================
    # TC-PROACTIVE-006: 扫描维度正确
    # =============================================================================
    def test_tc_proactive_006_scan_dimensions(self, tool):
        """TC-PROACTIVE-006: SCAN_DIMENSIONS 包含所有扫描类型"""
        assert "yoy_anomaly" in tool.SCAN_DIMENSIONS
        assert "qoq_anomaly" in tool.SCAN_DIMENSIONS
        assert "dimension_concentration" in tool.SCAN_DIMENSIONS
        assert "correlation_shift" in tool.SCAN_DIMENSIONS
        assert "quality_degradation" in tool.SCAN_DIMENSIONS

    # =============================================================================
    # TC-PROACTIVE-007: 洞察生成过滤
    # =============================================================================
    @pytest.mark.asyncio
    async def test_tc_proactive_007_insight_filtering(self, tool, context):
        """TC-PROACTIVE-007: 置信度 < 0.6 的检测不生成洞察"""
        result = await tool.execute(
            {
                "scan_type": "incremental",
                "metrics": [],
            },
            context,
        )

        assert result.success is True
        for insight in result.data.get("insights_generated", []):
            assert insight.get("confidence", 0) >= 0.6

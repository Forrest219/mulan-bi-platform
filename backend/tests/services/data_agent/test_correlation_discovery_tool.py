"""
CorrelationDiscoveryTool 单元测试
"""

import pytest

from services.data_agent.tools.correlation_discovery_tool import CorrelationDiscoveryTool
from services.data_agent.tool_base import ToolContext


class TestCorrelationDiscoveryTool:
    """CorrelationDiscoveryTool 测试用例"""

    @pytest.fixture
    def tool(self):
        return CorrelationDiscoveryTool()

    @pytest.fixture
    def context(self):
        return ToolContext(
            session_id="s1", user_id=1, connection_id=1, trace_id="t1"
        )

    # =============================================================================
    # TC-CORR-001: 基本相关性分析
    # =============================================================================
    @pytest.mark.asyncio
    async def test_tc_corr_001_basic_analysis(self, tool, context):
        """TC-CORR-001: 正常参数返回相关性结果"""
        result = await tool.execute(
            {
                "metrics": ["gmv", "order_count"],
                "time_range": {"start": "2026-01-01", "end": "2026-03-31"},
            },
            context,
        )

        assert result.success is True
        assert "correlations" in result.data
        assert "strong_correlations" in result.data
        assert "weak_correlations" in result.data

    # =============================================================================
    # TC-CORR-002: 少于2个指标
    # =============================================================================
    @pytest.mark.asyncio
    async def test_tc_corr_002_single_metric(self, tool, context):
        """TC-CORR-002: 只有1个指标时返回错误"""
        result = await tool.execute(
            {
                "metrics": ["gmv"],
                "time_range": {"start": "2026-01-01", "end": "2026-03-31"},
            },
            context,
        )

        assert result.success is False
        assert "2个指标" in result.error

    # =============================================================================
    # TC-CORR-003: 缺少 time_range
    # =============================================================================
    @pytest.mark.asyncio
    async def test_tc_corr_003_missing_time_range(self, tool, context):
        """TC-CORR-003: 缺少 time_range 返回错误"""
        result = await tool.execute(
            {
                "metrics": ["gmv", "order_count"],
            },
            context,
        )

        assert result.success is False
        assert "time_range" in result.error

    # =============================================================================
    # TC-CORR-004: 滞后分析
    # =============================================================================
    @pytest.mark.asyncio
    async def test_tc_corr_004_lag_analysis(self, tool, context):
        """TC-CORR-004: 启用滞后分析时返回滞后信息"""
        result = await tool.execute(
            {
                "metrics": ["gmv", "order_count"],
                "time_range": {"start": "2026-01-01", "end": "2026-03-31"},
                "lag_analysis": True,
            },
            context,
        )

        assert result.success is True
        assert result.data["lag_analysis"] is not None

    # =============================================================================
    # TC-CORR-005: 皮尔逊相关系数
    # =============================================================================
    @pytest.mark.asyncio
    async def test_tc_corr_005_pearson_method(self, tool, context):
        """TC-CORR-005: 指定皮尔逊方法"""
        result = await tool.execute(
            {
                "metrics": ["gmv", "order_count"],
                "time_range": {"start": "2026-01-01", "end": "2026-03-31"},
                "method": "pearson",
            },
            context,
        )

        assert result.success is True
        assert result.data["method"] == "pearson"
        for corr in result.data["correlations"]:
            assert "pearson_r" in corr

    # =============================================================================
    # TC-CORR-006: 工具元数据正确
    # =============================================================================
    def test_tc_corr_006_tool_metadata(self, tool):
        """TC-CORR-006: name, description, parameters_schema 正确"""
        assert tool.name == "correlation_discovery"
        assert "相关" in tool.description
        assert "metrics" in tool.parameters_schema["properties"]
        assert "time_range" in tool.parameters_schema["properties"]
        assert "method" in tool.parameters_schema["properties"]

    # =============================================================================
    # TC-CORR-007: 最小相关系数阈值
    # =============================================================================
    @pytest.mark.asyncio
    async def test_tc_corr_007_min_correlation_threshold(self, tool, context):
        """TC-CORR-007: min_correlation 参数正确过滤"""
        result = await tool.execute(
            {
                "metrics": ["gmv", "order_count"],
                "time_range": {"start": "2026-01-01", "end": "2026-03-31"},
                "min_correlation": 0.8,
            },
            context,
        )

        assert result.success is True
        for corr in result.data["strong_correlations"]:
            assert abs(corr["pearson_r"]) >= 0.8

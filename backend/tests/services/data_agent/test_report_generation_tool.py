"""
ReportGenerationTool 单元测试
"""

import pytest

from services.data_agent.tools.report_generation_tool import ReportGenerationTool
from services.data_agent.tool_base import ToolContext


class TestReportGenerationTool:
    """ReportGenerationTool 测试用例"""

    @pytest.fixture
    def tool(self):
        return ReportGenerationTool()

    @pytest.fixture
    def context(self):
        return ToolContext(
            session_id="s1", user_id=1, connection_id=None, trace_id="t1"
        )

    # =============================================================================
    # TC-REPORT-001: 正常调用
    # =============================================================================
    @pytest.mark.asyncio
    async def test_tc_report_001_basic_generation(self, tool, context):
        """TC-REPORT-001: 正常参数返回结构化报告"""
        result = await tool.execute(
            {
                "subject": "华北区域 Q1 分析报告",
                "analysis_type": "causation",
                "analysis_result": {
                    "metric_name": "GMV",
                    "direction": "decrease",
                    "magnitude": 0.12,
                    "root_cause_description": "北京区域流量下滑",
                    "confidence": 0.85,
                    "hypotheses": [
                        {
                            "id": "hyp_001",
                            "description": "北京区域流量下滑",
                            "status": "confirmed",
                            "confidence": 0.85,
                        }
                    ],
                    "recommended_actions": [
                        {"action": "调低 Q2 业绩目标", "priority": "HIGH"}
                    ],
                },
            },
            context,
        )

        assert result.success is True
        assert result.data["subject"] == "华北区域 Q1 分析报告"
        assert result.data["analysis_type"] == "causation"
        assert "content_json" in result.data
        assert "metadata" in result.data["content_json"]
        assert result.data["content_json"]["metadata"]["confidence"] == 0.85

    # =============================================================================
    # TC-REPORT-002: 缺少 subject
    # =============================================================================
    @pytest.mark.asyncio
    async def test_tc_report_002_missing_subject(self, tool, context):
        """TC-REPORT-002: 缺少 subject 返回错误"""
        result = await tool.execute(
            {
                "analysis_type": "causation",
                "analysis_result": {"metric_name": "GMV"},
            },
            context,
        )

        assert result.success is False
        assert "subject" in result.error

    # =============================================================================
    # TC-REPORT-003: 缺少 analysis_type
    # =============================================================================
    @pytest.mark.asyncio
    async def test_tc_report_003_missing_analysis_type(self, tool, context):
        """TC-REPORT-003: 缺少 analysis_type 返回错误"""
        result = await tool.execute(
            {
                "subject": "测试报告",
                "analysis_result": {"metric_name": "GMV"},
            },
            context,
        )

        assert result.success is False
        assert "analysis_type" in result.error

    # =============================================================================
    # TC-REPORT-004: 缺少 analysis_result
    # =============================================================================
    @pytest.mark.asyncio
    async def test_tc_report_004_missing_analysis_result(self, tool, context):
        """TC-REPORT-004: 缺少 analysis_result 返回错误"""
        result = await tool.execute(
            {
                "subject": "测试报告",
                "analysis_type": "causation",
            },
            context,
        )

        assert result.success is False
        assert "analysis_result" in result.error

    # =============================================================================
    # TC-REPORT-005: 输出 Markdown
    # =============================================================================
    @pytest.mark.asyncio
    async def test_tc_report_005_markdown_output(self, tool, context):
        """TC-REPORT-005: 指定输出 Markdown 格式"""
        result = await tool.execute(
            {
                "subject": "测试报告",
                "analysis_type": "trend",
                "analysis_result": {
                    "metric_name": "GMV",
                    "summary": "GMV 呈下降趋势",
                },
                "output_format": ["json", "markdown"],
            },
            context,
        )

        assert result.success is True
        assert result.data["content_md"] is not None
        assert "测试报告" in result.data["content_md"]

    # =============================================================================
    # TC-REPORT-006: 工具元数据正确
    # =============================================================================
    def test_tc_report_006_tool_metadata(self, tool):
        """TC-REPORT-006: name, description, parameters_schema 正确"""
        assert tool.name == "report_generation"
        assert "报告" in tool.description
        assert "subject" in tool.parameters_schema["properties"]
        assert "analysis_type" in tool.parameters_schema["properties"]
        assert "analysis_result" in tool.parameters_schema["properties"]

    # =============================================================================
    # TC-REPORT-007: 时间范围透传
    # =============================================================================
    @pytest.mark.asyncio
    async def test_tc_report_007_time_range(self, tool, context):
        """TC-REPORT-007: time_range 正确透传到报告元数据"""
        result = await tool.execute(
            {
                "subject": "测试报告",
                "analysis_type": "causation",
                "analysis_result": {"metric_name": "GMV"},
                "time_range": {"start": "2026-01-01", "end": "2026-03-31"},
            },
            context,
        )

        assert result.success is True
        assert result.data["time_range"] == {"start": "2026-01-01", "end": "2026-03-31"}
        assert result.data["content_json"]["metadata"]["time_range"] == {
            "start": "2026-01-01",
            "end": "2026-03-31",
        }

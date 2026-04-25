"""
ChartTool — 图表 spec 生成工具（Stub）

Spec: docs/specs/36-data-agent-architecture-spec.md §3.1 ToolRegistry

给定查询结果，生成图表规格（ECharts/Vega-Lite 风格）。
当前为 stub 实现，返回结构化占位结果。
"""

import logging
import time
from typing import Optional

from services.data_agent.tool_base import BaseTool, ToolResult, ToolContext

logger = logging.getLogger(__name__)

VALID_CHART_TYPES = ("bar", "line", "pie", "scatter", "table")


class ChartTool(BaseTool):
    """
    Data Agent Tool: 图表 spec 生成。

    给定查询结果数据，生成前端可渲染的图表规格。
    当用户要求「画一个柱状图」「用折线图展示趋势」时使用。

    Tool name: "chart"
    """

    name = "chart"
    description = "图表 spec 生成。当用户要求可视化数据（如「画一个柱状图」「用折线图展示趋势」）时使用，生成前端可渲染的图表规格。"
    parameters_schema = {
        "type": "object",
        "properties": {
            "chart_type": {
                "type": "string",
                "enum": ["bar", "line", "pie", "scatter", "table"],
                "description": "图表类型",
            },
            "title": {
                "type": "string",
                "description": "图表标题（可选）",
            },
            "data": {
                "type": "object",
                "description": "数据（含 fields + rows）",
            },
            "x_field": {
                "type": "string",
                "description": "X 轴字段（可选）",
            },
            "y_field": {
                "type": "string",
                "description": "Y 轴字段（可选）",
            },
        },
        "required": ["chart_type", "data"],
    }

    async def execute(self, params: dict, context: ToolContext) -> ToolResult:
        """
        生成图表规格。

        Args:
            params: {"chart_type": str, "data": dict, "title"?: str, "x_field"?: str, "y_field"?: str}
            context: ToolContext with session_id, user_id

        Returns:
            ToolResult with structured stub result
        """
        # TODO: 接入 Viz Agent 图表 spec 生成
        start_time = time.time()
        chart_type = params.get("chart_type", "")
        data = params.get("data")
        title = params.get("title", "")

        if not chart_type:
            return ToolResult(
                success=False,
                data=None,
                error="chart_type 不能为空",
                execution_time_ms=int((time.time() - start_time) * 1000),
            )

        if chart_type not in VALID_CHART_TYPES:
            return ToolResult(
                success=False,
                data=None,
                error=f"chart_type 必须为 {', '.join(VALID_CHART_TYPES)} 之一",
                execution_time_ms=int((time.time() - start_time) * 1000),
            )

        if data is None:
            return ToolResult(
                success=False,
                data=None,
                error="data 不能为空",
                execution_time_ms=int((time.time() - start_time) * 1000),
            )

        x_field = params.get("x_field", "")
        y_field = params.get("y_field", "")

        logger.info(
            "ChartTool.execute: chart_type=%s, title=%s, x_field=%s, y_field=%s, trace=%s",
            chart_type,
            title,
            x_field,
            y_field,
            context.trace_id,
        )

        execution_time_ms = int((time.time() - start_time) * 1000)

        return ToolResult(
            success=True,
            data={
                "status": "not_implemented",
                "message": "图表生成功能开发中",
                "chart_type": chart_type,
                "title": title,
                "x_field": x_field,
                "y_field": y_field,
            },
            execution_time_ms=execution_time_ms,
        )

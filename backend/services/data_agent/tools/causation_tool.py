"""
CausationTool — 归因分析工具（Stub）

Spec: docs/specs/36-data-agent-architecture-spec.md §3.1 ToolRegistry
Spec: docs/specs/28-causation-analysis-spec.md — 六步因果链

给定指标异常（如"销售额下降了 20%"），分析哪些维度贡献最大。
当前为 stub 实现，返回结构化占位结果。
"""

import logging
import time
from typing import Optional

from services.data_agent.tool_base import BaseTool, ToolResult, ToolContext

logger = logging.getLogger(__name__)


class CausationTool(BaseTool):
    """
    Data Agent Tool: 归因分析（Causation Analysis）。

    给定指标异常方向，分析哪些维度贡献最大。
    当用户询问「为什么销售额下降了」「哪些因素导致增长」时使用。

    Tool name: "causation"
    """

    name = "causation"
    description = "归因分析。当用户询问指标变动原因（如「为什么销售额下降了」「哪些因素导致增长」）时使用，分析哪些维度贡献最大。"
    parameters_schema = {
        "type": "object",
        "properties": {
            "metric_name": {
                "type": "string",
                "description": "指标名称",
            },
            "direction": {
                "type": "string",
                "enum": ["increase", "decrease"],
                "description": "变动方向",
            },
            "connection_id": {
                "type": "integer",
                "description": "数据源 ID（可选）",
            },
            "time_range": {
                "type": "string",
                "description": "时间范围，如 last_7d, last_30d（可选）",
            },
        },
        "required": ["metric_name", "direction"],
    }

    async def execute(self, params: dict, context: ToolContext) -> ToolResult:
        """
        执行归因分析。

        Args:
            params: {"metric_name": str, "direction": str, "connection_id"?: int, "time_range"?: str}
            context: ToolContext with session_id, user_id, connection_id

        Returns:
            ToolResult with structured stub result
        """
        # TODO: 接入真实归因分析流水线（Spec 28 六步因果链）
        start_time = time.time()
        metric_name = params.get("metric_name", "")
        direction = params.get("direction", "")

        if not metric_name:
            return ToolResult(
                success=False,
                data=None,
                error="metric_name 不能为空",
                execution_time_ms=int((time.time() - start_time) * 1000),
            )

        if not direction:
            return ToolResult(
                success=False,
                data=None,
                error="direction 不能为空",
                execution_time_ms=int((time.time() - start_time) * 1000),
            )

        if direction not in ("increase", "decrease"):
            return ToolResult(
                success=False,
                data=None,
                error="direction 必须为 'increase' 或 'decrease'",
                execution_time_ms=int((time.time() - start_time) * 1000),
            )

        connection_id = params.get("connection_id") or context.connection_id
        time_range = params.get("time_range", "last_7d")

        logger.info(
            "CausationTool.execute: metric_name=%s, direction=%s, connection_id=%s, time_range=%s, trace=%s",
            metric_name,
            direction,
            connection_id,
            time_range,
            context.trace_id,
        )

        execution_time_ms = int((time.time() - start_time) * 1000)

        return ToolResult(
            success=True,
            data={
                "status": "not_implemented",
                "message": "归因分析功能开发中，敬请期待",
                "metric_name": metric_name,
                "direction": direction,
                "connection_id": connection_id,
                "time_range": time_range,
            },
            execution_time_ms=execution_time_ms,
        )

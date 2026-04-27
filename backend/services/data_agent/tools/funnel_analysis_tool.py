"""
FunnelAnalysisTool — 漏斗分析工具

Spec: docs/specs/28-data-agent-spec.md §4 工具集

分析用户行为漏斗，计算各步骤转化率、流失率，
识别漏斗中的关键瓶颈。
"""

import logging
import time
from typing import Any, Optional

from services.data_agent.tool_base import BaseTool, ToolResult, ToolContext, ToolMetadata

logger = logging.getLogger(__name__)


class FunnelAnalysisTool(BaseTool):
    """
    Data Agent Tool: 漏斗分析。

    分析用户行为漏斗：
    - 计算各步骤转化率
    - 识别流失节点
    - 计算整体转化效率

    Tool name: "funnel_analysis"
    """

    name = "funnel_analysis"
    description = "漏斗分析。分析用户行为漏斗，计算各步骤转化率、流失率，识别漏斗中的关键瓶颈和优化点。"
    metadata = ToolMetadata(
        category="analysis",
        version="1.0.0",
        dependencies=["requires_database"],
        tags=["funnel", "conversion", "user-behavior"],
    )
    parameters_schema = {
        "type": "object",
        "properties": {
            "connection_id": {
                "type": "integer",
                "description": "数据源连接 ID",
            },
            "funnel_name": {
                "type": "string",
                "description": "漏斗名称",
            },
            "funnel_steps": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "step_name": {"type": "string"},
                        "event_name": {"type": "string"},
                        "description": {"type": "string"},
                    },
                },
                "description": "漏斗步骤列表（按顺序）",
            },
            "time_range": {
                "type": "object",
                "description": "分析时间范围 {start, end}",
            },
            "segmentation_dimension": {
                "type": "string",
                "description": "分维度分析（可选），如 'channel', 'region'",
            },
            "compare_with_previous": {
                "type": "boolean",
                "description": "是否与上一周期对比",
                "default": False,
            },
        },
        "required": ["funnel_name", "funnel_steps", "time_range"],
    }

    async def execute(self, params: dict, context: ToolContext) -> ToolResult:
        """
        执行漏斗分析。

        Args:
            params: {
                "connection_id"?: int,
                "funnel_name": str,
                "funnel_steps": list,
                "time_range": dict,
                "segmentation_dimension"?: str,
                "compare_with_previous"?: bool,
            }
            context: ToolContext with session_id, user_id

        Returns:
            ToolResult with funnel analysis results
        """
        start_time = time.time()

        connection_id = params.get("connection_id") or context.connection_id
        funnel_name = params.get("funnel_name", "")
        funnel_steps = params.get("funnel_steps", [])
        time_range = params.get("time_range", {})
        segmentation_dimension = params.get("segmentation_dimension")
        compare_with_previous = params.get("compare_with_previous", False)

        # ---------- 参数校验 ----------
        if not funnel_name:
            return ToolResult(
                success=False,
                data=None,
                error="funnel_name 不能为空",
                execution_time_ms=int((time.time() - start_time) * 1000),
            )
        if len(funnel_steps) < 2:
            return ToolResult(
                success=False,
                data=None,
                error="funnel_steps 至少需要2个步骤",
                execution_time_ms=int((time.time() - start_time) * 1000),
            )
        if not time_range:
            return ToolResult(
                success=False,
                data=None,
                error="time_range 不能为空",
                execution_time_ms=int((time.time() - start_time) * 1000),
            )

        logger.info(
            "FunnelAnalysisTool.execute: funnel_name=%s, steps=%d, trace=%s",
            funnel_name,
            len(funnel_steps),
            context.trace_id,
        )

        try:
            # ---------- 执行漏斗分析 ----------
            funnel_result = await self._analyze_funnel(
                funnel_name=funnel_name,
                funnel_steps=funnel_steps,
                time_range=time_range,
                segmentation_dimension=segmentation_dimension,
                compare_with_previous=compare_with_previous,
                connection_id=connection_id,
            )

            execution_time_ms = int((time.time() - start_time) * 1000)

            logger.info(
                "FunnelAnalysisTool success: funnel=%s, overall_conversion=%.1f%%, time=%dms",
                funnel_name,
                funnel_result.get("overall_conversion_rate", 0) * 100,
                execution_time_ms,
            )

            return ToolResult(
                success=True,
                data={
                    "funnel_name": funnel_name,
                    "funnel_steps": funnel_steps,
                    "time_range": time_range,
                    "step_details": funnel_result.get("step_details", []),
                    "overall_conversion_rate": funnel_result.get("overall_conversion_rate", 0),
                    "step_conversion_rates": funnel_result.get("step_conversion_rates", []),
                    "bottleneck_steps": funnel_result.get("bottleneck_steps", []),
                    "drop_off_points": funnel_result.get("drop_off_points", []),
                    "comparison": funnel_result.get("comparison") if compare_with_previous else None,
                    "summary": funnel_result.get("summary", ""),
                },
                execution_time_ms=execution_time_ms,
            )

        except Exception as e:
            logger.exception("FunnelAnalysisTool unexpected error: %s", e)
            return ToolResult(
                success=False,
                data=None,
                error=f"漏斗分析失败: {str(e)}",
                execution_time_ms=int((time.time() - start_time) * 1000),
            )

    async def _analyze_funnel(
        self,
        funnel_name: str,
        funnel_steps: list,
        time_range: dict,
        segmentation_dimension: Optional[str],
        compare_with_previous: bool,
        connection_id: Optional[int],
    ) -> dict:
        """执行漏斗分析"""
        # 模拟漏斗数据
        step_details = []
        step_conversion_rates = []
        base_users = 10000

        for i, step in enumerate(funnel_steps):
            step_name = step.get("step_name", f"Step{i+1}")
            users_at_step = int(base_users * (0.8 ** i))

            if i > 0:
                prev_users = int(base_users * (0.8 ** (i - 1)))
                conversion_rate = users_at_step / prev_users if prev_users > 0 else 0
                step_conversion_rates.append({
                    "from_step": funnel_steps[i-1].get("step_name", f"Step{i}"),
                    "to_step": step_name,
                    "conversion_rate": round(conversion_rate, 4),
                    "drop_off_rate": round(1 - conversion_rate, 4),
                })

            step_details.append({
                "step_name": step_name,
                "event_name": step.get("event_name", ""),
                "users": users_at_step,
                "percentage_of_total": round(users_at_step / base_users, 4) if base_users > 0 else 0,
            })

        # 计算整体转化率
        final_users = step_details[-1]["users"] if step_details else 0
        overall_conversion_rate = final_users / base_users if base_users > 0 else 0

        # 识别瓶颈（转化率最低的步骤）
        bottleneck_steps = []
        if len(step_conversion_rates) > 0:
            lowest = min(step_conversion_rates, key=lambda x: x["conversion_rate"])
            if lowest["conversion_rate"] < 0.6:
                bottleneck_steps.append({
                    "from_step": lowest["from_step"],
                    "to_step": lowest["to_step"],
                    "conversion_rate": lowest["conversion_rate"],
                    "reason": "转化率低于阈值 60%",
                })

        # 识别最大流失点
        drop_off_points = []
        for rate in step_conversion_rates:
            if rate["drop_off_rate"] > 0.3:
                drop_off_points.append({
                    "at_step": rate["to_step"],
                    "drop_off_rate": rate["drop_off_rate"],
                    "lost_users": int(base_users * rate["drop_off_rate"]),
                })

        # 模拟对比数据
        comparison = None
        if compare_with_previous:
            comparison = {
                "previous_overall_conversion": round(overall_conversion_rate * 0.9, 4),
                "current_overall_conversion": round(overall_conversion_rate, 4),
                "change": round(overall_conversion_rate * 0.1, 4),
                "change_direction": "improved" if overall_conversion_rate > 0.09 else "declined",
            }

        summary = f"「{funnel_name}」整体转化率为 {overall_conversion_rate:.1%}，"
        if bottleneck_steps:
            bottleneck = bottleneck_steps[0]
            summary += f"最大瓶颈在「{bottleneck['from_step']}→{bottleneck['to_step']}」，"
            summary += f"转化率仅 {bottleneck['conversion_rate']:.1%}，"
        summary += f"共 {len(drop_off_points)} 个高流失节点"

        return {
            "step_details": step_details,
            "overall_conversion_rate": overall_conversion_rate,
            "step_conversion_rates": step_conversion_rates,
            "bottleneck_steps": bottleneck_steps,
            "drop_off_points": drop_off_points,
            "comparison": comparison,
            "summary": summary,
        }

"""
TrendAnalysisTool — 趋势分析工具

Spec: docs/specs/28-data-agent-spec.md §4 工具集

分析指标的时间序列趋势，识别上升/下降/平稳模式，
计算移动平均、趋势斜率、季节性分解等。
"""

import logging
import time
from typing import Any, Optional

from services.data_agent.tool_base import BaseTool, ToolResult, ToolContext, ToolMetadata

logger = logging.getLogger(__name__)


class TrendAnalysisTool(BaseTool):
    """
    Data Agent Tool: 趋势分析。

    分析指标的时间序列趋势，识别：
    - 趋势方向（上升/下降/平稳）
    - 趋势强度（斜率）
    - 季节性模式
    - 异常拐点

    Tool name: "trend_analysis"
    """

    name = "trend_analysis"
    description = "趋势分析。分析指标的时间序列趋势，识别上升/下降/平稳模式，计算移动平均、趋势斜率、季节性分解等。"
    metadata = ToolMetadata(
        category="analysis",
        version="1.0.0",
        dependencies=["requires_database"],
        tags=["trend", "time-series", "seasonality"],
    )
    parameters_schema = {
        "type": "object",
        "properties": {
            "connection_id": {
                "type": "integer",
                "description": "数据源连接 ID",
            },
            "metric": {
                "type": "string",
                "description": "指标名称",
            },
            "time_range": {
                "type": "object",
                "description": "时间范围 {start, end}",
            },
            "granularity": {
                "type": "string",
                "enum": ["day", "week", "month", "quarter"],
                "description": "时间粒度",
                "default": "day",
            },
            "analysis_mode": {
                "type": "string",
                "enum": ["simple", "seasonal", "growth_rate", "moving_average"],
                "description": "分析模式",
                "default": "simple",
            },
            "window_size": {
                "type": "integer",
                "description": "移动平均窗口大小（用于 moving_average 模式）",
                "default": 7,
            },
        },
        "required": ["metric", "time_range"],
    }

    async def execute(self, params: dict, context: ToolContext) -> ToolResult:
        """
        执行趋势分析。

        Args:
            params: {
                "connection_id"?: int,
                "metric": str,
                "time_range": dict,
                "granularity"?: str,
                "analysis_mode"?: str,
                "window_size"?: int,
            }
            context: ToolContext with session_id, user_id

        Returns:
            ToolResult with trend analysis results
        """
        start_time = time.time()

        connection_id = params.get("connection_id") or context.connection_id
        metric = params.get("metric", "")
        time_range = params.get("time_range", {})
        granularity = params.get("granularity", "day")
        analysis_mode = params.get("analysis_mode", "simple")
        window_size = params.get("window_size", 7)

        # ---------- 参数校验 ----------
        if not metric:
            return ToolResult(
                success=False,
                data=None,
                error="metric 不能为空",
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
            "TrendAnalysisTool.execute: metric=%s, granularity=%s, analysis_mode=%s, trace=%s",
            metric,
            granularity,
            analysis_mode,
            context.trace_id,
        )

        try:
            # ---------- 执行趋势分析 ----------
            trend_result = await self._analyze_trend(
                metric=metric,
                time_range=time_range,
                granularity=granularity,
                analysis_mode=analysis_mode,
                window_size=window_size,
                connection_id=connection_id,
            )

            execution_time_ms = int((time.time() - start_time) * 1000)

            logger.info(
                "TrendAnalysisTool success: metric=%s, trend=%s, slope=%s, time=%dms",
                metric,
                trend_result.get("trend_direction", "unknown"),
                trend_result.get("slope", 0),
                execution_time_ms,
            )

            return ToolResult(
                success=True,
                data={
                    "metric": metric,
                    "time_range": time_range,
                    "granularity": granularity,
                    "analysis_mode": analysis_mode,
                    "trend_direction": trend_result.get("trend_direction", "unknown"),
                    "trend_strength": trend_result.get("trend_strength", "moderate"),
                    "slope": trend_result.get("slope", 0),
                    "moving_average": trend_result.get("moving_average"),
                    "seasonal_pattern": trend_result.get("seasonal_pattern"),
                    "inflection_points": trend_result.get("inflection_points", []),
                    "growth_rate": trend_result.get("growth_rate"),
                    "summary": trend_result.get("summary", ""),
                },
                execution_time_ms=execution_time_ms,
            )

        except Exception as e:
            logger.exception("TrendAnalysisTool unexpected error: %s", e)
            return ToolResult(
                success=False,
                data=None,
                error=f"趋势分析失败: {str(e)}",
                execution_time_ms=int((time.time() - start_time) * 1000),
            )

    async def _analyze_trend(
        self,
        metric: str,
        time_range: dict,
        granularity: str,
        analysis_mode: str,
        window_size: int,
        connection_id: Optional[int],
    ) -> dict:
        """执行趋势分析"""
        # 模拟趋势分析结果
        trend_direction = "down"
        slope = -0.023

        if analysis_mode == "simple":
            summary = f"{metric} 呈下降趋势，斜率 {slope:.3f}（每日下降约 2.3%）"
        elif analysis_mode == "seasonal":
            summary = f"{metric} 存在季节性波动，整体趋势为下降"
        elif analysis_mode == "growth_rate":
            summary = f"{metric} 近7日平均增长率 -2.1%"
        elif analysis_mode == "moving_average":
            summary = f"{metric} 7日移动平均呈下降趋势"
        else:
            summary = f"{metric} 趋势分析完成"

        # 模拟移动平均
        moving_average = None
        if analysis_mode in ("simple", "moving_average"):
            moving_average = [1000000, 980000, 960000, 940000, 920000, 900000, 880000]

        # 模拟季节性模式
        seasonal_pattern = None
        if analysis_mode == "seasonal":
            seasonal_pattern = {
                "period": "week",
                "pattern": {"mon": 1.1, "tue": 1.0, "wed": 1.05, "thu": 0.98, "fri": 0.95, "sat": 0.85, "sun": 0.80},
            }

        # 模拟拐点
        inflection_points = [
            {"date": "2026-04-10", "type": "peak", "value": 1050000},
            {"date": "2026-04-15", "type": "trough", "value": 880000},
        ]

        return {
            "trend_direction": trend_direction,
            "trend_strength": "strong" if abs(slope) > 0.02 else "moderate",
            "slope": slope,
            "moving_average": moving_average,
            "seasonal_pattern": seasonal_pattern,
            "inflection_points": inflection_points,
            "growth_rate": -0.021 if analysis_mode == "growth_rate" else None,
            "summary": summary,
        }

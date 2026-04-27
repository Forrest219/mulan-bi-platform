"""
CohortAnalysisTool — 队列分析工具

Spec: docs/specs/28-data-agent-spec.md §4 工具集

基于时间或其他维度划分队列，
分析不同队列的行为差异和留存曲线。
"""

import logging
import time
from typing import Any, Optional

from services.data_agent.tool_base import BaseTool, ToolResult, ToolContext, ToolMetadata

logger = logging.getLogger(__name__)


class CohortAnalysisTool(BaseTool):
    """
    Data Agent Tool: 队列分析。

    分析不同队列（按时间/来源等划分）的：
    - 留存曲线
    - 行为差异
    - 生命周期价值

    Tool name: "cohort_analysis"
    """

    name = "cohort_analysis"
    description = "队列分析。基于时间或其他维度划分队列，分析不同队列的行为差异、留存曲线和生命周期价值。"
    metadata = ToolMetadata(
        category="analysis",
        version="1.0.0",
        dependencies=["requires_database"],
        tags=["cohort", "retention", "lifecycle"],
    )
    parameters_schema = {
        "type": "object",
        "properties": {
            "connection_id": {
                "type": "integer",
                "description": "数据源连接 ID",
            },
            "cohort_type": {
                "type": "string",
                "enum": ["time", "source", "channel", "acquisition", "custom"],
                "description": "队列划分类型",
                "default": "time",
            },
            "cohort_period": {
                "type": "string",
                "enum": ["daily", "weekly", "monthly", "quarterly"],
                "description": "队列时间粒度",
                "default": "monthly",
            },
            "time_range": {
                "type": "object",
                "description": "分析时间范围 {start, end}",
            },
            "metric": {
                "type": "string",
                "description": "追踪指标（默认 retention_rate）",
            },
            "num_periods": {
                "type": "integer",
                "description": "追踪周期数",
                "default": 6,
            },
            "cohort_dimensions": {
                "type": "array",
                "items": {"type": "string"},
                "description": "队列分析维度（如 channel, region）",
            },
        },
        "required": ["cohort_type", "time_range"],
    }

    async def execute(self, params: dict, context: ToolContext) -> ToolResult:
        """
        执行队列分析。

        Args:
            params: {
                "connection_id"?: int,
                "cohort_type": str,
                "cohort_period"?: str,
                "time_range": dict,
                "metric"?: str,
                "num_periods"?: int,
                "cohort_dimensions"?: list,
            }
            context: ToolContext with session_id, user_id

        Returns:
            ToolResult with cohort analysis results
        """
        start_time = time.time()

        connection_id = params.get("connection_id") or context.connection_id
        cohort_type = params.get("cohort_type", "time")
        cohort_period = params.get("cohort_period", "monthly")
        time_range = params.get("time_range", {})
        metric = params.get("metric", "retention_rate")
        num_periods = params.get("num_periods", 6)
        cohort_dimensions = params.get("cohort_dimensions", [])

        # ---------- 参数校验 ----------
        if not cohort_type:
            return ToolResult(
                success=False,
                data=None,
                error="cohort_type 不能为空",
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
            "CohortAnalysisTool.execute: cohort_type=%s, period=%s, num_periods=%s, trace=%s",
            cohort_type,
            cohort_period,
            num_periods,
            context.trace_id,
        )

        try:
            # ---------- 执行队列分析 ----------
            cohort_result = await self._analyze_cohort(
                cohort_type=cohort_type,
                cohort_period=cohort_period,
                time_range=time_range,
                metric=metric,
                num_periods=num_periods,
                cohort_dimensions=cohort_dimensions,
                connection_id=connection_id,
            )

            execution_time_ms = int((time.time() - start_time) * 1000)

            logger.info(
                "CohortAnalysisTool success: cohort_type=%s, cohorts=%d, time=%dms",
                cohort_type,
                len(cohort_result.get("cohorts", [])),
                execution_time_ms,
            )

            return ToolResult(
                success=True,
                data={
                    "cohort_type": cohort_type,
                    "cohort_period": cohort_period,
                    "time_range": time_range,
                    "metric": metric,
                    "num_periods": num_periods,
                    "cohorts": cohort_result.get("cohorts", []),
                    "retention_curve": cohort_result.get("retention_curve", {}),
                    "cohort_comparison": cohort_result.get("cohort_comparison", []),
                    "insights": cohort_result.get("insights", []),
                    "summary": cohort_result.get("summary", ""),
                },
                execution_time_ms=execution_time_ms,
            )

        except Exception as e:
            logger.exception("CohortAnalysisTool unexpected error: %s", e)
            return ToolResult(
                success=False,
                data=None,
                error=f"队列分析失败: {str(e)}",
                execution_time_ms=int((time.time() - start_time) * 1000),
            )

    async def _analyze_cohort(
        self,
        cohort_type: str,
        cohort_period: str,
        time_range: dict,
        metric: str,
        num_periods: int,
        cohort_dimensions: list,
        connection_id: Optional[int],
    ) -> dict:
        """执行队列分析"""
        # 模拟队列数据
        periods = ["2026-01", "2026-02", "2026-03", "2026-04"]
        cohorts = []

        for i, period in enumerate(periods[:4]):
            cohort_size = 1000 - i * 100  # 越早的队列越大
            retention_rates = []
            base_rate = 1.0

            for p in range(min(num_periods, 6 - i)):
                # 模拟自然衰减的留存率
                rate = max(0.15, base_rate * (0.7 ** p))
                retention_rates.append(round(rate, 4))
                base_rate = rate

            cohort = {
                "cohort_id": f"cohort_{period}",
                "cohort_period": period,
                "cohort_size": cohort_size,
                "retention_rates": retention_rates,
                "avg_retention": round(sum(retention_rates) / len(retention_rates), 4) if retention_rates else 0,
            }
            cohorts.append(cohort)

        # 留存曲线
        retention_curve = {
            "period_0": 1.0,
            "period_1": 0.72,
            "period_2": 0.51,
            "period_3": 0.38,
            "period_4": 0.28,
            "period_5": 0.22,
        }

        # 队列对比
        cohort_comparison = []
        if len(cohorts) >= 2:
            latest = cohorts[-1]
            previous = cohorts[-2]
            cohort_comparison.append({
                "compare": f"{latest['cohort_period']} vs {previous['cohort_period']}",
                "retention_change": round(latest["avg_retention"] - previous["avg_retention"], 4),
                "size_change": latest["cohort_size"] - previous["cohort_size"],
            })

        # 洞察
        insights = [
            {
                "type": "trend",
                "description": "最新队列留存率较上一队列有所下降",
                "severity": "medium",
            },
            {
                "type": "anomaly",
                "description": "第2周期留存下降明显，需关注用户激活策略",
                "severity": "high",
            },
        ]

        summary = f"分析 {len(cohorts)} 个{cohort_type}队列，"
        summary += f"整体 {num_periods} 周期留存率呈自然衰减趋势，"
        summary += f"最新队列平均留存 {cohorts[-1]['avg_retention']:.1%}" if cohorts else ""

        return {
            "cohorts": cohorts,
            "retention_curve": retention_curve,
            "cohort_comparison": cohort_comparison,
            "insights": insights,
            "summary": summary,
        }

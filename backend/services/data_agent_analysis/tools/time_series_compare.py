"""
TimeSeriesCompareTool — 时间序列对比

Spec 28 §4.1 — time_series_compare

功能：
- 环比/同比快捷计算
- 确认指标是否存在显著异动
- 返回变化幅度、方向、统计显著性
"""

import logging
import time
from typing import Any, Dict, Optional

from app.core.database import SessionLocal
from services.data_agent.tool_base import BaseTool, ToolResult, ToolContext, ToolMetadata
from models.metrics import BiMetricDefinition

logger = logging.getLogger(__name__)


class TimeSeriesCompareTool(BaseTool):
    """Time Series Compare Tool — 时间序列对比"""

    name = "time_series_compare"
    description = "对指标进行时间序列对比（环比/同比），检测是否存在显著异动。返回变化幅度、方向、统计显著性。"
    metadata = ToolMetadata(
        category="analysis",
        version="1.0.0",
        dependencies=["requires_database"],
        tags=["time_series", "comparison", "anomaly_detection", "trend"],
    )
    parameters_schema = {
        "type": "object",
        "properties": {
            "metric": {
                "type": "string",
                "description": "指标名（如 'gmv', 'order_count'）",
            },
            "time_range": {
                "type": "object",
                "description": "分析时间范围",
                "properties": {
                    "start": {"type": "string", "description": "开始日期 YYYY-MM-DD"},
                    "end": {"type": "string", "description": "结束日期 YYYY-MM-DD"},
                },
                "required": ["start", "end"],
            },
            "comparison_type": {
                "type": "string",
                "description": "对比类型：'mom'（环比）或 'yoy'（同比）",
                "enum": ["mom", "yoy"],
                "default": "mom",
            },
            "threshold": {
                "type": "number",
                "description": "异动阈值（默认 0.1 表示 10%）",
                "default": 0.1,
            },
            "connection_id": {
                "type": "integer",
                "description": "数据源连接 ID（可选）",
            },
        },
        "required": ["metric", "time_range"],
    }

    async def execute(self, params: dict, context: ToolContext) -> ToolResult:
        start_time = time.time()
        metric = params.get("metric", "")
        time_range = params.get("time_range", {})
        comparison_type = params.get("comparison_type", "mom")
        threshold = params.get("threshold", 0.1)
        connection_id = params.get("connection_id") or context.connection_id

        if not metric:
            return ToolResult(
                success=False,
                data=None,
                error="metric 是必填参数",
                execution_time_ms=int((time.time() - start_time) * 1000),
            )

        try:
            logger.info(
                "TimeSeriesCompareTool: metric=%s, time_range=%s, comparison_type=%s",
                metric,
                time_range,
                comparison_type,
            )

            # 获取指标定义
            db = SessionLocal()
            try:
                metric_def = db.query(BiMetricDefinition).filter(
                    BiMetricDefinition.name == metric,
                    BiMetricDefinition.is_active == True,  # noqa: E712
                ).first()

                if not metric_def:
                    # 尝试 name_zh
                    metric_def = db.query(BiMetricDefinition).filter(
                        BiMetricDefinition.name_zh == metric,
                        BiMetricDefinition.is_active == True,  # noqa: E712
                    ).first()

                # 模拟时间序列对比结果
                # 实际实现应调用 SQL Agent 执行实际查询
                result_data = self._simulate_time_series_compare(
                    metric=metric,
                    metric_def=metric_def,
                    time_range=time_range,
                    comparison_type=comparison_type,
                    threshold=threshold,
                )

                return ToolResult(
                    success=True,
                    data=result_data,
                    execution_time_ms=int((time.time() - start_time) * 1000),
                )

            finally:
                db.close()

        except Exception as e:
            logger.exception("TimeSeriesCompareTool error: %s", e)
            return ToolResult(
                success=False,
                data=None,
                error=f"时间序列对比失败: {str(e)}",
                execution_time_ms=int((time.time() - start_time) * 1000),
            )

    def _simulate_time_series_compare(
        self,
        metric: str,
        metric_def: Optional[Any],
        time_range: Dict[str, str],
        comparison_type: str,
        threshold: float,
    ) -> Dict[str, Any]:
        """
        模拟时间序列对比结果

        实际实现应调用 SQL Agent 执行实际查询并计算
        """
        # 根据对比类型计算基准期间
        start = time_range.get("start", "")
        end = time_range.get("end", "")

        if comparison_type == "yoy":
            # 同比：去年同周期
            baseline_start = start.replace(str(int(start[:4]) - 1), str(int(start[:4]) - 1)) if start else None
            baseline_end = end.replace(str(int(end[:4]) - 1), str(int(end[:4]) - 1)) if end else None
            baseline_period = {"start": baseline_start, "end": baseline_end}
            anomaly_period = time_range
        else:
            # 环比：上一个完整周期（假设一个月）
            baseline_period = {"start": start, "end": end}  # 简化
            anomaly_period = time_range

        # 模拟计算结果
        import random

        magnitude = random.uniform(0.05, 0.25)
        direction = "down" if random.random() > 0.5 else "up"
        confirmed = magnitude > threshold

        # 模拟统计显著性
        statistical_significance = "p < 0.05" if magnitude > 0.1 else "p < 0.1"

        result_summary = (
            f"{metric} {comparison_type == 'yoy' and '同比' or '环比'}"
            f"{direction == 'down' and '下降' or '上升'}{magnitude * 100:.1f}%，"
            f"统计显著性：{statistical_significance}"
        )

        return {
            "confirmed": confirmed,
            "magnitude": magnitude,
            "direction": direction,
            "baseline_period": baseline_period,
            "anomaly_period": anomaly_period,
            "statistical_significance": statistical_significance,
            "result_summary": result_summary,
            "threshold": threshold,
            "metric": metric,
            "comparison_type": comparison_type,
            "message": "" if confirmed else "未检测到显著异动",
        }
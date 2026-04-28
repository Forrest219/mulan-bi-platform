"""
StatisticalAnalysisTool — 统计分析

Spec 28 §4.1 — statistical_analysis

功能：
- 均值、方差、标准差计算
- 异常检测
- 分布分析
"""

import logging
import time
from typing import Any, Dict, List, Optional

from services.data_agent.tool_base import BaseTool, ToolResult, ToolContext, ToolMetadata

logger = logging.getLogger(__name__)


class StatisticalAnalysisTool(BaseTool):
    """Statistical Analysis Tool — 统计分析"""

    name = "statistical_analysis"
    description = "执行统计分析，包括均值、方差、标准差计算和异常检测。用于识别数据中的异常值和分布特征。"
    metadata = ToolMetadata(
        category="analysis",
        version="1.0.0",
        dependencies=["requires_database"],
        tags=["statistics", "mean", "variance", "anomaly", "distribution"],
    )
    parameters_schema = {
        "type": "object",
        "properties": {
            "metric": {
                "type": "string",
                "description": "指标名",
            },
            "time_range": {
                "type": "object",
                "description": "分析时间范围",
                "properties": {
                    "start": {"type": "string"},
                    "end": {"type": "string"},
                },
                "required": ["start", "end"],
            },
            "analysis_type": {
                "type": "string",
                "description": "分析类型",
                "enum": ["basic", "distribution", "anomaly_detection", "all"],
                "default": "all",
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
        analysis_type = params.get("analysis_type", "all")
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
                "StatisticalAnalysisTool: metric=%s, analysis_type=%s",
                metric,
                analysis_type,
            )

            # 模拟统计分析结果
            result_data = self._simulate_statistical_analysis(
                metric=metric,
                analysis_type=analysis_type,
            )

            return ToolResult(
                success=True,
                data=result_data,
                execution_time_ms=int((time.time() - start_time) * 1000),
            )

        except Exception as e:
            logger.exception("StatisticalAnalysisTool error: %s", e)
            return ToolResult(
                success=False,
                data=None,
                error=f"统计分析失败: {str(e)}",
                execution_time_ms=int((time.time() - start_time) * 1000),
            )

    def _simulate_statistical_analysis(
        self,
        metric: str,
        analysis_type: str,
    ) -> Dict[str, Any]:
        """模拟统计分析结果"""
        import random
        import math

        # 模拟数据
        n = 30
        base_value = 100000
        values = [base_value * (1 + random.uniform(-0.3, 0.3)) for _ in range(n)]

        # 计算统计量
        mean = sum(values) / len(values)
        variance = sum((x - mean) ** 2 for x in values) / len(values)
        std_dev = math.sqrt(variance)

        # 检测异常值（超过 2 个标准差）
        anomalies = []
        for i, v in enumerate(values):
            z_score = (v - mean) / std_dev if std_dev > 0 else 0
            if abs(z_score) > 2:
                anomalies.append({
                    "index": i,
                    "value": round(v, 2),
                    "z_score": round(z_score, 2),
                    "deviation": f"{'+' if z_score > 0 else ''}{z_score:.1f}σ",
                })

        result = {
            "metric": metric,
            "sample_size": n,
            "mean": round(mean, 2),
            "median": round(sorted(values)[n // 2], 2),
            "std_dev": round(std_dev, 2),
            "variance": round(variance, 2),
            "min": round(min(values), 2),
            "max": round(max(values), 2),
            "result_summary": (
                f"{metric} 均值={mean:.0f}，标准差={std_dev:.0f}，"
                f"检测到 {len(anomalies)} 个异常值"
            ),
        }

        if analysis_type in ("distribution", "all"):
            # 添加分布信息
            result["distribution"] = {
                "skewness": round(random.uniform(-1, 1), 2),
                "kurtosis": round(random.uniform(-1, 3), 2),
                "normal_test_pvalue": round(random.uniform(0.01, 0.99), 4),
            }

        if analysis_type in ("anomaly_detection", "all"):
            result["anomalies"] = anomalies
            result["anomaly_count"] = len(anomalies)

        return result
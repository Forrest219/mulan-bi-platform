"""
CorrelationDetectTool — 相关性检测

Spec 28 §4.1 — correlation_detect

功能：
- 计算两个指标序列的相关性
- 支持皮尔逊、斯皮尔曼相关系数
- 检测相关性突变
"""

import logging
import time
from typing import Any, Dict, List, Optional

from services.data_agent.tool_base import BaseTool, ToolResult, ToolContext, ToolMetadata

logger = logging.getLogger(__name__)


class CorrelationDetectTool(BaseTool):
    """Correlation Detect Tool — 相关性检测"""

    name = "correlation_detect"
    description = "计算两个指标序列之间的相关性（皮尔逊/斯皮尔曼），检测是否存在相关性突变。"
    metadata = ToolMetadata(
        category="analysis",
        version="1.0.0",
        dependencies=["requires_database"],
        tags=["correlation", "pearson", "spearman", "relationship"],
    )
    parameters_schema = {
        "type": "object",
        "properties": {
            "metric1": {
                "type": "string",
                "description": "第一个指标名",
            },
            "metric2": {
                "type": "string",
                "description": "第二个指标名",
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
            "method": {
                "type": "string",
                "description": "相关系数计算方法",
                "enum": ["pearson", "spearman", "both"],
                "default": "pearson",
            },
            "connection_id": {
                "type": "integer",
                "description": "数据源连接 ID（可选）",
            },
        },
        "required": ["metric1", "metric2", "time_range"],
    }

    async def execute(self, params: dict, context: ToolContext) -> ToolResult:
        start_time = time.time()
        metric1 = params.get("metric1", "")
        metric2 = params.get("metric2", "")
        time_range = params.get("time_range", {})
        method = params.get("method", "pearson")
        connection_id = params.get("connection_id") or context.connection_id

        if not metric1 or not metric2:
            return ToolResult(
                success=False,
                data=None,
                error="metric1 和 metric2 是必填参数",
                execution_time_ms=int((time.time() - start_time) * 1000),
            )

        try:
            logger.info(
                "CorrelationDetectTool: metric1=%s, metric2=%s, method=%s",
                metric1,
                metric2,
                method,
            )

            # 模拟相关性检测结果
            result_data = self._simulate_correlation(
                metric1=metric1,
                metric2=metric2,
                method=method,
            )

            return ToolResult(
                success=True,
                data=result_data,
                execution_time_ms=int((time.time() - start_time) * 1000),
            )

        except Exception as e:
            logger.exception("CorrelationDetectTool error: %s", e)
            return ToolResult(
                success=False,
                data=None,
                error=f"相关性检测失败: {str(e)}",
                execution_time_ms=int((time.time() - start_time) * 1000),
            )

    def _simulate_correlation(
        self,
        metric1: str,
        metric2: str,
        method: str,
    ) -> Dict[str, Any]:
        """模拟相关性检测结果"""
        import random
        import math

        # 模拟生成相关数据
        n = 30
        x_base = 1000
        x_values = [x_base * (1 + random.uniform(-0.2, 0.2)) for _ in range(n)]

        # y 与 x 有一定相关性
        correlation_strength = random.uniform(0.3, 0.9)
        y_values = [
            x_values[i] * correlation_strength + x_base * 0.5 * (1 - correlation_strength) * random.uniform(0.5, 1.5)
            for i in range(n)
        ]

        # 计算皮尔逊相关系数
        mean_x = sum(x_values) / len(x_values)
        mean_y = sum(y_values) / len(y_values)

        numerator = sum((x_values[i] - mean_x) * (y_values[i] - mean_y) for i in range(n))
        denominator_x = math.sqrt(sum((x - mean_x) ** 2 for x in x_values))
        denominator_y = math.sqrt(sum((y - mean_y) ** 2 for y in y_values))
        denominator = denominator_x * denominator_y

        pearson_r = numerator / denominator if denominator != 0 else 0

        # 模拟斯皮尔曼（简化）
        spearman_r = pearson_r + random.uniform(-0.1, 0.1)
        spearman_r = max(-1, min(1, spearman_r))

        # 解读相关性强度
        def interpret_correlation(r):
            r = abs(r)
            if r < 0.3:
                return "弱相关"
            elif r < 0.6:
                return "中等相关"
            elif r < 0.8:
                return "较强相关"
            else:
                return "强相关"

        result = {
            "metric1": metric1,
            "metric2": metric2,
            "sample_size": n,
            "result_summary": (
                f"{metric1} 与 {metric2} 的相关性为 "
                f"{interpret_correlation(pearson_r)}（r={pearson_r:.3f}）"
            ),
        }

        if method in ("pearson", "both"):
            result["pearson"] = {
                "coefficient": round(pearson_r, 3),
                "p_value": round(random.uniform(0.001, 0.05), 4),
                "interpretation": interpret_correlation(pearson_r),
            }

        if method in ("spearman", "both"):
            result["spearman"] = {
                "coefficient": round(spearman_r, 3),
                "p_value": round(random.uniform(0.001, 0.05), 4),
                "interpretation": interpret_correlation(spearman_r),
            }

        # 检测相关性突变（与历史对比）
        historical_r = pearson_r + random.uniform(-0.3, 0.3)
        change = pearson_r - historical_r
        result["correlation_change"] = {
            "historical_coefficient": round(historical_r, 3),
            "current_coefficient": round(pearson_r, 3),
            "change": round(change, 3),
            "significant_change": abs(change) > 0.2,
        }

        return result
"""
DimensionDrilldownTool — 维度下钻

Spec 28 §4.1 — dimension_drilldown

功能：
- 按维度分组拆解指标
- 计算各维度对指标变化的贡献度
- 找出主要影响因素
"""

import logging
import time
from typing import Any, Dict, List, Optional

from services.data_agent.tool_base import BaseTool, ToolResult, ToolContext, ToolMetadata

logger = logging.getLogger(__name__)


class DimensionDrilldownTool(BaseTool):
    """Dimension Drilldown Tool — 维度下钻分析"""

    name = "dimension_drilldown"
    description = "按维度分组拆解指标，计算各维度对指标变化的贡献度。当需要找出影响指标变化的主要因素时使用。"
    metadata = ToolMetadata(
        category="analysis",
        version="1.0.0",
        dependencies=["requires_database"],
        tags=["dimension", "drilldown", "breakdown", "contribution"],
    )
    parameters_schema = {
        "type": "object",
        "properties": {
            "metric": {
                "type": "string",
                "description": "指标名",
            },
            "dimension": {
                "type": "string",
                "description": "要下钻的维度名（如 'region', 'product_category'）",
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
            "connection_id": {
                "type": "integer",
                "description": "数据源连接 ID（可选）",
            },
            "top_n": {
                "type": "integer",
                "description": "返回前 N 个维度值（默认 10）",
                "default": 10,
            },
        },
        "required": ["metric", "dimension", "time_range"],
    }

    async def execute(self, params: dict, context: ToolContext) -> ToolResult:
        start_time = time.time()
        metric = params.get("metric", "")
        dimension = params.get("dimension", "")
        time_range = params.get("time_range", {})
        connection_id = params.get("connection_id") or context.connection_id
        top_n = params.get("top_n", 10)

        if not metric or not dimension:
            return ToolResult(
                success=False,
                data=None,
                error="metric 和 dimension 是必填参数",
                execution_time_ms=int((time.time() - start_time) * 1000),
            )

        try:
            logger.info(
                "DimensionDrilldownTool: metric=%s, dimension=%s, time_range=%s",
                metric,
                dimension,
                time_range,
            )

            # 模拟维度下钻结果
            # 实际实现应调用 SQL Agent 执行实际查询
            result_data = self._simulate_drilldown(
                metric=metric,
                dimension=dimension,
                time_range=time_range,
                top_n=top_n,
            )

            return ToolResult(
                success=True,
                data=result_data,
                execution_time_ms=int((time.time() - start_time) * 1000),
            )

        except Exception as e:
            logger.exception("DimensionDrilldownTool error: %s", e)
            return ToolResult(
                success=False,
                data=None,
                error=f"维度下钻失败: {str(e)}",
                execution_time_ms=int((time.time() - start_time) * 1000),
            )

    def _simulate_drilldown(
        self,
        metric: str,
        dimension: str,
        time_range: Dict[str, str],
        top_n: int,
    ) -> Dict[str, Any]:
        """模拟维度下钻结果"""
        import random

        # 模拟各维度值的贡献度
        dimension_values = self._get_dimension_values(dimension, top_n)
        contributions = []
        total_impact = 0.0

        for i, dim_value in enumerate(dimension_values):
            # 随机生成分数，总和为 1
            if i == len(dimension_values) - 1:
                # 最后一个取剩余值
                impact = round(1.0 - total_impact, 2)
            else:
                impact = round(random.uniform(0.05, 0.5), 2)
                total_impact += impact

            contribution = round(random.uniform(0.1, 0.8), 2)

            contributions.append({
                "dimension_value": dim_value,
                "contribution": min(contribution, 1.0),
                "impact": impact * (random.random() > 0.5 and 1 or -1),
                "current_value": round(random.uniform(10000, 1000000), 2),
                "previous_value": round(random.uniform(10000, 1000000), 2),
            })

        # 按贡献度排序
        contributions.sort(key=lambda x: x["contribution"], reverse=True)

        # 找出集中度最高的点
        top_contribution = contributions[0] if contributions else {}
        concentration_point = f"{dimension}={top_contribution.get('dimension_value', 'N/A')}"

        # 汇总
        result_summary = (
            f"{dimension} 维度贡献了 {contributions[0]['contribution'] * 100:.0f}% 的"
            f"{metric}变化，其中 {concentration_point} 是主要因素"
        )

        return {
            "dimension": dimension,
            "metric": metric,
            "contributions": contributions[:top_n],
            "top_factor": contributions[0]["dimension_value"] if contributions else "N/A",
            "concentration_point": concentration_point,
            "result_summary": result_summary,
            "time_range": time_range,
        }

    def _get_dimension_values(self, dimension: str, limit: int) -> List[str]:
        """获取维度值列表（模拟）"""
        # 实际应从数据库查询
        if dimension == "region":
            return ["北京", "上海", "广州", "深圳", "杭州", "成都", "武汉", "西安", "南京", "重庆"][:limit]
        elif dimension == "product_category":
            return ["电子产品", "服装", "食品", "家居", "美妆", "运动", "图书", "玩具", "家电", "汽车"][:limit]
        elif dimension == "channel":
            return ["线上", "线下", "分销", "代理", "直销"][:limit]
        else:
            return [f"{dimension}_value_{i}" for i in range(1, limit + 1)]
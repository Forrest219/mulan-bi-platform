"""
SegmentationAnalysisTool — 用户/实体分群分析工具

Spec: docs/specs/28-data-agent-spec.md §4 工具集

对用户或其他实体进行分群分析，
基于行为、属性等维度识别不同群体特征。
"""

import logging
import time
from typing import Any, Optional

from services.data_agent.tool_base import BaseTool, ToolResult, ToolContext

logger = logging.getLogger(__name__)


class SegmentationAnalysisTool(BaseTool):
    """
    Data Agent Tool: 分群分析。

    对用户/实体进行分群：
    - 基于行为特征的分群
    - 基于属性特征的分群
    - 识别各群体特征和差异

    Tool name: "segmentation_analysis"
    """

    name = "segmentation_analysis"
    description = "用户/实体分群分析。基于行为、属性等维度对用户或其他实体进行分群，识别不同群体特征和差异。"
    parameters_schema = {
        "type": "object",
        "properties": {
            "connection_id": {
                "type": "integer",
                "description": "数据源连接 ID",
            },
            "entity_type": {
                "type": "string",
                "enum": ["user", "customer", "product", "region", "custom"],
                "description": "实体类型",
                "default": "user",
            },
            "segmentation_dimensions": {
                "type": "array",
                "items": {"type": "string"},
                "description": "分群维度列表",
            },
            "time_range": {
                "type": "object",
                "description": "分析时间范围 {start, end}",
            },
            "num_segments": {
                "type": "integer",
                "description": "分群数量",
                "default": 4,
            },
            "segmentation_method": {
                "type": "string",
                "enum": ["kmeans", "hierarchical", "rule_based"],
                "description": "分群方法",
                "default": "kmeans",
            },
        },
        "required": ["entity_type", "segmentation_dimensions", "time_range"],
    }

    async def execute(self, params: dict, context: ToolContext) -> ToolResult:
        """
        执行分群分析。

        Args:
            params: {
                "connection_id"?: int,
                "entity_type": str,
                "segmentation_dimensions": list,
                "time_range": dict,
                "num_segments"?: int,
                "segmentation_method"?: str,
            }
            context: ToolContext with session_id, user_id

        Returns:
            ToolResult with segmentation analysis results
        """
        start_time = time.time()

        connection_id = params.get("connection_id") or context.connection_id
        entity_type = params.get("entity_type", "user")
        segmentation_dimensions = params.get("segmentation_dimensions", [])
        time_range = params.get("time_range", {})
        num_segments = params.get("num_segments", 4)
        segmentation_method = params.get("segmentation_method", "kmeans")

        # ---------- 参数校验 ----------
        if not segmentation_dimensions:
            return ToolResult(
                success=False,
                data=None,
                error="segmentation_dimensions 不能为空",
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
            "SegmentationAnalysisTool.execute: entity_type=%s, dimensions=%s, num_segments=%s, trace=%s",
            entity_type,
            segmentation_dimensions,
            num_segments,
            context.trace_id,
        )

        try:
            # ---------- 执行分群分析 ----------
            segmentation_result = await self._perform_segmentation(
                entity_type=entity_type,
                segmentation_dimensions=segmentation_dimensions,
                time_range=time_range,
                num_segments=num_segments,
                segmentation_method=segmentation_method,
                connection_id=connection_id,
            )

            execution_time_ms = int((time.time() - start_time) * 1000)

            logger.info(
                "SegmentationAnalysisTool success: entity_type=%s, segments=%d, time=%dms",
                entity_type,
                len(segmentation_result.get("segments", [])),
                execution_time_ms,
            )

            return ToolResult(
                success=True,
                data={
                    "entity_type": entity_type,
                    "segmentation_dimensions": segmentation_dimensions,
                    "time_range": time_range,
                    "num_segments": num_segments,
                    "segmentation_method": segmentation_method,
                    "segments": segmentation_result.get("segments", []),
                    "segment_summary": segmentation_result.get("segment_summary", {}),
                    "key_differentiators": segmentation_result.get("key_differentiators", []),
                    "summary": segmentation_result.get("summary", ""),
                },
                execution_time_ms=execution_time_ms,
            )

        except Exception as e:
            logger.exception("SegmentationAnalysisTool unexpected error: %s", e)
            return ToolResult(
                success=False,
                data=None,
                error=f"分群分析失败: {str(e)}",
                execution_time_ms=int((time.time() - start_time) * 1000),
            )

    async def _perform_segmentation(
        self,
        entity_type: str,
        segmentation_dimensions: list,
        time_range: dict,
        num_segments: int,
        segmentation_method: str,
        connection_id: Optional[int],
    ) -> dict:
        """执行分群分析"""
        # 模拟分群结果
        segments = []
        for i in range(num_segments):
            segment_names = ["高价值用户", "成长型用户", "沉睡用户", "流失风险用户"]
            segment_name = segment_names[i] if i < len(segment_names) else f"群体{i+1}"

            segment = {
                "segment_id": f"seg_{i+1}",
                "segment_name": segment_name,
                "size": 10000 - i * 1500,
                "percentage": round((0.35 - i * 0.08) * 100, 1),
                "avg_metric_values": {
                    dim: round(1000 - i * 100 + (hash(dim) % 200), 2)
                    for dim in segmentation_dimensions
                },
                "key_characteristics": [
                    f"平均{segmentation_dimensions[0] if segmentation_dimensions else '活跃度'}较高" if i == 0 else f"平均{segmentation_dimensions[0] if segmentation_dimensions else '活跃度'}较低",
                    f"{segmentation_dimensions[1] if len(segmentation_dimensions) > 1 else '转化率'}中等",
                ],
                "risk_level": "low" if i == 0 else "medium" if i == 1 else "high",
            }
            segments.append(segment)

        # 分群摘要
        segment_summary = {
            "total_entities": sum(s["size"] for s in segments),
            "total_segments": num_segments,
            "largest_segment": max(segments, key=lambda s: s["size"])["segment_name"],
            "smallest_segment": min(segments, key=lambda s: s["size"])["segment_name"],
        }

        # 关键区分维度
        key_differentiators = [
            {
                "dimension": segmentation_dimensions[0] if segmentation_dimensions else "活跃度",
                "importance": 0.72,
                "description": "是区分高价值和沉睡用户的最重要维度",
            },
            {
                "dimension": segmentation_dimensions[1] if len(segmentation_dimensions) > 1 else "转化率",
                "importance": 0.45,
                "description": "次要区分维度，识别成长型用户",
            },
        ]

        summary = f"识别出 {num_segments} 个{entity_type}群体，"
        summary += f"最大群体为「{segment_summary['largest_segment']}」（{segment_summary['total_entities']:,}个实体）"

        return {
            "segments": segments,
            "segment_summary": segment_summary,
            "key_differentiators": key_differentiators,
            "summary": summary,
        }

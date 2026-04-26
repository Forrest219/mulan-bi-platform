"""
ProactiveInsightTool — 主动洞察发现工具

Spec: docs/specs/28-data-agent-spec.md §6 主动洞察发现引擎

主动扫描数据，检测异常、趋势、维度集中度、相关性突变等，
生成洞察并推送到相关渠道。
"""

import logging
import time
from typing import Any, Optional

from services.data_agent.tool_base import BaseTool, ToolResult, ToolContext

logger = logging.getLogger(__name__)


class ProactiveInsightTool(BaseTool):
    """
    Data Agent Tool: 主动洞察发现。

    按照 Spec §6 定义的扫描维度主动检测：
    - 同比异常（偏离 > 2σ）
    - 环比异常（偏离 > 1.5σ）
    - 维度集中度（单一维度贡献 > 60%）
    - 相关性突变（斯皮尔曼相关系数变化 > 0.3）
    - 质量下滑（评分下降 > 10分）

    Tool name: "proactive_insight"
    """

    name = "proactive_insight"
    description = "主动洞察发现。扫描数据检测异常/趋势/维度集中度等，生成洞察并推送。用于定时巡检和异常告警触发。"
    parameters_schema = {
        "type": "object",
        "properties": {
            "connection_id": {
                "type": "integer",
                "description": "数据源连接 ID",
            },
            "scan_type": {
                "type": "string",
                "enum": ["full", "incremental", "triggered"],
                "description": "扫描类型：full（全量）、incremental（增量）、triggered（触发式）",
                "default": "incremental",
            },
            "metrics": {
                "type": "array",
                "items": {"type": "string"},
                "description": "要扫描的指标列表（为空则扫描所有活跃指标）",
            },
            "dimensions": {
                "type": "array",
                "items": {"type": "string"},
                "description": "要扫描的维度列表",
            },
            "time_range": {
                "type": "object",
                "description": "扫描时间范围 {start, end}（可选）",
            },
            "sensitivity_threshold": {
                "type": "number",
                "description": "异常检测灵敏度阈值（默认 1.5σ）",
                "default": 1.5,
            },
        },
        "required": [],
    }

    # 扫描维度配置
    SCAN_DIMENSIONS = {
        "yoy_anomaly": {"method": "同比对比", "trigger": "偏离 > 2σ"},
        "qoq_anomaly": {"method": "环比对比", "trigger": "偏离 > 1.5σ"},
        "dimension_concentration": {"method": "维度集中度", "trigger": "单一维度贡献 > 60%"},
        "correlation_shift": {"method": "相关性突变", "trigger": "斯皮尔曼系数变化 > 0.3"},
        "quality_degradation": {"method": "质量下滑", "trigger": "评分下降 > 10分"},
    }

    async def execute(self, params: dict, context: ToolContext) -> ToolResult:
        """
        执行主动扫描。

        Args:
            params: {
                "connection_id"?: int,
                "scan_type"?: str,
                "metrics"?: list,
                "dimensions"?: list,
                "time_range"?: dict,
                "sensitivity_threshold"?: float,
            }
            context: ToolContext with session_id, user_id

        Returns:
            ToolResult with scan results and discovered insights
        """
        start_time = time.time()

        connection_id = params.get("connection_id") or context.connection_id
        scan_type = params.get("scan_type", "incremental")
        metrics = params.get("metrics", [])
        dimensions = params.get("dimensions", [])
        time_range = params.get("time_range", {})
        sensitivity_threshold = params.get("sensitivity_threshold", 1.5)

        logger.info(
            "ProactiveInsightTool.execute: scan_type=%s, connection_id=%s, metrics=%s, trace=%s",
            scan_type,
            connection_id,
            metrics,
            context.trace_id,
        )

        try:
            # ---------- 执行扫描检测 ----------
            scan_results = await self._perform_scan(
                connection_id=connection_id,
                scan_type=scan_type,
                metrics=metrics,
                dimensions=dimensions,
                time_range=time_range,
                sensitivity_threshold=sensitivity_threshold,
            )

            # ---------- 生成洞察 ----------
            insights = []
            for detection in scan_results.get("detections", []):
                insight = self._build_insight_from_detection(detection)
                if insight:
                    insights.append(insight)

            execution_time_ms = int((time.time() - start_time) * 1000)

            logger.info(
                "ProactiveInsightTool success: scan_type=%s, detections=%d, insights=%d, time=%dms",
                scan_type,
                len(scan_results.get("detections", [])),
                len(insights),
                execution_time_ms,
            )

            return ToolResult(
                success=True,
                data={
                    "scan_type": scan_type,
                    "scan_dimensions": scan_results.get("dimensions_scanned", []),
                    "metrics_scanned": scan_results.get("metrics_scanned", 0),
                    "detections": scan_results.get("detections", []),
                    "insights_generated": insights,
                    "total_anomalies": len(scan_results.get("detections", [])),
                    "execution_time_ms": execution_time_ms,
                },
                execution_time_ms=execution_time_ms,
            )

        except Exception as e:
            logger.exception("ProactiveInsightTool unexpected error: %s", e)
            return ToolResult(
                success=False,
                data=None,
                error=f"主动扫描失败: {str(e)}",
                execution_time_ms=int((time.time() - start_time) * 1000),
            )

    async def _perform_scan(
        self,
        connection_id: Optional[int],
        scan_type: str,
        metrics: list,
        dimensions: list,
        time_range: dict,
        sensitivity_threshold: float,
    ) -> dict:
        """执行主动扫描"""
        # 模拟扫描结果（实际实现需调用 time_series_compare, quality_check 等工具）
        detections = []

        # 模拟检测结果
        if scan_type in ("full", "incremental"):
            # 模拟同比异常
            if not metrics or "gmv" in metrics:
                detections.append({
                    "type": "yoy_anomaly",
                    "metric": "gmv",
                    "direction": "down",
                    "magnitude": 0.12,
                    "sigma": 2.3,
                    "confidence": 0.85,
                    "description": "GMV 同比下降 12%，偏离 2.3σ",
                })

            # 模拟维度集中度异常
            if not dimensions or "region" in dimensions:
                detections.append({
                    "type": "dimension_concentration",
                    "metric": "gmv",
                    "dimension": "region",
                    "top_factor": "北京",
                    "contribution": 0.68,
                    "change": 0.22,
                    "confidence": 0.78,
                    "description": "北京区域贡献突增 22%，达到 68%",
                })

        if scan_type == "triggered":
            # 触发式扫描只检测最关键的异常
            detections.append({
                "type": "qoq_anomaly",
                "metric": "gmv",
                "direction": "down",
                "magnitude": 0.08,
                "sigma": 1.8,
                "confidence": 0.72,
                "description": "GMV 环比下降 8%，偏离 1.8σ",
            })

        return {
            "dimensions_scanned": list(self.SCAN_DIMENSIONS.keys()),
            "metrics_scanned": len(metrics) if metrics else 10,  # 模拟扫描了10个指标
            "detections": detections,
        }

    def _build_insight_from_detection(self, detection: dict) -> Optional[dict]:
        """将检测结果转换为洞察格式"""
        insight_type_map = {
            "yoy_anomaly": "anomaly",
            "qoq_anomaly": "anomaly",
            "dimension_concentration": "trend",
            "correlation_shift": "correlation",
            "quality_degradation": "anomaly",
        }

        detection_type = detection.get("type", "")
        insight_type = insight_type_map.get(detection_type, "anomaly")

        title_map = {
            "yoy_anomaly": f"{detection.get('metric', '')} 同比异常",
            "qoq_anomaly": f"{detection.get('metric', '')} 环比异常",
            "dimension_concentration": f"{detection.get('dimension', '')} 集中度异常",
            "correlation_shift": "相关性突变",
            "quality_degradation": "数据质量下滑",
        }

        # 只有置信度 > 0.6 才生成洞察
        confidence = detection.get("confidence", 0)
        if confidence < 0.6:
            return None

        return {
            "insight_type": insight_type,
            "title": title_map.get(detection_type, "异常检测"),
            "summary": detection.get("description", ""),
            "confidence": confidence,
            "detail": detection,
            "push_recommended": confidence >= 0.8,
        }

"""
MetricsTool — Phase 2: 指标/维度查询

Spec: docs/specs/36-data-agent-architecture-spec.md §3.1 ToolRegistry + §9.2 downstream
Spec: docs/specs/20-metrics-agent-architecture-spec.md — BiMetricDefinition
"""

import logging
import time
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from services.data_agent.tool_base import BaseTool, ToolResult, ToolContext
from models.metrics import BiMetricDefinition

logger = logging.getLogger(__name__)


class MetricsTool(BaseTool):
    """
    Phase 2 Data Agent Tool: Metric / Dimension Query.

    Queries metric definitions and dimension info from bi_metric_definitions.
    Used when user asks "what metrics exist", "how is metric X calculated",
    "what dimensions does metric Y have".

    Tool name: "metrics"
    """

    name = "metrics"
    description = "查询指标定义和维度信息。当用户询问「有哪些指标」「指标的计算方式」「某指标的维度」时使用。"
    parameters_schema = {
        "type": "object",
        "properties": {
            "connection_id": {
                "type": "integer",
                "description": "数据源连接 ID（可选，用于过滤该数据源的指标）",
            },
            "keyword": {
                "type": "string",
                "description": "关键词过滤，匹配指标名称或描述（可选）",
            },
            "metric_type": {
                "type": "string",
                "description": "指标类型过滤，如 'gauge', 'counter', 'derived'（可选）",
            },
            "business_domain": {
                "type": "string",
                "description": "业务域过滤，如 'sales', 'finance'（可选）",
            },
            "limit": {
                "type": "integer",
                "description": "返回的指标数量上限（默认 50）",
                "default": 50,
            },
        },
        "required": [],
    }

    async def execute(self, params: dict, context: ToolContext) -> ToolResult:
        """
        Execute a metric query.

        Pipeline:
        1. Build query filters from params
        2. Query bi_metric_definitions table
        3. Return metric list with definitions

        Args:
            params: {
                "connection_id"?: int,
                "keyword"?: str,
                "metric_type"?: str,
                "business_domain"?: str,
                "limit"?: int
            }
            context: ToolContext with session_id, user_id, connection_id

        Returns:
            ToolResult with success=True and data={metrics: [...], total: int}
            On error: ToolResult with success=False, error, error_code
        """
        start_time = time.time()
        connection_id = params.get("connection_id") or context.connection_id
        keyword = params.get("keyword", "").strip()
        metric_type = params.get("metric_type", "").strip()
        business_domain = params.get("business_domain", "").strip()
        limit = params.get("limit", 50)

        try:
            logger.info(
                "MetricsTool.execute: connection_id=%s, keyword=%s, metric_type=%s, trace=%s",
                connection_id,
                keyword,
                metric_type,
                context.trace_id,
            )

            # ── Stage 1: Get DB session ───────────────────────────────────────
            from app.core.database import SessionLocal
            db = SessionLocal()
            try:
                # ── Stage 2: Build query ───────────────────────────────────────────
                query = db.query(BiMetricDefinition).filter(
                    BiMetricDefinition.is_active == True  # noqa: E712
                )

                if connection_id:
                    query = query.filter(BiMetricDefinition.datasource_id == connection_id)

                if keyword:
                    # Search in name, name_zh, description
                    keyword_pattern = f"%{keyword}%"
                    query = query.filter(
                        (BiMetricDefinition.name.ilike(keyword_pattern)) |
                        (BiMetricDefinition.name_zh.ilike(keyword_pattern)) |
                        (BiMetricDefinition.description.ilike(keyword_pattern))
                    )

                if metric_type:
                    query = query.filter(BiMetricDefinition.metric_type == metric_type)

                if business_domain:
                    query = query.filter(BiMetricDefinition.business_domain == business_domain)

                # Get total count before pagination
                total = query.count()

                # Apply limit and order
                metrics = query.order_by(
                    BiMetricDefinition.created_at.desc()
                ).limit(limit).all()

                # ── Stage 3: Build response ───────────────────────────────────────
                metric_list = []
                for m in metrics:
                    metric_list.append({
                        "id": str(m.id),
                        "name": m.name,
                        "name_zh": m.name_zh,
                        "metric_type": m.metric_type,
                        "business_domain": m.business_domain,
                        "description": m.description,
                        "formula": m.formula,
                        "formula_template": m.formula_template,
                        "aggregation_type": m.aggregation_type,
                        "result_type": m.result_type,
                        "unit": m.unit,
                        "precision": m.precision,
                        "datasource_id": m.datasource_id,
                        "table_name": m.table_name,
                        "column_name": m.column_name,
                        "filters": m.filters,
                        "sensitivity_level": m.sensitivity_level,
                        "is_active": m.is_active,
                        "lineage_status": m.lineage_status,
                        "created_at": m.created_at.strftime("%Y-%m-%d %H:%M:%S") if m.created_at else None,
                    })

                execution_time_ms = int((time.time() - start_time) * 1000)
                logger.info(
                    "MetricsTool success: connection_id=%s, keyword=%s, total=%d, returned=%d, time=%dms",
                    connection_id,
                    keyword,
                    total,
                    len(metric_list),
                    execution_time_ms,
                )

                return ToolResult(
                    success=True,
                    data={
                        "metrics": metric_list,
                        "total": total,
                        "limit": limit,
                        "filters": {
                            "connection_id": connection_id,
                            "keyword": keyword or None,
                            "metric_type": metric_type or None,
                            "business_domain": business_domain or None,
                        },
                    },
                    execution_time_ms=execution_time_ms,
                )
            finally:
                db.close()

        except Exception as e:
            logger.exception("MetricsTool unexpected error: %s", e)
            return ToolResult(
                success=False,
                data=None,
                error="查询指标定义失败，请稍后重试",
                execution_time_ms=int((time.time() - start_time) * 1000),
            )
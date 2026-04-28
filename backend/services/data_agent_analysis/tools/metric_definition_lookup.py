"""
MetricDefinitionLookupTool — 指标定义查询

Spec 28 §4.1 — metric_definition_lookup

功能：
- 查询业务指标的标准计算口径
- 返回指标名称、定义、类型、单位、数据源等
"""

import logging
import time
from typing import Any, Dict, List, Optional

from app.core.database import SessionLocal
from services.data_agent.tool_base import BaseTool, ToolResult, ToolContext, ToolMetadata
from models.metrics import BiMetricDefinition

logger = logging.getLogger(__name__)


class MetricDefinitionLookupTool(BaseTool):
    """Metric Definition Lookup Tool — 查询指标定义"""

    name = "metric_definition_lookup"
    description = "查询业务指标的标准计算口径。当需要知道某指标如何计算、指标包含哪些维度、使用什么数据源时使用。"
    metadata = ToolMetadata(
        category="query",
        version="1.0.0",
        dependencies=["requires_database"],
        tags=["metrics", "definition", "kpi", "business_metrics"],
    )
    parameters_schema = {
        "type": "object",
        "properties": {
            "connection_id": {
                "type": "integer",
                "description": "数据源连接 ID（可选，用于过滤该数据源的指标）",
            },
            "keyword": {
                "type": "string",
                "description": "关键词过滤，匹配指标名称或描述",
            },
            "metric_type": {
                "type": "string",
                "description": "指标类型过滤，如 'gauge', 'counter', 'derived'",
            },
            "business_domain": {
                "type": "string",
                "description": "业务域过滤，如 'sales', 'finance'",
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
        start_time = time.time()
        connection_id = params.get("connection_id") or context.connection_id
        keyword = params.get("keyword", "").strip()
        metric_type = params.get("metric_type", "").strip()
        business_domain = params.get("business_domain", "").strip()
        limit = params.get("limit", 50)

        try:
            logger.info(
                "MetricDefinitionLookupTool: connection_id=%s, keyword=%s, metric_type=%s",
                connection_id,
                keyword,
                metric_type,
            )

            db = SessionLocal()
            try:
                query = db.query(BiMetricDefinition).filter(
                    BiMetricDefinition.is_active == True  # noqa: E712
                )

                if connection_id:
                    query = query.filter(BiMetricDefinition.datasource_id == connection_id)

                if keyword:
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

                total = query.count()
                metrics = query.order_by(
                    BiMetricDefinition.created_at.desc()
                ).limit(limit).all()

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
                    })

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
                    execution_time_ms=int((time.time() - start_time) * 1000),
                )

            finally:
                db.close()

        except Exception as e:
            logger.exception("MetricDefinitionLookupTool error: %s", e)
            return ToolResult(
                success=False,
                data=None,
                error=f"查询指标定义失败: {str(e)}",
                execution_time_ms=int((time.time() - start_time) * 1000),
            )
"""
QualityCheckTool — 质量检查

Spec 28 §4.1 — quality_check

功能：
- 查询 Spec 15 质量结果
- 检查数据源健康度
- 返回 null_rate、freshness 等质量指标
"""

import logging
import time
from typing import Any, Dict, List, Optional

from app.core.database import SessionLocal
from services.data_agent.tool_base import BaseTool, ToolResult, ToolContext, ToolMetadata
from models.governance import BiQualityResult, BiQualityRule

logger = logging.getLogger(__name__)


class QualityCheckTool(BaseTool):
    """Quality Check Tool — 质量检查"""

    name = "quality_check"
    description = "查询数据质量检查结果。当需要检查数据源健康度或了解数据质量时使用。"
    metadata = ToolMetadata(
        category="query",
        version="1.0.0",
        dependencies=["requires_database"],
        tags=["quality", "governance", "health", "data_quality"],
    )
    parameters_schema = {
        "type": "object",
        "properties": {
            "datasource_id": {
                "type": "integer",
                "description": "数据源 ID",
            },
            "table_name": {
                "type": "string",
                "description": "表名（可选）",
            },
            "time_range": {
                "type": "object",
                "description": "检查时间范围",
                "properties": {
                    "start": {"type": "string"},
                    "end": {"type": "string"},
                },
            },
            "check_types": {
                "type": "array",
                "items": {"type": "string"},
                "description": "检查类型列表",
            },
            "limit": {
                "type": "integer",
                "description": "返回结果数量（默认 20）",
                "default": 20,
            },
        },
        "required": ["datasource_id"],
    }

    async def execute(self, params: dict, context: ToolContext) -> ToolResult:
        start_time = time.time()
        datasource_id = params.get("datasource_id")
        table_name = params.get("table_name")
        time_range = params.get("time_range")
        check_types = params.get("check_types", [])
        limit = params.get("limit", 20)

        if not datasource_id:
            return ToolResult(
                success=False,
                data=None,
                error="datasource_id 是必填参数",
                execution_time_ms=int((time.time() - start_time) * 1000),
            )

        try:
            logger.info(
                "QualityCheckTool: datasource_id=%s, table_name=%s, check_types=%s",
                datasource_id,
                table_name,
                check_types,
            )

            db = SessionLocal()
            try:
                query = db.query(BiQualityResult).join(
                    BiQualityRule,
                    BiQualityResult.rule_id == BiQualityRule.id,
                ).filter(
                    BiQualityRule.datasource_id == datasource_id,
                )

                if table_name:
                    query = query.filter(BiQualityRule.table_name == table_name)

                if check_types:
                    query = query.filter(BiQualityRule.rule_type.in_(check_types))

                results = query.order_by(
                    BiQualityResult.created_at.desc()
                ).limit(limit).all()

                checks = []
                for r in results:
                    checks.append({
                        "type": r.rule.rule_type if r.rule else "unknown",
                        "field": r.rule.field_name if r.rule else None,
                        "actual": r.actual_value,
                        "threshold": r.threshold_value,
                        "passed": r.is_passed,
                        "rule_name": r.rule.rule_name if r.rule else None,
                        "table_name": r.rule.table_name if r.rule else None,
                        "created_at": r.created_at.isoformat() if r.created_at else None,
                    })

                # 计算整体质量评分
                total_checks = len(checks)
                passed_checks = sum(1 for c in checks if c["passed"])
                overall_score = (passed_checks / total_checks * 100) if total_checks > 0 else 0

                # 格式化检查类型描述
                check_type_map = {
                    "null_rate": "空值率",
                    "not_null": "非空检查",
                    "row_count": "行数检查",
                    "duplicate_rate": "重复率",
                    "unique_count": "唯一值数量",
                    "referential": "参照完整性",
                    "cross_field": "跨字段校验",
                    "value_range": "值范围检查",
                    "freshness": "数据新鲜度",
                    "latency": "延迟检查",
                    "format_regex": "格式正则",
                    "enum_check": "枚举值检查",
                    "custom_sql": "自定义 SQL",
                }

                check_descriptions = [check_type_map.get(ct, ct) for ct in check_types]

                result_data = {
                    "datasource_id": datasource_id,
                    "table_name": table_name,
                    "checks": checks,
                    "overall_quality_score": round(overall_score, 1),
                    "total_checks": total_checks,
                    "passed_checks": passed_checks,
                    "failed_checks": total_checks - passed_checks,
                    "time_range": time_range,
                    "check_types_description": check_descriptions,
                    "result_summary": (
                        f"数据源 {datasource_id} 整体质量评分：{overall_score:.1f}分，"
                        f"共 {total_checks} 项检查，{passed_checks} 通过，{total_checks - passed_checks} 失败"
                    ),
                }

                return ToolResult(
                    success=True,
                    data=result_data,
                    execution_time_ms=int((time.time() - start_time) * 1000),
                )

            finally:
                db.close()

        except Exception as e:
            logger.exception("QualityCheckTool error: %s", e)
            return ToolResult(
                success=False,
                data=None,
                error=f"质量检查查询失败: {str(e)}",
                execution_time_ms=int((time.time() - start_time) * 1000),
            )
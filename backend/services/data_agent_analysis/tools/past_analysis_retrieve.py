"""
PastAnalysisRetrieveTool — 历史分析检索

Spec 28 §4.1 — past_analysis_retrieve

功能：
- 语义检索历史分析结论
- 基于关键词或语义相似度检索
- 返回历史洞察和报告
"""

import logging
import time
from typing import Any, Dict, List, Optional

from app.core.database import SessionLocal
from services.data_agent.tool_base import BaseTool, ToolResult, ToolContext, ToolMetadata
from services.data_agent.models import BiAnalysisSession, BiAnalysisInsight, BiAnalysisReport

logger = logging.getLogger(__name__)


class PastAnalysisRetrieveTool(BaseTool):
    """Past Analysis Retrieve Tool — 历史分析检索"""

    name = "past_analysis_retrieve"
    description = "检索历史分析结论和洞察。当需要参考类似问题的历史分析时使用。"
    metadata = ToolMetadata(
        category="state",
        version="1.0.0",
        dependencies=["requires_database"],
        tags=["history", "retrieval", "past_insights", "similar_analysis"],
    )
    parameters_schema = {
        "type": "object",
        "properties": {
            "tenant_id": {
                "type": "string",
                "description": "租户 ID",
            },
            "query": {
                "type": "string",
                "description": "检索关键词或描述",
            },
            "insight_type": {
                "type": "string",
                "description": "洞察类型过滤（可选）",
                "enum": ["anomaly", "trend", "correlation", "causation"],
            },
            "task_type": {
                "type": "string",
                "description": "分析任务类型过滤（可选）",
                "enum": ["causation", "report", "insight"],
            },
            "limit": {
                "type": "integer",
                "description": "返回结果数量（默认 10）",
                "default": 10,
            },
        },
        "required": ["tenant_id", "query"],
    }

    async def execute(self, params: dict, context: ToolContext) -> ToolResult:
        start_time = time.time()
        tenant_id = context.tenant_id or params.get("tenant_id", "")
        query = params.get("query", "")
        insight_type = params.get("insight_type")
        task_type = params.get("task_type")
        limit = params.get("limit", 10)

        if not tenant_id or not query:
            return ToolResult(
                success=False,
                data=None,
                error="tenant_id 和 query 是必填参数",
                execution_time_ms=int((time.time() - start_time) * 1000),
            )

        try:
            logger.info(
                "PastAnalysisRetrieveTool: tenant_id=%s, query=%s",
                tenant_id,
                query,
            )

            db = SessionLocal()
            try:
                # 检索已发布的洞察
                insight_query = db.query(BiAnalysisInsight).filter(
                    BiAnalysisInsight.tenant_id == tenant_id,
                    BiAnalysisInsight.status == "published",
                )

                # 关键词匹配
                query_lower = query.lower()
                insight_query = insight_query.filter(
                    (BiAnalysisInsight.title.ilike(f"%{query_lower}%")) |
                    (BiAnalysisInsight.summary.ilike(f"%{query_lower}%")) |
                    (BiAnalysisInsight.detail_json.cast(db.bind.dialect.name == "postgresql").ilike(f"%{query_lower}%"))
                )

                if insight_type:
                    insight_query = insight_query.filter(
                        BiAnalysisInsight.insight_type == insight_type
                    )

                insights = insight_query.order_by(
                    BiAnalysisInsight.published_at.desc()
                ).limit(limit).all()

                insight_results = []
                for ins in insights:
                    insight_results.append({
                        "id": str(ins.id),
                        "insight_type": ins.insight_type,
                        "title": ins.title,
                        "summary": ins.summary,
                        "confidence": ins.confidence,
                        "impact_scope": ins.impact_scope,
                        "datasource_ids": ins.datasource_ids,
                        "published_at": ins.published_at.isoformat() if ins.published_at else None,
                        "session_id": str(ins.session_id) if ins.session_id else None,
                    })

                # 检索相关会话
                session_query = db.query(BiAnalysisSession).filter(
                    BiAnalysisSession.tenant_id == tenant_id,
                    BiAnalysisSession.status.in_(["completed", "archived"]),
                )

                if task_type:
                    session_query = session_query.filter(
                        BiAnalysisSession.task_type == task_type
                    )

                sessions = session_query.order_by(
                    BiAnalysisSession.completed_at.desc()
                ).limit(limit).all()

                session_results = []
                for sess in sessions:
                    session_results.append({
                        "id": str(sess.id),
                        "task_type": sess.task_type,
                        "status": sess.status,
                        "current_step": sess.current_step,
                        "hypothesis_tree": sess.hypothesis_tree,
                        "created_by": sess.created_by,
                        "created_at": sess.created_at.isoformat() if sess.created_at else None,
                        "completed_at": sess.completed_at.isoformat() if sess.completed_at else None,
                    })

                result_data = {
                    "query": query,
                    "insights": insight_results,
                    "sessions": session_results,
                    "total_insights": len(insight_results),
                    "total_sessions": len(session_results),
                    "result_summary": (
                        f"找到 {len(insight_results)} 条相关洞察，"
                        f"{len(session_results)} 个相关分析会话"
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
            logger.exception("PastAnalysisRetrieveTool error: %s", e)
            return ToolResult(
                success=False,
                data=None,
                error=f"历史分析检索失败: {str(e)}",
                execution_time_ms=int((time.time() - start_time) * 1000),
            )
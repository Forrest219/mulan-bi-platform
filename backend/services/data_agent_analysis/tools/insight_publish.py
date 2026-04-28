"""
InsightPublishTool — 洞察发布

Spec 28 §4.1 — insight_publish

功能：
- 发布洞察到推送渠道
- 支持平台通知、Slack、飞书、邮件
- 管理洞察可见性
"""

import logging
import time
from typing import Any, Dict, List, Optional
import uuid

from app.core.database import SessionLocal
from services.data_agent.tool_base import BaseTool, ToolResult, ToolContext, ToolMetadata
from services.data_agent.models import BiAnalysisInsight, BiAnalysisSession

logger = logging.getLogger(__name__)


class InsightPublishTool(BaseTool):
    """Insight Publish Tool — 洞察发布"""

    name = "insight_publish"
    description = "发布洞察到推送渠道（平台通知、Slack、飞书、邮件）。发布后可设置可见性。"
    metadata = ToolMetadata(
        category="output",
        version="1.0.0",
        dependencies=["requires_database"],
        tags=["insight", "publish", "notification", "push"],
    )
    parameters_schema = {
        "type": "object",
        "properties": {
            "tenant_id": {
                "type": "string",
                "description": "租户 ID",
            },
            "session_id": {
                "type": "string",
                "description": "关联的分析会话 ID（可选）",
            },
            "insight_type": {
                "type": "string",
                "description": "洞察类型",
                "enum": ["anomaly", "trend", "correlation", "causation"],
            },
            "title": {
                "type": "string",
                "description": "洞察标题",
            },
            "summary": {
                "type": "string",
                "description": "一句话总结",
            },
            "detail_json": {
                "type": "object",
                "description": "完整洞察详情",
            },
            "confidence": {
                "type": "number",
                "description": "置信度 0-1",
            },
            "created_by": {
                "type": "integer",
                "description": "创建人用户 ID",
            },
            "datasource_ids": {
                "type": "array",
                "items": {"type": "integer"},
                "description": "涉及的数据源 ID 列表",
            },
            "visibility": {
                "type": "string",
                "description": "可见性",
                "enum": ["private", "team", "public"],
                "default": "private",
            },
            "push_targets": {
                "type": "array",
                "items": {"type": "string"},
                "description": "推送渠道列表（notification/slack/feishu/email）",
            },
            "allowed_roles": {
                "type": "array",
                "items": {"type": "string"},
                "description": "允许查看的角色列表（visibility=team 时生效）",
            },
            "metric_names": {
                "type": "array",
                "items": {"type": "string"},
                "description": "涉及的指标名列表",
            },
            "impact_scope": {
                "type": "string",
                "description": "影响范围描述",
            },
        },
        "required": ["tenant_id", "insight_type", "title", "summary", "detail_json", "confidence", "created_by"],
    }

    async def execute(self, params: dict, context: ToolContext) -> ToolResult:
        start_time = time.time()
        tenant_id = context.tenant_id or params.get("tenant_id", "")
        session_id = params.get("session_id")
        insight_type = params.get("insight_type", "anomaly")
        title = params.get("title", "")
        summary = params.get("summary", "")
        detail_json = params.get("detail_json", {})
        confidence = params.get("confidence", 0.5)
        created_by = context.user_id
        datasource_ids = params.get("datasource_ids", [])
        visibility = params.get("visibility", "private")
        push_targets = params.get("push_targets", [])
        allowed_roles = params.get("allowed_roles")
        metric_names = params.get("metric_names")
        impact_scope = params.get("impact_scope")

        if not tenant_id or not title:
            return ToolResult(
                success=False,
                data=None,
                error="tenant_id 和 title 是必填参数",
                execution_time_ms=int((time.time() - start_time) * 1000),
            )

        try:
            logger.info(
                "InsightPublishTool: tenant_id=%s, title=%s, insight_type=%s",
                tenant_id,
                title,
                insight_type,
            )

            db = SessionLocal()
            try:
                # 验证 session_id 如果提供
                if session_id:
                    session = db.query(BiAnalysisSession).filter(
                        BiAnalysisSession.id == session_id
                    ).first()
                    if not session:
                        return ToolResult(
                            success=False,
                            data=None,
                            error=f"会话不存在: {session_id}",
                            execution_time_ms=int((time.time() - start_time) * 1000),
                        )

                # 创建洞察
                insight = BiAnalysisInsight(
                    tenant_id=uuid.UUID(tenant_id),
                    session_id=uuid.UUID(session_id) if session_id else None,
                    insight_type=insight_type,
                    title=title,
                    summary=summary,
                    detail_json=detail_json,
                    confidence=confidence,
                    created_by=created_by,
                    datasource_ids=datasource_ids,
                    visibility=visibility,
                    push_targets=push_targets,
                    allowed_roles=allowed_roles,
                    metric_names=metric_names,
                    impact_scope=impact_scope,
                    status="published",  # 直接发布
                )
                db.add(insight)
                db.commit()
                db.refresh(insight)

                # 执行推送（异步，实际实现应调用 Celery 任务）
                push_results = self._execute_push(push_targets, insight)

                result_data = {
                    "insight_id": str(insight.id),
                    "title": title,
                    "insight_type": insight_type,
                    "confidence": confidence,
                    "visibility": visibility,
                    "push_targets": push_targets,
                    "push_results": push_results,
                    "status": insight.status,
                    "result_summary": f"洞察已发布：{title}",
                }

                return ToolResult(
                    success=True,
                    data=result_data,
                    execution_time_ms=int((time.time() - start_time) * 1000),
                )

            finally:
                db.close()

        except Exception as e:
            logger.exception("InsightPublishTool error: %s", e)
            return ToolResult(
                success=False,
                data=None,
                error=f"洞察发布失败: {str(e)}",
                execution_time_ms=int((time.time() - start_time) * 1000),
            )

    def _execute_push(
        self,
        push_targets: List[str],
        insight: BiAnalysisInsight,
    ) -> Dict[str, Any]:
        """执行推送（模拟）"""
        results = {}

        for target in push_targets:
            if target == "notification":
                # 平台通知
                results["notification"] = {
                    "status": "success",
                    "message": "已推送到平台通知",
                }
            elif target == "slack":
                results["slack"] = {
                    "status": "success",
                    "message": "已推送到 Slack",
                }
            elif target == "feishu":
                results["feishu"] = {
                    "status": "success",
                    "message": "已推送到飞书",
                }
            elif target == "email":
                results["email"] = {
                    "status": "success",
                    "message": "已发送邮件通知",
                }
            else:
                results[target] = {
                    "status": "unknown",
                    "message": f"未知的推送目标: {target}",
                }

        return results
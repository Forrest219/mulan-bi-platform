"""
ReportWriteTool — 报告写入

Spec 28 §4.1 — report_write

功能：
- 生成结构化报告（JSON 规范层）
- 渲染 Markdown
- 存储报告到数据库
"""

import json
import logging
import time
from typing import Any, Dict, List, Optional
import uuid

from app.core.database import SessionLocal
from services.data_agent.tool_base import BaseTool, ToolResult, ToolContext, ToolMetadata
from services.data_agent.models import BiAnalysisReport, BiAnalysisSession

logger = logging.getLogger(__name__)


class ReportWriteTool(BaseTool):
    """Report Write Tool — 报告写入"""

    name = "report_write"
    description = "生成结构化分析报告（JSON 规范层 + Markdown 渲染层），并存储到数据库。"
    metadata = ToolMetadata(
        category="output",
        version="1.0.0",
        dependencies=["requires_database"],
        tags=["report", "output", "markdown", "json_spec"],
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
            "subject": {
                "type": "string",
                "description": "报告主题",
            },
            "time_range": {
                "type": "string",
                "description": "分析时间范围",
            },
            "content_json": {
                "type": "object",
                "description": "报告内容（JSON 规范层）",
            },
            "author": {
                "type": "integer",
                "description": "作者用户 ID",
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
            "allowed_roles": {
                "type": "array",
                "items": {"type": "string"},
                "description": "允许查看的角色列表（visibility=team 时生效）",
            },
        },
        "required": ["tenant_id", "subject", "content_json", "author"],
    }

    async def execute(self, params: dict, context: ToolContext) -> ToolResult:
        start_time = time.time()
        tenant_id = context.tenant_id or params.get("tenant_id", "")
        session_id = params.get("session_id")
        subject = params.get("subject", "")
        time_range = params.get("time_range")
        content_json = params.get("content_json", {})
        author = context.user_id
        datasource_ids = params.get("datasource_ids", [])
        visibility = params.get("visibility", "private")
        allowed_roles = params.get("allowed_roles")

        if not tenant_id or not subject:
            return ToolResult(
                success=False,
                data=None,
                error="tenant_id 和 subject 是必填参数",
                execution_time_ms=int((time.time() - start_time) * 1000),
            )

        try:
            logger.info(
                "ReportWriteTool: tenant_id=%s, subject=%s",
                tenant_id,
                subject,
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

                # 生成 Markdown 渲染层
                content_md = self._render_markdown(content_json, subject, time_range)

                # 创建报告
                report = BiAnalysisReport(
                    tenant_id=uuid.UUID(tenant_id),
                    session_id=uuid.UUID(session_id) if session_id else None,
                    subject=subject,
                    time_range=time_range,
                    content_json=content_json,
                    content_md=content_md,
                    author=author,
                    datasource_ids=datasource_ids,
                    visibility=visibility,
                    allowed_roles=allowed_roles,
                )
                db.add(report)
                db.commit()
                db.refresh(report)

                return ToolResult(
                    success=True,
                    data={
                        "report_id": str(report.id),
                        "subject": subject,
                        "status": report.status,
                        "content_md": content_md[:500] + "..." if len(content_md) > 500 else content_md,
                        "result_summary": f"报告已创建：{subject}",
                    },
                    execution_time_ms=int((time.time() - start_time) * 1000),
                )

            finally:
                db.close()

        except Exception as e:
            logger.exception("ReportWriteTool error: %s", e)
            return ToolResult(
                success=False,
                data=None,
                error=f"报告写入失败: {str(e)}",
                execution_time_ms=int((time.time() - start_time) * 1000),
            )

    def _render_markdown(
        self,
        content_json: Dict[str, Any],
        subject: str,
        time_range: Optional[str],
    ) -> str:
        """将 JSON 规范层渲染为 Markdown"""
        md_lines = [
            f"# {subject}",
            "",
        ]

        if time_range:
            md_lines.append(f"**分析时间范围**：{time_range}")
            md_lines.append("")

        # 渲染 metadata
        metadata = content_json.get("metadata", {})
        if metadata:
            md_lines.append("## 基本信息")
            md_lines.append(f"- 生成时间：{metadata.get('generated_at', 'N/A')}")
            md_lines.append(f"- 置信度：{metadata.get('confidence', 'N/A')}")
            md_lines.append("")

        # 渲染 summary
        summary = content_json.get("summary", "")
        if summary:
            md_lines.append(f"## 摘要\n{summary}\n")

        # 渲染 sections
        sections = content_json.get("sections", [])
        for i, section in enumerate(sections, 1):
            section_type = section.get("type", "unknown")
            title = section.get("title", f"第 {i} 节")
            narrative = section.get("narrative", "")

            md_lines.append(f"## {i}. {title}")

            if section_type == "finding":
                md_lines.append("*类型：发现*\n")
            elif section_type == "evidence":
                md_lines.append("*类型：证据*\n")
            elif section_type == "recommendation":
                md_lines.append(f"*类型：建议（优先级：{section.get('priority', 'N/A')}）*\n")

            md_lines.append(f"{narrative}\n")

            # 渲染 chart_spec
            chart_spec = section.get("chart_spec")
            if chart_spec:
                md_lines.append("**图表配置**：")
                md_lines.append(f"```json\n{json.dumps(chart_spec, ensure_ascii=False, indent=2)}\n```\n")

        # 渲染 hypothesis_trace
        hypothesis_trace = content_json.get("hypothesis_trace", [])
        if hypothesis_trace:
            md_lines.append("## 假设追溯")
            for trace in hypothesis_trace:
                step = trace.get("step", "?")
                hypothesis = trace.get("hypothesis", "")
                status = trace.get("status", "")
                confidence = trace.get("confidence", "")
                md_lines.append(f"- Step {step}：{hypothesis}（状态：{status}，置信度：{confidence}）")
            md_lines.append("")

        # 渲染 confidence_score
        confidence_score = content_json.get("confidence_score")
        if confidence_score:
            md_lines.append(f"**整体置信度**：{confidence_score}\n")

        # 渲染 caveats
        caveats = content_json.get("caveats", [])
        if caveats:
            md_lines.append("## 注意事项")
            for caveat in caveats:
                md_lines.append(f"- {caveat}")
            md_lines.append("")

        return "\n".join(md_lines)
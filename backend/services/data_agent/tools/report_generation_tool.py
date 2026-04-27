"""
ReportGenerationTool — 自动报告生成工具

Spec: docs/specs/28-data-agent-spec.md §7 报告生成规范

将归因分析结论（或其他分析结果）自动生成为结构化报告。
支持 JSON 规范层 + Markdown 渲染层输出。
"""

import logging
import time
from typing import Any, Optional

from services.data_agent.tool_base import BaseTool, ToolResult, ToolContext, ToolMetadata

logger = logging.getLogger(__name__)


class ReportGenerationTool(BaseTool):
    """
    Data Agent Tool: 自动报告生成。

    将分析结论（归因分析、趋势分析等）生成为结构化报告。
    支持 JSON 规范层（Spec §7.1）和 Markdown 渲染层（Spec §7.2）。

    Tool name: "report_generation"
    """

    name = "report_generation"
    description = "自动生成分析报告。将归因分析、趋势分析等结论生成为结构化报告（JSON规范层 + Markdown渲染层）。"
    metadata = ToolMetadata(
        category="reporting",
        version="1.0.0",
        dependencies=["requires_database"],
        tags=["report", "markdown", "analysis-output"],
    )
    parameters_schema = {
        "type": "object",
        "properties": {
            "subject": {
                "type": "string",
                "description": "报告主题",
            },
            "analysis_type": {
                "type": "string",
                "enum": ["causation", "trend", "comparison", "correlation", "segmentation", "funnel", "cohort", "root_cause"],
                "description": "分析类型",
            },
            "analysis_result": {
                "type": "object",
                "description": "分析结果数据（来自其他工具的输出）",
            },
            "time_range": {
                "type": "object",
                "description": "分析时间范围 {start, end}",
            },
            "include_sections": {
                "type": "array",
                "items": {"type": "string"},
                "description": "包含的报告章节，如 ['finding', 'evidence', 'recommendation']",
            },
            "output_format": {
                "type": "array",
                "items": {"type": "string"},
                "description": "输出格式 ['json', 'markdown']",
                "default": ["json", "markdown"],
            },
        },
        "required": ["subject", "analysis_type", "analysis_result"],
    }

    async def execute(self, params: dict, context: ToolContext) -> ToolResult:
        """
        生成分析报告。

        Args:
            params: {
                "subject": str,
                "analysis_type": str,
                "analysis_result": dict,
                "time_range"?: dict,
                "include_sections"?: list,
                "output_format"?: list,
            }
            context: ToolContext with session_id, user_id

        Returns:
            ToolResult with report content (JSON + Markdown)
        """
        start_time = time.time()

        subject = params.get("subject", "")
        analysis_type = params.get("analysis_type", "")
        analysis_result = params.get("analysis_result", {})
        time_range = params.get("time_range", {})
        include_sections = params.get("include_sections", ["finding", "evidence", "recommendation"])
        output_format = params.get("output_format", ["json", "markdown"])

        # ---------- 参数校验 ----------
        if not subject:
            return ToolResult(
                success=False,
                data=None,
                error="subject 不能为空",
                execution_time_ms=int((time.time() - start_time) * 1000),
            )
        if not analysis_type:
            return ToolResult(
                success=False,
                data=None,
                error="analysis_type 不能为空",
                execution_time_ms=int((time.time() - start_time) * 1000),
            )
        if not analysis_result:
            return ToolResult(
                success=False,
                data=None,
                error="analysis_result 不能为空",
                execution_time_ms=int((time.time() - start_time) * 1000),
            )

        logger.info(
            "ReportGenerationTool.execute: subject=%s, analysis_type=%s, trace=%s",
            subject,
            analysis_type,
            context.trace_id,
        )

        # ---------- 生成报告内容 ----------
        try:
            # 构建 JSON 规范层
            report_json = self._build_json_report(
                subject=subject,
                analysis_type=analysis_type,
                analysis_result=analysis_result,
                time_range=time_range,
                include_sections=include_sections,
            )

            # 生成 Markdown 渲染层
            markdown_content = ""
            if "markdown" in output_format:
                markdown_content = self._build_markdown_report(
                    subject=subject,
                    analysis_type=analysis_type,
                    report_json=report_json,
                )

            execution_time_ms = int((time.time() - start_time) * 1000)

            logger.info(
                "ReportGenerationTool success: subject=%s, time=%dms",
                subject,
                execution_time_ms,
            )

            return ToolResult(
                success=True,
                data={
                    "subject": subject,
                    "analysis_type": analysis_type,
                    "content_json": report_json,
                    "content_md": markdown_content if markdown_content else None,
                    "time_range": time_range,
                    "sections_included": include_sections,
                    "formats_output": output_format,
                },
                execution_time_ms=execution_time_ms,
            )

        except Exception as e:
            logger.exception("ReportGenerationTool unexpected error: %s", e)
            return ToolResult(
                success=False,
                data=None,
                error=f"报告生成失败: {str(e)}",
                execution_time_ms=int((time.time() - start_time) * 1000),
            )

    def _build_json_report(
        self,
        subject: str,
        analysis_type: str,
        analysis_result: dict,
        time_range: dict,
        include_sections: list,
    ) -> dict:
        """构建 JSON 规范层报告（Spec §7.1）"""
        from datetime import datetime, timezone

        # 提取置信度
        confidence = analysis_result.get("confidence") or analysis_result.get("root_cause_confidence", 0.85)

        # 提取摘要
        summary = analysis_result.get("summary") or analysis_result.get("root_cause_description", "")
        if not summary and analysis_type == "causation":
            metric = analysis_result.get("metric_name", "")
            direction = analysis_result.get("direction", "")
            magnitude = analysis_result.get("magnitude", 0)
            summary = f"{metric} 异动 {direction}，幅度 {magnitude:.1%}"

        # 构建章节
        sections = []
        if "finding" in include_sections:
            sections.append(self._build_finding_section(analysis_type, analysis_result))
        if "evidence" in include_sections:
            sections.append(self._build_evidence_section(analysis_type, analysis_result))
        if "recommendation" in include_sections:
            sections.append(self._build_recommendation_section(analysis_result))

        # 构建假设追踪
        hypothesis_trace = []
        hypotheses = analysis_result.get("hypotheses", [])
        for i, h in enumerate(hypotheses):
            if isinstance(h, dict):
                hypothesis_trace.append({
                    "step": i + 1,
                    "hypothesis": h.get("description", ""),
                    "status": h.get("status", "pending"),
                    "confidence": h.get("confidence", 0),
                })

        report = {
            "metadata": {
                "subject": subject,
                "time_range": time_range,
                "generated_at": datetime.now(timezone.utc).isoformat(),
                "confidence": confidence,
                "author": "Data Agent",
            },
            "summary": summary,
            "sections": sections,
            "hypothesis_trace": hypothesis_trace,
            "confidence_score": confidence,
            "caveats": [
                "数据仅覆盖指定时间范围，更长周期需进一步验证",
                "外部因素（宏观经济等）未纳入分析",
            ],
        }

        return report

    def _build_finding_section(self, analysis_type: str, analysis_result: dict) -> dict:
        """构建 finding 章节"""
        if analysis_type == "causation":
            narrative = f"通过归因分析确认 {analysis_result.get('metric_name', '')} 存在显著"
            direction = analysis_result.get("direction", "下降")
            narrative += f"{direction}，幅度 {analysis_result.get('magnitude', 0):.1%}"
            significance = analysis_result.get("statistical_significance", "")
            if significance:
                narrative += f"（{significance}）"
            return {
                "type": "finding",
                "title": "异动确认",
                "narrative": narrative,
                "data_ref": analysis_result.get("data_ref", ""),
            }
        elif analysis_type == "trend":
            return {
                "type": "finding",
                "title": "趋势发现",
                "narrative": f"检测到 {analysis_result.get('metric_name', '')} 存在趋势变化",
                "data_ref": analysis_result.get("data_ref", ""),
            }
        elif analysis_type == "correlation":
            return {
                "type": "finding",
                "title": "相关性发现",
                "narrative": f"发现 {analysis_result.get('metric_a', '')} 与 {analysis_result.get('metric_b', '')} 存在相关性",
                "data_ref": analysis_result.get("data_ref", ""),
            }
        else:
            return {
                "type": "finding",
                "title": "分析发现",
                "narrative": analysis_result.get("summary", ""),
                "data_ref": analysis_result.get("data_ref", ""),
            }

    def _build_evidence_section(self, analysis_type: str, analysis_result: dict) -> dict:
        """构建 evidence 章节"""
        dimensions = analysis_result.get("dimensions", [])
        concentration = analysis_result.get("concentration_point", "")

        if analysis_type == "causation" and dimensions:
            top_dim = dimensions[0] if dimensions else {}
            narrative = f"{top_dim.get('name', '维度')} 贡献了最大的异动幅度，"
            narrative += f"其中 {top_dim.get('top_factor', '')} 影响最为显著"
            if concentration:
                narrative += f"（集中点：{concentration}）"
            return {
                "type": "evidence",
                "title": "维度分解",
                "narrative": narrative,
                "data_ref": analysis_result.get("data_ref", ""),
                "chart_spec": {
                    "type": "bar",
                    "dimensions": [d.get("name", "") for d in dimensions],
                    "metrics": ["contribution"],
                },
            }
        return {
            "type": "evidence",
            "title": "证据支撑",
            "narrative": "详见分析数据",
            "data_ref": analysis_result.get("data_ref", ""),
        }

    def _build_recommendation_section(self, analysis_result: dict) -> dict:
        """构建 recommendation 章节"""
        actions = analysis_result.get("recommended_actions", [])
        priority = "MEDIUM"
        if actions:
            first_priority = actions[0].get("priority", "MEDIUM") if isinstance(actions[0], dict) else "MEDIUM"
            priority = first_priority

        narrative = ""
        if actions:
            action_texts = []
            for a in actions[:3]:
                if isinstance(a, dict):
                    action_texts.append(a.get("action", ""))
                else:
                    action_texts.append(str(a))
            narrative = "建议采取以下措施：\n" + "\n".join(f"- {t}" for t in action_texts)
        else:
            narrative = "建议持续监控相关指标，等待更多数据支持"

        return {
            "type": "recommendation",
            "title": "行动建议",
            "narrative": narrative,
            "priority": priority,
        }

    def _build_markdown_report(
        self,
        subject: str,
        analysis_type: str,
        report_json: dict,
    ) -> str:
        """构建 Markdown 渲染层报告（Spec §7.2）"""
        lines = [
            f"# {subject}",
            "",
            f"**生成时间**: {report_json['metadata']['generated_at']}",
            f"**分析类型**: {analysis_type}",
            f"**置信度**: {report_json['confidence_score']:.0%}",
            "",
        ]

        if report_json.get("time_range"):
            tr = report_json["time_range"]
            start = tr.get("start", "N/A")
            end = tr.get("end", "N/A")
            lines.append(f"**时间范围**: {start} ~ {end}")
            lines.append("")

        lines.append(f"## 摘要")
        lines.append("")
        lines.append(report_json.get("summary", ""))
        lines.append("")

        for section in report_json.get("sections", []):
            section_type = section.get("type", "")
            title = section.get("title", "")
            narrative = section.get("narrative", "")

            lines.append(f"## {title}")
            lines.append("")
            lines.append(narrative)
            lines.append("")

            # 添加图表 spec（如果有）
            if section.get("chart_spec"):
                chart = section["chart_spec"]
                lines.append(f"*图表类型*: {chart.get('type', 'N/A')}")
                lines.append("")

        # 假设追踪
        trace = report_json.get("hypothesis_trace", [])
        if trace:
            lines.append("## 推理过程")
            lines.append("")
            for entry in trace:
                status_icon = "✅" if entry.get("status") == "confirmed" else "❌" if entry.get("status") == "rejected" else "⏳"
                lines.append(f"{status_icon} Step {entry.get('step')}: {entry.get('hypothesis', '')} (置信度: {entry.get('confidence', 0):.0%})")
            lines.append("")

        # 注意事项
        caveats = report_json.get("caveats", [])
        if caveats:
            lines.append("## 注意事项")
            lines.append("")
            for caveat in caveats:
                lines.append(f"- {caveat}")
            lines.append("")

        return "\n".join(lines)

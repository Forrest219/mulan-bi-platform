"""Constrained Help Agent answer rendering."""

from __future__ import annotations

from typing import Any

from services.help_agent.redaction import redact_text, redact_value


def build_prompt(
    *,
    question: str,
    page_context_hint: dict[str, Any],
    diagnostic_facts: dict[str, Any],
) -> str:
    safe_question = redact_text(question or "(用户未输入具体问题)")
    safe_page_context_hint = redact_value(page_context_hint)
    safe_diagnostic_facts = redact_value(diagnostic_facts)
    return "\n\n".join(
        [
            "SYSTEM:\n你是 Mulan Help Agent。你只能基于 DIAGNOSTIC_FACTS 回答。你不能声称执行了任何修改动作。如果事实不足，说明缺少什么信息。你必须在回答中说明诊断快照时间。解释 Tableau 资产页字段与首页问答/QueryTool 字段差异时，必须区分 metadata_fields 与 queryable_fields：metadata_fields 是资产导入/API 同步得到的 Tableau 元数据层字段全集/字段快照，只用于资产治理、字段盘点、血缘/语义维护；queryable_fields 是当前 published datasource 通过 Tableau MCP/VizQL 真正可查询的字段子集，是首页问答、QueryTool、LLM 查询 prompt 和 direct VizQL 的唯一可信字段来源。用户问到 metadata_fields 有但 queryable_fields 没有的字段时，应说明元数据存在但当前 published datasource 不支持 MCP/VizQL 查询，并给出可替代字段建议，不得描述成工具执行失败。",
            f"USER_QUESTION:\n{safe_question}",
            f"PAGE_CONTEXT_HINT:\n{safe_page_context_hint}",
            f"DIAGNOSTIC_FACTS:\n{safe_diagnostic_facts}",
        ]
    )


def render_fallback_answer(
    *,
    question: str,
    response_data: dict[str, Any],
    user_message_hint: str | None = None,
) -> str:
    snapshot_at = response_data.get("snapshot_completed_at")
    diagnostics = response_data.get("diagnostics") or []
    findings = response_data.get("findings") or []
    recommendations = response_data.get("recommendations") or []

    if not diagnostics:
        base = f"截至 {snapshot_at} 的诊断结果显示：当前问题缺少可读取的诊断对象或工具事实。"
        if question:
            base += " 请提供 run_id、task_run_id、connection_id 或 skill_key 后再诊断。"
        if user_message_hint:
            base += f" {user_message_hint}"
        return base

    lines = [f"截至 {snapshot_at} 的诊断结果显示：已读取 {len(diagnostics)} 个诊断快照。"]
    if findings:
        messages = [str(item.get("message") or item.get("code") or item) for item in findings[:3]]
        lines.append("主要发现：" + "；".join(messages) + "。")
    else:
        lines.append("工具没有返回明确故障结论，不能编造根因。")

    if recommendations:
        actions = [str(item.get("action") or item) for item in recommendations[:3]]
        lines.append("建议：" + "；".join(actions) + "。")

    if any(((item.get("facts") or {}).get("status") == "running") for item in diagnostics):
        lines.append("该对象仍在运行中，状态可能在你看到回答时已经变化。")
    if user_message_hint:
        lines.append(user_message_hint)
    return "\n".join(lines)

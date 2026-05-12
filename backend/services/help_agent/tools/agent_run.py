"""Data Agent run diagnostic tools."""

from __future__ import annotations

from typing import Any

from services.data_agent.models import BiAgentRun, BiAgentStep

from .base import (
    finding,
    isoformat,
    permission_denied_result,
    recommendation,
    related_entity,
    require_owner_or_admin,
    structured_error_payload,
    tool_result,
    user_id,
    is_admin_user,
)


SLOW_STEP_MS = 15_000
LONG_THINKING_RATIO = 0.60
TOOL_RATIO = 0.60


def _normalize_skill_name(tool_name: str | None) -> str | None:
    if not tool_name:
        return None
    name = tool_name.strip()
    if name.endswith("_tool"):
        name = name[:-5]
    return name or None


def _step_duration(step: Any, next_step: Any | None, run: Any) -> tuple[int | None, str]:
    recorded = getattr(step, "execution_time_ms", None)
    if recorded is not None:
        return recorded, "recorded"
    created_at = getattr(step, "created_at", None)
    next_created_at = getattr(next_step, "created_at", None) if next_step else getattr(run, "completed_at", None)
    if created_at and next_created_at:
        return max(int((next_created_at - created_at).total_seconds() * 1000), 0), "derived"
    return None, "missing"


def _step_payload(step: Any, duration_ms: int | None, duration_source: str) -> dict[str, Any]:
    return {
        "id": getattr(step, "id", None),
        "step_number": getattr(step, "step_number", None),
        "step_type": getattr(step, "step_type", None),
        "tool_name": getattr(step, "tool_name", None),
        "duration_ms": duration_ms,
        "duration_source": duration_source,
        "summary": getattr(step, "tool_result_summary", None),
        "content": getattr(step, "content", None),
        "structured_error": structured_error_payload(
            step,
            getattr(step, "tool_result_summary", None) or getattr(step, "content", None),
        ),
    }


def diagnose_agent_run(db: Any, current_user: Any, run_id: str) -> dict[str, Any]:
    target = {"type": "agent_run", "id": str(run_id)}
    run = db.query(BiAgentRun).filter(BiAgentRun.id == run_id).first()
    if not run:
        return tool_result(
            tool="diagnose_agent_run",
            target=target,
            findings=[finding("error", "RUN_NOT_FOUND", "没有找到该 Agent run。")],
        )

    try:
        require_owner_or_admin(current_user, getattr(run, "user_id", None))
    except PermissionError as exc:
        return permission_denied_result("diagnose_agent_run", target, str(exc))

    steps = (
        db.query(BiAgentStep)
        .filter(BiAgentStep.run_id == getattr(run, "id"))
        .order_by(BiAgentStep.step_number)
        .all()
    )
    step_payloads: list[dict[str, Any]] = []
    findings: list[dict[str, Any]] = []
    recommendations: list[dict[str, Any]] = []
    related: list[dict[str, Any]] = []

    for index, step in enumerate(steps):
        next_step = steps[index + 1] if index + 1 < len(steps) else None
        duration_ms, duration_source = _step_duration(step, next_step, run)
        payload = _step_payload(step, duration_ms, duration_source)
        step_payloads.append(payload)
        if duration_ms is not None and duration_ms >= SLOW_STEP_MS:
            findings.append(
                finding(
                    "warning",
                    "SLOW_STEP",
                    f"步骤 {getattr(step, 'step_number', '?')} 耗时 {duration_ms}ms，超过慢步骤阈值。",
                )
            )
        if duration_source == "derived":
            findings.append(finding("info", "DERIVED_TIMING", "部分旧步骤缺少记录耗时，已根据步骤时间推导。"))
        summary = (getattr(step, "tool_result_summary", None) or "").lower()
        if "error" in summary or "failed" in summary or "失败" in summary:
            findings.append(finding("warning", "TOOL_ERROR_SUMMARY", "工具结果摘要包含失败或错误信息。"))

    total_ms = getattr(run, "execution_time_ms", None)
    if total_ms is None:
        total_ms = sum(item["duration_ms"] or 0 for item in step_payloads) or None
    thinking_ms = sum((item["duration_ms"] or 0) for item in step_payloads if item["step_type"] == "thinking")
    tool_ms = sum((item["duration_ms"] or 0) for item in step_payloads if item["step_type"] in {"tool_call", "tool_result"})
    slowest_step = max(step_payloads, key=lambda item: item["duration_ms"] or -1, default=None)

    status = getattr(run, "status", None)
    if status in {"failed", "error"}:
        findings.append(finding("error", "RUN_FAILED", "该 Agent run 以失败状态结束。"))
    if getattr(run, "error_code", None):
        findings.append(finding("warning", "ERROR_CODE_PRESENT", "运行记录包含 error_code。"))
    if total_ms:
        if thinking_ms / total_ms >= LONG_THINKING_RATIO:
            findings.append(finding("warning", "LONG_THINKING", "主要耗时集中在 LLM thinking 阶段。"))
            recommendations.append(recommendation("P1", "对确定性 schema/query 类问题优先走确定性路径，减少 LLM 二次整理。"))
        if tool_ms / total_ms >= TOOL_RATIO:
            findings.append(finding("warning", "SLOW_TOOL", "主要耗时集中在工具调用或工具结果处理阶段。"))
            recommendations.append(recommendation("P1", "检查对应工具、连接状态和上游服务耗时。"))

    connection_id = getattr(run, "connection_id", None)
    if connection_id is not None:
        related.append(related_entity("connection", connection_id, "run.connection_id"))
    for tool_name in list(getattr(run, "tools_used", None) or []) + [item["tool_name"] for item in step_payloads]:
        skill_name = _normalize_skill_name(tool_name)
        if skill_name:
            related.append(related_entity("skill", skill_name, f"run.tools_used 包含 {skill_name}"))

    facts = {
        "run": {
            "id": str(getattr(run, "id")),
            "conversation_id": str(getattr(run, "conversation_id", "")),
            "user_id": getattr(run, "user_id", None),
            "status": status,
            "error_code": getattr(run, "error_code", None),
            "connection_id": connection_id,
            "tools_used": getattr(run, "tools_used", None) or [],
            "response_type": getattr(run, "response_type", None),
            "total_ms": total_ms,
            "created_at": isoformat(getattr(run, "created_at", None)),
            "completed_at": isoformat(getattr(run, "completed_at", None)),
        },
        "slowest_step": slowest_step,
        "steps": step_payloads,
        "tool_breakdown": [
            {
                "tool": item["tool_name"],
                "duration_ms": item["duration_ms"],
                "summary": item["summary"],
            }
            for item in step_payloads
            if item["tool_name"]
        ],
    }
    return tool_result(
        tool="diagnose_agent_run",
        target=target,
        facts=facts,
        findings=findings,
        recommendations=recommendations,
        related_entities=related,
    )


def diagnose_recent_agent_failure(db: Any, current_user: Any, page_context: dict[str, Any] | None = None) -> dict[str, Any]:
    page_context = page_context or {}
    owner_id = page_context.get("user_id") if is_admin_user(current_user) and page_context.get("user_id") else user_id(current_user)
    query = db.query(BiAgentRun).filter(BiAgentRun.user_id == owner_id)
    runs = (
        query.filter(BiAgentRun.status.in_(["failed", "error"]))
        .order_by(BiAgentRun.created_at.desc())
        .limit(5)
        .all()
    )
    if not runs:
        return tool_result(
            tool="diagnose_recent_agent_failure",
            target={"type": "agent_run", "id": None},
            facts={"user_id": owner_id, "recent_failures_checked": 5},
            findings=[finding("info", "NO_RECENT_FAILURE", "最近 5 条运行记录中没有发现失败记录。")],
        )
    return diagnose_agent_run(db, current_user, str(getattr(runs[0], "id")))


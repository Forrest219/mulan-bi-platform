"""Task run diagnostic tool."""

from __future__ import annotations

from typing import Any

from services.tasks.models import BiTaskRun

from .base import finding, isoformat, permission_denied_result, recommendation, require_admin, structured_error_payload, tool_result


def diagnose_task_run(db: Any, current_user: Any, task_run_id: int) -> dict[str, Any]:
    target = {"type": "task_run", "id": task_run_id}
    try:
        require_admin(current_user)
    except PermissionError as exc:
        return permission_denied_result("diagnose_task_run", target, str(exc))

    run = db.query(BiTaskRun).filter(BiTaskRun.id == task_run_id).first()
    if not run:
        return tool_result(
            tool="diagnose_task_run",
            target=target,
            findings=[finding("error", "TASK_RUN_NOT_FOUND", "没有找到该任务运行记录。")],
        )

    status = getattr(run, "status", None)
    error_message = getattr(run, "error_message", None)
    error_lower = (error_message or "").lower()
    findings: list[dict[str, Any]] = []
    recommendations: list[dict[str, Any]] = []
    if status == "failed":
        findings.append(finding("error", "TASK_FAILED", "该任务运行失败。"))
    if (getattr(run, "retry_count", 0) or 0) > 0:
        findings.append(finding("warning", "TASK_RETRIED", "该任务发生过重试。"))
    if (getattr(run, "duration_ms", 0) or 0) >= 300_000:
        findings.append(finding("warning", "TASK_SLOW", "该任务耗时超过 5 分钟。"))
    if any(word in error_lower for word in ("connection", "connect", "连接")):
        findings.append(finding("warning", "CONNECTION_ERROR", "错误信息指向连接问题。"))
        recommendations.append(recommendation("P1", "建议由管理员确认连接状态后再重跑任务。"))
    if any(word in error_lower for word in ("auth", "permission", "unauthorized", "认证", "权限")):
        findings.append(finding("warning", "AUTH_ERROR", "错误信息指向认证或权限问题。"))
    if "timeout" in error_lower or "超时" in error_lower:
        findings.append(finding("warning", "TIMEOUT", "错误信息指向超时。"))

    facts = {
        "task_run": {
            "id": getattr(run, "id", None),
            "task_name": getattr(run, "task_name", None),
            "task_label": getattr(run, "task_label", None),
            "trigger_type": getattr(run, "trigger_type", None),
            "status": status,
            "started_at": isoformat(getattr(run, "started_at", None)),
            "finished_at": isoformat(getattr(run, "finished_at", None)),
            "duration_ms": getattr(run, "duration_ms", None),
            "retry_count": getattr(run, "retry_count", None),
            "parent_run_id": getattr(run, "parent_run_id", None),
            "triggered_by": getattr(run, "triggered_by", None),
            "result_summary": getattr(run, "result_summary", None),
            "error": structured_error_payload(run, error_message),
        }
    }
    return tool_result(
        tool="diagnose_task_run",
        target=target,
        facts=facts,
        findings=findings,
        recommendations=recommendations,
    )


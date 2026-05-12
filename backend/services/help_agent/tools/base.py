"""Common contracts and guards for read-only Help Agent tools."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Iterable

from services.help_agent.redaction import redact_value
from services.help_agent.schemas import DiagnosticFinding, DiagnosticRecommendation, RelatedEntity, ToolResultData


ADMIN_ROLES = {"admin", "data_admin"}


class ToolPermissionError(PermissionError):
    """Raised when the caller cannot inspect a diagnostic target."""

    code = "HLP_003"


def snapshot_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def user_id(user: Any) -> Any:
    if isinstance(user, dict):
        return user.get("id")
    return getattr(user, "id", None)


def user_role(user: Any) -> str:
    if isinstance(user, dict):
        return str(user.get("role") or "user")
    return str(getattr(user, "role", "user") or "user")


def is_admin_user(user: Any) -> bool:
    return user_role(user) in ADMIN_ROLES


def require_admin(user: Any) -> None:
    if not is_admin_user(user):
        raise ToolPermissionError("没有权限查看该诊断对象。")


def require_owner_or_admin(user: Any, owner_id: Any) -> None:
    if is_admin_user(user):
        return
    if str(user_id(user)) != str(owner_id):
        raise ToolPermissionError("没有权限查看该运行记录。")


def isoformat(value: Any) -> Any:
    return value.isoformat() if hasattr(value, "isoformat") else value


def finding(severity: str, code: str, message: str) -> dict[str, Any]:
    return DiagnosticFinding(severity=severity, code=code, message=message).model_dump()


def recommendation(priority: str, action: str) -> dict[str, Any]:
    return DiagnosticRecommendation(priority=priority, action=action).model_dump()


def related_entity(entity_type: str, entity_id: Any, reason: str) -> dict[str, Any]:
    return RelatedEntity(type=entity_type, id=entity_id, reason=reason).model_dump()


def unique_related(entities: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[tuple[str, str]] = set()
    result: list[dict[str, Any]] = []
    for entity in entities:
        key = (str(entity.get("type")), str(entity.get("id")))
        if key in seen:
            continue
        seen.add(key)
        result.append(entity)
    return result


def tool_result(
    *,
    tool: str,
    target: dict[str, Any],
    facts: dict[str, Any] | None = None,
    findings: list[dict[str, Any]] | None = None,
    recommendations: list[dict[str, Any]] | None = None,
    related_entities: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    payload = ToolResultData(
        tool=tool,
        snapshot_at=snapshot_now(),
        target=target,
        facts=facts or {},
        findings=findings or [],
        recommendations=recommendations or [],
        related_entities=unique_related(related_entities or []),
        redaction_applied=True,
    ).model_dump()
    return redact_value(payload)


def permission_denied_result(tool: str, target: dict[str, Any], message: str) -> dict[str, Any]:
    return tool_result(
        tool=tool,
        target=target,
        findings=[finding("error", ToolPermissionError.code, message)],
        recommendations=[recommendation("P0", "请确认当前账号权限，或由管理员/data_admin 执行诊断。")],
    )


def structured_error_payload(record: Any, legacy_text: str | None = None) -> dict[str, Any] | None:
    structured = getattr(record, "structured_error", None)
    if structured:
        return {"source": "structured_error", "error": structured}
    if legacy_text:
        first_line = next((line.strip() for line in legacy_text.splitlines() if line.strip()), "")
        return {
            "source": "legacy_fallback",
            "error": {
                "message": first_line[:500],
            },
        }
    return None

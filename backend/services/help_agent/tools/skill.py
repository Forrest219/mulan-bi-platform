"""Skill diagnostic tool."""

from __future__ import annotations

from typing import Any

from services.skills.models import AgentSkill, AgentSkillVersion

from .base import finding, isoformat, permission_denied_result, recommendation, require_admin, tool_result


def diagnose_skill(db: Any, current_user: Any, skill_key: str) -> dict[str, Any]:
    target = {"type": "skill", "id": skill_key}
    try:
        require_admin(current_user)
    except PermissionError as exc:
        return permission_denied_result("diagnose_skill", target, str(exc))

    skill = db.query(AgentSkill).filter(AgentSkill.skill_key == skill_key).first()
    if not skill:
        return tool_result(
            tool="diagnose_skill",
            target=target,
            findings=[finding("error", "SKILL_NOT_FOUND", "没有找到该 skill 配置。")],
            recommendations=[recommendation("P1", "确认 skill_key 是否正确，或由管理员创建对应 skill。")],
        )

    active_version = (
        db.query(AgentSkillVersion)
        .filter(AgentSkillVersion.skill_id == getattr(skill, "id"), AgentSkillVersion.is_active.is_(True))
        .first()
    )
    versions = (
        db.query(AgentSkillVersion)
        .filter(AgentSkillVersion.skill_id == getattr(skill, "id"))
        .order_by(AgentSkillVersion.created_at.desc())
        .limit(10)
        .all()
    )
    findings: list[dict[str, Any]] = []
    recommendations: list[dict[str, Any]] = []
    if not getattr(skill, "is_enabled", False):
        findings.append(finding("error", "SKILL_DISABLED", "该 skill 当前未启用。"))
        recommendations.append(recommendation("P1", "建议由管理员确认后启用 skill 或切换到替代能力。"))
    if not active_version:
        findings.append(finding("error", "NO_ACTIVE_VERSION", "该 skill 没有活动版本。"))
        recommendations.append(recommendation("P1", "建议由管理员发布或激活一个 skill 版本。"))

    facts = {
        "skill": {
            "id": str(getattr(skill, "id")),
            "skill_key": getattr(skill, "skill_key", None),
            "name": getattr(skill, "name", None),
            "description": getattr(skill, "description", None),
            "category": getattr(skill, "category", None),
            "is_enabled": getattr(skill, "is_enabled", None),
            "created_by": getattr(skill, "created_by", None),
            "created_at": isoformat(getattr(skill, "created_at", None)),
            "updated_at": isoformat(getattr(skill, "updated_at", None)),
        },
        "active_version": {
            "id": str(getattr(active_version, "id")),
            "version_number": getattr(active_version, "version_number", None),
            "endpoint_type": getattr(active_version, "endpoint_type", None),
            "code_ref": getattr(active_version, "code_ref", None),
            "created_at": isoformat(getattr(active_version, "created_at", None)),
        }
        if active_version
        else None,
        "versions": [
            {
                "id": str(getattr(version, "id")),
                "version_number": getattr(version, "version_number", None),
                "is_active": getattr(version, "is_active", None),
                "endpoint_type": getattr(version, "endpoint_type", None),
                "code_ref": getattr(version, "code_ref", None),
                "created_at": isoformat(getattr(version, "created_at", None)),
            }
            for version in versions
        ],
    }
    return tool_result(
        tool="diagnose_skill",
        target=target,
        facts=facts,
        findings=findings,
        recommendations=recommendations,
    )


def list_enabled_skills(db: Any, current_user: Any, limit: int = 100) -> dict[str, Any]:
    target = {"type": "skill_inventory", "id": "enabled"}
    try:
        require_admin(current_user)
    except PermissionError as exc:
        return permission_denied_result("list_enabled_skills", target, str(exc))

    safe_limit = max(1, min(int(limit or 100), 100))
    skills = (
        db.query(AgentSkill)
        .filter(AgentSkill.is_enabled.is_(True))
        .order_by(AgentSkill.category.asc(), AgentSkill.skill_key.asc())
        .limit(safe_limit)
        .all()
    )

    items: list[dict[str, Any]] = []
    for skill in skills:
        active_version = (
            db.query(AgentSkillVersion)
            .filter(AgentSkillVersion.skill_id == getattr(skill, "id"), AgentSkillVersion.is_active.is_(True))
            .first()
        )
        items.append(
            {
                "id": str(getattr(skill, "id")),
                "skill_key": getattr(skill, "skill_key", None),
                "name": getattr(skill, "name", None),
                "description": getattr(skill, "description", None),
                "category": getattr(skill, "category", None),
                "is_enabled": getattr(skill, "is_enabled", None),
                "active_version": {
                    "id": str(getattr(active_version, "id")),
                    "version_number": getattr(active_version, "version_number", None),
                    "endpoint_type": getattr(active_version, "endpoint_type", None),
                    "code_ref": getattr(active_version, "code_ref", None),
                    "created_at": isoformat(getattr(active_version, "created_at", None)),
                }
                if active_version
                else None,
                "updated_at": isoformat(getattr(skill, "updated_at", None)),
            }
        )

    findings = []
    recommendations = []
    if not items:
        findings.append(finding("warning", "NO_ENABLED_SKILLS", "当前没有已启用的 skill。"))
        recommendations.append(recommendation("P1", "请到技能中心启用至少一个 skill，并确保存在 active version。"))

    return tool_result(
        tool="list_enabled_skills",
        target=target,
        facts={"skills": items, "total": len(items), "limit": safe_limit, "enabled_only": True},
        findings=findings,
        recommendations=recommendations,
    )

"""Lightweight page context hints for Help Agent planning."""

from __future__ import annotations

from typing import Any

from .base import related_entity, tool_result


def get_page_context_hint(path: str, page_context: dict[str, Any] | None = None) -> dict[str, Any]:
    page_context = page_context or {}
    normalized = path or "/"
    title = "Mulan BI Platform"
    available_entities: list[str] = []
    related: list[dict[str, Any]] = []

    if "agent-monitor" in normalized or page_context.get("run_id"):
        title = "Agent Monitor"
        available_entities.append("agent_run")
        if page_context.get("run_id"):
            related.append(related_entity("agent_run", page_context["run_id"], "page_context.run_id"))
    elif "/tasks" in normalized or page_context.get("task_run_id"):
        title = "Task Management"
        available_entities.append("task_run")
        if page_context.get("task_run_id"):
            related.append(related_entity("task_run", page_context["task_run_id"], "page_context.task_run_id"))
    elif "skills" in normalized or page_context.get("skill_key"):
        title = "Skills Center"
        available_entities.append("skill")
        if page_context.get("skill_key"):
            related.append(related_entity("skill", page_context["skill_key"], "page_context.skill_key"))
    elif "tableau" in normalized or page_context.get("connection_id"):
        title = "Tableau Connections"
        available_entities.append("connection")
        if page_context.get("connection_id"):
            related.append(related_entity("connection", page_context["connection_id"], "page_context.connection_id"))

    facts = {
        "path": normalized,
        "title": title,
        "available_entities": available_entities,
        "entry_point": page_context.get("entry_point"),
        "hint_strength": "strong" if page_context.get("entry_point") == "inline_panel" else "weak",
    }
    return tool_result(
        tool="get_page_context_hint",
        target={"type": "page", "id": normalized},
        facts=facts,
        related_entities=related,
    )


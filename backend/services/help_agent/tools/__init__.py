"""Read-only diagnostic tools for Help Agent P0."""

from __future__ import annotations

from typing import Any, Callable

from app.core.database import SessionLocal

from .agent_run import diagnose_agent_run, diagnose_recent_agent_failure
from .connection import diagnose_connection
from .page_context import get_page_context_hint
from .skill import diagnose_skill
from .task import diagnose_task_run


class HelpToolRegistry:
    """Execute Help Agent diagnostic tools with one short DB session per call."""

    def __init__(self, session_factory: Callable[[], Any] | None = None) -> None:
        self.session_factory = session_factory or SessionLocal

    async def execute(self, tool_name: str, params: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
        current_user = context.get("current_user") or {}
        if tool_name == "get_page_context_hint":
            return get_page_context_hint(params.get("path") or params.get("page_path") or "")

        session = self.session_factory()
        try:
            if tool_name == "diagnose_agent_run":
                return diagnose_agent_run(session, current_user, str(params.get("run_id") or context.get("target_id")))
            if tool_name == "diagnose_recent_agent_failure":
                return diagnose_recent_agent_failure(session, current_user, params.get("page_context"))
            if tool_name == "diagnose_task_run":
                return diagnose_task_run(session, current_user, int(params.get("task_run_id") or context.get("target_id")))
            if tool_name == "diagnose_connection":
                conn_id = params.get("connection_id") or params.get("tableau_connection_id") or context.get("target_id")
                return diagnose_connection(session, current_user, connection_id=int(conn_id))
            if tool_name == "diagnose_skill":
                return diagnose_skill(session, current_user, str(params.get("skill_key") or context.get("target_id")))
            raise ValueError(f"unknown help diagnostic tool: {tool_name}")
        finally:
            session.close()


__all__ = [
    "HelpToolRegistry",
    "diagnose_agent_run",
    "diagnose_recent_agent_failure",
    "diagnose_task_run",
    "diagnose_connection",
    "diagnose_skill",
    "get_page_context_hint",
]

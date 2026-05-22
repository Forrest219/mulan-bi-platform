"""Mulan built-in MCP tools.

Built-in tools are exposed through the MCP Host catalog and executed through
``MCPToolExecutor``. They are not private proxy branches.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping, MutableSequence
from dataclasses import dataclass
from typing import Any

from services.data_agent.tableau_mcp_response import TableauMcpResponseNormalizer

MULAN_LIST_TABLEAU_ASSETS_TOOL_NAME = "mulan-list-tableau-assets"
MULAN_BUILTIN_TOOL_NAMES = frozenset({MULAN_LIST_TABLEAU_ASSETS_TOOL_NAME})

_ASSET_TYPE_ALIASES = {
    "dashboard": "dashboard",
    "dashboards": "dashboard",
    "看板": "dashboard",
    "仪表板": "dashboard",
    "大屏": "dashboard",
    "workbook": "workbook",
    "workbooks": "workbook",
    "工作簿": "workbook",
    "view": "view",
    "views": "view",
    "视图": "view",
    "datasource": "datasource",
    "datasources": "datasource",
    "data_source": "datasource",
    "数据源": "datasource",
}
_DEFAULT_ASSET_TYPES = ("dashboard", "workbook", "view", "datasource")
_DEFAULT_LIMIT = 50
_MAX_LIMIT = 100
_NORMALIZER = TableauMcpResponseNormalizer()


TraceSink = MutableSequence[dict[str, Any]]


@dataclass(frozen=True)
class BuiltInToolExecution:
    """Result returned by a built-in MCP tool provider."""

    result: dict[str, Any]
    guardrail_decision: dict[str, Any]


class MulanBuiltInToolProvider:
    """Execute Mulan-owned MCP tools behind the unified executor."""

    def __init__(
        self,
        *,
        session_factory: Callable[[], Any] | None = None,
    ) -> None:
        self._session_factory = session_factory

    def has_tool(self, tool_name: str) -> bool:
        return str(tool_name or "").strip() in MULAN_BUILTIN_TOOL_NAMES

    def tool_definitions(self) -> list[dict[str, Any]]:
        return mulan_builtin_mcp_tools()

    def execute(
        self,
        tool_name: str,
        arguments: Mapping[str, Any],
        *,
        context: Any = None,
    ) -> BuiltInToolExecution:
        name = str(tool_name or "").strip()
        if name != MULAN_LIST_TABLEAU_ASSETS_TOOL_NAME:
            raise ValueError(f"Unknown Mulan built-in MCP tool: {name}")
        return self._list_tableau_assets(arguments, context=context)

    def _list_tableau_assets(self, arguments: Mapping[str, Any], *, context: Any = None) -> BuiltInToolExecution:
        connection_id = _coerce_int(arguments.get("connectionId") or arguments.get("connection_id"))
        if connection_id is None:
            connection_id = _coerce_int(_context_value(context, "connection_id"))
        if connection_id is None:
            return BuiltInToolExecution(
                result=_clarification_response(
                    message="请先选择一个 Tableau 连接或站点后再查看资产清单。",
                    reason="connection_required",
                ),
                guardrail_decision=_decision(
                    "clarify",
                    code="MULAN_ASSET_CONNECTION_REQUIRED",
                    message="Mulan asset inventory tool requires connection_id.",
                    connection_id=None,
                ),
            )

        user_id = _coerce_int(_context_value(context, "user_id"))
        user_role = str(_context_value(context, "user_role") or "").strip() or None
        asset_types = _normalize_asset_types(arguments)
        limit = _normalize_limit(arguments.get("limit"))
        query_text = str(arguments.get("query") or "").strip()

        try:
            session = self._session()
        except Exception as exc:
            return BuiltInToolExecution(
                result=_tool_unavailable_response(
                    code="MULAN_ASSET_CATALOG_UNAVAILABLE",
                    message="Tableau 资产目录暂不可用。",
                    user_hint="请稍后重试；如果持续失败，请联系管理员检查本地资产同步与数据库连接。",
                    detail={"error": str(exc), "connection_id": connection_id},
                ),
                guardrail_decision=_decision(
                    "reject",
                    code="MULAN_ASSET_CATALOG_UNAVAILABLE",
                    message="Asset catalog session could not be opened.",
                    connection_id=connection_id,
                ),
            )

        try:
            connection_decision = _verify_connection_access(
                session=session,
                connection_id=connection_id,
                user_id=user_id,
                user_role=user_role,
            )
            if connection_decision.get("decision") != "allow":
                return BuiltInToolExecution(
                    result=_tool_unavailable_response(
                        code=str(connection_decision.get("reject_code") or "MULAN_ASSET_CONNECTION_FORBIDDEN"),
                        message=str(connection_decision.get("message") or "当前用户无权访问该 Tableau 连接。"),
                        user_hint=str(connection_decision.get("user_hint") or "请切换到有权限的 Tableau 连接后再试。"),
                        detail={"connection_id": connection_id},
                    ),
                    guardrail_decision=connection_decision,
                )

            assets = _load_tableau_assets(
                session=session,
                connection_id=connection_id,
                asset_types=asset_types,
                query_text=query_text,
                limit=limit,
            )
            guardrail_decision = _decision(
                "allow",
                code=None,
                message="Mulan asset inventory request is scoped to an accessible Tableau connection.",
                connection_id=connection_id,
                args={
                    "connectionId": connection_id,
                    "assetTypes": list(asset_types),
                    "query": query_text or None,
                    "limit": limit,
                },
            )
            if not assets:
                return BuiltInToolExecution(
                    result=_asset_not_found_response(
                        query=query_text,
                        message="当前 Tableau 连接下未找到匹配的资产。",
                        connection_id=connection_id,
                    ),
                    guardrail_decision=guardrail_decision,
                )
            return BuiltInToolExecution(
                result=_asset_candidates_response(
                    assets=assets,
                    query=query_text,
                    connection_id=connection_id,
                    asset_types=asset_types,
                    limit=limit,
                ),
                guardrail_decision=guardrail_decision,
            )
        finally:
            close = getattr(session, "close", None)
            if callable(close):
                close()

    def _session(self) -> Any:
        if self._session_factory is not None:
            return self._session_factory()
        from app.core.database import SessionLocal

        return SessionLocal()


def mulan_builtin_mcp_tools() -> list[dict[str, Any]]:
    """Return MCP tools/list compatible definitions for Mulan built-ins."""
    return [
        {
            "name": MULAN_LIST_TABLEAU_ASSETS_TOOL_NAME,
            "description": (
                "List Tableau directory assets visible to the current user for the current connection. "
                "Use this only for asset inventory questions about dashboards, workbooks, views, or datasources. "
                "Do not use it to answer business metric questions."
            ),
            "inputSchema": mulan_list_tableau_assets_tool_schema(),
            "x-provider": "mulan_builtin",
        }
    ]


def mulan_list_tableau_assets_tool_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            "connectionId": {"type": "integer", "description": "Current Tableau connection id."},
            "assetTypes": {
                "type": "array",
                "items": {"type": "string", "enum": ["dashboard", "workbook", "view", "datasource"]},
                "description": "Optional Tableau asset type filter.",
            },
            "query": {"type": "string", "description": "Optional text search over asset name/project/workbook."},
            "limit": {"type": "integer", "minimum": 1, "maximum": _MAX_LIMIT},
        },
        "required": ["connectionId"],
        "additionalProperties": False,
    }


def _verify_connection_access(
    *,
    session: Any,
    connection_id: int,
    user_id: int | None,
    user_role: str | None,
) -> dict[str, Any]:
    from services.tableau.models import TableauConnection

    connection = session.query(TableauConnection).filter(TableauConnection.id == connection_id).first()
    if connection is None:
        return _decision(
            "reject",
            code="MULAN_ASSET_CONNECTION_NOT_FOUND",
            message="Tableau 连接不存在或不可用。",
            user_hint="请先选择一个可用的 Tableau 连接。",
            connection_id=connection_id,
        )
    if getattr(connection, "is_active", True) is False:
        return _decision(
            "reject",
            code="MULAN_ASSET_CONNECTION_INACTIVE",
            message="Tableau 连接已停用。",
            user_hint="请切换到启用中的 Tableau 连接后再试。",
            connection_id=connection_id,
        )
    if user_role == "admin":
        return _decision("allow", code=None, message="admin connection access allowed.", connection_id=connection_id)
    if user_id is not None and getattr(connection, "owner_id", None) == user_id:
        return _decision("allow", code=None, message="owner connection access allowed.", connection_id=connection_id)
    return _decision(
        "reject",
        code="MULAN_ASSET_CONNECTION_FORBIDDEN",
        message="当前用户无权访问该 Tableau 连接。",
        user_hint="请切换到有权限的 Tableau 连接后再试。",
        connection_id=connection_id,
    )


def _load_tableau_assets(
    *,
    session: Any,
    connection_id: int,
    asset_types: tuple[str, ...],
    query_text: str,
    limit: int,
) -> list[dict[str, Any]]:
    from sqlalchemy import or_
    from services.tableau.models import TableauAsset

    query = session.query(TableauAsset).filter(
        TableauAsset.connection_id == connection_id,
        TableauAsset.is_deleted == False,  # noqa: E712
    )
    if asset_types:
        query = query.filter(TableauAsset.asset_type.in_(list(asset_types)))
    if query_text:
        pattern = f"%{_escape_like(query_text)}%"
        query = query.filter(
            or_(
                TableauAsset.name.ilike(pattern, escape="\\"),
                TableauAsset.project_name.ilike(pattern, escape="\\"),
                TableauAsset.parent_workbook_name.ilike(pattern, escape="\\"),
            )
        )
    rows = (
        query.order_by(
            TableauAsset.updated_on_server.desc().nullslast(),
            TableauAsset.synced_at.desc().nullslast(),
            TableauAsset.id.asc(),
        )
        .limit(limit)
        .all()
    )
    return [_asset_payload(row) for row in rows]


def _asset_payload(row: Any) -> dict[str, Any]:
    return {
        "asset_id": getattr(row, "id", None),
        "id": getattr(row, "id", None),
        "connection_id": getattr(row, "connection_id", None),
        "tableau_id": getattr(row, "tableau_id", None),
        "luid": getattr(row, "tableau_id", None),
        "asset_type": getattr(row, "asset_type", None),
        "name": getattr(row, "name", None),
        "project_name": getattr(row, "project_name", None),
        "workbook_name": getattr(row, "parent_workbook_name", None),
        "parent_workbook_name": getattr(row, "parent_workbook_name", None),
        "description": getattr(row, "description", None),
        "owner_name": getattr(row, "owner_name", None),
        "tableau_url": getattr(row, "web_url", None) or getattr(row, "content_url", None),
        "web_url": getattr(row, "web_url", None),
        "content_url": getattr(row, "content_url", None),
        "view_count": getattr(row, "view_count", None),
        "synced_at": _serialize_datetime(getattr(row, "synced_at", None)),
        "updated_on_server": _serialize_datetime(getattr(row, "updated_on_server", None)),
    }


def _asset_candidates_response(
    *,
    assets: list[Mapping[str, Any]],
    query: str,
    connection_id: int,
    asset_types: tuple[str, ...],
    limit: int,
) -> dict[str, Any]:
    response = _NORMALIZER.asset_candidates(
        candidates=assets,
        query=query,
        source="tableau_asset_catalog",
        reason="asset_inventory",
        message="已读取当前 Tableau 连接下可见的资产清单。",
        chain_mode="mcp_proxy",
        candidate_limit=None,
        telemetry={"tool_provider": "mulan_builtin", "limit": limit},
    ).to_dict()
    response["response_data"]["connection_id"] = connection_id
    response["response_data"]["asset_types"] = list(asset_types)
    return response


def _asset_not_found_response(*, query: str, message: str, connection_id: int) -> dict[str, Any]:
    response = _NORMALIZER.asset_not_found(
        query=query,
        message=message,
        source="tableau_asset_catalog",
        chain_mode="mcp_proxy",
        telemetry={"tool_provider": "mulan_builtin"},
    ).to_dict()
    response["response_data"]["connection_id"] = connection_id
    return response


def _clarification_response(*, message: str, reason: str) -> dict[str, Any]:
    return {
        "response_type": "clarification",
        "response_data": {
            "source": "mulan_builtin_tool",
            "chain_mode": "mcp_proxy",
            "reason": reason,
            "message": message,
            "candidates": [],
        },
    }


def _tool_unavailable_response(
    *,
    code: str,
    message: str,
    user_hint: str,
    detail: Mapping[str, Any],
) -> dict[str, Any]:
    return _NORMALIZER.tool_unavailable(
        code=code,
        message=message,
        user_hint=user_hint,
        chain_mode="mcp_proxy",
        detail=detail,
        telemetry={"tool_provider": "mulan_builtin"},
    ).to_dict()


def _decision(
    decision: str,
    *,
    code: str | None,
    message: str,
    connection_id: int | None,
    user_hint: str = "",
    args: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "decision": decision,
        "args": dict(args or {}),
        "repairs": [],
        "reject_code": code,
        "message": message,
        "user_hint": user_hint,
        "tool_name": MULAN_LIST_TABLEAU_ASSETS_TOOL_NAME,
        "connection_id": connection_id,
        "tool_provider": "mulan_builtin",
    }


def _normalize_asset_types(arguments: Mapping[str, Any]) -> tuple[str, ...]:
    raw = arguments.get("assetTypes", arguments.get("asset_types", arguments.get("assetType", arguments.get("asset_type"))))
    if raw is None or raw == "":
        return _DEFAULT_ASSET_TYPES
    values = raw if isinstance(raw, list) else [raw]
    output: list[str] = []
    for value in values:
        normalized = _ASSET_TYPE_ALIASES.get(str(value or "").strip().casefold())
        if normalized and normalized not in output:
            output.append(normalized)
    return tuple(output or _DEFAULT_ASSET_TYPES)


def _normalize_limit(value: Any) -> int:
    try:
        limit = int(value)
    except (TypeError, ValueError):
        limit = _DEFAULT_LIMIT
    return max(1, min(limit, _MAX_LIMIT))


def _coerce_int(value: Any) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _context_value(context: Any, key: str) -> Any:
    if context is None:
        return None
    if isinstance(context, Mapping):
        return context.get(key)
    return getattr(context, key, None)


def _escape_like(value: str) -> str:
    return re.sub(r"([%_\\])", r"\\\1", value)


def _serialize_datetime(value: Any) -> Any:
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return value

"""Unified business guardrail for Tableau MCP tool calls."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from typing import Any

from services.data_agent.mcp_args_guardrail import (
    MCP_GET_DATASOURCE_METADATA_TOOL_NAME,
    MCP_LIST_DATASOURCES_TOOL_NAME,
    MCP_QUERY_DATASOURCE_TOOL_NAME,
    McpArgsGuardrailInput,
    McpArgsGuardrailResult,
    get_datasource_metadata_tool_schema,
    list_datasources_tool_schema,
    query_datasource_tool_schema,
    validate_mcp_args,
)
from services.data_agent.tableau_mcp_resolver import DatasourceCandidateResolver
from services.data_agent.tool_base import ToolContext

TABLEAU_MCP_ALLOWED_TOOLS = frozenset(
    {
        MCP_LIST_DATASOURCES_TOOL_NAME,
        MCP_GET_DATASOURCE_METADATA_TOOL_NAME,
        MCP_QUERY_DATASOURCE_TOOL_NAME,
    }
)


@dataclass(frozen=True)
class TableauMcpGuardrailRequest:
    """Business-level input contract for Tableau MCP guardrail validation."""

    question: str
    tool_name: str
    args: Mapping[str, Any]
    context: ToolContext | Mapping[str, Any] | None = None
    current_datasource: Mapping[str, Any] | None = None
    queryable_fields: Sequence[str] | None = None
    tool_schema: Mapping[str, Any] | None = None
    user_context: Mapping[str, Any] | None = None


@dataclass(frozen=True)
class TableauMcpGuardrailDecision:
    """Business-level guardrail decision."""

    decision: str
    args: dict[str, Any] | None
    repairs: list[Any]
    reject_code: str | None
    message: str
    user_hint: str
    tool_name: str
    connection_id: int | None = None
    datasource_luid: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "decision": self.decision,
            "args": self.args,
            "repairs": [repair.to_dict() if hasattr(repair, "to_dict") else asdict(repair) for repair in self.repairs],
            "reject_code": self.reject_code,
            "message": self.message,
            "user_hint": self.user_hint,
            "tool_name": self.tool_name,
            "connection_id": self.connection_id,
            "datasource_luid": self.datasource_luid,
        }


class TableauMcpGuardrailService:
    """Centralize Tableau MCP business checks before runtime execution."""

    def __init__(
        self,
        *,
        resolver: DatasourceCandidateResolver | None = None,
        allowed_tools: set[str] | frozenset[str] | None = None,
    ) -> None:
        self._resolver = resolver or DatasourceCandidateResolver()
        self._allowed_tools = frozenset(allowed_tools or TABLEAU_MCP_ALLOWED_TOOLS)

    def validate(self, request: TableauMcpGuardrailRequest) -> TableauMcpGuardrailDecision:
        """Validate a Tableau MCP tool call through one business entrypoint."""
        tool_name = str(request.tool_name or "").strip()
        if tool_name not in self._allowed_tools:
            return _reject(
                tool_name=tool_name,
                connection_id=None,
                datasource_luid=None,
                code="TABLEAU_MCP_TOOL_FORBIDDEN",
                message=f"不允许调用 Tableau MCP 工具：{tool_name or '<empty>'}。",
                user_hint="请使用受支持的 Tableau MCP 只读工具。",
            )
        if not isinstance(request.args, Mapping):
            return _reject(
                tool_name=tool_name,
                connection_id=None,
                datasource_luid=None,
                code="TABLEAU_MCP_ARGS_INVALID",
                message="Tableau MCP 参数必须是对象。",
                user_hint="请重新生成结构化工具参数后再试。",
            )

        args = dict(request.args)
        connection_id = _requested_connection_id(args)
        if connection_id is None:
            connection_id = _coerce_int(_mapping_value(request.current_datasource, "connection_id"))
        if connection_id is None:
            connection_id = _coerce_int(_context_value(request.context, "connection_id"))
        if connection_id is None:
            return _reject(
                tool_name=tool_name,
                connection_id=None,
                datasource_luid=None,
                code="TABLEAU_MCP_CONNECTION_REQUIRED",
                message="Tableau MCP 调用缺少 connection_id。",
                user_hint="请先选择一个可访问的 Tableau 连接。",
            )

        user_id = _coerce_int(_context_value(request.context, "user_id"))
        user_role = str(_context_value(request.context, "user_role") or "").strip() or None
        if not self._resolver.connection_is_accessible(connection_id, user_id=user_id, user_role=user_role):
            return _reject(
                tool_name=tool_name,
                connection_id=connection_id,
                datasource_luid=None,
                code="TABLEAU_MCP_CONNECTION_FORBIDDEN",
                message="当前用户无权访问该 Tableau 连接。",
                user_hint="请切换到有权限的 Tableau 连接后再试。",
            )

        datasource_luid = _requested_datasource_luid(args) or _current_datasource_luid(request.current_datasource)
        if tool_name in {MCP_QUERY_DATASOURCE_TOOL_NAME, MCP_GET_DATASOURCE_METADATA_TOOL_NAME}:
            if not datasource_luid:
                return _reject(
                    tool_name=tool_name,
                    connection_id=connection_id,
                    datasource_luid=None,
                    code="TABLEAU_MCP_DATASOURCE_REQUIRED",
                    message="Tableau MCP 调用缺少 datasource_luid。",
                    user_hint="请先选择一个当前连接下的数据源。",
                )
            if not self._resolver.datasource_belongs_to_connection(datasource_luid, connection_id):
                return _reject(
                    tool_name=tool_name,
                    connection_id=connection_id,
                    datasource_luid=datasource_luid,
                    code="TABLEAU_MCP_DATASOURCE_FORBIDDEN",
                    message="请求的数据源不属于当前 Tableau 连接。",
                    user_hint="请使用当前连接下的数据源重新查询。",
                )

        current_datasource = _current_datasource_context(request.current_datasource, connection_id, datasource_luid)
        user_context = _user_context(request.user_context, request.context, connection_id, datasource_luid)
        queryable_fields = list(request.queryable_fields or _queryable_fields_from_datasource(current_datasource))
        tool_schema = dict(request.tool_schema or _default_tool_schema(tool_name))
        args = _ensure_connection_arg(tool_name, args, connection_id, tool_schema)

        result = validate_mcp_args(
            McpArgsGuardrailInput(
                question=request.question,
                tool_name=tool_name,
                tool_schema=tool_schema,
                args=args,
                queryable_fields=queryable_fields,
                current_datasource=current_datasource,
                user_context=user_context,
            )
        )
        return _from_mcp_result(
            result,
            tool_name=tool_name,
            connection_id=connection_id,
            datasource_luid=datasource_luid,
        )


def _from_mcp_result(
    result: McpArgsGuardrailResult,
    *,
    tool_name: str,
    connection_id: int | None,
    datasource_luid: str | None,
) -> TableauMcpGuardrailDecision:
    return TableauMcpGuardrailDecision(
        decision=result.decision,
        args=result.args,
        repairs=list(result.repairs),
        reject_code=result.reject_code,
        message=result.message,
        user_hint=result.user_hint,
        tool_name=tool_name,
        connection_id=connection_id,
        datasource_luid=datasource_luid,
    )


def _reject(
    *,
    tool_name: str,
    connection_id: int | None,
    datasource_luid: str | None,
    code: str,
    message: str,
    user_hint: str,
) -> TableauMcpGuardrailDecision:
    return TableauMcpGuardrailDecision(
        decision="reject",
        args=None,
        repairs=[],
        reject_code=code,
        message=message,
        user_hint=user_hint,
        tool_name=tool_name,
        connection_id=connection_id,
        datasource_luid=datasource_luid,
    )


def _default_tool_schema(tool_name: str) -> dict[str, Any]:
    if tool_name == MCP_LIST_DATASOURCES_TOOL_NAME:
        return list_datasources_tool_schema()
    if tool_name == MCP_GET_DATASOURCE_METADATA_TOOL_NAME:
        return get_datasource_metadata_tool_schema()
    return query_datasource_tool_schema()


def _ensure_connection_arg(
    tool_name: str,
    args: dict[str, Any],
    connection_id: int,
    tool_schema: Mapping[str, Any],
) -> dict[str, Any]:
    properties = tool_schema.get("properties") if isinstance(tool_schema, Mapping) else None
    schema_properties = properties if isinstance(properties, Mapping) else {}
    allows_camel = "connectionId" in schema_properties
    allows_snake = "connection_id" in schema_properties
    safe_args = dict(args)

    if not allows_camel and not allows_snake:
        safe_args.pop("connectionId", None)
        safe_args.pop("connection_id", None)
        return safe_args

    if any(key in safe_args for key in ("connectionId", "connection_id")):
        return safe_args
    if tool_name in {MCP_LIST_DATASOURCES_TOOL_NAME, MCP_GET_DATASOURCE_METADATA_TOOL_NAME} and allows_camel:
        safe_args["connectionId"] = connection_id
    elif allows_snake:
        safe_args["connection_id"] = connection_id
    return safe_args


def _current_datasource_context(
    current_datasource: Mapping[str, Any] | None,
    connection_id: int,
    datasource_luid: str | None,
) -> dict[str, Any]:
    payload = dict(current_datasource or {})
    payload["connection_id"] = connection_id
    if datasource_luid:
        payload.setdefault("luid", datasource_luid)
        payload.setdefault("datasource_luid", datasource_luid)
    return payload


def _user_context(
    explicit: Mapping[str, Any] | None,
    context: ToolContext | Mapping[str, Any] | None,
    connection_id: int,
    datasource_luid: str | None,
) -> dict[str, Any]:
    payload = dict(explicit or {})
    payload.setdefault("connection_id", connection_id)
    payload.setdefault("accessible_connection_ids", [connection_id])
    if datasource_luid:
        payload.setdefault("accessible_datasource_luids", [datasource_luid])
    user_id = _context_value(context, "user_id")
    if user_id is not None:
        payload.setdefault("user_id", user_id)
    tenant_id = _context_value(context, "tenant_id")
    if tenant_id:
        payload.setdefault("tenant_id", tenant_id)
    return payload


def _queryable_fields_from_datasource(current_datasource: Mapping[str, Any]) -> list[str]:
    explicit = current_datasource.get("queryable_fields")
    if isinstance(explicit, Sequence) and not isinstance(explicit, (str, bytes)):
        return [str(item) for item in explicit if str(item or "").strip()]

    fields = current_datasource.get("fields") or current_datasource.get("metadata_fields") or []
    queryable: list[str] = []
    if not isinstance(fields, Sequence) or isinstance(fields, (str, bytes)):
        return queryable
    for item in fields:
        if isinstance(item, str) and item.strip():
            queryable.append(item)
            continue
        if not isinstance(item, Mapping):
            continue
        if item.get("mcp_queryable") is False:
            continue
        for key in ("fieldCaption", "field_caption", "caption", "name", "fieldName", "field_name"):
            value = str(item.get(key) or "").strip()
            if value:
                queryable.append(value)
                break
    return queryable


def _requested_connection_id(args: Mapping[str, Any]) -> int | None:
    for key in ("connectionId", "connection_id"):
        value = _coerce_int(args.get(key))
        if value is not None:
            return value
    return None


def _requested_datasource_luid(args: Mapping[str, Any]) -> str | None:
    for key in ("datasourceLuid", "datasource_luid", "datasourceId", "datasource_id"):
        value = str(args.get(key) or "").strip()
        if value:
            return value
    return None


def _current_datasource_luid(current_datasource: Mapping[str, Any] | None) -> str | None:
    if not current_datasource:
        return None
    for key in ("luid", "datasource_luid", "tableau_id", "id"):
        value = str(current_datasource.get(key) or "").strip()
        if value:
            return value
    return None


def _mapping_value(mapping: Mapping[str, Any] | None, key: str) -> Any:
    if not mapping:
        return None
    return mapping.get(key)


def _context_value(context: ToolContext | Mapping[str, Any] | None, key: str) -> Any:
    if context is None:
        return None
    if isinstance(context, Mapping):
        return context.get(key)
    return getattr(context, key, None)


def _coerce_int(value: Any) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None

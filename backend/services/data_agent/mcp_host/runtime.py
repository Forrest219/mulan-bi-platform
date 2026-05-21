from __future__ import annotations

import json
import os
from collections.abc import Mapping, MutableSequence
from copy import deepcopy
from dataclasses import dataclass
from typing import Any, Optional

from services.data_agent.tableau_mcp_cache import TableauMcpCacheFacade


TraceSink = MutableSequence[dict[str, Any]]
QUERY_DATASOURCE_TOOL = "query-datasource"
RESOURCE_CAP_MAX_ROWS = 1000
RESOURCE_CAP_MAX_BYTES = 5 * 1024 * 1024
RESOURCE_CAP_TIMEOUT_MS = 30000
_CATALOG_CACHE = TableauMcpCacheFacade()


class MCPHostRuntimeError(Exception):
    """Raised when the MCP Host runtime rejects a tool execution request."""

    def __init__(
        self,
        code: str,
        message: str,
        details: Optional[dict[str, Any]] = None,
    ) -> None:
        self.code = code
        self.message = message
        self.details = details or {}
        super().__init__(f"[{code}] {message}")


@dataclass(frozen=True)
class MCPToolDefinition:
    """One tool definition discovered from MCP tools/list."""

    name: str
    description: Optional[str]
    input_schema: dict[str, Any]
    raw: dict[str, Any]

    @classmethod
    def from_mcp_tool(cls, tool: Mapping[str, Any]) -> "MCPToolDefinition":
        name = str(tool.get("name") or "").strip()
        if not name:
            raise MCPHostRuntimeError(
                code="MCP_HOST_INVALID_CATALOG",
                message="MCP tools/list returned a tool without a name",
                details={"tool": _json_safe(dict(tool))},
            )

        raw = dict(tool)
        description = tool.get("description")
        input_schema = _input_schema_from_tool(tool)
        return cls(
            name=name,
            description=str(description) if description is not None else None,
            input_schema=input_schema,
            raw=raw,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "inputSchema": deepcopy(self.input_schema),
            "raw": deepcopy(self.raw),
        }


class MCPToolCatalog:
    """Catalog of tools discovered from MCP tools/list."""

    def __init__(self, tools: list[Mapping[str, Any]]) -> None:
        self._tools_by_name: dict[str, MCPToolDefinition] = {}
        for tool in tools:
            if not isinstance(tool, Mapping):
                raise MCPHostRuntimeError(
                    code="MCP_HOST_INVALID_CATALOG",
                    message="MCP tools/list returned a non-object tool entry",
                    details={"tool": _json_safe(tool)},
                )
            definition = MCPToolDefinition.from_mcp_tool(tool)
            self._tools_by_name.setdefault(definition.name, definition)

    @classmethod
    def discover(
        cls,
        client: Any,
        *,
        connection_id: Optional[int] = None,
        datasource_luid: Optional[str] = None,
        timeout: int = 30,
        jwt_token: Optional[str] = None,
        trace: Optional[TraceSink] = None,
    ) -> "MCPToolCatalog":
        tools = client.list_tools(
            timeout=timeout,
            connection_id=connection_id,
            datasource_luid=datasource_luid,
            jwt_token=jwt_token,
        )
        if not isinstance(tools, list):
            raise MCPHostRuntimeError(
                code="MCP_HOST_INVALID_CATALOG",
                message="MCP list_tools must return a list",
                details={"type": type(tools).__name__},
            )

        catalog = cls(tools)
        _record_trace(
            trace,
            "mcp_host.catalog",
            {
                "tool_count": len(catalog),
                "tool_names": catalog.tool_names(),
            },
        )
        return catalog

    def __len__(self) -> int:
        return len(self._tools_by_name)

    def __contains__(self, tool_name: object) -> bool:
        return isinstance(tool_name, str) and tool_name in self._tools_by_name

    def tool_names(self) -> list[str]:
        return list(self._tools_by_name.keys())

    def tools(self) -> list[MCPToolDefinition]:
        return list(self._tools_by_name.values())

    def as_mcp_tools(self) -> list[dict[str, Any]]:
        return [deepcopy(tool.raw) for tool in self._tools_by_name.values()]

    def get(self, tool_name: str) -> Optional[MCPToolDefinition]:
        return self._tools_by_name.get(tool_name)

    def require(self, tool_name: str) -> MCPToolDefinition:
        definition = self.get(tool_name)
        if definition is None:
            raise MCPHostRuntimeError(
                code="MCP_HOST_UNKNOWN_TOOL",
                message="MCP tool is not present in the discovered catalog",
                details={
                    "tool": tool_name,
                    "available_tools": self.tool_names(),
                },
            )
        return definition


class MCPToolExecutor:
    """Schema-constrained MCP tools/call executor."""

    def __init__(
        self,
        client: Any,
        catalog: MCPToolCatalog,
        *,
        connection_id: Optional[int] = None,
        datasource_luid: Optional[str] = None,
        timeout: int = 30,
        jwt_token: Optional[str] = None,
        trace: Optional[TraceSink] = None,
    ) -> None:
        self.client = client
        self.catalog = catalog
        self.connection_id = connection_id
        self.datasource_luid = datasource_luid
        self.timeout = timeout
        self.jwt_token = jwt_token
        self.trace = trace

    def execute(
        self,
        tool_name: str,
        arguments: Optional[dict[str, Any]] = None,
        *,
        timeout: Optional[int] = None,
        question: Optional[str] = None,
        context: Any = None,
        current_datasource: Optional[Mapping[str, Any]] = None,
        queryable_fields: Optional[list[Any]] = None,
        strict_connection_access: bool = False,
        execution_source: Optional[str] = None,
        compiler_status: Optional[str] = None,
        compiler_reason: Optional[str] = None,
        compiler_advisory: Optional[Mapping[str, Any]] = None,
    ) -> Any:
        name = str(tool_name or "").strip()
        definition = self.catalog.get(name)
        if definition is None:
            self._reject(
                code="MCP_HOST_UNKNOWN_TOOL",
                message="MCP tool is not present in the discovered catalog",
                tool_name=name,
                details={"available_tools": self.catalog.tool_names()},
            )

        if arguments is None:
            call_arguments: dict[str, Any] = {}
        elif isinstance(arguments, dict):
            call_arguments = dict(arguments)
        else:
            self._reject(
                code="MCP_HOST_INVALID_ARGUMENTS",
                message="MCP tool arguments must be a JSON object",
                tool_name=name,
                details={"argument_type": type(arguments).__name__},
            )

        missing = _missing_required_properties(
            definition.input_schema,
            call_arguments,
        )
        if missing:
            self._reject(
                code="MCP_HOST_MISSING_REQUIRED_ARGUMENTS",
                message="MCP tool arguments are missing required top-level properties",
                tool_name=name,
                details={"missing_required_properties": missing},
            )

        guardrail_decision = None
        if question is not None or context is not None or current_datasource is not None:
            guardrail_decision = self._validate_guardrail(
                question=question or "",
                tool_name=name,
                arguments=call_arguments,
                context=context,
                current_datasource=current_datasource,
                queryable_fields=queryable_fields,
                tool_schema=definition.input_schema,
                strict_connection_access=strict_connection_access,
            )
            _record_trace(
                self.trace,
                "mcp_host.guardrail",
                {
                    "tool": name,
                    "execution_source": execution_source,
                    "compiler_status": compiler_status,
                    "compiler_reason": compiler_reason,
                    "compiler_advisory": compiler_advisory or {},
                    "guardrail_decision": guardrail_decision,
                },
            )
            if guardrail_decision.get("decision") == "reject":
                self._reject(
                    code=str(guardrail_decision.get("reject_code") or "MCP_ARGS_REJECTED"),
                    message=str(guardrail_decision.get("message") or "MCP tool arguments rejected by guardrail"),
                    tool_name=name,
                    details={"guardrail_decision": guardrail_decision},
                )
            if isinstance(guardrail_decision.get("args"), Mapping):
                call_arguments = dict(guardrail_decision["args"])

        _record_trace(
            self.trace,
            "mcp_host.tool_call",
            {
                "tool": name,
                "arguments": call_arguments,
                "execution_source": execution_source,
                "compiler_status": compiler_status,
                "compiler_reason": compiler_reason,
                "compiler_advisory": compiler_advisory or {},
                "guardrail_decision": guardrail_decision,
            },
        )
        if name == QUERY_DATASOURCE_TOOL:
            call_arguments = _inject_resource_cap(call_arguments)
        try:
            effective_timeout = timeout if timeout is not None else self.timeout
            if name == QUERY_DATASOURCE_TOOL:
                effective_timeout = min(int(effective_timeout), max(1, RESOURCE_CAP_TIMEOUT_MS // 1000))
            result = self.client.call_tool(
                tool_name=name,
                arguments=call_arguments,
                timeout=effective_timeout,
                connection_id=self.connection_id,
                datasource_luid=self.datasource_luid,
                jwt_token=self.jwt_token,
            )
        except Exception as exc:
            _record_trace(
                self.trace,
                "mcp_host.tool_error",
                {
                    "tool": name,
                    "error_type": type(exc).__name__,
                    "message": str(exc),
                },
            )
            raise

        _record_trace(
            self.trace,
            "mcp_host.tool_result",
            {"tool": name, "result": result},
        )
        if name == QUERY_DATASOURCE_TOOL:
            result = _decorate_resource_cap_result(result, call_arguments)
        return result

    def _reject(
        self,
        *,
        code: str,
        message: str,
        tool_name: str,
        details: dict[str, Any],
    ) -> None:
        payload = {"tool": tool_name, "code": code, "message": message, **details}
        _record_trace(self.trace, "mcp_host.tool_rejected", payload)
        raise MCPHostRuntimeError(code=code, message=message, details=details)

    def _validate_guardrail(
        self,
        *,
        question: str,
        tool_name: str,
        arguments: Mapping[str, Any],
        context: Any,
        current_datasource: Optional[Mapping[str, Any]],
        queryable_fields: Optional[list[Any]],
        tool_schema: Mapping[str, Any],
        strict_connection_access: bool,
    ) -> dict[str, Any]:
        from services.data_agent.tableau_mcp_guardrail import (
            TableauMcpGuardrailRequest,
            TableauMcpGuardrailService,
        )
        from services.data_agent.tableau_mcp_resolver import DatasourceCandidateResolver

        def _access_checker(connection_id: int, user_id: int | None, user_role: str | None) -> bool:
            if not strict_connection_access:
                return True
            return _context_connection_id(context) == connection_id

        resolver = DatasourceCandidateResolver(
            connection_access_checker=_access_checker,
            datasource_connection_checker=lambda datasource_luid, connection_id: True,
        )
        service = TableauMcpGuardrailService(resolver=resolver)
        decision = service.validate(
            TableauMcpGuardrailRequest(
                question=question,
                tool_name=tool_name,
                args=arguments,
                context=context,
                current_datasource=current_datasource,
                queryable_fields=queryable_fields,
                tool_schema=tool_schema,
            )
        )
        return decision.to_dict()


class MCPHostRuntime:
    """Small runtime wrapper that caches a discovered catalog for one host session."""

    def __init__(
        self,
        client: Any,
        *,
        connection_id: Optional[int] = None,
        datasource_luid: Optional[str] = None,
        timeout: int = 30,
        jwt_token: Optional[str] = None,
        trace: Optional[TraceSink] = None,
    ) -> None:
        self.client = client
        self.connection_id = connection_id
        self.datasource_luid = datasource_luid
        self.timeout = timeout
        self.jwt_token = jwt_token
        self.trace_events: TraceSink = trace if trace is not None else []
        self.catalog: Optional[MCPToolCatalog] = None

    def load_catalog(self, *, force: bool = False) -> MCPToolCatalog:
        cache_enabled = _catalog_cache_enabled() and self.connection_id is not None
        gateway_version = _catalog_gateway_version()
        if not force and cache_enabled:
            cached = _CATALOG_CACHE.get_tools_catalog(
                connection_id=str(self.connection_id),
                gateway_version=gateway_version,
            )
            if cached.cache_hit and isinstance(cached.value, list):
                self.catalog = MCPToolCatalog(cached.value)
                _record_trace(
                    self.trace_events,
                    "mcp_host.catalog_cache",
                    {
                        "cache_hit": True,
                        "cache_key": cached.cache_key,
                        "source": cached.source,
                        "tool_count": len(self.catalog),
                    },
                )
                return self.catalog

        if self.catalog is None or force:
            self.catalog = MCPToolCatalog.discover(
                self.client,
                connection_id=self.connection_id,
                datasource_luid=self.datasource_luid,
                timeout=self.timeout,
                jwt_token=self.jwt_token,
                trace=self.trace_events,
            )
            if cache_enabled:
                cache_key = _CATALOG_CACHE.set_tools_catalog(
                    connection_id=str(self.connection_id),
                    gateway_version=gateway_version,
                    value=self.catalog.as_mcp_tools(),
                    ttl_seconds=_catalog_cache_ttl_seconds(),
                    source="mcp",
                )
                _record_trace(
                    self.trace_events,
                    "mcp_host.catalog_cache",
                    {
                        "cache_hit": False,
                        "cache_key": cache_key,
                        "source": "mcp",
                        "tool_count": len(self.catalog),
                    },
                )
        return self.catalog

    def executor(self) -> MCPToolExecutor:
        return MCPToolExecutor(
            self.client,
            self.load_catalog(),
            connection_id=self.connection_id,
            datasource_luid=self.datasource_luid,
            timeout=self.timeout,
            jwt_token=self.jwt_token,
            trace=self.trace_events,
        )

    def call_tool(
        self,
        tool_name: str,
        arguments: Optional[dict[str, Any]] = None,
        *,
        timeout: Optional[int] = None,
        question: Optional[str] = None,
        context: Any = None,
        current_datasource: Optional[Mapping[str, Any]] = None,
        queryable_fields: Optional[list[Any]] = None,
        strict_connection_access: bool = False,
        execution_source: Optional[str] = None,
        compiler_status: Optional[str] = None,
        compiler_reason: Optional[str] = None,
        compiler_advisory: Optional[Mapping[str, Any]] = None,
    ) -> Any:
        return self.executor().execute(
            tool_name,
            arguments,
            timeout=timeout,
            question=question,
            context=context,
            current_datasource=current_datasource,
            queryable_fields=queryable_fields,
            strict_connection_access=strict_connection_access,
            execution_source=execution_source,
            compiler_status=compiler_status,
            compiler_reason=compiler_reason,
            compiler_advisory=compiler_advisory,
        )


def _input_schema_from_tool(tool: Mapping[str, Any]) -> dict[str, Any]:
    schema = tool.get("inputSchema") or tool.get("input_schema") or {}
    return dict(schema) if isinstance(schema, Mapping) else {}


def reset_mcp_host_catalog_cache() -> None:
    """Clear process-local MCP Host catalog cache for tests and admin refresh."""
    _CATALOG_CACHE.cache.clear()


def _catalog_cache_enabled() -> bool:
    return str(os.getenv("TABLEAU_MCP_TOOLS_CACHE_ENABLED", "true")).strip().lower() not in {"0", "false", "no", "off"}


def _catalog_cache_ttl_seconds() -> int:
    try:
        return max(1, int(str(os.getenv("TABLEAU_MCP_TOOLS_CACHE_TTL_SECONDS", "600")).strip()))
    except (TypeError, ValueError):
        return 600


def _catalog_gateway_version() -> str:
    return str(os.getenv("TABLEAU_MCP_GATEWAY_VERSION", "default")).strip() or "default"


def _missing_required_properties(
    input_schema: Mapping[str, Any],
    arguments: Mapping[str, Any],
) -> list[str]:
    required = input_schema.get("required") if isinstance(input_schema, Mapping) else None
    if not isinstance(required, list):
        return []
    required_names = [str(item) for item in required if str(item)]
    return [name for name in required_names if name not in arguments]


def _context_connection_id(context: Any) -> int | None:
    value = context.get("connection_id") if isinstance(context, Mapping) else getattr(context, "connection_id", None)
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _record_trace(
    trace: Optional[TraceSink],
    event: str,
    payload: Mapping[str, Any],
) -> None:
    if trace is None:
        return
    record = {"event": event, "payload": _json_safe(dict(payload))}
    json.dumps(record, ensure_ascii=False)
    trace.append(record)


def _json_safe(value: Any) -> Any:
    try:
        return json.loads(json.dumps(value, ensure_ascii=False))
    except (TypeError, ValueError):
        try:
            return json.loads(json.dumps(value, ensure_ascii=False, default=str))
        except (TypeError, ValueError):
            return str(value)


def _inject_resource_cap(arguments: Mapping[str, Any]) -> dict[str, Any]:
    patched = dict(arguments)
    max_rows = int(patched.get("max_rows") or patched.get("limit") or RESOURCE_CAP_MAX_ROWS)
    patched["max_rows"] = min(max_rows, RESOURCE_CAP_MAX_ROWS)
    patched["limit"] = min(int(patched.get("limit") or patched["max_rows"]), patched["max_rows"])
    patched["max_bytes"] = int(patched.get("max_bytes") or RESOURCE_CAP_MAX_BYTES)
    timeout_ms = int(patched.get("timeout_ms") or RESOURCE_CAP_TIMEOUT_MS)
    patched["timeout_ms"] = min(timeout_ms, RESOURCE_CAP_TIMEOUT_MS)
    return patched


def _decorate_resource_cap_result(result: Any, arguments: Mapping[str, Any]) -> Any:
    if not isinstance(result, Mapping):
        return result
    payload = dict(result)
    rows = payload.get("rows")
    row_count = len(rows) if isinstance(rows, list) else None
    max_rows = int(arguments.get("max_rows") or arguments.get("limit") or RESOURCE_CAP_MAX_ROWS)
    truncated = bool(row_count is not None and row_count >= max_rows)
    metadata = dict(payload.get("metadata") or {})
    metadata["truncated_by_guardrail"] = truncated
    metadata["guardrail_resource_cap"] = {
        "max_rows": max_rows,
        "max_bytes": int(arguments.get("max_bytes") or RESOURCE_CAP_MAX_BYTES),
        "timeout_ms": int(arguments.get("timeout_ms") or RESOURCE_CAP_TIMEOUT_MS),
    }
    payload["metadata"] = metadata
    return payload

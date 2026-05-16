"""Model-native planner for the Mulan MCP Host route."""

from __future__ import annotations

import json
from collections.abc import Mapping
from collections.abc import Sequence
from dataclasses import asdict
from dataclasses import dataclass
from dataclasses import field
from dataclasses import is_dataclass
from typing import Any
from typing import Literal
from typing import Protocol


PlannerAction = Literal["tool_call", "final", "repair_unavailable"]

MCP_HOST_PLANNER_PURPOSE = "data_agent_mcp_host_planner"
MCP_HOST_PLANNER_TIMEOUT_SECONDS = 18
VALID_PLANNER_ACTIONS = frozenset({"tool_call", "final", "repair_unavailable"})

_QUERYSPEC_CONTAINER_KEYS = frozenset({"queryspec", "query_spec", "query_plan"})
_QUERYSPEC_STRUCTURAL_KEYS = frozenset(
    {
        "intent",
        "operator",
        "datasource",
        "metrics",
        "dimensions",
        "filters",
        "time",
        "sort",
        "answer_contract",
        "effective_operator",
        "source",
    }
)


class MCPHostPlannerError(ValueError):
    """Raised when planner output is not a valid MCP Host decision."""

    def __init__(self, code: str, message: str, *, detail: Mapping[str, Any] | None = None):
        self.code = code
        self.detail = dict(detail or {})
        super().__init__(message)


class PlannerLLM(Protocol):
    """Minimal async LLM protocol used by the MCP Host planner."""

    async def complete(
        self,
        *,
        prompt: str,
        system: str | None = None,
        timeout: int | None = None,
        purpose: str | None = None,
    ) -> Mapping[str, Any]:
        """Return an LLM completion payload containing content or an error."""


@dataclass(frozen=True)
class MCPHostPlannerInput:
    """All context the model may use to select the next MCP Host action."""

    original_question: str
    selected_datasource: Mapping[str, Any]
    mcp_tool_schemas: Any
    datasource_metadata: Any = None
    previous_response_data: Any = None
    repair_context: Any = None


@dataclass(frozen=True)
class MCPHostPlannerDecision:
    """Normalized planner decision returned to the route loop."""

    action: PlannerAction
    raw: dict[str, Any] = field(default_factory=dict)
    tool: str | None = None
    arguments: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        """Return the decision as the single JSON-object contract."""
        payload = dict(self.raw)
        payload["action"] = self.action
        if self.action == "tool_call":
            payload["tool"] = self.tool
            payload["arguments"] = dict(self.arguments or {})
            payload.pop("args", None)
        return payload


@dataclass(frozen=True)
class MCPToolCatalogView:
    """Read-only view over MCP tools/list schemas for planner validation."""

    tools: dict[str, dict[str, Any]]

    @classmethod
    def from_any(cls, source: Any) -> "MCPToolCatalogView":
        """Build a catalog view from MCP tools/list output or a catalog-like object."""
        if isinstance(source, cls):
            return source

        candidate = _unwrap_catalog_source(source)
        tools: dict[str, dict[str, Any]] = {}
        for fallback_name, schema in _iter_tool_schema_entries(candidate):
            schema_dict = _mapping_dict(schema)
            name = _tool_name(schema_dict, fallback_name=fallback_name)
            if not name:
                continue
            normalized = dict(schema_dict)
            normalized.setdefault("name", name)
            tools[name] = normalized
        return cls(tools=tools)

    @property
    def names(self) -> frozenset[str]:
        """Return available tool names."""
        return frozenset(self.tools)

    def has_tool(self, tool_name: str) -> bool:
        """Return whether a tool exists in the catalog."""
        return tool_name in self.tools

    def prompt_payload(self) -> list[dict[str, Any]]:
        """Return serializable schemas for prompt context."""
        return [_json_safe(schema) for schema in self.tools.values()]


class MCPHostPlanner:
    """LLM-backed planner that emits direct MCP Host actions."""

    def __init__(
        self,
        llm_service: PlannerLLM | None = None,
        *,
        timeout_seconds: int = MCP_HOST_PLANNER_TIMEOUT_SECONDS,
        purpose: str = MCP_HOST_PLANNER_PURPOSE,
    ):
        self._llm_service = llm_service
        self._timeout_seconds = timeout_seconds
        self._purpose = purpose

    async def plan(self, request: MCPHostPlannerInput) -> MCPHostPlannerDecision:
        """Ask the model for the next MCP Host planner decision."""
        llm = self._llm_service
        if llm is None:
            from services.llm.service import LLMService

            llm = LLMService()

        messages = build_mcp_host_planner_messages(request)
        result = await llm.complete(
            prompt=messages[-1]["content"],
            system=messages[0]["content"],
            timeout=self._timeout_seconds,
            purpose=self._purpose,
        )
        if "content" not in result:
            raise MCPHostPlannerError(
                "PLANNER_LLM_FAILED",
                str(result.get("error") or "MCP Host planner LLM returned no content."),
                detail={"llm_result": _json_safe(result)},
            )

        return parse_mcp_host_planner_output(
            str(result.get("content") or ""),
            request.mcp_tool_schemas,
        )


def build_mcp_host_planner_messages(request: MCPHostPlannerInput) -> list[dict[str, str]]:
    """Build model messages for the MCP Host planner."""
    catalog = MCPToolCatalogView.from_any(request.mcp_tool_schemas)
    user_payload = {
        "original_question": request.original_question,
        "selected_datasource": _json_safe(request.selected_datasource),
        "mcp_tool_schemas": catalog.prompt_payload(),
        "datasource_metadata": _json_safe(request.datasource_metadata),
        "previous_response_data": _json_safe(request.previous_response_data),
        "repair_context": _json_safe(request.repair_context),
    }
    return [
        {"role": "system", "content": _system_prompt()},
        {"role": "user", "content": json.dumps(user_payload, ensure_ascii=False, indent=2, sort_keys=True)},
    ]


def parse_mcp_host_planner_output(content: str, catalog_source: Any) -> MCPHostPlannerDecision:
    """Parse and validate one model-emitted MCP Host planner JSON object."""
    catalog = MCPToolCatalogView.from_any(catalog_source)
    raw = _extract_single_json_object(content)

    if _contains_queryspec_shape(raw):
        raise MCPHostPlannerError(
            "PLANNER_QUERYSPEC_FORBIDDEN",
            "MCP Host planner output must not contain a QuerySpec-shaped object.",
        )

    action = raw.get("action")
    if action not in VALID_PLANNER_ACTIONS:
        raise MCPHostPlannerError(
            "PLANNER_ACTION_INVALID",
            "MCP Host planner output action must be tool_call, final, or repair_unavailable.",
            detail={"action": action},
        )

    if action == "tool_call":
        return _validate_tool_call(raw, catalog)
    if action == "final":
        return _validate_terminal_action(raw, "final")
    return _validate_terminal_action(raw, "repair_unavailable")


def _system_prompt() -> str:
    return (
        "You are Mulan's MCP Host planner. Select the next action using only the selected datasource, "
        "the MCP tools/list schemas, datasource metadata, previous response_data, and any repair context. "
        "Return exactly one JSON object as the final answer. Valid actions are: "
        "{\"action\":\"tool_call\",\"tool\":\"<tool name from catalog>\",\"arguments\":{...}}, "
        "{\"action\":\"final\",...}, or {\"action\":\"repair_unavailable\",...}. "
        "Do not output QuerySpec, query plans, benchmark mappings, or any external planning-skill result. "
        "Do not infer a datasource from the question when selected_datasource is provided. "
        "For tool_call, generate arguments directly against the chosen MCP tool input schema. "
        "Do not invent SET filter values unless the user explicitly stated those values. "
        "For follow-up drilldowns or breakdowns, preserve previous non-metric grouping fields unless the user asks to remove them."
    )


def _validate_tool_call(raw: Mapping[str, Any], catalog: MCPToolCatalogView) -> MCPHostPlannerDecision:
    tool = raw.get("tool")
    if not isinstance(tool, str) or not tool.strip():
        raise MCPHostPlannerError(
            "PLANNER_TOOL_REQUIRED",
            "tool_call action requires a non-empty tool string.",
        )
    tool = tool.strip()
    if not catalog.has_tool(tool):
        raise MCPHostPlannerError(
            "PLANNER_TOOL_UNKNOWN",
            "tool_call.tool must exist in the MCP tool catalog.",
            detail={"tool": tool, "available_tools": sorted(catalog.names)},
        )

    arguments = raw.get("arguments", raw.get("args", {}))
    if not isinstance(arguments, Mapping):
        raise MCPHostPlannerError(
            "PLANNER_ARGUMENTS_INVALID",
            "tool_call.arguments must be a JSON object.",
            detail={"tool": tool},
        )

    return MCPHostPlannerDecision(
        action="tool_call",
        tool=tool,
        arguments=dict(arguments),
        raw=dict(raw),
    )


def _validate_terminal_action(raw: Mapping[str, Any], action: PlannerAction) -> MCPHostPlannerDecision:
    if raw.get("tool") is not None or raw.get("arguments") is not None or raw.get("args") is not None:
        raise MCPHostPlannerError(
            "PLANNER_TERMINAL_ACTION_INVALID",
            f"{action} action must not include a tool call.",
        )
    return MCPHostPlannerDecision(action=action, raw=dict(raw))


def _extract_single_json_object(content: str) -> dict[str, Any]:
    text = _strip_outer_json_fence(content.strip())
    decoder = json.JSONDecoder()
    objects: list[dict[str, Any]] = []
    index = 0
    while index < len(text):
        start = text.find("{", index)
        if start < 0:
            break
        try:
            value, offset = decoder.raw_decode(text[start:])
        except json.JSONDecodeError:
            index = start + 1
            continue
        if isinstance(value, Mapping):
            objects.append(dict(value))
            index = start + offset
            continue
        index = start + 1

    if not objects:
        raise MCPHostPlannerError(
            "PLANNER_JSON_NOT_FOUND",
            "MCP Host planner output did not contain a valid JSON object.",
            detail={"raw": content[:1000]},
        )
    if len(objects) > 1:
        raise MCPHostPlannerError(
            "PLANNER_JSON_MULTIPLE_OBJECTS",
            "MCP Host planner output must contain exactly one JSON object.",
        )
    return objects[0]


def _strip_outer_json_fence(text: str) -> str:
    if not text.startswith("```"):
        return text
    lines = text.splitlines()
    if len(lines) >= 2 and lines[-1].strip() == "```":
        return "\n".join(lines[1:-1]).strip()
    return text


def _contains_queryspec_shape(value: Any) -> bool:
    if isinstance(value, Mapping):
        keys = {str(key) for key in value}
        normalized_keys = {key.lower() for key in keys}
        if normalized_keys & _QUERYSPEC_CONTAINER_KEYS:
            return True
        if _is_queryspec_shaped(normalized_keys):
            return True
        return any(_contains_queryspec_shape(item) for item in value.values())
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return any(_contains_queryspec_shape(item) for item in value)
    return False


def _is_queryspec_shaped(keys: set[str]) -> bool:
    structural_count = len(keys & _QUERYSPEC_STRUCTURAL_KEYS)
    if {"metrics", "dimensions"}.issubset(keys) and keys & {"intent", "operator", "datasource", "answer_contract"}:
        return True
    if {"intent", "operator", "filters"}.issubset(keys) and keys & {"metrics", "dimensions", "time", "sort"}:
        return True
    return structural_count >= 6 and bool(keys & {"intent", "operator", "answer_contract"})


def _unwrap_catalog_source(source: Any) -> Any:
    if source is None:
        return {}
    for attr_name in ("as_mcp_tools", "tool_schemas", "schemas", "tools", "entries"):
        if hasattr(source, attr_name):
            value = getattr(source, attr_name)
            return value() if callable(value) else value
    return source


def _iter_tool_schema_entries(source: Any) -> list[tuple[str | None, Any]]:
    if isinstance(source, Mapping):
        if _tool_name(source):
            return [(None, source)]
        tools_value = source.get("tools")
        if _is_sequence(tools_value):
            return _iter_tool_schema_entries(tools_value)
        entries: list[tuple[str | None, Any]] = []
        for name, schema in source.items():
            if isinstance(schema, Mapping) or is_dataclass(schema):
                entries.append((str(name), schema))
        return entries

    if _is_sequence(source):
        return [(None, item) for item in source]

    if is_dataclass(source):
        return _iter_tool_schema_entries(asdict(source))

    return []


def _tool_name(schema: Any, *, fallback_name: str | None = None) -> str | None:
    if not isinstance(schema, Mapping):
        return fallback_name
    for key in ("name", "tool"):
        value = schema.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    function = schema.get("function")
    if isinstance(function, Mapping):
        value = function.get("name")
        if isinstance(value, str) and value.strip():
            return value.strip()
    return fallback_name.strip() if isinstance(fallback_name, str) and fallback_name.strip() else None


def _mapping_dict(value: Any) -> dict[str, Any]:
    if isinstance(value, Mapping):
        return dict(value)
    to_dict = getattr(value, "to_dict", None)
    if callable(to_dict):
        result = to_dict()
        if isinstance(result, Mapping):
            return dict(result)
    if is_dataclass(value):
        return asdict(value)
    return {}


def _json_safe(value: Any) -> Any:
    if is_dataclass(value):
        return _json_safe(asdict(value))
    if isinstance(value, Mapping):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [_json_safe(item) for item in value]
    try:
        json.dumps(value)
    except TypeError:
        return str(value)
    return value


def _is_sequence(value: Any) -> bool:
    return isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray))

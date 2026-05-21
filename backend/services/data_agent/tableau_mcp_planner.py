"""LLM planner for Tableau MCP controlled-chain tool plans."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass, field, is_dataclass
from typing import Any, Literal, Protocol

from services.data_agent.mcp_args_guardrail import (
    MCP_GET_DATASOURCE_METADATA_TOOL_NAME,
    MCP_LIST_DATASOURCES_TOOL_NAME,
    MCP_QUERY_DATASOURCE_TOOL_NAME,
    get_datasource_metadata_tool_schema,
    list_datasources_tool_schema,
    query_datasource_tool_schema,
)
from services.data_agent.tableau_mcp_guardrail import TABLEAU_MCP_ALLOWED_TOOLS
from services.llm.service import LLMService

TABLEAU_MCP_LLM_PLANNER_PURPOSE = "data_agent_mcp_proxy_args"
TABLEAU_MCP_LLM_PLANNER_TIMEOUT_SECONDS = 18
DEFAULT_MIN_CONFIDENCE = 0.65

PlannerStatus = Literal["planned", "clarification", "planner_timeout", "planner_failed", "invalid_output"]

_REQUIRED_PLAN_KEYS = frozenset({"tool_name", "args", "reason", "confidence", "needs_clarification"})
_OPTIONAL_PLAN_KEYS = frozenset({"clarification"})
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


class TableauMcpPlannerError(ValueError):
    """Raised when model output cannot be accepted as a Tableau MCP plan."""

    def __init__(self, code: str, message: str, *, detail: Mapping[str, Any] | None = None) -> None:
        """Create a planner validation error with a stable machine code."""
        self.code = code
        self.detail = dict(detail or {})
        super().__init__(message)


class TableauMcpPlannerLLM(Protocol):
    """Minimal async LLM protocol used by the Tableau MCP planner."""

    async def complete(
        self,
        *,
        prompt: str,
        system: str | None = None,
        timeout: int | None = None,
        purpose: str | None = None,
    ) -> Mapping[str, Any]:
        """Return an LLM completion payload containing content or error details."""


@dataclass(frozen=True)
class TableauMcpPlannerRequest:
    """Input context for planning one Tableau MCP tool call."""

    question: str
    datasource: Mapping[str, Any] | None = None
    metadata_fields: Sequence[Mapping[str, Any]] | None = None
    queryable_fields: Sequence[Any] | None = None
    context: Mapping[str, Any] | Any | None = None
    analysis_context: Mapping[str, Any] | None = None
    compiler_reason: str | None = None
    compiler_advisory: Mapping[str, Any] | None = None


@dataclass(frozen=True)
class TableauMcpToolPlan:
    """Structured Tableau MCP plan emitted by the LLM planner.

    `planned` results are candidates only. Callers must still run
    TableauMcpGuardrailService before executing any MCP tool.
    """

    tool_name: str | None
    args: dict[str, Any]
    reason: str
    confidence: float
    needs_clarification: bool
    clarification: Any
    status: PlannerStatus = "planned"
    error_code: str | None = None
    raw: dict[str, Any] = field(default_factory=dict)

    @property
    def is_executable(self) -> bool:
        """Return whether this plan may proceed to guardrail validation."""
        return self.status == "planned" and not self.needs_clarification and bool(self.tool_name)

    def to_dict(self) -> dict[str, Any]:
        """Return the plan as a JSON-serializable contract."""
        return {
            "tool_name": self.tool_name,
            "args": dict(self.args),
            "reason": self.reason,
            "confidence": self.confidence,
            "needs_clarification": self.needs_clarification,
            "clarification": _json_safe(self.clarification),
            "status": self.status,
            "error_code": self.error_code,
            "raw": _json_safe(self.raw),
        }


class TableauMcpLlmPlanner:
    """Generate structured Tableau MCP tool plans without calling MCP."""

    def __init__(
        self,
        llm_service: TableauMcpPlannerLLM | None = None,
        *,
        timeout_seconds: int = TABLEAU_MCP_LLM_PLANNER_TIMEOUT_SECONDS,
        purpose: str = TABLEAU_MCP_LLM_PLANNER_PURPOSE,
        min_confidence: float = DEFAULT_MIN_CONFIDENCE,
        allowed_tools: set[str] | frozenset[str] | None = None,
    ) -> None:
        """Create an LLM-backed planner with injectable runtime dependencies."""
        self._llm_service = llm_service
        self._timeout_seconds = timeout_seconds
        self._purpose = purpose
        self._min_confidence = min(1.0, max(0.0, float(min_confidence)))
        self._allowed_tools = frozenset(allowed_tools or TABLEAU_MCP_ALLOWED_TOOLS)

    async def plan(self, request: TableauMcpPlannerRequest) -> TableauMcpToolPlan:
        """Ask the model for a Tableau MCP tool plan and normalize failures."""
        llm = self._llm_service
        if llm is None:
            llm = LLMService()

        messages = build_tableau_mcp_planner_messages(request, allowed_tools=self._allowed_tools)
        try:
            result = await asyncio.wait_for(
                llm.complete(
                    prompt=messages[-1]["content"],
                    system=messages[0]["content"],
                    timeout=self._timeout_seconds,
                    purpose=self._purpose,
                ),
                timeout=self._timeout_seconds,
            )
        except TimeoutError as exc:
            return _failure_plan(
                status="planner_timeout",
                code="TABLEAU_MCP_PLANNER_TIMEOUT",
                reason="Tableau MCP planner LLM timed out.",
                detail={"error": str(exc), "timeout_seconds": self._timeout_seconds},
            )
        except Exception as exc:
            return _failure_plan(
                status="planner_failed",
                code="TABLEAU_MCP_PLANNER_FAILED",
                reason="Tableau MCP planner LLM failed.",
                detail={"error": str(exc), "error_type": exc.__class__.__name__},
            )

        if "content" not in result:
            error_code = str(result.get("error_code") or "")
            status: PlannerStatus = "planner_timeout" if "TIMEOUT" in error_code.upper() else "planner_failed"
            return _failure_plan(
                status=status,
                code="TABLEAU_MCP_PLANNER_TIMEOUT" if status == "planner_timeout" else "TABLEAU_MCP_PLANNER_FAILED",
                reason=str(result.get("error") or "Tableau MCP planner LLM returned no content."),
                detail={"llm_result": _json_safe(result)},
            )

        try:
            return parse_tableau_mcp_planner_output(
                str(result.get("content") or ""),
                allowed_tools=self._allowed_tools,
                min_confidence=self._min_confidence,
            )
        except TableauMcpPlannerError as exc:
            return _failure_plan(
                status="invalid_output",
                code=exc.code,
                reason=str(exc),
                detail=exc.detail,
            )


def build_tableau_mcp_planner_messages(
    request: TableauMcpPlannerRequest,
    *,
    allowed_tools: set[str] | frozenset[str] | None = None,
) -> list[dict[str, str]]:
    """Build deterministic system/user messages for Tableau MCP planning."""
    tools = sorted(allowed_tools or TABLEAU_MCP_ALLOWED_TOOLS)
    user_payload = {
        "question": request.question,
        "selected_datasource": _json_safe(request.datasource or {}),
        "metadata_fields": _json_safe(list(request.metadata_fields or [])[:80]),
        "queryable_fields": _json_safe(list(request.queryable_fields or [])[:120]),
        "context": _context_payload(request.context),
        "analysis_context": _json_safe(request.analysis_context or {}),
        "compiler_reason": request.compiler_reason,
        "compiler_advisory": _json_safe(request.compiler_advisory or {}),
        "compiler_advisory_contract": (
            "Compiler advisory is a non-authoritative hint only. "
            "Do not treat advisory candidates as facts; use selected datasource metadata/queryable_fields "
            "and produce args that still pass tool schema and guardrail validation."
        ),
        "allowed_tools": tools,
        "tool_schemas": _tool_schemas_for_prompt(tools),
        "output_contract": {
            "tool_name": "one of allowed_tools, or null when clarification is needed",
            "args": "JSON object for the MCP tool; empty object when not executable",
            "reason": "short reason for the selected tool or clarification",
            "confidence": "number from 0 to 1",
            "needs_clarification": "boolean",
            "clarification": "optional when needs_clarification=false; required non-empty object/string when true",
        },
    }
    return [
        {"role": "system", "content": _system_prompt()},
        {"role": "user", "content": json.dumps(user_payload, ensure_ascii=False, indent=2, sort_keys=True)},
    ]


def parse_tableau_mcp_planner_output(
    content: str,
    *,
    allowed_tools: set[str] | frozenset[str] | None = None,
    min_confidence: float = DEFAULT_MIN_CONFIDENCE,
) -> TableauMcpToolPlan:
    """Parse and validate one LLM-emitted Tableau MCP plan object."""
    allowed = frozenset(allowed_tools or TABLEAU_MCP_ALLOWED_TOOLS)
    raw = _extract_single_json_object(content)

    missing = sorted(_REQUIRED_PLAN_KEYS - set(raw))
    missing_optional = sorted(_OPTIONAL_PLAN_KEYS - set(raw))
    raw_with_contract_detail = _raw_with_contract_detail(raw, missing_optional=missing_optional)
    if missing:
        raise TableauMcpPlannerError(
            "TABLEAU_MCP_PLANNER_CONTRACT_MISSING",
            "Planner output is missing required plan fields.",
            detail={"missing": missing, "missing_optional": missing_optional, "raw": _json_safe(raw)},
        )
    if _contains_queryspec_shape(raw):
        raise TableauMcpPlannerError(
            "TABLEAU_MCP_PLANNER_QUERYSPEC_FORBIDDEN",
            "Planner output must be an MCP tool plan, not QuerySpec.",
            detail={"raw": _json_safe(raw_with_contract_detail)},
        )

    confidence = _coerce_confidence(raw.get("confidence"))
    needs_clarification = raw.get("needs_clarification")
    if not isinstance(needs_clarification, bool):
        raise TableauMcpPlannerError(
            "TABLEAU_MCP_PLANNER_CLARIFICATION_FLAG_INVALID",
            "Planner output needs_clarification must be boolean.",
            detail={"needs_clarification": needs_clarification},
        )

    args = raw.get("args")
    if not isinstance(args, Mapping):
        raise TableauMcpPlannerError(
            "TABLEAU_MCP_PLANNER_ARGS_INVALID",
            "Planner output args must be a JSON object.",
            detail={"args_type": type(args).__name__},
        )

    tool_name = _normalize_tool_name(raw.get("tool_name"))
    if tool_name is not None and tool_name not in allowed:
        raise TableauMcpPlannerError(
            "TABLEAU_MCP_PLANNER_TOOL_FORBIDDEN",
            "Planner selected a tool outside the Tableau MCP allowlist.",
            detail={"tool_name": tool_name, "allowed_tools": sorted(allowed)},
        )

    reason = str(raw.get("reason") or "").strip()
    if not reason:
        raise TableauMcpPlannerError(
            "TABLEAU_MCP_PLANNER_REASON_REQUIRED",
            "Planner output reason must be non-empty.",
        )

    if needs_clarification:
        clarification = raw.get("clarification")
        if not _has_non_empty_clarification(clarification):
            raise TableauMcpPlannerError(
                "TABLEAU_MCP_PLANNER_CLARIFICATION_REQUIRED",
                "Planner output clarification must be non-empty when needs_clarification is true.",
                detail={"missing_optional": missing_optional, "raw": _json_safe(raw_with_contract_detail)},
            )
        return TableauMcpToolPlan(
            tool_name=None,
            args={},
            reason=reason,
            confidence=confidence,
            needs_clarification=True,
            clarification=_clarification_payload(clarification, reason=reason),
            status="clarification",
            raw=raw_with_contract_detail,
        )

    if confidence < min_confidence:
        return TableauMcpToolPlan(
            tool_name=None,
            args={},
            reason="planner_low_confidence",
            confidence=confidence,
            needs_clarification=True,
            clarification=_clarification_payload(
                raw.get("clarification"),
                reason="planner_low_confidence",
                fallback_message="我还不能确定应该如何查询这个 Tableau 数据源，请补充字段、筛选条件或分析口径。",
            ),
            status="clarification",
            error_code="TABLEAU_MCP_PLANNER_LOW_CONFIDENCE",
            raw=raw_with_contract_detail,
        )

    if not tool_name:
        raise TableauMcpPlannerError(
            "TABLEAU_MCP_PLANNER_TOOL_REQUIRED",
            "Executable planner output requires an allowlisted tool_name.",
        )
    _validate_executable_args(tool_name, args)

    return TableauMcpToolPlan(
        tool_name=tool_name,
        args=dict(args),
        reason=reason,
        confidence=confidence,
        needs_clarification=False,
        clarification=None,
        status="planned",
        raw=raw_with_contract_detail,
    )


def _system_prompt() -> str:
    return (
        "You are Mulan's Tableau MCP planner. Return exactly one JSON object and nothing else. "
        "Your job is only to choose a Tableau MCP read-only tool and produce its JSON arguments. "
        "Never call MCP, never return QuerySpec, SQL, VizQL wrappers, code, markdown, or legacy query plans. "
        "Valid tools are list-datasources, get-datasource-metadata, and query-datasource. "
        "For query-datasource, use selected_datasource.datasource_luid or selected_datasource.luid as datasourceLuid. "
        "If the user intent, datasource, fields, filters, or metric definitions are ambiguous, set needs_clarification=true. "
        "Compiler advisory may appear in the user payload; it is only a hint, not a fact source, and does not override "
        "selected datasource metadata, queryable fields, tool schemas, or guardrails. "
        "If confidence is below 0.65, ask for clarification instead of guessing."
    )


def _tool_schemas_for_prompt(tool_names: Sequence[str]) -> dict[str, Any]:
    schemas = {
        MCP_LIST_DATASOURCES_TOOL_NAME: list_datasources_tool_schema(),
        MCP_GET_DATASOURCE_METADATA_TOOL_NAME: get_datasource_metadata_tool_schema(),
        MCP_QUERY_DATASOURCE_TOOL_NAME: query_datasource_tool_schema(),
    }
    return {tool: _json_safe(schemas[tool]) for tool in tool_names if tool in schemas}


def _failure_plan(
    *,
    status: PlannerStatus,
    code: str,
    reason: str,
    detail: Mapping[str, Any] | None = None,
) -> TableauMcpToolPlan:
    return TableauMcpToolPlan(
        tool_name=None,
        args={},
        reason=reason,
        confidence=0.0,
        needs_clarification=False,
        clarification=None,
        status=status,
        error_code=code,
        raw={"detail": _json_safe(dict(detail or {}))},
    )


def _extract_single_json_object(content: str) -> dict[str, Any]:
    text = _strip_outer_json_fence(str(content or "").strip())
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
        raise TableauMcpPlannerError(
            "TABLEAU_MCP_PLANNER_JSON_NOT_FOUND",
            "Planner output did not contain a valid JSON object.",
            detail={"raw": content[:1000]},
        )
    if len(objects) > 1:
        raise TableauMcpPlannerError(
            "TABLEAU_MCP_PLANNER_JSON_MULTIPLE_OBJECTS",
            "Planner output must contain exactly one JSON object.",
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


def _coerce_confidence(value: Any) -> float:
    if isinstance(value, bool):
        raise TableauMcpPlannerError(
            "TABLEAU_MCP_PLANNER_CONFIDENCE_INVALID",
            "Planner output confidence must be a number from 0 to 1.",
            detail={"confidence": value},
        )
    try:
        confidence = float(value)
    except (TypeError, ValueError) as exc:
        raise TableauMcpPlannerError(
            "TABLEAU_MCP_PLANNER_CONFIDENCE_INVALID",
            "Planner output confidence must be a number from 0 to 1.",
            detail={"confidence": value},
        ) from exc
    if confidence < 0.0 or confidence > 1.0:
        raise TableauMcpPlannerError(
            "TABLEAU_MCP_PLANNER_CONFIDENCE_INVALID",
            "Planner output confidence must be a number from 0 to 1.",
            detail={"confidence": value},
        )
    return confidence


def _normalize_tool_name(value: Any) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise TableauMcpPlannerError(
            "TABLEAU_MCP_PLANNER_TOOL_INVALID",
            "Planner output tool_name must be a string or null.",
            detail={"tool_name": value},
        )
    stripped = value.strip()
    return stripped or None


def _validate_executable_args(tool_name: str, args: Mapping[str, Any]) -> None:
    if tool_name != MCP_QUERY_DATASOURCE_TOOL_NAME:
        return

    missing: list[str] = []
    datasource_luid = args.get("datasourceLuid")
    if not isinstance(datasource_luid, str) or not datasource_luid.strip():
        missing.append("args.datasourceLuid")

    query = args.get("query")
    if not isinstance(query, Mapping):
        missing.append("args.query")
        missing.append("args.query.fields")
    else:
        fields = query.get("fields")
        if not isinstance(fields, Sequence) or isinstance(fields, (str, bytes, bytearray)) or not fields:
            missing.append("args.query.fields")

    if missing:
        raise TableauMcpPlannerError(
            "TABLEAU_MCP_PLANNER_EXECUTABLE_ARGS_MISSING",
            "Executable query-datasource planner output is missing required args fields.",
            detail={"missing": missing},
        )


def _has_non_empty_clarification(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, Mapping):
        return any(_has_non_empty_clarification(item) for item in value.values())
    if isinstance(value, Sequence) and not isinstance(value, (bytes, bytearray)):
        return any(_has_non_empty_clarification(item) for item in value)
    return True


def _raw_with_contract_detail(raw: Mapping[str, Any], *, missing_optional: Sequence[str]) -> dict[str, Any]:
    payload = dict(raw)
    if missing_optional:
        payload["_planner_contract"] = {"missing_optional": list(missing_optional)}
    return payload


def _clarification_payload(
    value: Any,
    *,
    reason: str,
    fallback_message: str = "请补充更明确的信息后继续。",
) -> Any:
    if isinstance(value, Mapping):
        payload = dict(value)
        payload.setdefault("reason", reason)
        payload.setdefault("message", fallback_message)
        return payload
    if isinstance(value, str) and value.strip():
        return {"message": value.strip(), "reason": reason}
    return {"message": fallback_message, "reason": reason}


def _context_payload(context: Any) -> dict[str, Any]:
    if context is None:
        return {}
    if isinstance(context, Mapping):
        return _json_safe(dict(context))
    payload: dict[str, Any] = {}
    for attr in ("session_id", "user_id", "tenant_id", "connection_id", "datasource_luid", "datasource_name", "trace_id"):
        value = getattr(context, attr, None)
        if value is not None:
            payload[attr] = value
    return _json_safe(payload)


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

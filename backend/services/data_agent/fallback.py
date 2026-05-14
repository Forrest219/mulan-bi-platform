"""Standardized Data Agent fallback payloads.

Fallbacks are product responses, not raw exceptions. They intentionally keep
tool routing explicit so data questions never degrade into schema inventory.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
import re
from typing import Any, Dict, Optional

from .router_guardrail import RouteDecision


@dataclass(frozen=True)
class StandardFallback:
    fallback_type: str
    error_code: str
    message: str
    user_hint: str
    trace_id: str
    retryable: bool = True
    suggested_actions: list[str] = field(default_factory=list)
    route_decision: Optional[Dict[str, Any]] = None
    tools_used: list[str] = field(default_factory=lambda: ["query"])
    type: str = "fallback"

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @property
    def answer(self) -> str:
        return self.message if not self.user_hint else f"{self.message}\n\n{self.user_hint}"


FALLBACK_DEFINITIONS: Dict[str, Dict[str, Any]] = {
    "datasource_not_matched": {
        "error_code": "NLQ_008",
        "message": "我没有找到能回答这个问题的数据源。",
        "user_hint": "请补充要查询的数据源名称，或换成当前连接中的字段/指标名后重试。",
        "suggested_actions": ["补充数据源名称", "使用当前连接中的字段或指标名"],
    },
    "query_plan_unavailable": {
        "error_code": "NLQ_006",
        "message": "这个问题暂时无法生成可执行查询。",
        "user_hint": "请明确指标、维度和时间范围，例如：2024 年各区域销售额。",
        "suggested_actions": ["明确指标", "明确维度", "明确时间范围"],
    },
    "field_unavailable": {
        "error_code": "QUERY_001",
        "message": "当前数据源没有可查询的请求字段。",
        "user_hint": "请改用可查询字段后重试。",
        "suggested_actions": ["改用可查询字段", "查看数据源字段结构"],
    },
    "date_repair_failed": {
        "error_code": "QUERY_002",
        "message": "查询使用的日期字段在 Tableau 当前可查询元数据中不可用，自动替换后仍未成功。",
        "user_hint": "请指定可用日期字段，或联系数据管理员同步字段元数据。",
        "suggested_actions": ["指定可用日期字段", "联系数据管理员同步字段元数据"],
    },
    "query_timeout": {
        "error_code": "NLQ_007",
        "message": "数据源响应超时。",
        "user_hint": "请缩小时间范围、减少维度，或稍后重试。",
        "suggested_actions": ["缩小时间范围", "减少拆分维度", "稍后重试"],
    },
    "query_execution_failed": {
        "error_code": "NLQ_006",
        "message": "查询已生成，但执行失败。",
        "user_hint": "请稍后重试；如果持续失败，请带 trace_id 联系管理员排查 Tableau/MCP 执行日志。",
        "suggested_actions": ["稍后重试", "联系管理员排查执行日志"],
    },
    "auth_or_permission_failed": {
        "error_code": "NLQ_009",
        "message": "当前账号无权访问该数据源，或 Tableau/MCP 已拒绝请求。",
        "user_hint": "请检查连接权限后重试。",
        "retryable": False,
        "suggested_actions": ["检查连接权限", "联系管理员授权"],
    },
    "service_unavailable": {
        "error_code": "AGENT_003",
        "message": "数据查询服务暂时不可用。",
        "user_hint": "请稍后重试。",
        "suggested_actions": ["稍后重试"],
    },
    "router_guardrail_blocked": {
        "error_code": "ROUTER_GUARDRAIL_BLOCKED",
        "message": "该问题已被路由保护拦截，不能调用当前工具。",
        "user_hint": "请保持问题类型一致：问数据时查询指标和维度，问资产时查看字段和结构。",
        "retryable": False,
        "suggested_actions": ["改为查询业务数据", "改为查看数据资产/字段结构"],
    },
    "clarification_required": {
        "error_code": "ROUTER_CLARIFY_REQUIRED",
        "message": "我还不能确定你是想查看数据资产，还是查询业务数据。",
        "user_hint": "请选择：查看数据资产/字段结构，或查询业务数据/指标。",
        "retryable": True,
        "suggested_actions": ["查看数据资产/字段结构", "查询业务数据/指标"],
    },
}


def make_fallback(
    fallback_type: str,
    *,
    trace_id: str = "",
    error_code: Optional[str] = None,
    message: Optional[str] = None,
    user_hint: Optional[str] = None,
    retryable: Optional[bool] = None,
    suggested_actions: Optional[list[str]] = None,
    route_decision: Optional[RouteDecision] = None,
    tools_used: Optional[list[str]] = None,
) -> StandardFallback:
    definition = FALLBACK_DEFINITIONS.get(fallback_type, FALLBACK_DEFINITIONS["service_unavailable"])
    return StandardFallback(
        fallback_type=fallback_type if fallback_type in FALLBACK_DEFINITIONS else "service_unavailable",
        error_code=error_code or str(definition["error_code"]),
        message=message or str(definition["message"]),
        user_hint=user_hint or str(definition["user_hint"]),
        trace_id=trace_id,
        retryable=bool(definition.get("retryable", True) if retryable is None else retryable),
        suggested_actions=suggested_actions or list(definition.get("suggested_actions") or []),
        route_decision=route_decision.to_dict() if route_decision else None,
        tools_used=["query"] if tools_used is None else tools_used,
    )


def make_clarification_fallback(*, trace_id: str, route_decision: Optional[RouteDecision] = None) -> StandardFallback:
    return make_fallback(
        "clarification_required",
        trace_id=trace_id,
        route_decision=route_decision,
        tools_used=[],
    )


def make_router_blocked_fallback(
    *,
    tool_name: str,
    trace_id: str,
    route_decision: Optional[RouteDecision] = None,
) -> StandardFallback:
    return make_fallback(
        "router_guardrail_blocked",
        trace_id=trace_id,
        route_decision=route_decision,
        tools_used=[tool_name] if tool_name else [],
    )


def fallback_from_tool_result(
    result_data: Dict[str, Any],
    *,
    trace_id: str = "",
    route_decision: Optional[RouteDecision] = None,
    default_type: str = "query_execution_failed",
) -> StandardFallback:
    """Map a QueryTool result dict to a standard fallback."""
    fallback_payload = _extract_existing_fallback(result_data)
    if fallback_payload:
        return make_fallback(
            str(fallback_payload.get("fallback_type") or default_type),
            trace_id=trace_id or str(fallback_payload.get("trace_id") or ""),
            error_code=fallback_payload.get("error_code"),
            message=fallback_payload.get("message"),
            user_hint=fallback_payload.get("user_hint"),
            retryable=fallback_payload.get("retryable"),
            suggested_actions=fallback_payload.get("suggested_actions"),
            route_decision=route_decision,
        )

    data = result_data.get("data") if isinstance(result_data, dict) else None
    if isinstance(data, dict) and data.get("field_unavailable"):
        unavailable = data.get("field_unavailable") or {}
        requested = unavailable.get("requested") or "该字段"
        suggestion = unavailable.get("suggestion")
        message = f"当前数据源没有可查询字段「{requested}」。"
        hint = f"可用的相近字段是「{suggestion}」。请改用可查询字段后重试。" if suggestion else "请改用可查询字段后重试。"
        return make_fallback(
            "field_unavailable",
            trace_id=trace_id,
            message=message,
            user_hint=hint,
            route_decision=route_decision,
        )

    raw_error = str(result_data.get("error") or result_data.get("message") or "")
    fallback_type = fallback_type_from_error(
        error_code=result_data.get("error_code"),
        message=raw_error,
        default_type=default_type,
    )
    return make_fallback(
        fallback_type,
        trace_id=trace_id,
        error_code=result_data.get("error_code"),
        message=None,
        user_hint=None,
        route_decision=route_decision,
    )


def fallback_type_from_error(
    *,
    error_code: Optional[str] = None,
    message: str = "",
    default_type: str = "query_execution_failed",
) -> str:
    code = str(error_code or _extract_error_code(message) or "")
    lower_message = (message or "").casefold()

    if code in {"NLQ_009", "NLQ_010", "NLQ_011"} or any(token in lower_message for token in ("permission", "unauthorized", "forbidden", "无权", "权限", "认证", "限流")):
        return "auth_or_permission_failed"
    if code == "NLQ_008" or "数据源" in message and ("找不到" in message or "无法找到" in message):
        return "datasource_not_matched"
    if code == "NLQ_007" or "timeout" in lower_message or "timed out" in lower_message or "超时" in message:
        return "query_timeout"
    if code == "QUERY_001" or "field_unavailable" in lower_message:
        return "field_unavailable"
    if code == "QUERY_002" or ("日期字段" in message and "仍未成功" in message):
        return "date_repair_failed"
    if "vizql" in lower_message and ("空" in message or "empty" in lower_message):
        return "query_plan_unavailable"
    if code == "NLQ_006":
        return "query_execution_failed"
    return default_type


def query_tool_error_payload(
    fallback_type: str,
    *,
    trace_id: str = "",
    error_code: Optional[str] = None,
    message: Optional[str] = None,
    user_hint: Optional[str] = None,
    retryable: Optional[bool] = None,
    suggested_actions: Optional[list[str]] = None,
) -> Dict[str, Any]:
    """Return the dict shape QueryTool should embed in ToolResult.data."""
    return make_fallback(
        fallback_type,
        trace_id=trace_id,
        error_code=error_code,
        message=message,
        user_hint=user_hint,
        retryable=retryable,
        suggested_actions=suggested_actions,
    ).to_dict()


def is_fallback_payload(value: Any) -> bool:
    return isinstance(value, dict) and value.get("type") == "fallback" and bool(value.get("fallback_type"))


def _extract_existing_fallback(result_data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    if is_fallback_payload(result_data):
        return result_data
    data = result_data.get("data") if isinstance(result_data, dict) else None
    if is_fallback_payload(data):
        return data
    return None


def _extract_error_code(message: str) -> Optional[str]:
    match = re.search(r"\[?([A-Z]+_\d{3})\]?", message or "")
    return match.group(1) if match else None

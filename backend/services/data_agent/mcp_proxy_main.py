"""Transparent MCP proxy chain for Data Agent data questions."""

from __future__ import annotations

import inspect
import json
import logging
import os
from typing import Any, AsyncGenerator, Mapping, Optional

from services.data_agent.intent_classifier import IntentClassification
from services.data_agent.mcp_args_guardrail import (
    MCP_ARGS_GUARDRAIL_PASS,
    MCP_ARGS_GUARDRAIL_REJECT,
    McpArgsGuardrailInput,
    query_datasource_tool_schema,
    validate_mcp_args,
)
from services.data_agent.mcp_first_main import (
    _call_llm_json,
    _queryable_fields,
    _redact_large,
    _resolve_datasource,
)
from services.data_agent.response import AgentEvent
from services.data_agent.table_display import infer_table_display_schema
from services.data_agent.tool_base import ToolContext
from services.llm.service import LLMService

logger = logging.getLogger(__name__)

CHAIN_MODE = "mcp_proxy"
MCP_TOOL_NAME = "query-datasource"


def mcp_proxy_enabled() -> bool:
    """Return whether the experimental transparent MCP proxy is enabled."""
    return str(os.getenv("DATA_AGENT_MCP_PROXY_ENABLED", "false")).strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


async def run_mcp_proxy_main_path(
    *,
    question: str,
    context: ToolContext,
    intent_result: IntentClassification,
    datasource_name_hint: Optional[str] = None,
    analysis_context: Optional[Mapping[str, Any]] = None,
    llm_service: Optional[LLMService] = None,
) -> AsyncGenerator[AgentEvent, None]:
    """Run the transparent MCP args chain.

    This path intentionally does not build or validate QuerySpec. The LLM emits
    official MCP tool arguments, then `mcp_args_guardrail` decides whether those
    arguments may be sent to Tableau MCP.
    """

    llm = llm_service or LLMService()
    yield AgentEvent(type="thinking", content="已进入 MCP Args 直通实验链路。")

    ds_info = _resolve_datasource(question, context, datasource_name_hint)
    if not ds_info:
        yield AgentEvent(type="error", content=_guardrail_fallback_payload(
            "MCP_PROXY_DATASOURCE_NOT_MATCHED",
            "未找到可安全查询的 Tableau 数据源。",
            "请先选择一个 Tableau 数据源，或在问题中明确数据源名称。",
            context.trace_id,
            intent_result,
            detail={"chain_mode": CHAIN_MODE, "guardrail_decision": None, "guardrail_repairs": []},
        ))
        return

    queryable_fields = _queryable_fields(ds_info, connection_id=context.connection_id)
    if not queryable_fields:
        yield AgentEvent(type="error", content=_guardrail_fallback_payload(
            "MCP_PROXY_FIELDS_UNAVAILABLE",
            "当前数据源没有可用于 MCP 查询的字段。",
            "请确认 published datasource 字段已同步，且字段可被 Tableau MCP 查询。",
            context.trace_id,
            intent_result,
            detail={"chain_mode": CHAIN_MODE, "guardrail_decision": None, "guardrail_repairs": []},
        ))
        return

    tool_description = _mcp_tool_description(ds_info, queryable_fields)
    tool_schema = _query_datasource_tool_schema()

    yield AgentEvent(type="tool_call", content={
        "tool": "mcp_tool_description_loader",
        "params": {
            "tool": MCP_TOOL_NAME,
            "datasource": {"name": ds_info.get("name"), "luid": ds_info.get("luid")},
            "field_count": len(queryable_fields),
            "chain_mode": CHAIN_MODE,
        },
    })
    yield AgentEvent(type="tool_result", content={
        "tool": "mcp_tool_description_loader",
        "result": {"data": _redact_large({"description": tool_description, "schema": tool_schema})},
    })

    yield AgentEvent(type="tool_call", content={
        "tool": "llm_mcp_args",
        "params": {
            "tool": MCP_TOOL_NAME,
            "datasource": {"name": ds_info.get("name"), "luid": ds_info.get("luid")},
            "chain_mode": CHAIN_MODE,
        },
    })
    llm_result = await _call_llm_json(
        llm,
        _build_mcp_args_prompt(
            question=question,
            tool_description=tool_description,
            tool_schema=tool_schema,
            datasource=ds_info,
            queryable_fields=queryable_fields,
            analysis_context=analysis_context or {},
        ),
        purpose="data_agent_mcp_proxy_args",
    )
    if not llm_result.get("ok"):
        error_code = str(llm_result.get("error_code") or llm_result.get("error") or "MCP_ARGS_LLM_INVALID")
        error = str(llm_result.get("message") or llm_result.get("error") or "llm_mcp_args_failed")
        yield AgentEvent(type="tool_result", content={
            "tool": "llm_mcp_args",
            "result": {"success": False, "error": error_code, "data": llm_result},
        })
        yield AgentEvent(type="error", content=_guardrail_fallback_payload(
            error_code if error_code.startswith("LLM_") else "MCP_ARGS_LLM_INVALID",
            "LLM 未生成可执行的 MCP tool args。",
            "请换一种更明确的问法，补充指标、时间范围或维度。",
            context.trace_id,
            intent_result,
            detail={
                "chain_mode": CHAIN_MODE,
                "guardrail_decision": "reject",
                "guardrail_repairs": [],
                "llm_error": error[:500],
                "fallback_reason": error_code,
            },
        ))
        return

    raw_args = llm_result["json"]
    yield AgentEvent(type="tool_result", content={
        "tool": "llm_mcp_args",
        "result": {"data": {"args": _redact_large(raw_args), "chain_mode": CHAIN_MODE}},
    })

    guardrail = validate_mcp_args(
        McpArgsGuardrailInput(
            question=question,
            tool_name=MCP_TOOL_NAME,
            tool_schema=tool_schema,
            args=raw_args,
            queryable_fields=queryable_fields,
            current_datasource=_current_datasource(ds_info, context),
            user_context=_user_context(ds_info, context),
        )
    )
    guardrail_payload = guardrail.to_dict()
    yield AgentEvent(type="tool_call", content={
        "tool": "mcp_args_guardrail",
        "params": {"tool": MCP_TOOL_NAME, "chain_mode": CHAIN_MODE},
    })
    yield AgentEvent(type="tool_result", content={
        "tool": "mcp_args_guardrail",
        "result": {
            "success": guardrail.decision != "reject",
            "event": MCP_ARGS_GUARDRAIL_REJECT if guardrail.decision == "reject" else MCP_ARGS_GUARDRAIL_PASS,
            "data": guardrail_payload,
        },
    })

    if guardrail.decision == "reject":
        yield AgentEvent(type="error", content=_guardrail_fallback_payload(
            guardrail.reject_code or "MCP_ARGS_REJECTED",
            guardrail.message,
            guardrail.user_hint,
            context.trace_id,
            intent_result,
            detail={
                "chain_mode": CHAIN_MODE,
                "guardrail_decision": guardrail.decision,
                "guardrail_repairs": [],
                "raw_args": _redact_large(raw_args),
            },
        ))
        return

    safe_args = guardrail.args or {}
    yield AgentEvent(type="tool_call", content={
        "tool": "tableau_mcp",
        "params": {
            "mcp_tool": MCP_TOOL_NAME,
            "datasource_luid": safe_args.get("datasourceLuid"),
            "chain_mode": CHAIN_MODE,
            "guardrail_decision": guardrail.decision,
            "guardrail_repairs": [repair.to_dict() for repair in guardrail.repairs],
        },
    })
    try:
        mcp_result = await _execute_query_datasource_args(safe_args, context)
    except Exception as exc:
        logger.exception("MCP proxy execution failed")
        yield AgentEvent(type="tool_result", content={
            "tool": "tableau_mcp",
            "result": {"success": False, "error": str(exc), "data": {"error": str(exc)}},
        })
        yield AgentEvent(type="error", content=_guardrail_fallback_payload(
            "MCP_PROXY_EXECUTION_FAILED",
            "Tableau MCP 查询失败，本次不输出结论。",
            "请稍后重试；如果持续失败，请带 trace_id 联系管理员排查 Tableau/MCP 执行日志。",
            context.trace_id,
            intent_result,
            detail={
                "chain_mode": CHAIN_MODE,
                "guardrail_decision": guardrail.decision,
                "guardrail_repairs": [repair.to_dict() for repair in guardrail.repairs],
            },
        ))
        return

    response_data = _normalize_response_data(
        mcp_result,
        ds_info=ds_info,
        args=safe_args,
        guardrail_payload=guardrail_payload,
    )
    yield AgentEvent(type="tool_result", content={
        "tool": "tableau_mcp",
        "result": {"data": response_data},
    })
    yield AgentEvent(type="answer", content=_render_proxy_answer(response_data))


def _query_datasource_tool_schema() -> dict[str, Any]:
    return query_datasource_tool_schema()


def _mcp_tool_description(ds_info: Mapping[str, Any], queryable_fields: list[str]) -> str:
    fields_preview = "\n".join(f"- {field}" for field in queryable_fields[:80])
    return (
        "Tool: query-datasource\n"
        "Purpose: read aggregated data from one Tableau published datasource.\n"
        "Arguments JSON shape: {\"datasourceLuid\": string, \"query\": {\"fields\": [...], "
        "\"filters\": [...]}, \"limit\": integer}.\n"
        f"Current datasource: {ds_info.get('name')} ({ds_info.get('luid')}).\n"
        "Only use fields from this queryable field list. Do not invent fields or add business metrics "
        "not requested by the user.\n"
        f"Queryable fields:\n{fields_preview}"
    )


def _build_mcp_args_prompt(
    *,
    question: str,
    tool_description: str,
    tool_schema: dict[str, Any],
    datasource: Mapping[str, Any],
    queryable_fields: list[str],
    analysis_context: Mapping[str, Any],
) -> list[dict[str, str]]:
    system = (
        "You generate arguments for a Tableau MCP tool. Return exactly one JSON object and no prose. "
        "Do not create QuerySpec. Do not add metrics, dimensions, filters, or operators that the user did "
        "not ask for. If the request is ambiguous, still return your best safe read-only MCP args using only "
        "the supplied tool schema and field list."
    )
    user = json.dumps(
        {
            "question": question,
            "tool_description": tool_description,
            "tool_schema": tool_schema,
            "current_datasource": {"name": datasource.get("name"), "luid": datasource.get("luid")},
            "queryable_fields": queryable_fields,
            "analysis_context": analysis_context,
        },
        ensure_ascii=False,
    )
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]


async def _execute_query_datasource_args(args: Mapping[str, Any], context: ToolContext) -> dict[str, Any]:
    from services.tableau.mcp_client import get_tableau_mcp_client

    datasource_luid = str(args.get("datasourceLuid") or "")
    query = args.get("query") or {}
    limit = int(args.get("limit") or 100)
    client = get_tableau_mcp_client(connection_id=context.connection_id)
    result = client.query_datasource(
        datasource_luid,
        query,
        limit=limit,
        connection_id=context.connection_id,
        timeout=30,
    )
    if inspect.isawaitable(result):
        result = await result
    return result


def _normalize_response_data(
    result: Mapping[str, Any],
    *,
    ds_info: Mapping[str, Any],
    args: Mapping[str, Any],
    guardrail_payload: Mapping[str, Any],
) -> dict[str, Any]:
    fields = list(result.get("fields") or [])
    rows = [list(row) if isinstance(row, list) else row for row in list(result.get("rows") or [])]
    metric_names = _metric_names_from_args(args)
    payload = dict(result)
    payload.update({
        "fields": fields,
        "rows": rows,
        "datasource_name": ds_info.get("name"),
        "datasource_luid": ds_info.get("luid"),
        "chain_mode": CHAIN_MODE,
        "guardrail_decision": guardrail_payload.get("decision"),
        "guardrail_repairs": guardrail_payload.get("repairs") or [],
        "mcp_args": _redact_large(dict(args)),
        "table_display": infer_table_display_schema(
            fields,
            rows,
            operator="mcp_proxy",
            metric_names=metric_names,
        ),
    })
    return payload


def _metric_names_from_args(args: Mapping[str, Any]) -> list[str]:
    query = args.get("query")
    if not isinstance(query, Mapping):
        return []
    names: list[str] = []
    for field in query.get("fields") or []:
        if not isinstance(field, Mapping):
            continue
        function = field.get("function") or field.get("aggregation")
        caption = field.get("fieldAlias") or field.get("fieldCaption") or field.get("fieldName") or field.get("name")
        if function and caption:
            names.append(str(caption))
    return names


def _render_proxy_answer(response_data: Mapping[str, Any]) -> str:
    rows = response_data.get("rows") if isinstance(response_data, Mapping) else []
    row_count = len(rows) if isinstance(rows, list) else 0
    if row_count == 0:
        return "查询已完成，未返回数据行。"
    return f"查询已完成，返回 {row_count} 行结果。"


def _current_datasource(ds_info: Mapping[str, Any], context: ToolContext) -> dict[str, Any]:
    payload = {
        "name": ds_info.get("name"),
        "luid": ds_info.get("luid"),
        "connection_id": context.connection_id,
    }
    if isinstance(ds_info.get("field_synonyms"), Mapping):
        payload["field_synonyms"] = dict(ds_info["field_synonyms"])
    if isinstance(ds_info.get("safe_field_synonyms"), Mapping):
        payload["safe_field_synonyms"] = dict(ds_info["safe_field_synonyms"])
    return payload


def _user_context(ds_info: Mapping[str, Any], context: ToolContext) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "user_id": context.user_id,
        "connection_id": context.connection_id,
    }
    if ds_info.get("luid"):
        payload["accessible_datasource_luids"] = [ds_info.get("luid")]
    if context.connection_id is not None:
        payload["accessible_connection_ids"] = [context.connection_id]
    if context.tenant_id:
        payload["tenant_id"] = context.tenant_id
    return payload


def _guardrail_fallback_payload(
    error_code: str,
    message: str,
    user_hint: str,
    trace_id: str,
    intent_result: IntentClassification,
    *,
    detail: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    return {
        "fallback_type": "guardrail_rejected",
        "error_code": error_code,
        "message": message,
        "user_hint": user_hint,
        "trace_id": trace_id,
        "retryable": True,
        "suggested_actions": ["请缩小查询范围，或明确指标、维度、时间范围和返回行数后重试。"],
        "tools_used": ["intent_classifier", "llm_mcp_args", "mcp_args_guardrail"],
        "intent_classifier": intent_result.to_dict(),
        "controlled_chain": {"status": "failed", "detail": detail or {"chain_mode": CHAIN_MODE}},
    }

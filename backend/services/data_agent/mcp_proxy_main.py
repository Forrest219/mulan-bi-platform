"""Transparent MCP proxy chain for Data Agent data questions."""

from __future__ import annotations

import inspect
import json
import logging
import os
import re
from copy import deepcopy
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
_FOLLOWUP_REFERENCE_RE = re.compile(r"(这个|这些|上述|上面|上一[轮次]|该|继续)")
_FOLLOWUP_BREAKDOWN_RE = re.compile(
    r"(继续|再按|拆分|拆解|分解|细分|每年|每月|每周|每日|年份|月份|季度|趋势|by\s+(year|month|quarter|week|day|time))",
    re.IGNORECASE,
)
_AGGREGATE_FIELD_RE = re.compile(r"^\s*(SUM|AVG|COUNT|COUNTD|MIN|MAX|MEDIAN|ATTR)\s*\(\s*(.+?)\s*\)\s*$", re.IGNORECASE)
_METRIC_FUNCTIONS = {"SUM", "AVG", "COUNT", "COUNTD", "MIN", "MAX", "MEDIAN", "ATTR"}


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
    """Run the MCP Host proxy chain."""
    from services.data_agent import mcp_first_main as thin_mcp

    yield AgentEvent(type="thinking", content="已进入 MCP Host 代理链路。")

    ds_info = thin_mcp._resolve_explicit_datasource(
        context=context,
        datasource_name_hint=datasource_name_hint,
        analysis_context=analysis_context,
    )
    if not ds_info:
        yield AgentEvent(type="error", content=thin_mcp._mcp_passthrough_error_payload(
            thin_mcp.MCP_EXPLICIT_DATASOURCE_REQUIRED,
            "请先选择一个 Tableau 数据源后再提问。",
            "当前主链路不从问题文本推断数据源；请在请求上下文中传入 datasource_luid 或已选择的数据源。",
            context.trace_id,
            intent_result,
            chain_mode=CHAIN_MODE,
            detail={"chain_mode": CHAIN_MODE, "reason": "missing_explicit_datasource"},
        ))
        return

    yield AgentEvent(type="tool_call", content={
        "tool": "context_resolver",
        "params": {"chain_mode": CHAIN_MODE, "intent": intent_result.intent},
    })
    yield AgentEvent(type="tool_result", content={
        "tool": "context_resolver",
        "result": {"data": _context_trace_payload(question, analysis_context)},
    })

    attempt = await thin_mcp._run_mcp_main_route(
        question=question,
        context=context,
        intent_result=intent_result,
        datasource=ds_info,
        analysis_context=analysis_context,
        llm_service=llm_service,
        chain_mode=CHAIN_MODE,
    )
    for event in attempt.events:
        yield event
    if attempt.success:
        return

    yield AgentEvent(type="error", content=thin_mcp._mcp_passthrough_error_payload(
        attempt.error_code or thin_mcp.MCP_NL_TOOL_UNAVAILABLE,
        attempt.message,
        attempt.user_hint,
        context.trace_id,
        intent_result,
        chain_mode=CHAIN_MODE,
        detail={
            "chain_mode": CHAIN_MODE,
            "reason": attempt.reason or thin_mcp.MCP_NL_TOOL_UNAVAILABLE,
            "original_error": thin_mcp._queryspec_original_error(attempt.original_error),
        },
    ))
    return

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

    current_datasource_context = _current_datasource(ds_info, context)

    yield AgentEvent(type="tool_call", content={
        "tool": "context_resolver",
        "params": {"chain_mode": CHAIN_MODE, "intent": intent_result.intent},
    })
    yield AgentEvent(type="tool_result", content={
        "tool": "context_resolver",
        "result": {"data": _context_trace_payload(question, analysis_context)},
    })

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
            datasource=current_datasource_context,
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

    raw_args, context_additions = _apply_followup_context_to_mcp_args(
        llm_result["json"],
        question=question,
        datasource=current_datasource_context,
        queryable_fields=queryable_fields,
        analysis_context=analysis_context or {},
    )
    yield AgentEvent(type="tool_result", content={
        "tool": "llm_mcp_args",
        "result": {
            "data": {
                "args": _redact_large(raw_args),
                "chain_mode": CHAIN_MODE,
                **({"context_additions": context_additions} if context_additions else {}),
            }
        },
    })

    guardrail = validate_mcp_args(
        McpArgsGuardrailInput(
            question=question,
            tool_name=MCP_TOOL_NAME,
            tool_schema=tool_schema,
            args=raw_args,
            queryable_fields=queryable_fields,
            current_datasource=current_datasource_context,
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
        "query.fields must be an array of field objects, never an array of strings. "
        "Each field object must include fieldCaption and may include function when aggregation is requested; "
        "do not use aggregation or agg as field object keys.\n"
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
    conversation_context = _mcp_args_conversation_context(
        question=question,
        datasource=datasource,
        queryable_fields=queryable_fields,
        analysis_context=analysis_context,
    )
    system = (
        "You generate arguments for a Tableau MCP tool. Return exactly one JSON object and no prose. "
        "Do not create QuerySpec. Do not add metrics, dimensions, filters, or operators that the user did "
        "not ask for. If the request is ambiguous, still return your best safe read-only MCP args using only "
        "the supplied tool schema and field list. For generic follow-up breakdown questions, preserve prior "
        "breakdown dimensions and prior executable metrics from conversation_context unless the user explicitly "
        "replaces them. Use official query.fields objects only: dimensions as {\"fieldCaption\": \"...\"}, "
        "metrics as {\"fieldCaption\": \"...\", \"function\": \"SUM\"} when a function is supplied by context; "
        "never use aggregation or agg keys. Do not compute metric formulas or business values."
    )
    user = json.dumps(
        {
            "question": question,
            "tool_description": tool_description,
            "tool_schema": tool_schema,
            "current_datasource": {"name": datasource.get("name"), "luid": datasource.get("luid")},
            "datasource_metadata": _safe_datasource_metadata(datasource, queryable_fields),
            "queryable_fields": queryable_fields,
            "analysis_context": analysis_context,
            "conversation_context": conversation_context,
        },
        ensure_ascii=False,
    )
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]


def _mcp_args_conversation_context(
    *,
    question: str,
    datasource: Mapping[str, Any],
    queryable_fields: list[str],
    analysis_context: Mapping[str, Any],
) -> dict[str, Any]:
    metadata = _field_metadata_by_caption(datasource)
    prior_dimensions = _context_dimension_field_objects(analysis_context, queryable_fields, metadata)
    prior_metrics = _context_metric_field_objects(analysis_context, queryable_fields, metadata)
    return {
        "is_followup_breakdown": _is_followup_breakdown_question(question, analysis_context),
        "prior_breakdown_dimensions": prior_dimensions,
        "prior_executable_metrics": prior_metrics,
        "prior_dimension_names": list(analysis_context.get("dimension_names") or []),
        "prior_metric_names": list(analysis_context.get("metric_names") or []),
        "filter_names": list(analysis_context.get("filter_names") or []),
        "time": _context_time_payload(analysis_context),
        "field_contract": {
            "fields_array": "query.fields",
            "caption_key": "fieldCaption",
            "function_key": "function",
            "forbidden_keys": ["aggregation", "agg"],
        },
    }


def _safe_datasource_metadata(datasource: Mapping[str, Any], queryable_fields: list[str]) -> list[dict[str, Any]]:
    metadata = _field_metadata_by_caption(datasource)
    payload: list[dict[str, Any]] = []
    seen: set[str] = set()
    for caption in queryable_fields:
        normalized = _compact_text(caption)
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        item = metadata.get(normalized, {})
        field_payload: dict[str, Any] = {"fieldCaption": caption}
        for target_key, source_keys in {
            "role": ("role",),
            "dataType": ("dataType", "data_type", "type"),
            "isCalculated": ("isCalculated", "is_calculated", "calculated"),
        }.items():
            value = _metadata_raw_value(item, *source_keys)
            if value is not None:
                field_payload[target_key] = value
        if _field_is_aggregate_calculation(caption, metadata):
            field_payload["isAggregateCalculation"] = True
        payload.append(field_payload)
    return payload[:120]


def _apply_followup_context_to_mcp_args(
    args: Any,
    *,
    question: str,
    datasource: Mapping[str, Any],
    queryable_fields: list[str],
    analysis_context: Mapping[str, Any],
) -> tuple[Any, list[dict[str, Any]]]:
    if not isinstance(args, dict) or not _is_followup_breakdown_question(question, analysis_context):
        return args, []

    query = args.get("query")
    if not isinstance(query, dict):
        return args, []
    fields = query.get("fields")
    if not isinstance(fields, list) or any(not isinstance(item, Mapping) for item in fields):
        return args, []

    metadata = _field_metadata_by_caption(datasource)
    next_args = deepcopy(args)
    next_fields = list(next_args.get("query", {}).get("fields") or [])
    existing = _existing_field_keys(next_fields)
    existing_captions = _existing_field_captions(next_fields)
    additions: list[dict[str, Any]] = []

    prefix_dimensions: list[dict[str, Any]] = []
    for field in _context_dimension_field_objects(analysis_context, queryable_fields, metadata):
        key = _field_object_key(field)
        caption_key = key[0]
        if key in existing or caption_key in existing_captions:
            continue
        prefix_dimensions.append(field)
        existing.add(key)
        existing_captions.add(caption_key)
        additions.append({"kind": "prior_dimension", "field": field})

    default_function = _single_existing_metric_function(next_fields)
    suffix_metrics: list[dict[str, Any]] = []
    for field in _context_metric_field_objects(
        analysis_context,
        queryable_fields,
        metadata,
        default_function=default_function,
    ):
        key = _field_object_key(field)
        caption_key = key[0]
        if key in existing or caption_key in existing_captions:
            continue
        suffix_metrics.append(field)
        existing.add(key)
        existing_captions.add(caption_key)
        additions.append({"kind": "prior_metric", "field": field})

    if not additions:
        return args, []

    next_args["query"]["fields"] = [*prefix_dimensions, *next_fields, *suffix_metrics]
    return next_args, additions


def _is_followup_breakdown_question(question: str, analysis_context: Mapping[str, Any]) -> bool:
    if not analysis_context:
        return False
    return bool(_FOLLOWUP_BREAKDOWN_RE.search(question or ""))


def _context_dimension_field_objects(
    analysis_context: Mapping[str, Any],
    queryable_fields: list[str],
    metadata: Mapping[str, Mapping[str, Any]],
) -> list[dict[str, Any]]:
    fields: list[dict[str, Any]] = []
    for name in _context_dimension_names(analysis_context):
        caption = _match_queryable_field(name, queryable_fields)
        if not caption or not _is_safe_dimension_field(caption, metadata):
            continue
        fields.append({"fieldCaption": caption})
    return _dedupe_field_objects(fields)


def _context_metric_field_objects(
    analysis_context: Mapping[str, Any],
    queryable_fields: list[str],
    metadata: Mapping[str, Mapping[str, Any]],
    *,
    default_function: str | None = None,
) -> list[dict[str, Any]]:
    fields: list[dict[str, Any]] = []

    for item in _iter_prior_mcp_field_objects(analysis_context):
        field = _normalize_metric_field_object(item, queryable_fields, metadata)
        if field:
            fields.append(field)

    for item in _context_metric_specs(analysis_context):
        field = _metric_spec_to_field_object(item, queryable_fields, metadata)
        if field:
            fields.append(field)

    for name in analysis_context.get("metric_names") or []:
        if not isinstance(name, str):
            continue
        parsed = _parse_aggregate_field_label(name)
        if parsed:
            caption, function = parsed
        else:
            caption = name
            function = default_function
        field = _metric_caption_to_field_object(caption, function, queryable_fields, metadata)
        if field:
            fields.append(field)

    return _dedupe_field_objects(fields)


def _iter_prior_mcp_field_objects(analysis_context: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    candidates: list[Any] = [
        analysis_context.get("mcp_args"),
        analysis_context.get("query_args"),
        analysis_context.get("last_mcp_args"),
    ]
    response_data = analysis_context.get("response_data")
    if isinstance(response_data, Mapping):
        candidates.append(response_data.get("mcp_args"))

    fields: list[Mapping[str, Any]] = []
    for candidate in candidates:
        if not isinstance(candidate, Mapping):
            continue
        query = candidate.get("query")
        if not isinstance(query, Mapping):
            continue
        raw_fields = query.get("fields")
        if not isinstance(raw_fields, list):
            continue
        fields.extend(item for item in raw_fields if isinstance(item, Mapping))
    return fields


def _context_metric_specs(analysis_context: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    specs: list[Mapping[str, Any]] = []
    for key in ("metrics", "executable_metrics", "prior_executable_metrics"):
        value = analysis_context.get(key)
        if isinstance(value, list):
            specs.extend(item for item in value if isinstance(item, Mapping))
    query_plan = analysis_context.get("query_plan")
    if isinstance(query_plan, Mapping):
        metrics = query_plan.get("metrics")
        if isinstance(metrics, list):
            specs.extend(item for item in metrics if isinstance(item, Mapping))
    return specs


def _context_dimension_names(analysis_context: Mapping[str, Any]) -> list[str]:
    names: list[str] = []
    for key in ("dimension_names", "dimensions", "breakdown_dimensions"):
        value = analysis_context.get(key)
        if isinstance(value, list):
            names.extend(_field_caption(item) for item in value)
    query_plan = analysis_context.get("query_plan")
    if isinstance(query_plan, Mapping):
        dimensions = query_plan.get("dimensions")
        if isinstance(dimensions, list):
            names.extend(_field_caption(item) for item in dimensions)
    return [name for name in names if name]


def _context_time_payload(analysis_context: Mapping[str, Any]) -> Any:
    time_payload = analysis_context.get("time")
    if time_payload is not None:
        return time_payload
    query_plan = analysis_context.get("query_plan")
    if isinstance(query_plan, Mapping):
        return query_plan.get("time")
    return None


def _normalize_metric_field_object(
    item: Mapping[str, Any],
    queryable_fields: list[str],
    metadata: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any] | None:
    function = _normalized_metric_function(item.get("function"))
    caption = _field_caption(item)
    if not function and _field_is_aggregate_calculation(caption, metadata):
        matched = _match_queryable_field(caption, queryable_fields)
        return {"fieldCaption": matched} if matched else None
    if not function:
        return None
    return _metric_caption_to_field_object(caption, function, queryable_fields, metadata)


def _metric_spec_to_field_object(
    item: Mapping[str, Any],
    queryable_fields: list[str],
    metadata: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any] | None:
    caption = _field_caption(item)
    function = _normalized_metric_function(item.get("function") or item.get("aggregation"))
    if function:
        return _metric_caption_to_field_object(caption, function, queryable_fields, metadata)
    if caption and _field_is_aggregate_calculation(caption, metadata):
        matched = _match_queryable_field(caption, queryable_fields)
        return {"fieldCaption": matched} if matched else None
    return None


def _metric_caption_to_field_object(
    caption: str,
    function: str | None,
    queryable_fields: list[str],
    metadata: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any] | None:
    matched = _match_queryable_field(caption, queryable_fields)
    if not matched:
        return None
    if function:
        if not _is_safe_metric_field(matched, metadata, allow_without_metadata=True):
            return None
        return {"fieldCaption": matched, "function": function}
    if _field_is_aggregate_calculation(matched, metadata):
        return {"fieldCaption": matched}
    return None


def _parse_aggregate_field_label(value: str) -> tuple[str, str] | None:
    match = _AGGREGATE_FIELD_RE.match(value or "")
    if not match:
        return None
    function = _normalized_metric_function(match.group(1))
    caption = match.group(2).strip()
    if not function or not caption:
        return None
    return caption, function


def _normalized_metric_function(value: Any) -> str | None:
    function = str(value or "").strip().upper()
    return function if function in _METRIC_FUNCTIONS else None


def _single_existing_metric_function(fields: list[Any]) -> str | None:
    functions: set[str] = set()
    for field in fields:
        if not isinstance(field, Mapping):
            continue
        function = _normalized_metric_function(field.get("function"))
        if function:
            functions.add(function)
    return next(iter(functions)) if len(functions) == 1 else None


def _existing_field_keys(fields: list[Any]) -> set[tuple[str, str | None]]:
    keys: set[tuple[str, str | None]] = set()
    for field in fields:
        if isinstance(field, Mapping):
            keys.add(_field_object_key(field))
    return keys


def _existing_field_captions(fields: list[Any]) -> set[str]:
    captions: set[str] = set()
    for field in fields:
        if isinstance(field, Mapping):
            caption = _compact_text(_field_caption(field))
            if caption:
                captions.add(caption)
    return captions


def _field_object_key(field: Mapping[str, Any]) -> tuple[str, str | None]:
    return (_compact_text(_field_caption(field)), _normalized_function_for_key(field.get("function")))


def _normalized_function_for_key(value: Any) -> str | None:
    function = str(value or "").strip().upper()
    return function or None


def _dedupe_field_objects(fields: list[dict[str, Any]]) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    seen: set[tuple[str, str | None]] = set()
    for field in fields:
        key = _field_object_key(field)
        if not key[0] or key in seen:
            continue
        seen.add(key)
        output.append(field)
    return output


def _is_safe_dimension_field(caption: str, metadata: Mapping[str, Mapping[str, Any]]) -> bool:
    item = metadata.get(_compact_text(caption))
    if not item:
        return True
    role = _metadata_string(item, "role").upper()
    if role and role != "DIMENSION":
        return False
    if _field_is_aggregate_calculation(caption, metadata):
        return False
    return True


def _is_safe_metric_field(
    caption: str,
    metadata: Mapping[str, Mapping[str, Any]],
    *,
    allow_without_metadata: bool,
) -> bool:
    item = metadata.get(_compact_text(caption))
    if not item:
        return allow_without_metadata
    role = _metadata_string(item, "role").upper()
    if role and role != "MEASURE":
        return False
    function_source = _metadata_string(item, "dataType", "data_type", "type").upper()
    return "DATE" not in function_source


def _field_is_aggregate_calculation(caption: str, metadata: Mapping[str, Mapping[str, Any]]) -> bool:
    item = metadata.get(_compact_text(caption))
    if not item:
        return False
    formula = _metadata_string(item, "formula")
    if not formula:
        return False
    normalized = formula.upper()
    return any(re.search(rf"(?<![A-Z0-9_]){function}\s*\(", normalized) for function in _METRIC_FUNCTIONS)


def _field_metadata_by_caption(datasource: Mapping[str, Any]) -> dict[str, Mapping[str, Any]]:
    metadata_fields = datasource.get("metadata_fields") or datasource.get("fields") or []
    indexed: dict[str, Mapping[str, Any]] = {}
    for item in metadata_fields:
        if not isinstance(item, Mapping):
            continue
        caption = _field_caption(item)
        if caption:
            indexed.setdefault(_compact_text(caption), item)
    return indexed


def _match_queryable_field(value: Any, queryable_fields: list[str]) -> str | None:
    normalized = _compact_text(value)
    if not normalized:
        return None
    for field in queryable_fields:
        caption = str(field or "").strip()
        if _compact_text(caption) == normalized:
            return caption
    return None


def _field_caption(value: Any) -> str:
    if isinstance(value, Mapping):
        for key in ("fieldCaption", "field_caption", "caption", "field", "name", "semantic_name", "display_name"):
            raw = value.get(key)
            if raw:
                return str(raw).strip()
        return ""
    return str(value or "").strip()


def _metadata_string(metadata: Mapping[str, Any], *keys: str) -> str:
    value = _metadata_raw_value(metadata, *keys)
    return str(value).strip() if value is not None else ""


def _metadata_raw_value(metadata: Mapping[str, Any], *keys: str) -> Any:
    for key in keys:
        if key in metadata and metadata.get(key) is not None:
            return metadata.get(key)
    mcp = metadata.get("mcp")
    if isinstance(mcp, Mapping):
        for key in keys:
            if key in mcp and mcp.get(key) is not None:
                return mcp.get(key)
    return None


def _compact_text(value: Any) -> str:
    return re.sub(r"\s+", "", str(value or "")).casefold()


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
        user_id=context.user_id,
        trace_id=context.trace_id,
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
    field_metadata = _datasource_field_metadata(ds_info)
    if field_metadata:
        payload["fields"] = field_metadata
    if isinstance(ds_info.get("field_synonyms"), Mapping):
        payload["field_synonyms"] = dict(ds_info["field_synonyms"])
    if isinstance(ds_info.get("safe_field_synonyms"), Mapping):
        payload["safe_field_synonyms"] = dict(ds_info["safe_field_synonyms"])
    return payload


def _datasource_field_metadata(ds_info: Mapping[str, Any]) -> list[dict[str, Any]]:
    metadata_fields = ds_info.get("metadata_fields")
    if isinstance(metadata_fields, list):
        return [dict(item) for item in metadata_fields if isinstance(item, Mapping)]

    asset_id = ds_info.get("asset_id")
    datasource_luid = ds_info.get("luid") or ds_info.get("datasource_luid")
    if not asset_id or not datasource_luid:
        return []

    try:
        from app.core.database import SessionLocal
        from services.tableau.models import TableauDatasourceField

        session = SessionLocal()
        try:
            rows = (
                session.query(TableauDatasourceField)
                .filter(
                    TableauDatasourceField.asset_id == asset_id,
                    TableauDatasourceField.datasource_luid == datasource_luid,
                )
                .all()
            )
            return [row.to_dict() for row in rows]
        finally:
            session.close()
    except Exception:
        logger.debug("datasource field metadata lookup skipped", exc_info=True)
        return []


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
        "fallback_trace_event": "WARN",
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


def _context_trace_payload(question: str, analysis_context: Optional[Mapping[str, Any]]) -> dict[str, Any]:
    context = dict(analysis_context or {})
    unresolved = bool(_FOLLOWUP_REFERENCE_RE.search(question or "") and not context)
    return {
        "status": "unresolved" if unresolved else ("resolved" if context else "empty"),
        "datasource_name": context.get("datasource_name"),
        "metric_names": list(context.get("metric_names") or []),
        "dimension_names": list(context.get("dimension_names") or []),
        "filter_names": list(context.get("filter_names") or []),
        "unresolved_references": unresolved,
        "calculation_performed": False,
    }

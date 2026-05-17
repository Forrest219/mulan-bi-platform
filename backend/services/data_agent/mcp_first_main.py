"""MCP-first controlled main path for homepage Data Agent questions."""

from __future__ import annotations

import inspect
import importlib
import json
import logging
import os
import re
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Any, AsyncGenerator, Mapping, Optional

from services.data_agent.answer_prompt_builder import build_answer_prompt
from services.data_agent.dynamic_column_engine import append_derived_columns, derived_metric_names_in_text
from services.data_agent.intent_classifier import IntentClassification
from services.data_agent.query_plan import OperatorResult, QueryPlanContext
from services.data_agent.queryspec import ALLOWED_INTENTS, ALLOWED_OPERATORS, FilterSpec, MetricSpec, QuerySpec, SortSpec
from services.data_agent.queryspec_fallback import build_fallback_queryspec, infer_fallback_operator
from services.data_agent.queryspec_prompt_builder import build_queryspec_prompt, build_queryspec_repair_prompt
from services.data_agent.queryspec_validator import validate_queryspec
from services.data_agent.response import AgentEvent
from services.data_agent.result_guardrail import (
    DETAIL_SCAN_BLOCKED,
    ResultGuardrailInput,
    evaluate_result_guardrail,
)
from services.data_agent.semantic_operators.base import DataContinuityError
from services.data_agent.semantic_operators.registry import default_registry
from services.data_agent.skill_prompt_loader import SkillPromptLoader
from services.data_agent.table_display import infer_table_display_schema
from services.data_agent.tool_base import ToolContext
from services.llm.nlq_service import get_datasource_fields_cached, route_datasource
from services.llm.service import (
    LLM_AUTH_CONFIG_ERROR,
    LLM_EMPTY_RESPONSE,
    LLM_NOT_CONFIGURED,
    LLM_PROVIDER_ERROR,
    LLM_PROVIDER_TIMEOUT,
    LLM_THINKING_ONLY_RESPONSE,
    LLMService,
)
from services.tableau.mcp_metadata_fields import (
    extract_mcp_field_metadata,
    extract_queryable_fields_from_metadata,
    field_display_name,
    normalize_field_name,
)

logger = logging.getLogger(__name__)

ENV_DCE_SHADOW_ENABLED = "DATA_AGENT_DCE_SHADOW_ENABLED"
FALLBACK_TRIGGERED_EVENT = "FALLBACK_TRIGGERED"
WARN_EVENT = "WARN"
MCP_MAIN_CHAIN_MODE = "mcp_first_mcp_main"
MCP_MAIN_QUERYSPEC_FALLBACK_CHAIN_MODE = "mcp_main_queryspec_fallback"
QUERYSPEC_MCP_FALLBACK_CHAIN_MODE = "queryspec_mcp_fallback"
ENV_QUERYSPEC_MCP_FALLBACK_ENABLED = "DATA_AGENT_QUERYSPEC_MCP_FALLBACK_ENABLED"
ENV_MCP_NL_QUERY_TOOL_NAME = "DATA_AGENT_MCP_NL_QUERY_TOOL_NAME"
ENV_TABLEAU_MCP_NL_QUERY_TOOL_NAME = "TABLEAU_MCP_NL_QUERY_TOOL_NAME"
ENV_MCP_HOST_THIN_FALLBACK_ENABLED = "DATA_AGENT_MCP_HOST_THIN_FALLBACK_ENABLED"
MCP_NL_TOOL_UNAVAILABLE = "MCP_NL_TOOL_UNAVAILABLE"
MCP_EXPLICIT_DATASOURCE_REQUIRED = "MCP_EXPLICIT_DATASOURCE_REQUIRED"
MCP_HOST_RUNTIME_UNAVAILABLE = "MCP_HOST_RUNTIME_UNAVAILABLE"
MCP_HOST_PLANNER_UNAVAILABLE = "MCP_HOST_PLANNER_UNAVAILABLE"
MCP_HOST_CATALOG_UNAVAILABLE = "MCP_HOST_CATALOG_UNAVAILABLE"
MCP_HOST_TOOL_EXECUTION_FAILED = "MCP_HOST_TOOL_EXECUTION_FAILED"
MCP_HOST_NO_QUERY_RESULT = "MCP_HOST_NO_QUERY_RESULT"
MCP_HOST_LOOP_BUDGET_EXHAUSTED = "MCP_HOST_LOOP_BUDGET_EXHAUSTED"
MCP_HOST_TOOL_NOT_IN_CATALOG = "MCP_HOST_TOOL_NOT_IN_CATALOG"
MCP_CATALOG_ONLY_FIELD = "MCP_CATALOG_ONLY_FIELD"
RESULT_GUARDRAIL_BLOCKED = "RESULT_GUARDRAIL_BLOCKED"
MCP_HOST_METADATA_TOOL_NAME = "get-datasource-metadata"
MCP_HOST_QUERY_TOOL_NAME = "query-datasource"
MCP_HOST_MAX_TOOL_CALLS = 4
MCP_HOST_REPAIR_BUDGET = 1
JSON_PLANNING_TIMEOUT_SECONDS = 18
QS_JSON_INVALID = "QS_JSON_INVALID"
QS_JSON_NOT_FOUND = "QS_JSON_NOT_FOUND"
QS_MODEL_INVALID = "QS_MODEL_INVALID"
QS_VALIDATION_FAILED = "QS_VALIDATION_FAILED"
QUERYSPEC_REPAIRABLE_ERROR_CODES = {
    QS_JSON_INVALID,
    QS_JSON_NOT_FOUND,
    QS_MODEL_INVALID,
    QS_VALIDATION_FAILED,
}
NON_REPAIRABLE_LLM_ERROR_CODES = {
    LLM_NOT_CONFIGURED,
    LLM_AUTH_CONFIG_ERROR,
    LLM_PROVIDER_TIMEOUT,
    LLM_EMPTY_RESPONSE,
    LLM_THINKING_ONLY_RESPONSE,
}
_FOLLOWUP_REFERENCE_RE = re.compile(r"(这个|这些|上述|上面|上一[轮次]|该|继续)")
_QUERYABLE_FIELDS_CONTEXT: ContextVar[tuple[str, ...]] = ContextVar("mcp_first_queryable_fields", default=())


@dataclass(frozen=True)
class _McpMainAttempt:
    success: bool
    events: list[AgentEvent]
    reason: Optional[str] = None
    error_code: Optional[str] = None
    original_error: Any = None
    message: str = "MCP 主路由未能完成查询。"
    user_hint: str = "已切换到 QuerySpec fallback 继续尝试。"


@dataclass(frozen=True)
class _McpHostComponents:
    catalog: Any
    executor: Any
    planner: Any


@dataclass(frozen=True)
class _McpHostToolResult:
    success: bool
    data: Any = None
    error_code: Optional[str] = None
    error: Any = None
    raw: Any = None


async def run_mcp_first_main_path(
    *,
    question: str,
    context: ToolContext,
    intent_result: IntentClassification,
    datasource_name_hint: Optional[str] = None,
    analysis_context: Optional[Mapping[str, Any]] = None,
    llm_service: Optional[LLMService] = None,
) -> AsyncGenerator[AgentEvent, None]:
    """Execute the MCP Host route for data intents."""

    yield AgentEvent(type="thinking", content=f"已进入 Tableau MCP Host 主链路：{intent_result.intent}。")

    ds_info = _resolve_explicit_datasource(
        context=context,
        datasource_name_hint=datasource_name_hint,
        analysis_context=analysis_context,
    )
    if not ds_info:
        yield AgentEvent(type="error", content=_mcp_passthrough_error_payload(
            MCP_EXPLICIT_DATASOURCE_REQUIRED,
            "请先选择一个 Tableau 数据源后再提问。",
            "当前主链路不从问题文本推断数据源；请在请求上下文中传入 datasource_luid 或已选择的数据源。",
            context.trace_id,
            intent_result,
            chain_mode=MCP_MAIN_CHAIN_MODE,
            detail={"chain_mode": MCP_MAIN_CHAIN_MODE, "reason": "missing_explicit_datasource"},
        ))
        return

    yield AgentEvent(type="tool_call", content={
        "tool": "context_resolver",
        "params": {"chain_mode": MCP_MAIN_CHAIN_MODE, "intent": intent_result.intent},
    })
    yield AgentEvent(type="tool_result", content={
        "tool": "context_resolver",
        "result": {"data": _context_trace_payload(question, analysis_context)},
    })

    field_captions, _metadata_fields = _queryable_field_context(ds_info, context.connection_id)
    preflight_error = _catalog_only_preflight(question, ds_info, field_captions)
    if preflight_error:
        yield AgentEvent(type="error", content=_catalog_only_error_payload(
            preflight_error,
            context.trace_id,
            intent_result,
            chain_mode=MCP_MAIN_CHAIN_MODE,
        ))
        return
    deterministic_operator = infer_fallback_operator(question, intent_result.intent)
    if deterministic_operator in {
        "aggregate",
        "ranking",
        "customer_record",
        "set_difference",
        "trend_condition",
        "all_period_condition",
        "root_cause",
    }:
        raw_spec = _build_fallback_queryspec(
            question=question,
            intent_result=intent_result,
            datasource=ds_info,
            queryable_fields=field_captions,
            analysis_context=analysis_context,
            reason="semantic_operator_preflight",
        )
        if raw_spec:
            yield AgentEvent(type="tool_call", content={
                "tool": "queryspec_fallback",
                "params": {
                    "reason": "semantic_operator_preflight",
                    "intent": intent_result.intent,
                    "operator": deterministic_operator,
                },
            })
            yield AgentEvent(type="tool_result", content={
                "tool": "queryspec_fallback",
                "result": {
                    "event": FALLBACK_TRIGGERED_EVENT,
                    "data": {
                        "queryspec": _redact_large(raw_spec),
                        "reason": "semantic_operator_preflight",
                        "original_error": None,
                    },
                },
            })
            spec = _normalize_queryspec_for_mcp(
                QuerySpec.model_validate(raw_spec),
                question,
                field_captions,
                ds_info,
                analysis_context,
            )
            yield AgentEvent(type="tool_call", content={
                "tool": "tableau_mcp",
                "params": {
                    "operator": spec.effective_operator,
                    "datasource_luid": ds_info.get("luid"),
                    "chain_mode": MCP_MAIN_QUERYSPEC_FALLBACK_CHAIN_MODE,
                },
            })
            try:
                mcp_data = await _execute_queryspec(
                    spec,
                    ds_info,
                    context,
                    question,
                    queryable_fields=field_captions,
                )
            except Exception as exc:
                logger.exception("semantic preflight MCP execution failed")
                yield AgentEvent(type="tool_result", content={
                    "tool": "tableau_mcp",
                    "result": {
                        "success": False,
                        "error": str(exc),
                        "data": {"error": str(exc), "chain_mode": MCP_MAIN_QUERYSPEC_FALLBACK_CHAIN_MODE},
                    },
                })
            else:
                yield AgentEvent(type="tool_result", content={
                    "tool": "tableau_mcp",
                    "result": {"data": mcp_data},
                })
                rendered = _render_deterministic_answer(mcp_data, spec)
                yield AgentEvent(type="tool_call", content={
                    "tool": "answer_renderer",
                    "params": {
                        "renderer": "deterministic_table",
                        "operator": spec.effective_operator,
                        "row_count": len(mcp_data.get("rows") or []),
                    },
                })
                yield AgentEvent(type="tool_result", content={
                    "tool": "answer_renderer",
                    "result": {"data": mcp_data, "renderer": "deterministic_table"},
                })
                yield AgentEvent(type="answer", content=rendered)
                return

    mcp_main_attempt = await _run_mcp_main_route(
        question=question,
        context=context,
        intent_result=intent_result,
        datasource=ds_info,
        analysis_context=analysis_context,
        llm_service=llm_service,
        chain_mode=MCP_MAIN_CHAIN_MODE,
    )
    for event in mcp_main_attempt.events:
        yield event
    if mcp_main_attempt.success:
        return

    yield AgentEvent(type="error", content=_mcp_passthrough_error_payload(
        mcp_main_attempt.error_code or MCP_NL_TOOL_UNAVAILABLE,
        mcp_main_attempt.message,
        mcp_main_attempt.user_hint,
        context.trace_id,
        intent_result,
        chain_mode=MCP_MAIN_CHAIN_MODE,
        detail={
            "chain_mode": MCP_MAIN_CHAIN_MODE,
            "reason": mcp_main_attempt.reason or MCP_NL_TOOL_UNAVAILABLE,
            "original_error": _queryspec_original_error(mcp_main_attempt.original_error),
        },
    ))
    return

    planning_skill = loader.load_planning(intent_result.intent)
    yield AgentEvent(type="tool_call", content={
        "tool": "planning_skill_loader",
        "params": {"skill_key": intent_result.intent, "kind": "planning"},
    })
    yield AgentEvent(type="tool_result", content={
        "tool": "planning_skill_loader",
        "result": {"data": _skill_result_summary(planning_skill)},
    })
    if not planning_skill.ok or not planning_skill.content:
        async for event in _run_queryspec_mcp_fallback(
            question=question,
            context=context,
            intent_result=intent_result,
            datasource=ds_info,
            queryable_fields=field_captions,
            analysis_context=analysis_context,
            llm=llm,
            phase="planning",
            reason="planning_skill_missing",
            original_error=planning_skill.error or _skill_result_summary(planning_skill),
            error_code="query_plan_unavailable",
            message="未找到该意图对应的 planning skill。",
            user_hint="请联系管理员补齐 planning skill 配置。",
            failure_fallback_type="query_plan_unavailable",
        ):
            yield event
        return

    datasource_payload = {"name": ds_info.get("name"), "luid": ds_info.get("luid")}
    queryspec_fallback_enabled = _queryspec_fallback_enabled()
    queryspec_fallback_used = False
    queryspec_fallback_reason: Optional[str] = None
    queryspec_repair_attempted = False

    raw_spec = None
    if queryspec_fallback_enabled and _should_prefer_deterministic_queryspec(question, intent_result, analysis_context):
        raw_spec = _build_fallback_queryspec(
            question=question,
            intent_result=intent_result,
            datasource=ds_info,
            queryable_fields=field_captions,
            analysis_context=analysis_context,
            reason="deterministic_preflight",
        )
        if raw_spec:
            queryspec_fallback_used = True
            queryspec_fallback_reason = "deterministic_preflight"
            yield AgentEvent(type="tool_call", content={
                "tool": "queryspec_fallback",
                "params": {"reason": "deterministic_preflight", "intent": intent_result.intent},
            })
            yield AgentEvent(type="tool_result", content={
                "tool": "queryspec_fallback",
                "result": {
                    "event": FALLBACK_TRIGGERED_EVENT,
                    "data": {
                        "queryspec": _redact_large(raw_spec),
                        "reason": "deterministic_preflight",
                        "original_error": None,
                        "metrics": _queryspec_trace_metrics(
                            main_path_success=False,
                            fallback_triggered=True,
                            fallback_mode="deterministic_queryspec",
                            fallback_reason="deterministic_preflight",
                        ),
                    },
                },
            })

    if raw_spec is None:
        prompt_messages = build_queryspec_prompt(
            question=question,
            intent=intent_result.intent,
            datasource=datasource_payload,
            queryable_fields=field_captions,
            analysis_context=analysis_context or {},
            planning_skill_content=planning_skill.content,
        )
        yield AgentEvent(type="tool_call", content={
            "tool": "llm_queryspec",
            "params": {
                "intent": intent_result.intent,
                "datasource": datasource_payload,
                "field_count": len(field_captions),
                "skill_checksum": planning_skill.checksum,
            },
        })
        queryspec_result = await _call_llm_json(llm, prompt_messages, purpose="data_agent_queryspec")
        if not queryspec_result.get("ok"):
            failure_code = _queryspec_failure_code(queryspec_result, QS_JSON_INVALID)
            yield AgentEvent(type="tool_result", content={
                "tool": "llm_queryspec",
                "result": {
                    "success": False,
                    "error": failure_code,
                    "data": queryspec_result,
                    "fallback_reason": failure_code,
                },
            })
            if _is_queryspec_repairable(failure_code):
                queryspec_repair_attempted = True
                yield AgentEvent(type="tool_call", content={
                    "tool": "llm_queryspec_repair",
                    "params": {
                        "reason": failure_code,
                        "intent": intent_result.intent,
                        "datasource": datasource_payload,
                    },
                })
                repair_result = await _repair_queryspec_once(
                    llm=llm,
                    question=question,
                    intent=intent_result.intent,
                    datasource_payload=datasource_payload,
                    queryable_fields=field_captions,
                    analysis_context=analysis_context,
                    planning_skill_content=planning_skill.content,
                    original_output=queryspec_result.get("raw") or queryspec_result,
                    error_summary=queryspec_result,
                )
                if repair_result.get("ok"):
                    raw_spec = repair_result["json"]
                    yield AgentEvent(type="tool_result", content={
                        "tool": "llm_queryspec_repair",
                        "result": {"data": {"queryspec": _redact_large(raw_spec)}, "success": True},
                    })
                else:
                    yield AgentEvent(type="tool_result", content={
                        "tool": "llm_queryspec_repair",
                        "result": {
                            "success": False,
                            "error": _queryspec_failure_code(repair_result, QS_JSON_INVALID),
                            "data": repair_result,
                        },
                    })
                    queryspec_result = _queryspec_repair_error_payload(
                        error_code=failure_code,
                        original_error=queryspec_result,
                        repair_error=repair_result,
                    )
            if not queryspec_fallback_enabled:
                if raw_spec is not None:
                    pass
                else:
                    async for event in _run_queryspec_mcp_fallback(
                        question=question,
                        context=context,
                        intent_result=intent_result,
                        datasource=ds_info,
                        queryable_fields=field_captions,
                        analysis_context=analysis_context,
                        llm=llm,
                        phase="queryspec_generation",
                        reason=failure_code,
                        original_error=queryspec_result,
                        error_code=failure_code,
                        message="LLM 未生成可执行的 QuerySpec。",
                        user_hint="请换一种更明确的问法，补充指标、时间范围或维度。",
                    ):
                        yield event
                    return
            if raw_spec is not None:
                pass
            elif not queryspec_fallback_enabled:
                return
            else:
                raw_spec = _build_fallback_queryspec(
                    question=question,
                    intent_result=intent_result,
                    datasource=ds_info,
                    queryable_fields=field_captions,
                    analysis_context=analysis_context,
                    reason=failure_code,
                )
                if not raw_spec:
                    async for event in _run_queryspec_mcp_fallback(
                        question=question,
                        context=context,
                        intent_result=intent_result,
                        datasource=ds_info,
                        queryable_fields=field_captions,
                        analysis_context=analysis_context,
                        llm=llm,
                        phase="queryspec_repair" if queryspec_repair_attempted else "queryspec_generation",
                        reason=failure_code,
                        original_error=_queryspec_repair_error_payload(
                            error_code=failure_code,
                            original_error=queryspec_result,
                            repair_error="deterministic_queryspec_unavailable",
                        ),
                        error_code=failure_code,
                        message="没有生成可安全执行的 QuerySpec。",
                        user_hint="请换一种更明确的问法，补充指标、时间范围或维度。",
                        failure_fallback_type="query_plan_unavailable",
                    ):
                        yield event
                    return
                queryspec_fallback_used = True
                queryspec_fallback_reason = failure_code
                yield AgentEvent(type="tool_call", content={
                    "tool": "queryspec_fallback",
                    "params": {"reason": failure_code, "intent": intent_result.intent},
                })
                yield AgentEvent(type="tool_result", content={
                    "tool": "queryspec_fallback",
                    "result": {
                        "event": FALLBACK_TRIGGERED_EVENT,
                        "data": {
                            "queryspec": _redact_large(raw_spec),
                            "reason": failure_code,
                            "original_error": _queryspec_original_error(queryspec_result),
                            "metrics": _queryspec_trace_metrics(
                                main_path_success=False,
                                fallback_triggered=True,
                                fallback_mode="deterministic_queryspec",
                                fallback_reason=failure_code,
                            ),
                        },
                    },
                })
        else:
            raw_spec = queryspec_result["json"]
            yield AgentEvent(type="tool_result", content={
                "tool": "llm_queryspec",
                "result": {"data": {"queryspec": _redact_large(raw_spec)}},
            })

    try:
        spec = _normalize_queryspec_for_mcp(QuerySpec.model_validate(raw_spec), question, field_captions, ds_info, analysis_context)
    except Exception as exc:
        model_error = exc
        if not queryspec_repair_attempted:
            queryspec_repair_attempted = True
            yield AgentEvent(type="tool_call", content={
                "tool": "llm_queryspec_repair",
                "params": {"reason": QS_MODEL_INVALID, "intent": intent_result.intent, "datasource": datasource_payload},
            })
            repair_result = await _repair_queryspec_once(
                llm=llm,
                question=question,
                intent=intent_result.intent,
                datasource_payload=datasource_payload,
                queryable_fields=field_captions,
                analysis_context=analysis_context,
                planning_skill_content=planning_skill.content,
                original_output=raw_spec,
                error_summary={"error_code": QS_MODEL_INVALID, "error": _queryspec_original_error(exc)},
            )
            if repair_result.get("ok"):
                raw_spec = repair_result["json"]
                try:
                    spec = _normalize_queryspec_for_mcp(QuerySpec.model_validate(raw_spec), question, field_captions, ds_info, analysis_context)
                    model_error = None
                except Exception as repair_exc:
                    model_error = repair_exc
                    yield AgentEvent(type="tool_result", content={
                        "tool": "llm_queryspec_repair",
                        "result": {
                            "success": False,
                            "error": QS_MODEL_INVALID,
                            "data": _queryspec_repair_error_payload(
                                error_code=QS_MODEL_INVALID,
                                original_error=exc,
                                repair_error=repair_exc,
                            ),
                        },
                    })
                else:
                    yield AgentEvent(type="tool_result", content={
                        "tool": "llm_queryspec_repair",
                        "result": {"data": {"queryspec": _redact_large(raw_spec)}, "success": True},
                    })
            else:
                yield AgentEvent(type="tool_result", content={
                    "tool": "llm_queryspec_repair",
                    "result": {
                        "success": False,
                        "error": _queryspec_failure_code(repair_result, QS_JSON_INVALID),
                        "data": repair_result,
                    },
                })
                model_error = _queryspec_repair_error_payload(
                    error_code=QS_MODEL_INVALID,
                    original_error=exc,
                    repair_error=repair_result,
                )

        if model_error is not None:
            if not queryspec_fallback_enabled:
                async for event in _run_queryspec_mcp_fallback(
                    question=question,
                    context=context,
                    intent_result=intent_result,
                    datasource=ds_info,
                    queryable_fields=field_captions,
                    analysis_context=analysis_context,
                    llm=llm,
                    phase="queryspec_model_validation",
                    reason=QS_MODEL_INVALID,
                    original_error=model_error,
                    error_code=QS_MODEL_INVALID,
                    message="QuerySpec 结构不符合契约。",
                    user_hint="我没有生成可安全执行的查询计划，请换一种更明确的问法。",
                ):
                    yield event
                return
            raw_spec = _build_fallback_queryspec(
                question=question,
                intent_result=intent_result,
                datasource=ds_info,
                queryable_fields=field_captions,
                analysis_context=analysis_context,
                reason=QS_MODEL_INVALID,
            )
            if not raw_spec:
                async for event in _run_queryspec_mcp_fallback(
                    question=question,
                    context=context,
                    intent_result=intent_result,
                    datasource=ds_info,
                    queryable_fields=field_captions,
                    analysis_context=analysis_context,
                    llm=llm,
                    phase="queryspec_repair",
                    reason=QS_MODEL_INVALID,
                    original_error=_queryspec_repair_error_payload(
                        error_code=QS_MODEL_INVALID,
                        original_error=model_error,
                        repair_error="deterministic_queryspec_unavailable",
                    ),
                    error_code=QS_MODEL_INVALID,
                    message="QuerySpec 结构不符合契约。",
                    user_hint="我没有生成可安全执行的查询计划，请换一种更明确的问法。",
                    failure_fallback_type="query_plan_unavailable",
                ):
                    yield event
                return
            queryspec_fallback_used = True
            queryspec_fallback_reason = QS_MODEL_INVALID
            yield AgentEvent(type="tool_call", content={
                "tool": "queryspec_fallback",
                "params": {"reason": QS_MODEL_INVALID, "intent": intent_result.intent},
            })
            yield AgentEvent(type="tool_result", content={
                "tool": "queryspec_fallback",
                "result": {
                    "event": FALLBACK_TRIGGERED_EVENT,
                    "data": {
                        "queryspec": _redact_large(raw_spec),
                        "reason": QS_MODEL_INVALID,
                        "original_error": _queryspec_original_error(model_error),
                        "metrics": _queryspec_trace_metrics(
                            main_path_success=False,
                            fallback_triggered=True,
                            fallback_mode="deterministic_queryspec",
                            fallback_reason=QS_MODEL_INVALID,
                        ),
                    },
                },
            })
            try:
                spec = _normalize_queryspec_for_mcp(QuerySpec.model_validate(raw_spec), question, field_captions, ds_info, analysis_context)
            except Exception as repair_exc:
                async for event in _run_queryspec_mcp_fallback(
                    question=question,
                    context=context,
                    intent_result=intent_result,
                    datasource=ds_info,
                    queryable_fields=field_captions,
                    analysis_context=analysis_context,
                    llm=llm,
                    phase="queryspec_repair",
                    reason=QS_MODEL_INVALID,
                    original_error=_queryspec_repair_error_payload(
                        error_code=QS_MODEL_INVALID,
                        original_error=model_error,
                        repair_error=repair_exc,
                    ),
                    error_code=QS_MODEL_INVALID,
                    message="QuerySpec 结构不符合契约。",
                    user_hint="我没有生成可安全执行的查询计划，请换一种更明确的问法。",
                    failure_fallback_type="query_plan_unavailable",
                ):
                    yield event
                return

    replacement_reason = _queryspec_replacement_reason(question, intent_result, spec, analysis_context)
    if replacement_reason:
        replacement_error = {"validator_code": "QS_OPERATOR_MISMATCH", "fallback_reason": replacement_reason, "queryspec": _redact_large(raw_spec)}
        if not queryspec_fallback_enabled:
            async for event in _run_queryspec_mcp_fallback(
                question=question,
                context=context,
                intent_result=intent_result,
                datasource=ds_info,
                queryable_fields=field_captions,
                analysis_context=analysis_context,
                llm=llm,
                phase="queryspec_semantic_check",
                reason=QS_VALIDATION_FAILED,
                original_error=replacement_error,
                error_code=QS_VALIDATION_FAILED,
                message="QuerySpec 与用户问题的语义方向不一致。",
                user_hint="请重新提问并明确要查询的指标、维度和判断方向。",
            ):
                yield event
            return
        fallback_raw = _build_fallback_queryspec(
            question=question,
            intent_result=intent_result,
            datasource=ds_info,
            queryable_fields=field_captions,
            analysis_context=analysis_context,
            reason=QS_VALIDATION_FAILED,
        )
        if fallback_raw:
            queryspec_fallback_used = True
            queryspec_fallback_reason = QS_VALIDATION_FAILED
            yield AgentEvent(type="tool_call", content={
                "tool": "queryspec_fallback",
                "params": {"reason": QS_VALIDATION_FAILED, "intent": intent_result.intent, "code": "QS_OPERATOR_MISMATCH"},
            })
            yield AgentEvent(type="tool_result", content={
                "tool": "queryspec_fallback",
                "result": {
                    "event": FALLBACK_TRIGGERED_EVENT,
                    "data": {
                        "queryspec": _redact_large(fallback_raw),
                        "reason": QS_VALIDATION_FAILED,
                        "original_error": replacement_error,
                        "metrics": _queryspec_trace_metrics(
                            main_path_success=False,
                            fallback_triggered=True,
                            fallback_mode="deterministic_queryspec",
                            fallback_reason=QS_VALIDATION_FAILED,
                        ),
                    },
                },
            })
            try:
                spec = _normalize_queryspec_for_mcp(QuerySpec.model_validate(fallback_raw), question, field_captions, ds_info, analysis_context)
            except Exception as repair_exc:
                async for event in _run_queryspec_mcp_fallback(
                    question=question,
                    context=context,
                    intent_result=intent_result,
                    datasource=ds_info,
                    queryable_fields=field_captions,
                    analysis_context=analysis_context,
                    llm=llm,
                    phase="queryspec_repair",
                    reason=QS_VALIDATION_FAILED,
                    original_error={
                        "queryspec_error": replacement_error,
                        "repair_error": _queryspec_original_error(repair_exc),
                    },
                    error_code=QS_VALIDATION_FAILED,
                    message="QuerySpec 与用户问题的语义方向不一致。",
                    user_hint="请重新提问并明确要查询的指标、维度和判断方向。",
                    failure_fallback_type="query_plan_unavailable",
                ):
                    yield event
                return
        else:
            async for event in _run_queryspec_mcp_fallback(
                question=question,
                context=context,
                intent_result=intent_result,
                datasource=ds_info,
                queryable_fields=field_captions,
                analysis_context=analysis_context,
                llm=llm,
                phase="queryspec_repair",
                reason=QS_VALIDATION_FAILED,
                original_error={
                    "queryspec_error": replacement_error,
                    "repair_error": "deterministic_queryspec_unavailable",
                },
                error_code=QS_VALIDATION_FAILED,
                message="QuerySpec 与用户问题的语义方向不一致。",
                user_hint="请重新提问并明确要查询的指标、维度和判断方向。",
                failure_fallback_type="query_plan_unavailable",
            ):
                yield event
            return

    validation = validate_queryspec(
        spec,
        field_captions,
        {
            "name": ds_info.get("name"),
            "luid": ds_info.get("luid"),
            "metadata_fields": ds_info.get("metadata_fields") or [],
        },
        {
            "accessible_datasource_luids": [ds_info.get("luid")],
            "question": question,
            "analysis_context": analysis_context or {},
        },
    )
    yield AgentEvent(type="tool_call", content={
        "tool": "queryspec_validator",
        "params": {"intent": spec.intent, "operator": spec.effective_operator},
    })
    yield AgentEvent(type="tool_result", content={
        "tool": "queryspec_validator",
        "result": {
            "data": validation.to_dict(),
            "success": validation.passed,
            "metrics": _queryspec_trace_metrics(
                main_path_success=validation.passed and not queryspec_fallback_used,
                fallback_triggered=queryspec_fallback_used,
                fallback_mode="deterministic_queryspec" if queryspec_fallback_used else None,
                fallback_reason=queryspec_fallback_reason,
            ),
        },
    })
    if not validation.passed:
        fallback_raw = None
        initial_validation = validation
        if not queryspec_repair_attempted and spec.source != "deterministic_fallback":
            queryspec_repair_attempted = True
            yield AgentEvent(type="tool_call", content={
                "tool": "llm_queryspec_repair",
                "params": {
                    "reason": QS_VALIDATION_FAILED,
                    "intent": intent_result.intent,
                    "datasource": datasource_payload,
                    "validator_code": validation.code,
                },
            })
            repair_result = await _repair_queryspec_once(
                llm=llm,
                question=question,
                intent=intent_result.intent,
                datasource_payload=datasource_payload,
                queryable_fields=field_captions,
                analysis_context=analysis_context,
                planning_skill_content=planning_skill.content,
                original_output=raw_spec,
                error_summary={"error_code": QS_VALIDATION_FAILED, "validation": validation.to_dict()},
            )
            if repair_result.get("ok"):
                raw_spec = repair_result["json"]
                try:
                    spec = _normalize_queryspec_for_mcp(QuerySpec.model_validate(raw_spec), question, field_captions, ds_info, analysis_context)
                    validation = validate_queryspec(
                        spec,
                        field_captions,
                        {
                            "name": ds_info.get("name"),
                            "luid": ds_info.get("luid"),
                            "metadata_fields": ds_info.get("metadata_fields") or [],
                        },
                        {
                            "accessible_datasource_luids": [ds_info.get("luid")],
                            "question": question,
                            "analysis_context": analysis_context or {},
                        },
                    )
                    yield AgentEvent(type="tool_result", content={
                        "tool": "llm_queryspec_repair",
                        "result": {"data": {"queryspec": _redact_large(raw_spec)}, "success": True},
                    })
                    yield AgentEvent(type="tool_call", content={
                        "tool": "queryspec_validator",
                        "params": {"intent": spec.intent, "operator": spec.effective_operator, "source": spec.source},
                    })
                    yield AgentEvent(type="tool_result", content={
                        "tool": "queryspec_validator",
                        "result": {
                            "data": validation.to_dict(),
                            "success": validation.passed,
                            "metrics": _queryspec_trace_metrics(
                                main_path_success=validation.passed and not queryspec_fallback_used,
                                fallback_triggered=queryspec_fallback_used,
                                fallback_mode="deterministic_queryspec" if queryspec_fallback_used else None,
                                fallback_reason=queryspec_fallback_reason,
                            ),
                        },
                    })
                except Exception as repair_exc:
                    validation = initial_validation
                    repair_result = _queryspec_repair_error_payload(
                        error_code=QS_MODEL_INVALID,
                        original_error=initial_validation.to_dict(),
                        repair_error=repair_exc,
                    )
                    yield AgentEvent(type="tool_result", content={
                        "tool": "llm_queryspec_repair",
                        "result": {"success": False, "error": QS_MODEL_INVALID, "data": repair_result},
                    })
            else:
                yield AgentEvent(type="tool_result", content={
                    "tool": "llm_queryspec_repair",
                    "result": {
                        "success": False,
                        "error": _queryspec_failure_code(repair_result, QS_JSON_INVALID),
                        "data": repair_result,
                    },
                })

        if validation.passed:
            pass
        elif queryspec_fallback_enabled and spec.source != "deterministic_fallback":
            fallback_raw = _build_fallback_queryspec(
                question=question,
                intent_result=intent_result,
                datasource=ds_info,
                queryable_fields=field_captions,
                analysis_context=analysis_context,
                reason=QS_VALIDATION_FAILED,
            )
        if fallback_raw:
            queryspec_fallback_used = True
            queryspec_fallback_reason = QS_VALIDATION_FAILED
            yield AgentEvent(type="tool_call", content={
                "tool": "queryspec_fallback",
                "params": {"reason": QS_VALIDATION_FAILED, "intent": intent_result.intent, "code": validation.code},
            })
            yield AgentEvent(type="tool_result", content={
                "tool": "queryspec_fallback",
                "result": {
                    "event": FALLBACK_TRIGGERED_EVENT,
                    "data": {
                        "queryspec": _redact_large(fallback_raw),
                        "reason": QS_VALIDATION_FAILED,
                        "original_error": validation.to_dict(),
                        "metrics": _queryspec_trace_metrics(
                            main_path_success=False,
                            fallback_triggered=True,
                            fallback_mode="deterministic_queryspec",
                            fallback_reason=QS_VALIDATION_FAILED,
                        ),
                    },
                },
            })
            try:
                spec = _normalize_queryspec_for_mcp(QuerySpec.model_validate(fallback_raw), question, field_captions, ds_info, analysis_context)
            except Exception as repair_exc:
                async for event in _run_queryspec_mcp_fallback(
                    question=question,
                    context=context,
                    intent_result=intent_result,
                    datasource=ds_info,
                    queryable_fields=field_captions,
                    analysis_context=analysis_context,
                    llm=llm,
                    phase="queryspec_repair",
                    reason=QS_VALIDATION_FAILED,
                    original_error={
                        "queryspec_error": initial_validation.to_dict(),
                        "repair_error": _queryspec_original_error(repair_exc),
                    },
                    error_code=QS_VALIDATION_FAILED,
                    message=initial_validation.message,
                    user_hint=initial_validation.user_hint,
                    failure_fallback_type="query_plan_unavailable",
                ):
                    yield event
                return
            validation = validate_queryspec(
                spec,
                field_captions,
                {
                    "name": ds_info.get("name"),
                    "luid": ds_info.get("luid"),
                    "metadata_fields": ds_info.get("metadata_fields") or [],
                },
                {
                    "accessible_datasource_luids": [ds_info.get("luid")],
                    "question": question,
                    "analysis_context": analysis_context or {},
                },
            )
            yield AgentEvent(type="tool_call", content={
                "tool": "queryspec_validator",
                "params": {"intent": spec.intent, "operator": spec.effective_operator, "source": spec.source},
            })
            yield AgentEvent(type="tool_result", content={
                "tool": "queryspec_validator",
                "result": {
                    "data": validation.to_dict(),
                    "success": validation.passed,
                    "metrics": _queryspec_trace_metrics(
                        main_path_success=False,
                        fallback_triggered=True,
                        fallback_mode="deterministic_queryspec",
                        fallback_reason=queryspec_fallback_reason,
                    ),
                },
            })
        if not validation.passed:
            rejection_detail = dict(validation.detail or {})
            rejection_detail.update({
                "fallback_reason": QS_VALIDATION_FAILED,
                "validator_code": validation.code,
                "initial_validation": initial_validation.to_dict(),
            })
            async for event in _run_queryspec_mcp_fallback(
                question=question,
                context=context,
                intent_result=intent_result,
                datasource=ds_info,
                queryable_fields=field_captions,
                analysis_context=analysis_context,
                llm=llm,
                phase="queryspec_repair" if queryspec_repair_attempted else "queryspec_validation",
                reason=QS_VALIDATION_FAILED,
                original_error=rejection_detail,
                error_code=QS_VALIDATION_FAILED,
                message=validation.message,
                user_hint=validation.user_hint,
                failure_fallback_type="query_plan_unavailable" if queryspec_repair_attempted else "query_plan_rejected",
            ):
                yield event
            return

    yield AgentEvent(type="tool_call", content={
        "tool": "tableau_mcp",
        "params": {"operator": spec.effective_operator, "datasource_luid": ds_info.get("luid")},
    })
    try:
        mcp_data = await _execute_queryspec(spec, ds_info, context, question, queryable_fields=field_captions)
    except DataContinuityError as exc:
        logger.warning("semantic operator data continuity failed: %s", exc)
        yield AgentEvent(type="tool_result", content={
            "tool": "tableau_mcp",
            "result": {
                "success": False,
                "error": str(exc),
                "error_code": exc.code,
                "data": {"error": str(exc), "error_code": exc.code, "detail": exc.detail},
            },
        })
        yield AgentEvent(type="error", content=_fallback_payload(
            error_code=exc.code,
            message="MCP 返回数据不满足语义算子的连续性要求，本次不输出结论。",
            user_hint="请检查数据源周期是否完整，或缩小时间范围后重试。",
            trace_id=context.trace_id,
            intent_result=intent_result,
            fallback_type="query_plan_unavailable",
            detail={"reason": exc.code, "operator": spec.effective_operator, "detail": exc.detail},
        ))
        return
    except Exception as exc:
        logger.exception("controlled MCP execution failed")
        yield AgentEvent(type="tool_result", content={
            "tool": "tableau_mcp",
            "result": {"success": False, "error": str(exc), "data": {"error": str(exc)}},
        })
        async for event in _run_queryspec_mcp_fallback(
            question=question,
            context=context,
            intent_result=intent_result,
            datasource=ds_info,
            queryable_fields=field_captions,
            analysis_context=analysis_context,
            llm=llm,
            phase="queryspec_mcp_execution",
            reason="mcp_execution_failed",
            original_error=exc,
            error_code="mcp_execution_failed",
            message="Tableau MCP 查询失败，本次不输出结论。",
            user_hint="请稍后重试；如果持续失败，请带 trace_id 联系管理员排查 Tableau/MCP 执行日志。",
            failure_fallback_type="query_plan_unavailable",
        ):
            yield event
        return
    yield AgentEvent(type="tool_result", content={
        "tool": "tableau_mcp",
        "result": {"data": mcp_data},
    })
    mcp_data = _apply_result_guardrail(
        question=question,
        chain_mode=MCP_MAIN_CHAIN_MODE,
        response_data=mcp_data,
        semantic_operator=str(spec.effective_operator or "unknown"),
        fallback_triggered=bool(queryspec_fallback_used),
        fallback_reason=queryspec_fallback_reason,
    )
    guardrail = mcp_data.get("result_guardrail") if isinstance(mcp_data.get("result_guardrail"), Mapping) else {}
    if guardrail.get("decision") == "block":
        yield AgentEvent(type="error", content=_fallback_payload(
            error_code=str(guardrail.get("error_code") or DETAIL_SCAN_BLOCKED),
            message=str(guardrail.get("message") or "结果触发质量门禁，已阻断回答。"),
            user_hint="请缩小时间范围、减少明细粒度后重试。",
            trace_id=context.trace_id,
            intent_result=intent_result,
            fallback_type="query_plan_unavailable",
            detail={
                "reason": RESULT_GUARDRAIL_BLOCKED,
                "result_guardrail": guardrail,
                "chain_mode": MCP_MAIN_CHAIN_MODE,
            },
        ))
        return

    rendering_skill = loader.load_rendering("answer_renderer")
    yield AgentEvent(type="tool_call", content={
        "tool": "rendering_skill_loader",
        "params": {"skill_key": "answer_renderer", "kind": "rendering"},
    })
    yield AgentEvent(type="tool_result", content={
        "tool": "rendering_skill_loader",
        "result": {"data": _skill_result_summary(rendering_skill)},
    })
    if not rendering_skill.ok or not rendering_skill.content:
        rendered = _render_deterministic_answer(mcp_data, spec)
        yield AgentEvent(type="tool_call", content={
            "tool": "answer_renderer",
            "params": {
                "renderer": "deterministic_table",
                "reason": "answer_render_unavailable",
                "row_count": len(mcp_data.get("rows") or []),
            },
        })
        yield AgentEvent(type="tool_result", content={
            "tool": "answer_renderer",
            "result": {
                "success": False,
                "error": "answer_render_unavailable",
                "data": mcp_data,
                "renderer": "deterministic_table",
                "fallback_answer": rendered,
            },
        })
        yield AgentEvent(type="answer", content=rendered)
        return

    if spec.source == "deterministic_fallback":
        rendered = _render_deterministic_answer(mcp_data, spec)
        yield AgentEvent(type="tool_call", content={
            "tool": "answer_renderer",
            "params": {"renderer": "deterministic_table", "row_count": len(mcp_data.get("rows") or [])},
        })
        yield AgentEvent(type="tool_result", content={
            "tool": "answer_renderer",
            "result": {"data": mcp_data, "renderer": "deterministic_table"},
        })
        yield AgentEvent(type="answer", content=rendered)
        return

    answer_messages = build_answer_prompt(
        question=question,
        response_data=mcp_data,
        rendering_skill_content=rendering_skill.content,
    )
    yield AgentEvent(type="tool_call", content={
        "tool": "answer_renderer",
        "params": {"skill_checksum": rendering_skill.checksum, "row_count": len(mcp_data.get("rows") or [])},
    })
    rendered = await _call_llm_text(llm, answer_messages, purpose="data_agent_answer")
    answer_consistency = _answer_consistency_check(rendered, mcp_data, spec, question)
    answer_replacement_reason = answer_consistency["reason"] if answer_consistency["status"] != "pass" else None
    if answer_replacement_reason:
        rendered = _render_deterministic_answer(mcp_data, spec)
        yield AgentEvent(type="tool_result", content={
            "tool": "answer_renderer",
            "result": {
                "success": False,
                "error": answer_replacement_reason,
                "data": mcp_data,
                "renderer": "deterministic_table",
                "fallback_answer": rendered,
                "consistency": answer_consistency,
            },
        })
        yield AgentEvent(type="answer", content=rendered)
        return

    yield AgentEvent(type="tool_result", content={
        "tool": "answer_renderer",
        "result": {"data": mcp_data, "consistency": answer_consistency},
    })
    yield AgentEvent(type="answer", content=rendered)


def _resolve_datasource(question: str, context: ToolContext, datasource_name_hint: Optional[str]) -> Optional[dict[str, Any]]:
    if datasource_name_hint:
        try:
            from services.data_agent.tools.query_tool import _lookup_datasource_by_name

            matched = _lookup_datasource_by_name(datasource_name_hint, connection_id=context.connection_id)
            if matched:
                return matched
        except Exception:
            logger.debug("datasource hint lookup skipped", exc_info=True)
    return route_datasource(question, connection_id=context.connection_id)


def _queryable_field_context(
    ds_info: Mapping[str, Any],
    connection_id: Optional[int] = None,
) -> tuple[list[str], list[dict[str, Any]]]:
    luid = ds_info.get("luid")
    if luid and connection_id:
        try:
            from services.tableau.mcp_client import get_tableau_mcp_client

            metadata = get_tableau_mcp_client(connection_id=connection_id).get_datasource_metadata(
                str(luid),
                timeout=20,
            )
            field_metadata = extract_mcp_field_metadata(metadata)
            mcp_fields = _field_metadata_names(field_metadata)
            if mcp_fields:
                if isinstance(ds_info, dict):
                    ds_info.setdefault("queryable_fields", mcp_fields)
                return mcp_fields, field_metadata
        except Exception:
            logger.warning("MCP metadata fields unavailable; falling back to local cache", exc_info=True)

    asset_id = ds_info.get("asset_id")
    if not asset_id:
        return [], []
    local_context = _local_field_capability_context(asset_id)
    if isinstance(ds_info, dict):
        ds_info.update({key: value for key, value in local_context.items() if value not in (None, [], {})})
    fields = local_context.get("queryable_fields") or []
    return [str(field) for field in fields if str(field or "").strip()], []


def _queryable_fields(ds_info: Mapping[str, Any], connection_id: Optional[int] = None) -> list[str]:
    fields, metadata = _queryable_field_context(ds_info, connection_id=connection_id)
    if metadata and isinstance(ds_info, dict):
        ds_info.setdefault("metadata_fields", metadata)
    return fields


def _local_field_capability_context(asset_id: Any) -> dict[str, Any]:
    if not asset_id:
        return {}
    try:
        from app.core.database import SessionLocal
        from services.tableau.field_reconciliation import queryability_status, summarize_field_capabilities
        from services.tableau.models import TableauDatasourceField

        session = SessionLocal()
        try:
            rows = (
                session.query(TableauDatasourceField)
                .filter(TableauDatasourceField.asset_id == int(asset_id))
                .order_by(TableauDatasourceField.role, TableauDatasourceField.field_name)
                .all()
            )
            catalog_fields = [_catalog_field_name(row) for row in rows if _catalog_field_name(row)]
            queryable_fields = [_catalog_field_name(row) for row in rows if getattr(row, "mcp_queryable", None) is True and _catalog_field_name(row)]
            catalog_only_fields = [
                _catalog_field_name(row)
                for row in rows
                if queryability_status(row) == "catalog_only" and _catalog_field_name(row)
            ]
            return {
                "catalog_fields": catalog_fields,
                "queryable_fields": queryable_fields,
                "catalog_only_fields": catalog_only_fields,
                "field_capability_summary": summarize_field_capabilities(rows),
            }
        finally:
            session.close()
    except Exception:
        logger.debug("local field capability context unavailable", exc_info=True)
        return {}


def _catalog_field_name(row: Any) -> str:
    return str(getattr(row, "field_caption", None) or getattr(row, "field_name", None) or "").strip()


def _catalog_only_preflight(
    question: str,
    ds_info: Mapping[str, Any],
    queryable_fields: list[str],
) -> Optional[dict[str, Any]]:
    context = _catalog_queryable_context(ds_info, queryable_fields)
    catalog_only_fields = context.get("catalog_only_fields") or []
    if not catalog_only_fields:
        return None
    queryable = context.get("queryable_fields") or queryable_fields
    mentioned = _mentioned_catalog_only_fields(question, catalog_only_fields, queryable)
    if not mentioned:
        return None
    return {
        "fields": mentioned,
        "alternatives": _queryable_alternatives(mentioned[0], queryable),
        "catalog_field_count": len(context.get("catalog_fields") or []),
        "queryable_field_count": len(queryable),
        "catalog_only_count": len(catalog_only_fields),
    }


def _catalog_queryable_context(ds_info: Mapping[str, Any], queryable_fields: list[str]) -> dict[str, Any]:
    local_context = {}
    if not ds_info.get("catalog_fields") and ds_info.get("asset_id"):
        local_context = _local_field_capability_context(ds_info.get("asset_id"))
    catalog_fields = list(ds_info.get("catalog_fields") or local_context.get("catalog_fields") or [])
    queryable = list(queryable_fields or ds_info.get("queryable_fields") or local_context.get("queryable_fields") or [])
    queryable_norm = {normalize_field_name(field) for field in queryable}
    explicit_catalog_only = list(ds_info.get("catalog_only_fields") or local_context.get("catalog_only_fields") or [])
    if explicit_catalog_only:
        catalog_only = explicit_catalog_only
    elif catalog_fields and queryable:
        catalog_only = [
            field
            for field in catalog_fields
            if normalize_field_name(field) and normalize_field_name(field) not in queryable_norm
        ]
    else:
        catalog_only = []
    if isinstance(ds_info, dict):
        ds_info.setdefault("catalog_fields", catalog_fields)
        ds_info.setdefault("queryable_fields", queryable)
        ds_info.setdefault("catalog_only_fields", catalog_only)
        if local_context.get("field_capability_summary"):
            ds_info.setdefault("field_capability_summary", local_context["field_capability_summary"])
    return {
        "catalog_fields": catalog_fields,
        "queryable_fields": queryable,
        "catalog_only_fields": catalog_only,
    }


def _mentioned_catalog_only_fields(question: str, catalog_only_fields: list[str], queryable_fields: list[str]) -> list[str]:
    normalized_question = normalize_field_name(question)
    queryable_norm = {normalize_field_name(field) for field in queryable_fields}
    matches: list[str] = []
    seen: set[str] = set()
    for field in catalog_only_fields:
        normalized = normalize_field_name(field)
        if not normalized or normalized in queryable_norm:
            continue
        if normalized == normalized_question or (len(normalized) >= 2 and normalized in normalized_question):
            if normalized not in seen:
                seen.add(normalized)
                matches.append(field)
    return matches


def _queryable_alternatives(field: str, queryable_fields: list[str]) -> list[str]:
    scored: list[tuple[int, str]] = []
    for candidate in queryable_fields:
        score = 0
        if normalize_field_name(field) in normalize_field_name(candidate) or normalize_field_name(candidate) in normalize_field_name(field):
            score += 3
        for marker in ("日期", "年份", "时间", "年", "月", "区域", "省", "类", "客户", "销售", "利润", "数量"):
            if marker in field and marker in candidate:
                score += 2
        if score:
            scored.append((score, candidate))
    scored.sort(key=lambda item: (-item[0], item[1]))
    return [candidate for _, candidate in scored[:3]]


def _catalog_only_error_payload(
    preflight_error: Mapping[str, Any],
    trace_id: str,
    intent_result: IntentClassification,
    *,
    chain_mode: str,
) -> dict[str, Any]:
    fields = [str(field) for field in preflight_error.get("fields") or [] if str(field or "").strip()]
    alternatives = [str(field) for field in preflight_error.get("alternatives") or [] if str(field or "").strip()]
    field_text = "、".join(fields) if fields else "该字段"
    alt_text = f"当前可替代字段有：{'、'.join(alternatives)}。" if alternatives else "当前没有可自动替代的 Agent 可查询字段。"
    return _mcp_passthrough_error_payload(
        MCP_CATALOG_ONLY_FIELD,
        f"字段存在于 Tableau 资产目录，但当前 Agent/MCP 不支持查询：{field_text}",
        f"{alt_text} 请调整问题后再查询。",
        trace_id,
        intent_result,
        chain_mode=chain_mode,
        detail={
            "chain_mode": chain_mode,
            "reason": "catalog_only_field_preflight",
            "catalog_only_fields": fields,
            "alternatives": alternatives,
            "catalog_field_count": preflight_error.get("catalog_field_count"),
            "queryable_field_count": preflight_error.get("queryable_field_count"),
            "catalog_only_count": preflight_error.get("catalog_only_count"),
        },
    )


def _field_metadata_names(fields: list[dict[str, Any]]) -> list[str]:
    return [name for item in fields if (name := field_display_name(item))]


async def _call_llm_json(llm: LLMService, messages: list[dict[str, str]], *, purpose: str) -> dict[str, Any]:
    try:
        result = await llm.complete(
            prompt=messages[-1]["content"],
            system=messages[0]["content"],
            timeout=JSON_PLANNING_TIMEOUT_SECONDS,
            purpose=purpose,
        )
    except Exception as exc:
        logger.warning("LLM QuerySpec generation failed: %s", exc)
        return _llm_exception_failure(exc)
    if "content" not in result and result.get("error"):
        return _llm_result_failure(result)
    content = (result.get("content") or "").strip()
    if not content:
        error_code = result.get("error_code") or LLM_EMPTY_RESPONSE
        return {
            "ok": False,
            "error": error_code,
            "error_code": error_code,
            "message": result.get("error") or "LLM provider 返回空文本",
            "detail": _redact_large(result),
        }
    if purpose == "data_agent_queryspec":
        return _parse_queryspec_json_content(content)
    try:
        return {"ok": True, "json": json.loads(_strip_json_fence(content))}
    except json.JSONDecodeError as exc:
        extracted = _extract_first_json_object(content)
        if extracted:
            try:
                return {"ok": True, "json": json.loads(extracted)}
            except json.JSONDecodeError:
                pass
        return {
            "ok": False,
            "error": "JSON_INVALID",
            "error_code": "JSON_INVALID",
            "message": f"invalid_json: {exc}",
            "raw": content[:1000],
        }


async def _call_llm_text(llm: LLMService, messages: list[dict[str, str]], *, purpose: str) -> str:
    try:
        result = await llm.complete(
            prompt=messages[-1]["content"],
            system=messages[0]["content"],
            timeout=45,
            purpose=purpose,
        )
    except Exception:
        logger.warning("LLM answer rendering failed", exc_info=True)
        return ""
    return (result.get("content") or "").strip()


async def _repair_queryspec_once(
    *,
    llm: LLMService,
    question: str,
    intent: str,
    datasource_payload: Mapping[str, Any],
    queryable_fields: list[str],
    analysis_context: Optional[Mapping[str, Any]],
    planning_skill_content: str,
    original_output: Any,
    error_summary: Any,
) -> dict[str, Any]:
    messages = build_queryspec_repair_prompt(
        question=question,
        intent=intent,
        datasource=datasource_payload,
        queryable_fields=queryable_fields,
        analysis_context=analysis_context or {},
        original_output=original_output,
        error_summary=error_summary,
        planning_skill_content=planning_skill_content,
    )
    return await _call_llm_json(llm, messages, purpose="data_agent_queryspec")


def _queryspec_failure_code(value: Mapping[str, Any] | BaseException | None, default: str) -> str:
    if isinstance(value, Mapping):
        return str(value.get("error_code") or value.get("error") or default)
    return default


def _is_queryspec_repairable(error_code: str) -> bool:
    return error_code in QUERYSPEC_REPAIRABLE_ERROR_CODES and error_code not in NON_REPAIRABLE_LLM_ERROR_CODES


def _queryspec_repair_error_payload(
    *,
    error_code: str,
    original_error: Any,
    repair_error: Any,
) -> dict[str, Any]:
    return {
        "error_code": error_code,
        "queryspec_error": _queryspec_original_error(original_error),
        "repair_error": _queryspec_original_error(repair_error),
    }


def _strip_json_fence(content: str) -> str:
    stripped = content.strip()
    fenced = re.match(r"^```(?:json)?\s*(.*?)\s*```$", stripped, flags=re.DOTALL | re.IGNORECASE)
    return fenced.group(1).strip() if fenced else stripped


def _extract_first_json_object(content: str) -> Optional[str]:
    for item in _iter_json_objects(content):
        return item
    return None


def _parse_queryspec_json_content(content: str) -> dict[str, Any]:
    stripped = _strip_json_fence(content)
    first_error: dict[str, Any] | None = None

    try:
        parsed = json.loads(stripped)
    except json.JSONDecodeError as exc:
        code = QS_JSON_INVALID if "{" in stripped else QS_JSON_NOT_FOUND
        first_error = {
            "ok": False,
            "error": code,
            "error_code": code,
            "message": f"invalid_json: {exc}",
            "raw": content[:1000],
        }
    else:
        rejection = _queryspec_contract_rejection(parsed)
        if rejection is None:
            return {"ok": True, "json": parsed}
        first_error = _queryspec_json_failure(rejection, content)

    for candidate in _iter_json_objects(content):
        try:
            parsed = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        rejection = _queryspec_contract_rejection(parsed)
        if rejection is None:
            return {"ok": True, "json": parsed}
        if first_error is None:
            first_error = _queryspec_json_failure(rejection, content)

    if first_error is not None:
        return first_error
    code = QS_JSON_INVALID if "{" in content else QS_JSON_NOT_FOUND
    return {
        "ok": False,
        "error": code,
        "error_code": code,
        "message": "未找到满足 QuerySpec 顶层契约的 JSON object。",
        "raw": content[:1000],
    }


def _queryspec_contract_rejection(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, Mapping):
        return {"code": QS_JSON_INVALID, "reason": "queryspec_top_level_not_object"}
    intent = value.get("intent")
    operator = value.get("operator")
    if not isinstance(intent, str) or intent not in ALLOWED_INTENTS:
        return {"code": QS_JSON_NOT_FOUND, "reason": "queryspec_intent_missing_or_invalid"}
    if operator is not None and (not isinstance(operator, str) or operator not in ALLOWED_OPERATORS):
        return {"code": QS_JSON_NOT_FOUND, "reason": "queryspec_operator_invalid"}
    required = ("datasource", "metrics", "dimensions", "filters")
    missing = [key for key in required if key not in value]
    if missing:
        return {"code": QS_JSON_NOT_FOUND, "reason": "queryspec_required_fields_missing", "missing": missing}
    if not isinstance(value.get("datasource"), Mapping):
        return {"code": QS_JSON_INVALID, "reason": "queryspec_datasource_not_object"}
    if not isinstance(value.get("metrics"), list):
        return {"code": QS_JSON_INVALID, "reason": "queryspec_metrics_not_list"}
    if not isinstance(value.get("dimensions"), list):
        return {"code": QS_JSON_INVALID, "reason": "queryspec_dimensions_not_list"}
    if not isinstance(value.get("filters"), list):
        return {"code": QS_JSON_INVALID, "reason": "queryspec_filters_not_list"}
    return None


def _queryspec_json_failure(rejection: Mapping[str, Any], content: str) -> dict[str, Any]:
    code = str(rejection.get("code") or QS_JSON_INVALID)
    return {
        "ok": False,
        "error": code,
        "error_code": code,
        "message": "未找到满足 QuerySpec 顶层契约的 JSON object。",
        "detail": dict(rejection),
        "raw": content[:1000],
    }


def _iter_json_objects(content: str) -> list[str]:
    objects: list[str] = []
    for start, char in enumerate(content):
        if char != "{":
            continue
        depth = 0
        in_string = False
        escape = False
        for index, current in enumerate(content[start:], start=start):
            if in_string:
                if escape:
                    escape = False
                elif current == "\\":
                    escape = True
                elif current == '"':
                    in_string = False
                continue
            if current == '"':
                in_string = True
            elif current == "{":
                depth += 1
            elif current == "}":
                depth -= 1
                if depth == 0:
                    objects.append(content[start:index + 1])
                    break
    return objects


def _llm_result_failure(result: Mapping[str, Any]) -> dict[str, Any]:
    error_code = str(result.get("error_code") or LLM_PROVIDER_ERROR)
    return {
        "ok": False,
        "error": error_code,
        "error_code": error_code,
        "message": str(result.get("error") or error_code),
        "detail": _redact_large(dict(result)),
    }


def _llm_exception_failure(exc: BaseException) -> dict[str, Any]:
    detail = getattr(exc, "error_detail", None)
    if not isinstance(detail, Mapping):
        raw_detail = getattr(exc, "detail", None)
        if isinstance(raw_detail, Mapping):
            nested = raw_detail.get("detail")
            detail = nested if isinstance(nested, Mapping) else raw_detail
    if isinstance(detail, Mapping):
        attempts = detail.get("attempts")
        error_code = detail.get("error_code") or _last_attempt_error_code(attempts)
        if error_code:
            return {
                "ok": False,
                "error": str(error_code),
                "error_code": str(error_code),
                "message": str(getattr(exc, "message", "") or error_code),
                "detail": _redact_large(dict(detail)),
            }
    error_code = _classify_llm_exception_text(exc)
    return {
        "ok": False,
        "error": error_code,
        "error_code": error_code,
        "message": str(exc)[:500],
    }


def _last_attempt_error_code(attempts: Any) -> Optional[str]:
    if not isinstance(attempts, list):
        return None
    for attempt in reversed(attempts):
        if isinstance(attempt, Mapping) and attempt.get("error_code"):
            return str(attempt["error_code"])
    return None


def _classify_llm_exception_text(exc: BaseException) -> str:
    text = f"{exc.__class__.__name__} {exc}".lower()
    if "timeout" in text or "timed out" in text:
        return LLM_PROVIDER_TIMEOUT
    if "auth" in text or "unauthorized" in text or "api key" in text:
        return LLM_AUTH_CONFIG_ERROR
    return LLM_PROVIDER_ERROR


async def _execute_queryspec(
    spec: QuerySpec,
    ds_info: Mapping[str, Any],
    context: ToolContext,
    question: str,
    *,
    queryable_fields: Optional[list[str]] = None,
) -> dict[str, Any]:
    token = _QUERYABLE_FIELDS_CONTEXT.set(tuple(queryable_fields or []))
    try:
        operator = spec.effective_operator
        if operator == "asset_inventory":
            raise ValueError("asset_inventory is handled by deterministic schema route")

        if operator == "aggregate":
            vizql = _vizql_from_queryspec(spec)
            result = await _execute_vizql(ds_info["luid"], vizql, context, question, limit=spec.limit or 1000)
            return _normalize_mcp_data(result, spec, ds_info)

        if operator == "trend_condition" and not spec.dimensions:
            vizql = _vizql_from_queryspec(spec)
            result = await _execute_vizql(ds_info["luid"], vizql, context, question, limit=spec.limit or 100)
            return _normalize_mcp_data(result, spec, ds_info)

        registry = default_registry()
        semantic_operator = registry.get(operator)
        ctx = _query_plan_context(spec, ds_info, context, question)
        steps = semantic_operator.build_steps(ctx)
        step_results: dict[str, dict[str, Any]] = {}
        for step in steps:
            step_results[step.name] = await _execute_vizql(
                ds_info["luid"],
                step.vizql_json,
                context,
                question,
                limit=step.mcp_limit(),
            )
        reduced = semantic_operator.reduce(ctx, step_results)
        return _operator_result_to_data(reduced, ds_info, spec, step_results)
    finally:
        _QUERYABLE_FIELDS_CONTEXT.reset(token)


async def _execute_vizql(
    datasource_luid: str,
    vizql_json: dict[str, Any],
    context: ToolContext,
    question: str,
    *,
    limit: int,
) -> dict[str, Any]:
    from services.data_agent.mcp_args_guardrail import (
        McpArgsGuardrailRejected,
        validate_query_datasource_args,
    )
    from services.data_agent.tools.query_tool import _execute_query_with_date_fallback

    queryable_fields = list(_QUERYABLE_FIELDS_CONTEXT.get()) or _field_names_from_vizql(vizql_json)
    guardrail = validate_query_datasource_args(
        question=question,
        datasource_luid=datasource_luid,
        query=vizql_json,
        limit=limit,
        timeout=None,
        connection_id=context.connection_id,
        queryable_fields=queryable_fields,
        current_datasource={
            "luid": datasource_luid,
            "connection_id": context.connection_id,
        },
        user_context={
            "user_id": context.user_id,
            "connection_id": context.connection_id,
            "accessible_datasource_luids": [datasource_luid],
            **({"accessible_connection_ids": [context.connection_id]} if context.connection_id is not None else {}),
        },
    )
    if guardrail.decision == "reject":
        raise McpArgsGuardrailRejected(guardrail)

    safe_args = guardrail.args or {}
    safe_query = safe_args.get("query") if isinstance(safe_args.get("query"), dict) else vizql_json
    safe_limit = int(safe_args.get("limit") or limit)
    result, _effective_vizql, substitutions = await _execute_query_with_date_fallback(
        datasource_luid=str(safe_args.get("datasourceLuid") or datasource_luid),
        vizql_json=safe_query,
        connection_id=context.connection_id,
        question=question,
        limit=safe_limit,
    )
    if substitutions:
        result = dict(result)
        result["field_substitutions"] = substitutions
    if inspect.isawaitable(result):
        result = await result
    if isinstance(result, dict):
        result.setdefault("mcp_args_guardrail", guardrail.to_dict())
    return result


def _vizql_from_queryspec(spec: QuerySpec) -> dict[str, Any]:
    fields: list[dict[str, Any]] = []
    if spec.time and spec.time.field and spec.time.grain:
        fields.append({"fieldCaption": spec.time.field, "function": spec.time.grain})
    fields.extend({"fieldCaption": dimension} for dimension in spec.dimensions)
    metric_fields = [_metric_to_vizql(metric, _effective_sorts(spec)) for metric in spec.metrics]
    fields.extend(metric_fields)
    return {"fields": fields, "filters": _filters_from_queryspec(spec)}


def _field_names_from_vizql(vizql_json: Mapping[str, Any]) -> list[str]:
    names: list[str] = []
    seen: set[str] = set()

    def add(value: Any) -> None:
        name = str(value or "").strip()
        if name and name not in seen:
            seen.add(name)
            names.append(name)

    def visit(node: Any) -> None:
        if isinstance(node, Mapping):
            for key in ("fieldCaption", "fieldName", "field", "name", "caption"):
                add(node.get(key))
            for value in node.values():
                if isinstance(value, (Mapping, list)):
                    visit(value)
        elif isinstance(node, list):
            for item in node:
                if isinstance(item, str):
                    add(item)
                else:
                    visit(item)

    visit(vizql_json)
    return names


def _effective_sorts(spec: QuerySpec) -> list[SortSpec]:
    if spec.sort:
        return list(spec.sort)
    if spec.effective_operator != "aggregate" or not spec.metrics:
        return []
    if spec.dimensions and not spec.time:
        metric = spec.metrics[0]
        sort_field = f"{metric.aggregation}({metric.field})" if metric.aggregation else metric.field
        return [SortSpec(field=sort_field, direction="DESC")]
    return []


def _metric_to_vizql(metric: MetricSpec, sorts: list[SortSpec]) -> dict[str, Any]:
    field = {"fieldCaption": metric.field}
    if metric.aggregation:
        field["function"] = metric.aggregation
    sort = _matching_metric_sort(metric, sorts)
    if sort:
        field["sortDirection"] = sort.direction
        field["sortPriority"] = 1
    if metric.alias:
        field["fieldAlias"] = metric.alias
    return field


def _matching_metric_sort(metric: MetricSpec, sorts: list[SortSpec]) -> Optional[SortSpec]:
    expected = (
        f"{metric.aggregation}({metric.field})" if metric.aggregation else metric.field
    ).casefold().replace(" ", "")
    for sort in sorts:
        if sort.field.casefold().replace(" ", "") in {expected, metric.field.casefold().replace(" ", "")}:
            return sort
    return None


def _filters_from_queryspec(spec: QuerySpec) -> list[dict[str, Any]]:
    filters = [_filter_to_vizql(item) for item in spec.filters]
    if spec.time:
        time_filter = _time_filter_to_vizql(spec.time.field, spec.time.range)
        if time_filter:
            filters.append(time_filter)
    return [item for item in filters if item]


def _filter_to_vizql(filter_spec: FilterSpec) -> dict[str, Any]:
    values = filter_spec.values or ([] if filter_spec.value is None else [filter_spec.value])
    if filter_spec.op in {"IN", "=", "=="}:
        return {"field": {"fieldCaption": filter_spec.field}, "filterType": "SET", "values": values}
    return {"field": {"fieldCaption": filter_spec.field}, "filterType": "SET", "values": values}


def _time_filter_to_vizql(field: str, range_spec: Mapping[str, Any]) -> Optional[dict[str, Any]]:
    if not field or not range_spec:
        return None
    value = range_spec.get("value")
    if value and str(value).isdigit() and len(str(value)) == 4:
        year = int(value)
        return _year_date_filter(field, year)
    start = range_spec.get("start") or range_spec.get("from") or range_spec.get("start_year")
    end = range_spec.get("end") or range_spec.get("to") or range_spec.get("end_year")
    if start and end and str(start).isdigit() and str(end).isdigit():
        return {
            "field": {"fieldCaption": field},
            "filterType": "QUANTITATIVE_DATE",
            "quantitativeFilterType": "RANGE",
            "minDate": f"{int(start)}-01-01",
            "maxDate": f"{int(end)}-12-31",
        }
    return None


def _year_date_filter(field: str, year: int) -> dict[str, Any]:
    return {
        "field": {"fieldCaption": field},
        "filterType": "QUANTITATIVE_DATE",
        "quantitativeFilterType": "RANGE",
        "minDate": f"{year}-01-01",
        "maxDate": f"{year}-12-31",
    }


def _query_plan_context(
    spec: QuerySpec,
    ds_info: Mapping[str, Any],
    context: ToolContext,
    question: str,
) -> QueryPlanContext:
    params = dict(spec.params or {})
    params.update(spec.operator_spec or {})
    if spec.limit:
        params.setdefault("n", spec.limit)
        params.setdefault("top_n", spec.limit)
        params.setdefault("top_n_per_dimension", spec.limit)
        params.setdefault("max_groups", spec.limit)
        params.setdefault("max_rows", min(max(spec.limit * 10, 100), 1000))
    if spec.direction:
        params.setdefault("direction", spec.direction)
    if spec.sort:
        params.setdefault("sort_direction", spec.sort[0].direction)
    if spec.time and spec.time.grain:
        params.setdefault("period_function", spec.time.grain)
    if spec.time and spec.time.range:
        params.setdefault("time_range", spec.time.range)
        range_years = _range_years(spec.time.range)
        if range_years:
            params.setdefault("expected_periods", range_years)
    if spec.breakdown_dimensions:
        params.setdefault("candidate_dimensions", spec.breakdown_dimensions)
    if spec.metrics:
        params.setdefault("metrics", [metric.model_dump(mode="json") for metric in spec.metrics])
    if spec.universe:
        params.setdefault("target_dimension", spec.universe.target_dimension)
        params.setdefault("universe_filters", _clause_filters(spec.universe))
    if spec.occurred:
        params.setdefault("occurred_filters", _clause_filters(spec.occurred))
    return QueryPlanContext(
        question=question,
        datasource_luid=str(ds_info.get("luid") or ""),
        datasource_name=str(ds_info.get("name") or ""),
        connection_id=context.connection_id,
        fields=[],
        trace_id=context.trace_id,
        intent="analysis",
        metric=spec.metrics[0].field if spec.metrics else None,
        dimensions=spec.breakdown_dimensions or spec.dimensions,
        time_field=spec.time.field if spec.time else None,
        filters=_filters_from_queryspec(spec),
        operator_hint=spec.effective_operator,
        params=params,
    )


def _clause_filters(clause: Any) -> list[dict[str, Any]]:
    filters = [_filter_to_vizql(item) for item in (clause.filters or [])]
    if clause.time:
        time_filter = _time_filter_to_vizql(clause.time.field, clause.time.range)
        if time_filter:
            filters.append(time_filter)
    return filters


def _normalize_mcp_data(result: Mapping[str, Any], spec: QuerySpec, ds_info: Mapping[str, Any]) -> dict[str, Any]:
    fields = list(result.get("fields") or [])
    rows = [list(row) if isinstance(row, list) else row for row in list(result.get("rows") or [])]
    dce_shadow = _derived_metric_shadow_diagnostics(fields, rows, spec)
    rows = _sort_result_rows(fields, rows, spec)
    payload = {
        "fields": fields,
        "rows": rows,
        "intent": spec.intent,
        "operator": spec.effective_operator,
        "confidence": 0.95,
        "datasource_name": ds_info.get("name"),
        "datasource_luid": ds_info.get("luid"),
        "queryspec": spec.model_dump(mode="json"),
        "table_display": infer_table_display_schema(
            fields,
            rows,
            operator=spec.effective_operator,
            metric_names=_table_metric_names(spec),
        ),
        **({"field_substitutions": result["field_substitutions"]} if result.get("field_substitutions") else {}),
        **({"mcp_args_guardrail": result["mcp_args_guardrail"]} if result.get("mcp_args_guardrail") else {}),
    }
    if dce_shadow:
        diagnostics = dict(result.get("diagnostics") or {})
        diagnostics["dynamic_column_engine_shadow"] = dce_shadow
        payload["diagnostics"] = diagnostics
    return payload


def _table_metric_names(spec: QuerySpec) -> list[str]:
    names = [metric.field for metric in spec.metrics if metric.field]
    names.extend(metric.name for metric in spec.derived_metrics if metric.name)
    requested = _requested_derived_metrics(spec)
    names.extend(name for name in requested if name not in names)
    return names


def _append_derived_metric_columns(
    fields: list[Any],
    rows: list[Any],
    spec: QuerySpec,
):
    if not _dce_shadow_enabled():
        return append_derived_columns(
            fields,
            rows,
            requested_metric_names=[],
        )
    return append_derived_columns(
        fields,
        rows,
        requested_metric_names=_requested_derived_metrics(spec),
    )


def _derived_metric_shadow_diagnostics(
    fields: list[Any],
    rows: list[Any],
    spec: QuerySpec,
) -> dict[str, Any] | None:
    requested = _requested_derived_metrics(spec)
    if not requested or not _dce_shadow_enabled():
        return None
    result = append_derived_columns(
        fields,
        rows,
        requested_metric_names=requested,
    )
    return {
        "enabled": True,
        "requested_metric_names": sorted(requested),
        "metadata": result.metadata,
        "diagnostics": result.diagnostics,
        "shadow_fields": result.fields,
        "shadow_rows_sample": result.rows[:5],
        "authoritative": False,
    }


def _dce_shadow_enabled() -> bool:
    return str(os.getenv(ENV_DCE_SHADOW_ENABLED, "false")).strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def _requested_derived_metrics(spec: QuerySpec) -> set[str]:
    names: set[str] = set()
    for metric in spec.derived_metrics:
        if metric.name:
            names.add(metric.name)
    if isinstance(spec.params, Mapping):
        raw = spec.params.get("derived_metrics")
        if isinstance(raw, list):
            for item in raw:
                if isinstance(item, Mapping) and item.get("name"):
                    names.add(str(item["name"]))
                elif isinstance(item, str):
                    names.add(item)
    return {name for name in names if name}


def _sort_result_rows(fields: list[Any], rows: list[Any], spec: QuerySpec) -> list[Any]:
    sorts = _effective_sorts(spec)
    if not sorts or not rows:
        return rows
    display_fields = [_display_field(field) for field in fields]
    sort_idx = _sort_field_index(display_fields, sorts[0].field)
    if sort_idx is None:
        return rows
    reverse = sorts[0].direction.upper() != "ASC"

    valid_rows: list[Any] = []
    missing_rows: list[Any] = []
    for row in rows:
        if isinstance(row, list) and len(row) > sort_idx and row[sort_idx] is not None:
            valid_rows.append(row)
        else:
            missing_rows.append(row)

    numeric_values = [_numeric(row[sort_idx]) for row in valid_rows if isinstance(row, list)]
    numeric_sort = len(numeric_values) == len(valid_rows) and all(value is not None for value in numeric_values)

    def sort_key(row: Any) -> Any:
        value = _numeric(row[sort_idx])
        if numeric_sort and value is not None:
            return value
        return str(row[sort_idx])

    return sorted(valid_rows, key=sort_key, reverse=reverse) + missing_rows


def _sort_field_index(fields: list[str], sort_field: str) -> Optional[int]:
    expected = sort_field.casefold().replace(" ", "")
    for index, field in enumerate(fields):
        normalized = field.casefold().replace(" ", "")
        if normalized == expected:
            return index
        clean = _clean_metric_name(field).casefold().replace(" ", "")
        if clean == expected:
            return index
    return None


def _operator_result_to_data(
    result: OperatorResult,
    ds_info: Mapping[str, Any],
    spec: QuerySpec,
    step_results: Mapping[str, Any],
) -> dict[str, Any]:
    payload = result.to_tool_data(datasource_name=str(ds_info.get("name") or ""))
    payload.update({
        "datasource_luid": ds_info.get("luid"),
        "operator": spec.effective_operator,
        "queryspec": spec.model_dump(mode="json"),
        "mcp_steps": {
            name: {
                "fields": value.get("fields"),
                "row_count": len(value.get("rows") or []),
                **({"mcp_args_guardrail": value["mcp_args_guardrail"]} if value.get("mcp_args_guardrail") else {}),
            }
            for name, value in step_results.items()
            if isinstance(value, Mapping)
        },
    })
    return payload


def _skill_result_summary(result: Any) -> dict[str, Any]:
    return {
        "ok": result.ok,
        "skill_key": result.skill_key,
        "kind": result.kind,
        "checksum": result.checksum,
        "version": result.version,
        "source_path": result.source_path,
        "error": result.error,
    }


async def _run_mcp_main_route(
    *,
    question: str,
    context: ToolContext,
    intent_result: IntentClassification,
    datasource: Mapping[str, Any],
    analysis_context: Optional[Mapping[str, Any]],
    llm_service: Optional[LLMService] = None,
    chain_mode: str = MCP_MAIN_CHAIN_MODE,
) -> _McpMainAttempt:
    queryable_fields = list(datasource.get("queryable_fields") or [])
    if not queryable_fields:
        queryable_fields, _ = _queryable_field_context(datasource, context.connection_id)
    preflight_error = _catalog_only_preflight(question, datasource, queryable_fields)
    if preflight_error:
        fields = [str(field) for field in preflight_error.get("fields") or [] if str(field or "").strip()]
        alternatives = [str(field) for field in preflight_error.get("alternatives") or [] if str(field or "").strip()]
        field_text = "、".join(fields) if fields else "该字段"
        alt_text = f"可替代字段：{'、'.join(alternatives)}。" if alternatives else "当前没有可自动替代的 Agent 可查询字段。"
        return _McpMainAttempt(
            success=False,
            events=[],
            reason=MCP_CATALOG_ONLY_FIELD,
            error_code=MCP_CATALOG_ONLY_FIELD,
            original_error=preflight_error,
            message=f"字段存在于 Tableau 资产目录，但当前 Agent/MCP 不支持查询：{field_text}",
            user_hint=f"{alt_text} 请调整问题后再查询。",
        )

    attempt = await _run_mcp_host_route(
        question=question,
        context=context,
        intent_result=intent_result,
        datasource=datasource,
        analysis_context=analysis_context,
        llm_service=llm_service,
        chain_mode=chain_mode,
    )
    if attempt.success or attempt.reason in {RESULT_GUARDRAIL_BLOCKED, MCP_CATALOG_ONLY_FIELD} or not _mcp_host_thin_fallback_enabled():
        return attempt

    fallback_events = list(attempt.events)
    fallback_events.append(AgentEvent(type="tool_call", content={
        "tool": "mcp_host_thin_fallback",
        "params": {
            "chain_mode": chain_mode,
            "reason": attempt.reason or attempt.error_code,
            "fallback_enabled": True,
        },
    }))
    thin_attempt = await _run_thin_mcp_passthrough_route(
        question=question,
        context=context,
        intent_result=intent_result,
        datasource=datasource,
        analysis_context=analysis_context,
        chain_mode=chain_mode,
    )
    fallback_events.append(AgentEvent(type="tool_result", content={
        "tool": "mcp_host_thin_fallback",
        "result": {
            "success": thin_attempt.success,
            "data": {
                "chain_mode": chain_mode,
                "fallback_mode": "thin_mcp_passthrough",
                "original_error": _queryspec_original_error(attempt.original_error),
            },
        },
    }))
    fallback_events.extend(thin_attempt.events)
    if thin_attempt.success:
        return _McpMainAttempt(success=True, events=fallback_events)
    return _McpMainAttempt(
        success=False,
        events=fallback_events,
        reason=thin_attempt.reason or attempt.reason,
        error_code=thin_attempt.error_code or attempt.error_code,
        original_error={
            "host_error": _queryspec_original_error(attempt.original_error),
            "thin_error": _queryspec_original_error(thin_attempt.original_error),
        },
        message=thin_attempt.message,
        user_hint=thin_attempt.user_hint,
    )


async def _run_thin_mcp_passthrough_route(
    *,
    question: str,
    context: ToolContext,
    intent_result: IntentClassification,
    datasource: Mapping[str, Any],
    analysis_context: Optional[Mapping[str, Any]],
    chain_mode: str = MCP_MAIN_CHAIN_MODE,
) -> _McpMainAttempt:
    events: list[AgentEvent] = []
    events.append(AgentEvent(type="tool_call", content={
        "tool": "mcp_nl_tool_discovery",
        "params": {
            "datasource": {"name": datasource.get("name"), "luid": datasource.get("luid")},
            "chain_mode": chain_mode,
        },
    }))

    tool_name = await _discover_mcp_nl_query_tool(context)
    if not tool_name:
        events.append(AgentEvent(type="tool_result", content={
            "tool": "mcp_nl_tool_discovery",
            "result": {
                "success": False,
                "error": MCP_NL_TOOL_UNAVAILABLE,
                "data": {
                    "available": False,
                    "configured_tool": _configured_mcp_nl_tool_name(),
                    "chain_mode": chain_mode,
                },
            },
        }))
        return _McpMainAttempt(
            success=False,
            events=events,
            reason=MCP_NL_TOOL_UNAVAILABLE,
            error_code=MCP_NL_TOOL_UNAVAILABLE,
            original_error={"configured_tool": _configured_mcp_nl_tool_name()},
            message="当前 Tableau MCP 未提供自然语言查询工具。",
            user_hint="请启用或配置 Tableau MCP 自然语言查询工具后重试。",
        )

    events.append(AgentEvent(type="tool_result", content={
        "tool": "mcp_nl_tool_discovery",
        "result": {
            "success": True,
            "data": {
                "available": True,
                "tool": tool_name,
                "chain_mode": chain_mode,
            },
        },
    }))

    arguments = _mcp_nl_tool_arguments(question=question, datasource=datasource)
    events.append(AgentEvent(type="tool_call", content={
        "tool": "tableau_mcp_nl",
        "params": {
            "mcp_tool": tool_name,
            "datasource_luid": datasource.get("luid"),
            "chain_mode": chain_mode,
            "question_passthrough": True,
        },
    }))
    try:
        mcp_result = await _call_mcp_nl_query_tool(tool_name, arguments, context)
    except Exception as exc:
        logger.exception("MCP natural-language route execution failed")
        events.append(AgentEvent(type="tool_result", content={
            "tool": "tableau_mcp_nl",
            "result": {"success": False, "error": str(exc), "data": {"error": str(exc)}},
        }))
        return _McpMainAttempt(
            success=False,
            events=events,
            reason="mcp_nl_execution_failed",
            error_code="MCP_NL_EXECUTION_FAILED",
            original_error=exc,
            message="Tableau MCP 自然语言查询失败。",
            user_hint="请稍后重试；如果持续失败，请带 trace_id 联系管理员排查 Tableau/MCP 执行日志。",
        )

    response_data = _normalize_mcp_nl_response_data(
        mcp_result,
        ds_info=datasource,
        tool_name=tool_name,
        chain_mode=chain_mode,
        question=question,
        analysis_context=analysis_context,
    )
    response_data = _apply_result_guardrail(
        question=question,
        chain_mode=chain_mode,
        response_data=response_data,
        semantic_operator=str(intent_result.intent or "unknown"),
        fallback_triggered=True,
        fallback_reason="thin_mcp_passthrough",
    )
    events.append(AgentEvent(type="tool_result", content={
        "tool": "tableau_mcp_nl",
        "result": {"data": response_data},
    }))
    guardrail = response_data.get("result_guardrail") if isinstance(response_data.get("result_guardrail"), Mapping) else {}
    if guardrail.get("decision") == "block":
        return _McpMainAttempt(
            success=False,
            events=events,
            reason=RESULT_GUARDRAIL_BLOCKED,
            error_code=str(guardrail.get("error_code") or DETAIL_SCAN_BLOCKED),
            original_error=guardrail,
            message=str(guardrail.get("message") or "结果触发质量门禁，已阻断回答。"),
            user_hint="请缩小时间范围、减少明细粒度后重试。",
        )

    rendered = _render_thin_mcp_answer(response_data)
    events.append(AgentEvent(type="tool_call", content={
        "tool": "answer_renderer",
        "params": {
            "renderer": "deterministic_table",
            "chain_mode": chain_mode,
            "row_count": len(response_data.get("rows") or []),
        },
    }))
    events.append(AgentEvent(type="tool_result", content={
        "tool": "answer_renderer",
        "result": {
            "data": response_data,
            "renderer": "deterministic_table",
            "calculation_performed": False,
        },
    }))
    events.append(AgentEvent(type="answer", content=rendered))
    return _McpMainAttempt(success=True, events=events)


async def _run_mcp_host_route(
    *,
    question: str,
    context: ToolContext,
    intent_result: IntentClassification,
    datasource: Mapping[str, Any],
    analysis_context: Optional[Mapping[str, Any]],
    llm_service: Optional[LLMService],
    chain_mode: str,
) -> _McpMainAttempt:
    events: list[AgentEvent] = []
    components: Optional[_McpHostComponents] = None
    try:
        components = await _load_mcp_host_components(context=context, datasource=datasource, llm_service=llm_service)
    except Exception as exc:
        logger.debug("MCP Host components unavailable", exc_info=True)
        events.append(AgentEvent(type="tool_call", content={
            "tool": "mcp_host_catalog",
            "params": {"chain_mode": chain_mode, "datasource": _datasource_trace_payload(datasource)},
        }))
        events.append(AgentEvent(type="tool_result", content={
            "tool": "mcp_host_catalog",
            "result": {
                "success": False,
                "error": MCP_HOST_RUNTIME_UNAVAILABLE,
                "data": {"chain_mode": chain_mode, "error": str(exc)},
            },
        }))
        return _McpMainAttempt(
            success=False,
            events=events,
            reason=MCP_HOST_RUNTIME_UNAVAILABLE,
            error_code=MCP_HOST_RUNTIME_UNAVAILABLE,
            original_error=exc,
            message="MCP Host runtime 尚不可用。",
            user_hint="请等待 MCP Host runtime/planner 完成部署，或显式开启 thin MCP fallback。",
        )

    events.append(AgentEvent(type="tool_call", content={
        "tool": "mcp_host_catalog",
        "params": {"chain_mode": chain_mode, "datasource": _datasource_trace_payload(datasource)},
    }))
    try:
        catalog_payload = await _discover_host_catalog(components.catalog, context=context)
    except Exception as exc:
        logger.exception("MCP Host catalog discovery failed")
        events.append(AgentEvent(type="tool_result", content={
            "tool": "mcp_host_catalog",
            "result": {
                "success": False,
                "error": MCP_HOST_CATALOG_UNAVAILABLE,
                "data": {"chain_mode": chain_mode, "error": str(exc)},
            },
        }))
        return _McpMainAttempt(
            success=False,
            events=events,
            reason=MCP_HOST_CATALOG_UNAVAILABLE,
            error_code=MCP_HOST_CATALOG_UNAVAILABLE,
            original_error=exc,
            message="MCP Host 无法获取 Tableau MCP tool catalog。",
            user_hint="请稍后重试；如果持续失败，请带 trace_id 联系管理员排查 MCP tools/list。",
        )

    catalog_tools = _catalog_tools(catalog_payload)
    events.append(AgentEvent(type="tool_result", content={
        "tool": "mcp_host_catalog",
        "result": {
            "success": True,
            "data": {
                "chain_mode": chain_mode,
                "tool_count": len(catalog_tools),
                "tools": [_tool_trace_summary(tool) for tool in catalog_tools],
            },
        },
    }))

    metadata = None
    metadata_tool = _find_catalog_tool(catalog_payload, MCP_HOST_METADATA_TOOL_NAME)
    history: list[dict[str, Any]] = []
    if metadata_tool:
        metadata_args = _metadata_tool_arguments(metadata_tool, datasource)
        events.append(_mcp_host_tool_call_event(
            tool_name=_tool_name(metadata_tool) or MCP_HOST_METADATA_TOOL_NAME,
            arguments=metadata_args,
            datasource=datasource,
            chain_mode=chain_mode,
            phase="metadata",
        ))
        metadata_result = await _execute_host_tool(
            components.executor,
            tool_name=_tool_name(metadata_tool) or MCP_HOST_METADATA_TOOL_NAME,
            arguments=metadata_args,
            context=context,
            catalog=components.catalog,
        )
        events.append(_mcp_host_tool_result_event(
            tool_name=_tool_name(metadata_tool) or MCP_HOST_METADATA_TOOL_NAME,
            result=metadata_result,
            chain_mode=chain_mode,
            phase="metadata",
        ))
        if not metadata_result.success:
            return _McpMainAttempt(
                success=False,
                events=events,
                reason="metadata_tool_failed",
                error_code=metadata_result.error_code or MCP_HOST_TOOL_EXECUTION_FAILED,
                original_error=metadata_result.error,
                message="Tableau MCP 数据源元数据读取失败。",
                user_hint="请稍后重试；如果持续失败，请带 trace_id 联系管理员排查 Tableau/MCP 元数据工具。",
            )
        metadata = metadata_result.data
        history.append({
            "tool": _tool_name(metadata_tool) or MCP_HOST_METADATA_TOOL_NAME,
            "arguments": metadata_args,
            "result": _redact_large(metadata),
        })

    previous_response_data = _previous_response_data(analysis_context)
    last_query_result: Any = None
    last_query_tool: Optional[str] = None
    last_query_args: Mapping[str, Any] = {}
    planner_error: Optional[dict[str, Any]] = None
    repair_budget = _mcp_host_repair_budget()
    max_tool_calls = _mcp_host_max_tool_calls()

    for step in range(max_tool_calls):
        events.append(AgentEvent(type="tool_call", content={
            "tool": "mcp_host_planner",
            "params": {
                "chain_mode": chain_mode,
                "step": step + 1,
                "catalog_tool_count": len(catalog_tools),
                "has_metadata": metadata is not None,
                "repair_budget_remaining": repair_budget,
            },
        }))
        try:
            planner_output = await _invoke_host_planner(
                components.planner,
                question=question,
                datasource=_datasource_trace_payload(datasource),
                catalog=catalog_payload,
                tool_schemas=catalog_tools,
                metadata=metadata,
                previous_response_data=previous_response_data,
                history=history,
                error=planner_error,
                repair_budget_remaining=repair_budget,
                intent=intent_result.intent,
                context=context,
            )
        except Exception as exc:
            logger.exception("MCP Host planner failed")
            events.append(AgentEvent(type="tool_result", content={
                "tool": "mcp_host_planner",
                "result": {
                    "success": False,
                    "error": MCP_HOST_PLANNER_UNAVAILABLE,
                    "data": {"chain_mode": chain_mode, "error": str(exc)},
                },
            }))
            if repair_budget > 0:
                planner_error = {
                    "error_code": MCP_HOST_PLANNER_UNAVAILABLE,
                    "message": str(exc),
                }
                repair_budget -= 1
                events.extend(_mcp_host_repair_events(
                    chain_mode=chain_mode,
                    reason=MCP_HOST_PLANNER_UNAVAILABLE,
                    error=planner_error,
                    repair_budget_remaining=repair_budget,
                ))
                continue
            return _McpMainAttempt(
                success=False,
                events=events,
                reason=MCP_HOST_PLANNER_UNAVAILABLE,
                error_code=MCP_HOST_PLANNER_UNAVAILABLE,
                original_error=exc,
                message="MCP Host planner 未能生成下一步动作。",
                user_hint="请稍后重试；如果持续失败，请带 trace_id 联系管理员排查 planner 日志。",
            )

        action = _planner_action(planner_output)
        events.append(AgentEvent(type="tool_result", content={
            "tool": "mcp_host_planner",
            "result": {
                "success": bool(action),
                "data": _redact_large({
                    "chain_mode": chain_mode,
                    "action": action,
                    "planner_output": _planner_trace_payload(planner_output),
                }),
            },
        }))

        if action == "final" and last_query_result is None:
            rescue_arguments = _context_followup_trend_arguments(
                question=question,
                datasource=datasource,
                metadata=metadata,
                previous_response_data=previous_response_data,
                analysis_context=analysis_context,
            )
            if rescue_arguments is not None:
                planner_output = {
                    "action": "tool_call",
                    "tool": MCP_HOST_QUERY_TOOL_NAME,
                    "arguments": rescue_arguments,
                    "source": "context_followup_final_repair",
                    "planner_final_without_query_result": _planner_trace_payload(planner_output),
                }
                action = "tool_call"
            else:
                return _McpMainAttempt(
                    success=False,
                    events=events,
                    reason="planner_final_without_query_result",
                    error_code=MCP_HOST_NO_QUERY_RESULT,
                    original_error=planner_output,
                    message="MCP Host planner 没有可用于回答的查询结果。",
                    user_hint="请换一种更明确的问法，补充指标、维度或时间范围。",
                )

        if action == "final":
            response_data = _normalize_mcp_host_response_data(
                last_query_result,
                ds_info=datasource,
                tool_name=last_query_tool or MCP_HOST_QUERY_TOOL_NAME,
                tool_args=last_query_args,
                chain_mode=chain_mode,
                question=question,
                analysis_context=analysis_context,
                planner_output=planner_output,
                datasource_metadata=metadata,
            )
            response_data = _apply_result_guardrail(
                question=question,
                chain_mode=chain_mode,
                response_data=response_data,
                semantic_operator=str(intent_result.intent or "unknown"),
            )
            guardrail = response_data.get("result_guardrail") if isinstance(response_data.get("result_guardrail"), Mapping) else {}
            if guardrail.get("decision") == "block":
                events.append(AgentEvent(type="tool_result", content={
                    "tool": "mcp_host_final_response",
                    "result": {"success": False, "error": guardrail.get("error_code"), "data": response_data},
                }))
                return _McpMainAttempt(
                    success=False,
                    events=events,
                    reason=RESULT_GUARDRAIL_BLOCKED,
                    error_code=str(guardrail.get("error_code") or DETAIL_SCAN_BLOCKED),
                    original_error=guardrail,
                    message=str(guardrail.get("message") or "结果触发质量门禁，已阻断回答。"),
                    user_hint="请缩小时间范围、减少明细粒度后重试。",
                )
            rendered = _render_mcp_host_answer(response_data)
            events.append(AgentEvent(type="tool_call", content={
                "tool": "mcp_host_final_response",
                "params": {
                    "chain_mode": chain_mode,
                    "row_count": len(response_data.get("rows") or []),
                    "mcp_tool": response_data.get("mcp_tool"),
                },
            }))
            events.append(AgentEvent(type="tool_result", content={
                "tool": "mcp_host_final_response",
                "result": {
                    "success": True,
                    "data": response_data,
                    "calculation_performed": False,
                },
            }))
            events.append(AgentEvent(type="answer", content=rendered))
            return _McpMainAttempt(success=True, events=events)

        if action == "repair_unavailable":
            rescue_arguments = _context_followup_trend_arguments(
                question=question,
                datasource=datasource,
                metadata=metadata,
                previous_response_data=previous_response_data,
                analysis_context=analysis_context,
            )
            if rescue_arguments is None:
                return _McpMainAttempt(
                    success=False,
                    events=events,
                    reason="planner_repair_unavailable",
                    error_code=MCP_HOST_TOOL_EXECUTION_FAILED,
                    original_error=planner_output,
                    message="MCP Host planner 无法修复 MCP tool 参数。",
                    user_hint="请换一种更明确的问法，补充指标、维度或时间范围。",
                )
            planner_output = {
                "action": "tool_call",
                "tool": MCP_HOST_QUERY_TOOL_NAME,
                "arguments": rescue_arguments,
                "source": "context_followup_repair",
                "planner_repair_unavailable": _planner_trace_payload(planner_output),
            }
            action = "tool_call"

        if action != "tool_call":
            return _McpMainAttempt(
                success=False,
                events=events,
                reason="planner_action_invalid",
                error_code=MCP_HOST_PLANNER_UNAVAILABLE,
                original_error=planner_output,
                message="MCP Host planner 返回了无效动作。",
                user_hint="请稍后重试；如果持续失败，请带 trace_id 联系管理员排查 planner 输出。",
            )

        tool_name, arguments = _planner_tool_call(planner_output)
        if not tool_name or not _catalog_contains_tool(catalog_payload, tool_name):
            planner_error = {
                "error_code": MCP_HOST_TOOL_NOT_IN_CATALOG,
                "message": "Planner selected a tool that is not present in MCP tools/list.",
                "tool": tool_name,
            }
            if repair_budget <= 0:
                return _McpMainAttempt(
                    success=False,
                    events=events,
                    reason="tool_not_in_catalog",
                    error_code=MCP_HOST_TOOL_NOT_IN_CATALOG,
                    original_error=planner_error,
                    message="MCP Host planner 选择了 catalog 中不存在的工具。",
                    user_hint="请稍后重试；如果持续失败，请带 trace_id 联系管理员排查 planner 输出。",
                )
            repair_budget -= 1
            events.extend(_mcp_host_repair_events(
                chain_mode=chain_mode,
                reason=MCP_HOST_TOOL_NOT_IN_CATALOG,
                error=planner_error,
                repair_budget_remaining=repair_budget,
            ))
            continue

        arguments = _sanitize_mcp_host_tool_arguments(
            tool_name=tool_name,
            arguments=arguments,
            catalog_payload=catalog_payload,
            metadata=metadata,
            question=question,
            previous_response_data=previous_response_data,
            analysis_context=analysis_context,
        )
        if _is_query_tool_name(tool_name):
            guardrail_result = _validate_mcp_host_query_arguments(
                question=question,
                tool_name=tool_name,
                arguments=arguments,
                datasource=datasource,
                metadata=metadata,
                context=context,
            )
            if guardrail_result.decision == "reject":
                return _McpMainAttempt(
                    success=False,
                    events=events,
                    reason=guardrail_result.reject_code or "mcp_host_args_guardrail_rejected",
                    error_code=guardrail_result.reject_code or "MCP_HOST_ARGS_GUARDRAIL_REJECTED",
                    original_error=guardrail_result.to_dict(),
                    message=guardrail_result.message,
                    user_hint=guardrail_result.user_hint,
                )
            if guardrail_result.args:
                arguments = guardrail_result.args
        events.append(_mcp_host_tool_call_event(
            tool_name=tool_name,
            arguments=arguments,
            datasource=datasource,
            chain_mode=chain_mode,
            phase="query" if not _is_metadata_tool_name(tool_name) else "metadata",
        ))
        tool_result = await _execute_host_tool(
            components.executor,
            tool_name=tool_name,
            arguments=arguments,
            context=context,
            catalog=components.catalog,
        )
        events.append(_mcp_host_tool_result_event(
            tool_name=tool_name,
            result=tool_result,
            chain_mode=chain_mode,
            phase="query" if not _is_metadata_tool_name(tool_name) else "metadata",
        ))
        if not tool_result.success and repair_budget > 0 and _is_transient_mcp_error(tool_result.error):
            retry_error = {
                "error_code": tool_result.error_code or MCP_HOST_TOOL_EXECUTION_FAILED,
                "message": _queryspec_original_error(tool_result.error),
                "tool": tool_name,
            }
            repair_budget -= 1
            events.extend(_mcp_host_repair_events(
                chain_mode=chain_mode,
                reason="transient_mcp_tool_error",
                error=retry_error,
                repair_budget_remaining=repair_budget,
            ))
            tool_result = await _execute_host_tool(
                components.executor,
                tool_name=tool_name,
                arguments=arguments,
                context=context,
                catalog=components.catalog,
            )
            events.append(_mcp_host_tool_result_event(
                tool_name=tool_name,
                result=tool_result,
                chain_mode=chain_mode,
                phase="query" if not _is_metadata_tool_name(tool_name) else "metadata",
            ))

        if not tool_result.success:
            planner_error = {
                "error_code": tool_result.error_code or MCP_HOST_TOOL_EXECUTION_FAILED,
                "message": _queryspec_original_error(tool_result.error),
                "tool": tool_name,
                "arguments": _redact_large(arguments),
            }
            if repair_budget > 0 and _is_repairable_mcp_error(planner_error):
                repair_budget -= 1
                events.extend(_mcp_host_repair_events(
                    chain_mode=chain_mode,
                    reason=str(planner_error.get("error_code") or "mcp_argument_error"),
                    error=planner_error,
                    repair_budget_remaining=repair_budget,
                ))
                history.append({
                    "tool": tool_name,
                    "arguments": _redact_large(arguments),
                    "error": planner_error,
                })
                continue
            return _McpMainAttempt(
                success=False,
                events=events,
                reason="mcp_tool_execution_failed",
                error_code=tool_result.error_code or MCP_HOST_TOOL_EXECUTION_FAILED,
                original_error=tool_result.error,
                message="Tableau MCP 工具调用失败，本次不输出结论。",
                user_hint="请稍后重试；如果持续失败，请带 trace_id 联系管理员排查 Tableau/MCP 执行日志。",
            )

        history.append({
            "tool": tool_name,
            "arguments": _redact_large(arguments),
            "result": _redact_large(tool_result.data),
        })
        planner_error = None
        if _is_metadata_tool_name(tool_name):
            metadata = tool_result.data
        else:
            last_query_result = tool_result.data
            last_query_tool = tool_name
            last_query_args = dict(arguments)
            response_data = _normalize_mcp_host_response_data(
                last_query_result,
                ds_info=datasource,
                tool_name=last_query_tool,
                tool_args=last_query_args,
                chain_mode=chain_mode,
                question=question,
                analysis_context=analysis_context,
                planner_output={"action": "final", "source": "auto_final_after_successful_query"},
                datasource_metadata=metadata,
            )
            response_data = _apply_result_guardrail(
                question=question,
                chain_mode=chain_mode,
                response_data=response_data,
                semantic_operator=str(intent_result.intent or "unknown"),
            )
            guardrail = response_data.get("result_guardrail") if isinstance(response_data.get("result_guardrail"), Mapping) else {}
            if guardrail.get("decision") == "block":
                events.append(AgentEvent(type="tool_result", content={
                    "tool": "mcp_host_final_response",
                    "result": {"success": False, "error": guardrail.get("error_code"), "data": response_data},
                }))
                return _McpMainAttempt(
                    success=False,
                    events=events,
                    reason=RESULT_GUARDRAIL_BLOCKED,
                    error_code=str(guardrail.get("error_code") or DETAIL_SCAN_BLOCKED),
                    original_error=guardrail,
                    message=str(guardrail.get("message") or "结果触发质量门禁，已阻断回答。"),
                    user_hint="请缩小时间范围、减少明细粒度后重试。",
                )
            rendered = _render_mcp_host_answer(response_data)
            events.append(AgentEvent(type="tool_call", content={
                "tool": "mcp_host_final_response",
                "params": {
                    "chain_mode": chain_mode,
                    "row_count": len(response_data.get("rows") or []),
                    "mcp_tool": response_data.get("mcp_tool"),
                },
            }))
            events.append(AgentEvent(type="tool_result", content={
                "tool": "mcp_host_final_response",
                "result": {
                    "success": True,
                    "data": response_data,
                    "calculation_performed": False,
                },
            }))
            events.append(AgentEvent(type="answer", content=rendered))
            return _McpMainAttempt(success=True, events=events)

    return _McpMainAttempt(
        success=False,
        events=events,
        reason="mcp_host_loop_budget_exhausted",
        error_code=MCP_HOST_LOOP_BUDGET_EXHAUSTED,
        original_error={"max_tool_calls": max_tool_calls},
        message="MCP Host 查询循环超过预算。",
        user_hint="请换一种更明确的问法，减少一次问题中的查询步骤。",
    )


async def _load_mcp_host_components(
    *,
    context: ToolContext,
    datasource: Mapping[str, Any],
    llm_service: Optional[LLMService],
) -> _McpHostComponents:
    runtime = importlib.import_module("services.data_agent.mcp_host.runtime")
    planner_module = importlib.import_module("services.data_agent.mcp_host.planner")
    client = _tableau_mcp_client_for_context(context)

    runtime_class = getattr(runtime, "MCPHostRuntime", None)
    if inspect.isclass(runtime_class):
        host_runtime = _call_with_compatible_kwargs(
            runtime_class,
            client=client,
            context=context,
            connection_id=context.connection_id,
            datasource_luid=datasource.get("luid") or datasource.get("datasource_luid"),
        )
        planner = _instantiate_public_component(
            planner_module,
            ("MCPHostPlanner", "HostPlanner"),
            llm_service=llm_service or LLMService(),
            context=context,
        )
        return _McpHostComponents(catalog=host_runtime, executor=host_runtime, planner=planner)

    catalog = _instantiate_public_component(
        runtime,
        ("MCPToolCatalog", "ToolCatalog"),
        client=client,
        context=context,
        connection_id=context.connection_id,
    )
    executor = _instantiate_public_component(
        runtime,
        ("MCPToolExecutor", "ToolExecutor"),
        client=client,
        catalog=catalog,
        context=context,
        connection_id=context.connection_id,
    )
    planner = _instantiate_public_component(
        planner_module,
        ("MCPHostPlanner", "HostPlanner"),
        llm_service=llm_service or LLMService(),
        catalog=catalog,
        context=context,
    )
    return _McpHostComponents(catalog=catalog, executor=executor, planner=planner)


def _instantiate_public_component(module: Any, names: tuple[str, ...], **kwargs: Any) -> Any:
    for name in names:
        component = getattr(module, name, None)
        if component is None:
            continue
        if inspect.isclass(component):
            return _call_with_compatible_kwargs(component, **kwargs)
        if callable(component):
            return _call_with_compatible_kwargs(component, **kwargs)
        return component
    return module


async def _discover_host_catalog(catalog: Any, *, context: ToolContext) -> Any:
    for method_name in ("load_catalog", "discover", "load", "refresh", "list_tools", "tools_list", "get_tools", "to_dict"):
        method = getattr(catalog, method_name, None)
        if callable(method):
            return await _maybe_await(_call_with_compatible_kwargs(method, context=context, connection_id=context.connection_id))
    if isinstance(catalog, Mapping) or isinstance(catalog, list):
        return catalog
    tools_attr = getattr(catalog, "tools", None)
    if tools_attr is not None:
        return {"tools": tools_attr() if callable(tools_attr) else tools_attr}
    raise RuntimeError("MCP Host catalog has no public discovery API")


async def _invoke_host_planner(planner: Any, **kwargs: Any) -> Any:
    for method_name in ("plan", "next_action", "decide", "run"):
        method = getattr(planner, method_name, None)
        if callable(method):
            return await _maybe_await(_call_planner_method(method, **kwargs))
    if callable(planner):
        return await _maybe_await(_call_planner_method(planner, **kwargs))
    raise RuntimeError("MCP Host planner has no public planning API")


def _call_planner_method(method: Any, **kwargs: Any) -> Any:
    try:
        signature = inspect.signature(method)
    except (TypeError, ValueError):
        return method(**kwargs)
    parameters = signature.parameters
    if "request" in parameters and not any(param.kind == inspect.Parameter.VAR_KEYWORD for param in parameters.values()):
        return method(_planner_request_for_method(method, **kwargs))
    return _call_with_compatible_kwargs(method, **kwargs)


def _planner_request_for_method(method: Any, **kwargs: Any) -> Any:
    module_name = getattr(method, "__module__", "")
    try:
        planner_module = importlib.import_module(module_name)
        request_class = getattr(planner_module, "MCPHostPlannerInput")
    except Exception:
        request_class = None

    repair_context = kwargs.get("error")
    request_payload = {
        "original_question": kwargs.get("question"),
        "selected_datasource": kwargs.get("datasource"),
        "mcp_tool_schemas": kwargs.get("catalog") or kwargs.get("tool_schemas"),
        "datasource_metadata": kwargs.get("metadata"),
        "previous_response_data": kwargs.get("previous_response_data"),
        "repair_context": repair_context,
    }
    if request_class is not None:
        return _call_with_compatible_kwargs(request_class, **request_payload)
    return request_payload


async def _execute_host_tool(
    executor: Any,
    *,
    tool_name: str,
    arguments: Mapping[str, Any],
    context: ToolContext,
    catalog: Any,
) -> _McpHostToolResult:
    try:
        raw_result = None
        for method_name in ("execute_tool", "call_tool", "execute", "call", "run"):
            method = getattr(executor, method_name, None)
            if not callable(method):
                continue
            raw_result = await _maybe_await(_call_tool_executor_method(
                method,
                tool_name=tool_name,
                arguments=arguments,
                context=context,
                catalog=catalog,
            ))
            break
        else:
            if callable(executor):
                raw_result = await _maybe_await(_call_tool_executor_method(
                    executor,
                    tool_name=tool_name,
                    arguments=arguments,
                    context=context,
                    catalog=catalog,
                ))
            else:
                raise RuntimeError("MCP Host executor has no public execution API")
        return _normalize_host_tool_result(raw_result)
    except Exception as exc:
        return _McpHostToolResult(
            success=False,
            error_code=_exception_error_code(exc),
            error=exc,
            raw=exc,
        )


def _call_tool_executor_method(method: Any, **kwargs: Any) -> Any:
    try:
        return _call_with_compatible_kwargs(method, **kwargs)
    except TypeError:
        try:
            return method(kwargs["tool_name"], dict(kwargs["arguments"]), kwargs["context"])
        except TypeError:
            return method({"tool": kwargs["tool_name"], "arguments": dict(kwargs["arguments"])})


def _call_with_compatible_kwargs(callable_obj: Any, **kwargs: Any) -> Any:
    try:
        signature = inspect.signature(callable_obj)
    except (TypeError, ValueError):
        return callable_obj(**kwargs)
    parameters = signature.parameters
    if any(param.kind == inspect.Parameter.VAR_KEYWORD for param in parameters.values()):
        return callable_obj(**kwargs)
    filtered = {key: value for key, value in kwargs.items() if key in parameters}
    try:
        return callable_obj(**filtered)
    except TypeError:
        if filtered != kwargs:
            return callable_obj(**kwargs)
        raise


async def _maybe_await(value: Any) -> Any:
    if inspect.isawaitable(value):
        return await value
    return value


def _normalize_host_tool_result(result: Any) -> _McpHostToolResult:
    if isinstance(result, _McpHostToolResult):
        return result
    if isinstance(result, Mapping):
        explicit_success = result.get("success")
        if explicit_success is None:
            explicit_success = result.get("ok")
        if explicit_success is False:
            return _McpHostToolResult(
                success=False,
                data=result.get("data") or result.get("result"),
                error_code=str(result.get("error_code") or result.get("code") or MCP_HOST_TOOL_EXECUTION_FAILED),
                error=result.get("error") or result.get("message") or result,
                raw=result,
            )
        if explicit_success is True:
            return _McpHostToolResult(success=True, data=result.get("data") if "data" in result else result, raw=result)
        return _McpHostToolResult(success=True, data=result, raw=result)
    success = getattr(result, "success", None)
    if success is None:
        success = getattr(result, "ok", None)
    if success is False:
        return _McpHostToolResult(
            success=False,
            data=getattr(result, "data", None),
            error_code=str(getattr(result, "error_code", None) or getattr(result, "code", None) or MCP_HOST_TOOL_EXECUTION_FAILED),
            error=getattr(result, "error", None) or getattr(result, "message", None) or result,
            raw=result,
        )
    data = getattr(result, "data", result)
    return _McpHostToolResult(success=True, data=data, raw=result)


def _planner_action(output: Any) -> Optional[str]:
    if isinstance(output, Mapping):
        action = output.get("action")
    else:
        action = getattr(output, "action", None)
    if isinstance(action, str):
        return action.strip().lower()
    return None


def _planner_tool_call(output: Any) -> tuple[Optional[str], dict[str, Any]]:
    payload = output if isinstance(output, Mapping) else getattr(output, "tool_call", None)
    if isinstance(output, Mapping) and isinstance(output.get("tool_call"), Mapping):
        payload = output["tool_call"]
    if not isinstance(output, Mapping) and payload is None:
        tool_name = getattr(output, "tool", None)
        arguments = getattr(output, "arguments", None) or {}
        return (str(tool_name).strip() if tool_name else None, dict(arguments) if isinstance(arguments, Mapping) else {})
    if not isinstance(payload, Mapping):
        return None, {}
    tool_name = payload.get("tool") or payload.get("name") or payload.get("tool_name")
    arguments = payload.get("arguments") or payload.get("args") or payload.get("input") or payload.get("params") or {}
    return (str(tool_name).strip() if tool_name else None, dict(arguments) if isinstance(arguments, Mapping) else {})


def _planner_trace_payload(output: Any) -> Any:
    if isinstance(output, Mapping):
        payload = dict(output)
        if isinstance(payload.get("tool_call"), Mapping):
            tool_call = dict(payload["tool_call"])
            if isinstance(tool_call.get("arguments"), Mapping):
                tool_call["arguments"] = _redact_large(tool_call["arguments"])
            payload["tool_call"] = tool_call
        return payload
    to_dict = getattr(output, "to_dict", None)
    if callable(to_dict):
        return to_dict()
    model_dump = getattr(output, "model_dump", None)
    if callable(model_dump):
        return model_dump()
    return repr(output)


def _catalog_tools(catalog_payload: Any) -> list[Any]:
    if isinstance(catalog_payload, Mapping):
        raw_tools = (
            catalog_payload.get("tools")
            or catalog_payload.get("catalog")
            or catalog_payload.get("data")
            or catalog_payload.get("entries")
            or []
        )
    else:
        raw_tools = catalog_payload
    if isinstance(raw_tools, Mapping):
        return list(raw_tools.values())
    if isinstance(raw_tools, list):
        return list(raw_tools)
    for attr_name in ("tools", "as_mcp_tools", "tool_schemas", "schemas", "entries"):
        if hasattr(catalog_payload, attr_name):
            value = getattr(catalog_payload, attr_name)
            resolved = value() if callable(value) else value
            if resolved is catalog_payload:
                continue
            return _catalog_tools(resolved)
    return []


def _find_catalog_tool(catalog_payload: Any, tool_name: str) -> Optional[Any]:
    for tool in _catalog_tools(catalog_payload):
        if _tool_name(tool) == tool_name:
            return tool
    return None


def _catalog_contains_tool(catalog_payload: Any, tool_name: str) -> bool:
    return _find_catalog_tool(catalog_payload, tool_name) is not None


def _tool_name(tool: Any) -> Optional[str]:
    if isinstance(tool, str) and tool.strip():
        return tool.strip()
    if isinstance(tool, Mapping):
        for key in ("name", "tool", "tool_name"):
            value = tool.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
    for attr in ("name", "tool", "tool_name"):
        value = getattr(tool, attr, None)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _tool_input_schema(tool: Any) -> Mapping[str, Any]:
    if isinstance(tool, Mapping):
        schema = tool.get("inputSchema") or tool.get("input_schema") or tool.get("schema") or {}
    else:
        schema = getattr(tool, "inputSchema", None) or getattr(tool, "input_schema", None) or getattr(tool, "schema", None) or {}
    return schema if isinstance(schema, Mapping) else {}


def _tool_trace_summary(tool: Any) -> dict[str, Any]:
    schema = _tool_input_schema(tool)
    return {
        "name": _tool_name(tool),
        "required": list(schema.get("required") or []) if isinstance(schema, Mapping) else [],
        "has_input_schema": bool(schema),
    }


def _metadata_tool_arguments(tool: Any, datasource: Mapping[str, Any]) -> dict[str, Any]:
    schema = _tool_input_schema(tool)
    properties = schema.get("properties") if isinstance(schema, Mapping) else {}
    if not isinstance(properties, Mapping):
        properties = {}
    luid = str(datasource.get("luid") or datasource.get("datasource_luid") or "")
    preferred_keys = ("datasourceLuid", "datasource_luid", "luid")
    for key in preferred_keys:
        if key in properties:
            return {key: luid}
    required = [str(item) for item in schema.get("required") or []] if isinstance(schema, Mapping) else []
    for key in required:
        if "datasource" in key.lower() or key.lower() == "luid":
            return {key: luid}
    return {"datasourceLuid": luid}


def _sanitize_mcp_host_tool_arguments(
    *,
    tool_name: str,
    arguments: Mapping[str, Any],
    catalog_payload: Any,
    metadata: Any,
    question: str = "",
    previous_response_data: Any = None,
    analysis_context: Optional[Mapping[str, Any]] = None,
) -> dict[str, Any]:
    """Apply generic MCP schema and metadata cleanup before tools/call."""

    sanitized = _json_roundtrip(dict(arguments))
    tool = _find_catalog_tool(catalog_payload, tool_name)
    schema = _tool_input_schema(tool) if tool is not None else {}
    if schema:
        sanitized = _prune_additional_properties(sanitized, schema)
    if tool_name != MCP_HOST_QUERY_TOOL_NAME:
        return sanitized

    query = sanitized.get("query")
    if not isinstance(query, dict):
        return sanitized

    query_schema = _nested_object_schema(schema, "query")
    if query_schema:
        sanitized["query"] = _prune_additional_properties(query, query_schema)
        query = sanitized["query"]

    _inherit_mcp_host_followup_dimensions(
        query=query,
        question=question,
        previous_response_data=previous_response_data,
        analysis_context=analysis_context,
        metadata=metadata,
    )
    _inherit_mcp_host_followup_metrics(
        query=query,
        question=question,
        previous_response_data=previous_response_data,
        analysis_context=analysis_context,
        metadata=metadata,
    )
    _remove_unmentioned_set_filters(query=query, question=question)

    fields = query.get("fields")
    if isinstance(fields, list):
        allowed_field_keys = _allowed_field_keys_from_schema(query_schema)
        metadata_by_caption = _metadata_fields_by_caption(metadata)
        cleaned_fields: list[Any] = []
        for field in fields:
            if not isinstance(field, Mapping):
                cleaned_fields.append(field)
                continue
            cleaned = dict(field)
            if allowed_field_keys:
                cleaned = {key: value for key, value in cleaned.items() if key in allowed_field_keys}
            cleaned.pop("fieldAlias", None)
            caption = str(cleaned.get("fieldCaption") or "").strip()
            field_meta = metadata_by_caption.get(caption)
            if field_meta is not None:
                cleaned.pop("calculation", None)
            if field_meta is not None and _metadata_field_is_calculation(field_meta):
                cleaned.pop("function", None)
            if str(cleaned.get("function") or "").upper() == "AGG":
                cleaned.pop("function", None)
            if metadata_by_caption and caption and field_meta is None and not cleaned.get("calculation"):
                continue
            cleaned_fields.append(cleaned)
        query["fields"] = cleaned_fields
    return sanitized


def _is_query_tool_name(tool_name: str) -> bool:
    return str(tool_name or "") == MCP_HOST_QUERY_TOOL_NAME


def _validate_mcp_host_query_arguments(
    *,
    question: str,
    tool_name: str,
    arguments: Mapping[str, Any],
    datasource: Mapping[str, Any],
    metadata: Any,
    context: ToolContext,
):
    from services.data_agent.mcp_args_guardrail import McpArgsGuardrailInput, query_datasource_tool_schema, validate_mcp_args

    queryable_fields = list(datasource.get("queryable_fields") or [])
    if not queryable_fields:
        queryable_fields = extract_queryable_fields_from_metadata(metadata)
    enriched_datasource = dict(datasource)
    _catalog_queryable_context(enriched_datasource, queryable_fields)
    current_datasource: dict[str, Any] = {
        "name": datasource.get("name"),
        "luid": datasource.get("luid"),
        "connection_id": context.connection_id,
    }
    for key in ("catalog_fields", "queryable_fields", "catalog_only_fields", "field_capability_summary"):
        value = enriched_datasource.get(key)
        if value:
            current_datasource[key] = value
    return validate_mcp_args(
        McpArgsGuardrailInput(
            question=question,
            tool_name=tool_name,
            tool_schema=query_datasource_tool_schema(),
            args=dict(arguments),
            queryable_fields=queryable_fields,
            current_datasource=current_datasource,
            user_context={
                "user_id": context.user_id,
                "connection_id": context.connection_id,
                "accessible_datasource_luids": [datasource.get("luid")],
                **({"accessible_connection_ids": [context.connection_id]} if context.connection_id is not None else {}),
            },
        )
    )


def _context_followup_trend_arguments(
    *,
    question: str,
    datasource: Mapping[str, Any],
    metadata: Any,
    previous_response_data: Any,
    analysis_context: Optional[Mapping[str, Any]],
) -> dict[str, Any] | None:
    if not _looks_like_followup_metric_question(question):
        return None

    metadata_by_caption = _metadata_fields_by_caption(metadata)
    if not metadata_by_caption:
        return None

    fields: list[dict[str, Any]] = []
    time_field = _year_grouping_field_from_metadata(metadata_by_caption)
    if time_field is not None:
        fields.append(time_field)

    metric_fields = _metric_fields_from_previous_response(previous_response_data)
    if not metric_fields and isinstance(analysis_context, Mapping):
        metric_fields = _metric_fields_from_context_names(analysis_context, metadata_by_caption)
    fields.extend(metric_fields)

    unique_fields: list[dict[str, Any]] = []
    seen: set[str] = set()
    for field in fields:
        identity = _query_field_output_identity(field, metadata_by_caption)
        if not identity or identity in seen:
            continue
        unique_fields.append(field)
        seen.add(identity)

    if len(unique_fields) < 2 or time_field is None:
        return None
    return {
        "datasourceLuid": datasource.get("luid"),
        "query": {"fields": unique_fields},
    }


def _year_grouping_field_from_metadata(metadata_by_caption: Mapping[str, Mapping[str, Any]]) -> dict[str, Any] | None:
    for caption, field_meta in metadata_by_caption.items():
        canonical = _canonical_output_label_from_formula(field_meta)
        if canonical and str(canonical.get("label") or "").upper().startswith("YEAR("):
            return {"fieldCaption": caption, "sortDirection": "ASC", "sortPriority": 1}
    for caption, field_meta in metadata_by_caption.items():
        data_type = str(field_meta.get("dataType") or field_meta.get("data_type") or "").upper()
        if data_type in {"DATE", "DATETIME"}:
            return {"fieldCaption": caption, "function": "YEAR", "sortDirection": "ASC", "sortPriority": 1}
    return None


def _metric_fields_from_previous_response(previous_response_data: Any) -> list[dict[str, Any]]:
    fields: list[dict[str, Any]] = []
    for field_name in _response_data_fields(previous_response_data):
        field = _query_field_from_aggregate_output_label(field_name)
        if field is not None:
            fields.append(field)
    return fields


def _metric_fields_from_context_names(
    analysis_context: Mapping[str, Any],
    metadata_by_caption: Mapping[str, Mapping[str, Any]],
) -> list[dict[str, Any]]:
    fields: list[dict[str, Any]] = []
    for name in analysis_context.get("metric_names") or []:
        caption = _query_field_caption({"fieldCaption": name})
        if not caption:
            continue
        field_meta = metadata_by_caption.get(caption)
        if field_meta is None:
            continue
        if _metadata_field_is_dimension(field_meta):
            fields.append({"fieldCaption": caption, "function": "COUNTD"})
            continue
        if _metadata_field_is_calculation(field_meta):
            fields.append({"fieldCaption": caption})
            continue
        aggregation = str(field_meta.get("defaultAggregation") or field_meta.get("default_aggregation") or "").upper()
        if not aggregation or aggregation == "AGG":
            aggregation = "SUM"
        fields.append({"fieldCaption": caption, "function": aggregation})
    return fields


def _inherit_mcp_host_followup_dimensions(
    *,
    query: dict[str, Any],
    question: str,
    previous_response_data: Any,
    analysis_context: Optional[Mapping[str, Any]],
    metadata: Any,
) -> None:
    if not _looks_like_followup_breakdown(question):
        return
    fields = query.get("fields")
    if not isinstance(fields, list):
        return
    previous_fields = _response_data_fields(previous_response_data)
    if not previous_fields and isinstance(analysis_context, Mapping):
        previous_fields = _context_dimension_names(analysis_context)
    if not previous_fields:
        return

    metadata_by_caption = _metadata_fields_by_caption(metadata)
    current_captions = {_query_field_caption(field) for field in fields if isinstance(field, Mapping)}
    inherited: list[dict[str, Any]] = []
    for field_name in previous_fields:
        caption = str(field_name or "").strip()
        if not caption or caption in current_captions or _is_aggregate_output_label(caption):
            continue
        field_meta = metadata_by_caption.get(caption)
        if field_meta is not None and not _metadata_field_is_dimension(field_meta):
            continue
        if field_meta is None and _is_calculated_output_label(caption):
            continue
        inherited.append({"fieldCaption": caption})
        current_captions.add(caption)
    if inherited:
        query["fields"] = inherited + fields


def _inherit_mcp_host_followup_metrics(
    *,
    query: dict[str, Any],
    question: str,
    previous_response_data: Any,
    analysis_context: Optional[Mapping[str, Any]],
    metadata: Any,
) -> None:
    if not _looks_like_followup_metric_question(question):
        return
    fields = query.get("fields")
    if not isinstance(fields, list):
        return

    metadata_by_caption = _metadata_fields_by_caption(metadata)
    existing = {
        _query_field_output_identity(field, metadata_by_caption)
        for field in fields
        if isinstance(field, Mapping)
    }
    candidate_fields = _metric_fields_from_previous_response(previous_response_data)
    if isinstance(analysis_context, Mapping):
        candidate_fields.extend(_metric_fields_from_context_names(analysis_context, metadata_by_caption))
    if not candidate_fields:
        return

    inherited: list[dict[str, Any]] = []
    for field in candidate_fields:
        identity = _query_field_output_identity(field, metadata_by_caption)
        if identity in existing:
            continue
        inherited.append(field)
        existing.add(identity)
    if inherited:
        query["fields"] = fields + inherited


def _remove_unmentioned_set_filters(*, query: dict[str, Any], question: str) -> None:
    filters = query.get("filters")
    if not isinstance(filters, list) or not filters:
        return
    retained: list[Any] = []
    for filter_spec in filters:
        if not isinstance(filter_spec, Mapping):
            retained.append(filter_spec)
            continue
        filter_type = str(filter_spec.get("filterType") or filter_spec.get("type") or "").upper()
        values = filter_spec.get("values")
        if filter_type == "SET" and isinstance(values, list) and not _filter_values_mentioned(question, values):
            continue
        retained.append(filter_spec)
    query["filters"] = retained


def _looks_like_followup_breakdown(question: str) -> bool:
    normalized = str(question or "").strip().lower()
    return any(token in normalized for token in ("继续", "进一步", "拆分", "break down", "breakdown", "continue", "drill"))


def _looks_like_followup_metric_question(question: str) -> bool:
    normalized = str(question or "").strip().lower()
    return bool(_FOLLOWUP_REFERENCE_RE.search(normalized)) or any(
        token in normalized for token in ("trend", "趋势", "过去", "历年", "每年")
    )


def _response_data_fields(response_data: Any) -> list[str]:
    if not isinstance(response_data, Mapping):
        return []
    fields = response_data.get("fields")
    if isinstance(fields, list):
        return [str(field) for field in fields if str(field or "").strip()]
    records = response_data.get("data")
    if isinstance(records, list) and records and isinstance(records[0], Mapping):
        return [str(field) for field in records[0].keys() if str(field or "").strip()]
    return []


def _query_field_caption(field: Mapping[str, Any]) -> str:
    return str(
        field.get("fieldCaption")
        or field.get("fieldName")
        or field.get("field")
        or field.get("name")
        or field.get("caption")
        or ""
    ).strip()


def _query_field_from_aggregate_output_label(value: Any) -> dict[str, Any] | None:
    text = str(value or "").strip()
    match = re.match(r"^\s*([A-Z][A-Z0-9_]*)\s*\(\s*([^)]+?)\s*\)\s*$", text, flags=re.I)
    if not match:
        return None
    return {"fieldCaption": match.group(2).strip(), "function": match.group(1).upper()}


def _query_field_output_identity(
    field: Mapping[str, Any],
    metadata_by_caption: Mapping[str, Mapping[str, Any]],
) -> str:
    caption = _query_field_caption(field)
    function = str(field.get("function") or "").strip().upper()
    if function:
        return f"{function}({caption})"
    field_meta = metadata_by_caption.get(caption)
    canonical = _canonical_output_label_from_formula(field_meta)
    if canonical:
        return str(canonical["label"])
    return caption


def _is_aggregate_output_label(value: str) -> bool:
    return bool(re.match(r"^\s*[A-Z][A-Z0-9_]*\s*\(", str(value or "").strip(), flags=re.I))


def _is_calculated_output_label(value: str) -> bool:
    text = str(value or "").strip()
    return bool(text and ("/" in text or re.search(r"\b(rate|ratio|率)\b", text, flags=re.I)))


def _metadata_field_is_dimension(field_meta: Mapping[str, Any]) -> bool:
    role = str(field_meta.get("role") or field_meta.get("dataCategory") or "").upper()
    return role == "DIMENSION" or role in {"NOMINAL", "ORDINAL"}


def _filter_values_mentioned(question: str, values: list[Any]) -> bool:
    question_text = str(question or "")
    normalized_question = re.sub(r"\s+", "", question_text)
    for value in values:
        value_text = str(value or "").strip()
        if value_text and value_text in normalized_question:
            return True
    return False


def _json_roundtrip(value: Any) -> Any:
    try:
        return json.loads(json.dumps(value, ensure_ascii=False, default=str))
    except Exception:
        return value


def _nested_object_schema(schema: Mapping[str, Any], property_name: str) -> dict[str, Any]:
    properties = schema.get("properties") if isinstance(schema, Mapping) else {}
    nested = properties.get(property_name) if isinstance(properties, Mapping) else None
    return dict(nested) if isinstance(nested, Mapping) else {}


def _prune_additional_properties(value: Any, schema: Mapping[str, Any]) -> Any:
    if not isinstance(value, dict) or schema.get("additionalProperties") is not False:
        return value
    properties = schema.get("properties") if isinstance(schema, Mapping) else {}
    if not isinstance(properties, Mapping):
        return value
    return {key: item for key, item in value.items() if key in properties}


def _allowed_field_keys_from_schema(query_schema: Mapping[str, Any]) -> set[str]:
    properties = query_schema.get("properties") if isinstance(query_schema, Mapping) else {}
    fields_schema = properties.get("fields") if isinstance(properties, Mapping) else None
    if not isinstance(fields_schema, Mapping):
        return set()
    item_schema = fields_schema.get("items")
    if not isinstance(item_schema, Mapping):
        return set()
    variants = item_schema.get("anyOf") or item_schema.get("oneOf") or []
    allowed: set[str] = set()
    if isinstance(variants, list):
        for variant in variants:
            variant_props = variant.get("properties") if isinstance(variant, Mapping) else None
            if isinstance(variant_props, Mapping):
                allowed.update(str(key) for key in variant_props.keys())
    item_props = item_schema.get("properties")
    if isinstance(item_props, Mapping):
        allowed.update(str(key) for key in item_props.keys())
    return allowed


def _metadata_fields_by_caption(metadata: Any) -> dict[str, Mapping[str, Any]]:
    fields: list[Mapping[str, Any]] = []
    if isinstance(metadata, Mapping):
        raw_fields = metadata.get("fields")
        if isinstance(raw_fields, list):
            fields.extend(item for item in raw_fields if isinstance(item, Mapping))
        raw_groups = metadata.get("fieldGroups")
        if isinstance(raw_groups, list):
            for group in raw_groups:
                group_fields = group.get("fields") if isinstance(group, Mapping) else None
                if isinstance(group_fields, list):
                    fields.extend(item for item in group_fields if isinstance(item, Mapping))
        datasource = metadata.get("datasource")
        datasource_fields = datasource.get("fields") if isinstance(datasource, Mapping) else None
        if isinstance(datasource_fields, list):
            fields.extend(item for item in datasource_fields if isinstance(item, Mapping))
    output: dict[str, Mapping[str, Any]] = {}
    for item in fields:
        caption = str(
            item.get("name")
            or item.get("fieldCaption")
            or item.get("caption")
            or item.get("remoteFieldName")
            or ""
        ).strip()
        if caption and caption not in output:
            output[caption] = item
    return output


def _metadata_field_is_calculation(field_meta: Mapping[str, Any]) -> bool:
    column_class = str(field_meta.get("columnClass") or field_meta.get("column_class") or "").upper()
    if column_class == "CALCULATION":
        return True
    return bool(field_meta.get("calculation") or field_meta.get("formula"))


def _mcp_host_tool_call_event(
    *,
    tool_name: str,
    arguments: Mapping[str, Any],
    datasource: Mapping[str, Any],
    chain_mode: str,
    phase: str,
) -> AgentEvent:
    return AgentEvent(type="tool_call", content={
        "tool": "tableau_mcp",
        "params": {
            "mcp_tool": tool_name,
            "datasource_luid": datasource.get("luid"),
            "chain_mode": chain_mode,
            "host_phase": phase,
            "arguments": _redact_large(dict(arguments)),
        },
    })


def _mcp_host_tool_result_event(
    *,
    tool_name: str,
    result: _McpHostToolResult,
    chain_mode: str,
    phase: str,
) -> AgentEvent:
    payload: dict[str, Any] = {
        "success": result.success,
        "mcp_tool": tool_name,
        "chain_mode": chain_mode,
        "host_phase": phase,
    }
    if result.success:
        payload["data"] = _redact_large(result.data)
    else:
        payload.update({
            "error": result.error_code or MCP_HOST_TOOL_EXECUTION_FAILED,
            "data": {"error": _queryspec_original_error(result.error)},
        })
    return AgentEvent(type="tool_result", content={"tool": "tableau_mcp", "result": payload})


def _mcp_host_repair_events(
    *,
    chain_mode: str,
    reason: str,
    error: Mapping[str, Any],
    repair_budget_remaining: int,
) -> list[AgentEvent]:
    params = {
        "chain_mode": chain_mode,
        "reason": reason,
        "repair_budget_remaining": repair_budget_remaining,
    }
    return [
        AgentEvent(type="tool_call", content={"tool": "mcp_host_repair", "params": params}),
        AgentEvent(type="tool_result", content={
            "tool": "mcp_host_repair",
            "result": {"success": True, "data": {"error": _redact_large(dict(error)), **params}},
        }),
    ]


def _canonicalize_mcp_host_response_fields(payload: dict[str, Any], metadata: Any) -> dict[str, Any]:
    metadata_by_caption = _metadata_fields_by_caption(metadata)
    if not metadata_by_caption:
        return payload

    rename_map: dict[str, str] = {}
    converters: dict[str, str] = {}
    for field_name in _payload_field_names(payload):
        field_meta = metadata_by_caption.get(str(field_name))
        canonical = _canonical_output_label_from_formula(field_meta)
        if not canonical:
            continue
        rename_map[str(field_name)] = canonical["label"]
        if canonical.get("converter"):
            converters[str(field_name)] = str(canonical["converter"])
    if not rename_map:
        return payload

    normalized = dict(payload)
    records = normalized.get("data")
    if isinstance(records, list):
        normalized["data"] = [
            _rename_record_fields(record, rename_map, converters) if isinstance(record, Mapping) else record
            for record in records
        ]

    fields = normalized.get("fields")
    rows = normalized.get("rows")
    if isinstance(fields, list):
        original_fields = [str(field) for field in fields]
        normalized["fields"] = [rename_map.get(field, field) for field in original_fields]
        if isinstance(rows, list):
            normalized["rows"] = [
                _convert_row_values(row, original_fields, converters) if isinstance(row, list) else row
                for row in rows
            ]
    return normalized


def _payload_field_names(payload: Mapping[str, Any]) -> list[str]:
    fields = payload.get("fields")
    if isinstance(fields, list) and fields:
        return [str(field) for field in fields]
    records = payload.get("data")
    if isinstance(records, list) and records and isinstance(records[0], Mapping):
        return [str(field) for field in records[0].keys()]
    return []


def _canonical_output_label_from_formula(field_meta: Mapping[str, Any] | None) -> dict[str, str] | None:
    if not field_meta or not _metadata_field_is_calculation(field_meta):
        return None
    formula = str(field_meta.get("formula") or field_meta.get("calculation") or "").strip()
    aggregate = re.match(
        r"^\s*(COUNTD|COUNT|SUM|AVG|MIN|MAX)\s*\(\s*\[([^\]]+)\]\s*\)\s*$",
        formula,
        flags=re.I,
    )
    if aggregate:
        return {"label": f"{aggregate.group(1).upper()}({aggregate.group(2).strip()})"}

    year = re.match(r"^\s*(?:STR\s*\(\s*)?YEAR\s*\(\s*\[([^\]]+)\]\s*\)\s*\)?\s*$", formula, flags=re.I)
    if year:
        return {"label": f"YEAR({year.group(1).strip()})", "converter": "year_int"}
    return None


def _rename_record_fields(
    record: Mapping[str, Any],
    rename_map: Mapping[str, str],
    converters: Mapping[str, str],
) -> dict[str, Any]:
    renamed: dict[str, Any] = {}
    for key, value in record.items():
        old_key = str(key)
        new_key = rename_map.get(old_key, old_key)
        renamed[new_key] = _convert_canonical_value(value, converters.get(old_key))
    return renamed


def _convert_row_values(row: list[Any], fields: list[str], converters: Mapping[str, str]) -> list[Any]:
    converted: list[Any] = []
    for index, value in enumerate(row):
        field_name = fields[index] if index < len(fields) else ""
        converted.append(_convert_canonical_value(value, converters.get(field_name)))
    return converted


def _convert_canonical_value(value: Any, converter: str | None) -> Any:
    if converter != "year_int":
        return value
    if isinstance(value, str) and re.fullmatch(r"\d{4}", value.strip()):
        return int(value.strip())
    return value


def _normalize_mcp_host_response_data(
    result: Any,
    *,
    ds_info: Mapping[str, Any],
    tool_name: str,
    tool_args: Mapping[str, Any],
    chain_mode: str,
    question: str,
    analysis_context: Optional[Mapping[str, Any]],
    planner_output: Any,
    datasource_metadata: Any = None,
) -> dict[str, Any]:
    source = result.get("response_data") if isinstance(result, Mapping) and isinstance(result.get("response_data"), Mapping) else result
    payload = dict(source) if isinstance(source, Mapping) else {"raw_result": source}
    payload = _canonicalize_mcp_host_response_fields(payload, datasource_metadata)
    fields, rows = _tabular_shape_from_mcp_result(payload)
    payload.update({
        "fields": fields,
        "rows": rows,
        "datasource_name": ds_info.get("name"),
        "datasource_luid": ds_info.get("luid"),
        "chain_mode": chain_mode,
        "main_chain_mode": chain_mode,
        "mcp_tool": tool_name,
        "mcp_host": True,
        "mcp_args": _redact_large(dict(tool_args)),
        "context_trace": _context_trace_payload(question, analysis_context),
        "planner_final": _planner_trace_payload(planner_output),
        "table_display": infer_table_display_schema(fields, rows, operator="mcp_host"),
    })
    return payload


def _render_mcp_host_answer(response_data: Mapping[str, Any]) -> str:
    return _render_thin_mcp_answer(response_data)


def _apply_result_guardrail(
    *,
    question: str,
    chain_mode: str,
    response_data: Mapping[str, Any],
    semantic_operator: str,
    fallback_triggered: bool = False,
    fallback_reason: Optional[str] = None,
) -> dict[str, Any]:
    verdict = evaluate_result_guardrail(
        ResultGuardrailInput(
            question=question,
            chain_mode=chain_mode,
            fallback_triggered=fallback_triggered,
            fallback_reason=fallback_reason,
            semantic_operator=semantic_operator,
            context_snapshot={},
            tool_name="query-datasource",
            safe_args={},
            result={
                "fields": response_data.get("fields") or [],
                "rows": response_data.get("rows") or [],
                "metadata": dict(response_data.get("metadata") or {}),
            },
            thresholds={"max_detail_rows": 200},
        )
    )
    payload = dict(response_data)
    data_qa = dict(payload.get("data_qa") or {})
    data_qa.update(
        {
            "semantic_status": verdict.semantic_status,
            "semantic_operator": semantic_operator or "unknown",
            "fallback_triggered": fallback_triggered,
            "result_guardrail_decision": verdict.decision,
            "result_guardrail_error_code": verdict.error_code,
        }
    )
    payload["data_qa"] = data_qa
    payload["result_guardrail"] = verdict.to_dict()
    return payload


def _datasource_trace_payload(datasource: Mapping[str, Any]) -> dict[str, Any]:
    return {"name": datasource.get("name"), "luid": datasource.get("luid")}


def _previous_response_data(analysis_context: Optional[Mapping[str, Any]]) -> Any:
    if not isinstance(analysis_context, Mapping):
        return None
    response_data = analysis_context.get("response_data")
    if response_data is not None:
        return response_data
    return analysis_context.get("previous_response_data")


def _is_metadata_tool_name(tool_name: str) -> bool:
    return "metadata" in (tool_name or "").lower()


def _is_repairable_mcp_error(error: Mapping[str, Any]) -> bool:
    text = json.dumps(
        {
            "error_code": error.get("error_code"),
            "message": error.get("message"),
        },
        ensure_ascii=False,
        default=str,
    ).lower()
    return any(token in text for token in ("schema", "argument", "arguments", "validation", "invalid", "required"))


def _is_transient_mcp_error(error: Any) -> bool:
    text = json.dumps(error, ensure_ascii=False, default=str).lower()
    return any(
        token in text
        for token in (
            "socket disconnected",
            "tls connection",
            "connection reset",
            "econnreset",
            "etimedout",
            "timeout",
            "temporarily unavailable",
            "network",
        )
    )


def _exception_error_code(exc: Exception) -> str:
    for attr in ("error_code", "code"):
        value = getattr(exc, attr, None)
        if value:
            return str(value)
    return exc.__class__.__name__


def _mcp_host_thin_fallback_enabled() -> bool:
    return str(os.getenv(ENV_MCP_HOST_THIN_FALLBACK_ENABLED, "false")).strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def _mcp_host_max_tool_calls() -> int:
    return _positive_int_env("DATA_AGENT_MCP_HOST_MAX_TOOL_CALLS", MCP_HOST_MAX_TOOL_CALLS)


def _mcp_host_repair_budget() -> int:
    return _positive_int_env("DATA_AGENT_MCP_HOST_REPAIR_BUDGET", MCP_HOST_REPAIR_BUDGET, allow_zero=True)


def _positive_int_env(name: str, default: int, *, allow_zero: bool = False) -> int:
    try:
        value = int(str(os.getenv(name, str(default))).strip())
    except (TypeError, ValueError):
        return default
    minimum = 0 if allow_zero else 1
    return max(minimum, value)


def _resolve_explicit_datasource(
    *,
    context: ToolContext,
    datasource_name_hint: Optional[str],
    analysis_context: Optional[Mapping[str, Any]],
) -> Optional[dict[str, Any]]:
    """Resolve only a datasource explicitly supplied by request/context."""

    _ = datasource_name_hint
    for candidate in _explicit_datasource_candidates(context, analysis_context):
        resolved = _datasource_payload_from_candidate(candidate)
        if resolved:
            return resolved

    return None


def _explicit_datasource_candidates(
    context: ToolContext,
    analysis_context: Optional[Mapping[str, Any]],
) -> list[Any]:
    candidates: list[Any] = []
    for attr in ("selected_datasource", "datasource"):
        if hasattr(context, attr):
            candidates.append(getattr(context, attr))
    for attr in ("selected_datasource_luid", "datasource_luid", "tableau_datasource_luid"):
        if hasattr(context, attr):
            candidates.append({
                "luid": getattr(context, attr),
                "name": getattr(context, "datasource_name", None),
            })

    if isinstance(analysis_context, Mapping):
        for key in (
            "selected_datasource",
            "datasource",
            "selected_datasource_luid",
            "datasource_luid",
            "tableau_datasource_luid",
        ):
            if key in analysis_context:
                candidates.append(analysis_context.get(key))
        for key in ("scope", "request_context"):
            nested = analysis_context.get(key)
            if isinstance(nested, Mapping):
                candidates.append(nested)
    return candidates


def _datasource_payload_from_candidate(candidate: Any) -> Optional[dict[str, Any]]:
    if isinstance(candidate, Mapping):
        luid = (
            candidate.get("luid")
            or candidate.get("datasource_luid")
            or candidate.get("selected_datasource_luid")
            or candidate.get("tableau_datasource_luid")
        )
        if not luid:
            return None
        payload = {
            "luid": str(luid),
            "name": candidate.get("name") or candidate.get("datasource_name") or candidate.get("caption") or str(luid),
        }
        for key in ("asset_id", "metadata_fields", "fields"):
            if key in candidate:
                payload[key] = candidate[key]
        return payload

    if isinstance(candidate, str) and candidate.strip():
        return {"luid": candidate.strip(), "name": candidate.strip()}

    return None


async def _discover_mcp_nl_query_tool(context: ToolContext) -> Optional[str]:
    client = _tableau_mcp_client_for_context(context)
    if client is None:
        return None

    for method_name in (
        "discover_natural_language_query_tool",
        "get_natural_language_query_tool",
        "find_natural_language_query_tool",
    ):
        method = getattr(client, method_name, None)
        if not callable(method):
            continue
        result = method()
        if inspect.isawaitable(result):
            result = await result
        tool_name = _mcp_nl_tool_name_from_result(result)
        configured = _configured_mcp_nl_tool_name()
        if tool_name and (not configured or tool_name == configured):
            return tool_name

    configured = _configured_mcp_nl_tool_name()
    if not configured:
        return None

    tools = await _list_mcp_tools_from_client(client)
    return configured if _mcp_tool_list_contains(tools, configured) else None


def _configured_mcp_nl_tool_name() -> Optional[str]:
    for env_name in (ENV_MCP_NL_QUERY_TOOL_NAME, ENV_TABLEAU_MCP_NL_QUERY_TOOL_NAME):
        value = os.getenv(env_name)
        if value and value.strip():
            return value.strip()
    return None


def _tableau_mcp_client_for_context(context: ToolContext) -> Any:
    if context.connection_id is None:
        return None
    try:
        from services.tableau.mcp_client import get_tableau_mcp_client

        return get_tableau_mcp_client(connection_id=context.connection_id)
    except Exception:
        logger.debug("Tableau MCP client unavailable for NL tool discovery", exc_info=True)
        return None


async def _list_mcp_tools_from_client(client: Any) -> Any:
    for method_name in ("list_tools", "tools_list", "list_mcp_tools"):
        method = getattr(client, method_name, None)
        if not callable(method):
            continue
        result = method()
        if inspect.isawaitable(result):
            result = await result
        return result
    return None


def _mcp_tool_list_contains(tools: Any, tool_name: str) -> bool:
    if isinstance(tools, Mapping):
        raw_tools = tools.get("tools") or tools.get("data") or []
    else:
        raw_tools = tools
    if not isinstance(raw_tools, list):
        return False
    for item in raw_tools:
        if isinstance(item, Mapping) and item.get("name") == tool_name:
            return True
        if isinstance(item, str) and item == tool_name:
            return True
    return False


def _mcp_nl_tool_name_from_result(result: Any) -> Optional[str]:
    if isinstance(result, str) and result.strip():
        return result.strip()
    if isinstance(result, Mapping):
        for key in ("name", "tool", "tool_name"):
            value = result.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
    return None


def _mcp_nl_tool_arguments(*, question: str, datasource: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "question": question,
        "datasourceLuid": str(datasource.get("luid") or datasource.get("datasource_luid") or ""),
    }


async def _call_mcp_nl_query_tool(
    tool_name: str,
    arguments: Mapping[str, Any],
    context: ToolContext,
) -> Mapping[str, Any]:
    client = _tableau_mcp_client_for_context(context)
    if client is None:
        raise RuntimeError(MCP_NL_TOOL_UNAVAILABLE)

    for method_name in ("call_natural_language_query_tool", "call_nl_query_tool"):
        method = getattr(client, method_name, None)
        if not callable(method):
            continue
        try:
            result = method(tool_name, dict(arguments), timeout=30, connection_id=context.connection_id)
        except TypeError:
            result = method(tool_name, dict(arguments))
        if inspect.isawaitable(result):
            result = await result
        return result

    method = getattr(client, "call_tool", None)
    if callable(method):
        try:
            result = method(tool_name, dict(arguments), timeout=30, connection_id=context.connection_id)
        except TypeError:
            result = method(tool_name, dict(arguments))
        if inspect.isawaitable(result):
            result = await result
        return result

    raise RuntimeError(MCP_NL_TOOL_UNAVAILABLE)


def _normalize_mcp_nl_response_data(
    result: Mapping[str, Any],
    *,
    ds_info: Mapping[str, Any],
    tool_name: str,
    chain_mode: str,
    question: str,
    analysis_context: Optional[Mapping[str, Any]],
) -> dict[str, Any]:
    source = result.get("response_data") if isinstance(result.get("response_data"), Mapping) else result
    payload = dict(source)
    fields, rows = _tabular_shape_from_mcp_result(payload)
    payload.update({
        "fields": fields,
        "rows": rows,
        "datasource_name": ds_info.get("name"),
        "datasource_luid": ds_info.get("luid"),
        "chain_mode": chain_mode,
        "main_chain_mode": chain_mode,
        "mcp_tool": tool_name,
        "mcp_passthrough": True,
        "context_trace": _context_trace_payload(question, analysis_context),
        "table_display": infer_table_display_schema(fields, rows, operator="mcp_nl_passthrough"),
    })
    return payload


def _tabular_shape_from_mcp_result(result: Mapping[str, Any]) -> tuple[list[Any], list[Any]]:
    fields = list(result.get("fields") or [])
    rows = [list(row) if isinstance(row, list) else row for row in list(result.get("rows") or [])]
    if fields or rows:
        return fields, rows

    records = result.get("data")
    if not isinstance(records, list) or not all(isinstance(record, Mapping) for record in records):
        return fields, rows
    if not records:
        return [], []

    field_names = list(records[0].keys())
    record_rows = [[record.get(field) for field in field_names] for record in records]
    return field_names, record_rows


def _render_thin_mcp_answer(response_data: Mapping[str, Any]) -> str:
    rows = response_data.get("rows") if isinstance(response_data, Mapping) else []
    row_count = len(rows) if isinstance(rows, list) else 0
    if row_count == 0:
        return "查询已完成，未返回数据行。"
    return f"查询已完成，返回 {row_count} 行结果。"


def _mcp_passthrough_error_payload(
    error_code: str,
    message: str,
    user_hint: str,
    trace_id: str,
    intent_result: IntentClassification,
    *,
    chain_mode: str,
    detail: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    return {
        "fallback_type": "mcp_nl_passthrough_unavailable",
        "fallback_trace_event": WARN_EVENT,
        "error_code": error_code,
        "message": message,
        "user_hint": user_hint,
        "trace_id": trace_id,
        "retryable": True,
        "suggested_actions": ["请选择数据源，并确认 Tableau MCP 自然语言查询工具已启用。"],
        "tools_used": ["intent_classifier", "mcp_nl_tool_discovery"],
        "intent_classifier": intent_result.to_dict(),
        "controlled_chain": {"status": "failed", "detail": detail or {"chain_mode": chain_mode}},
    }


async def _emit_mcp_main_queryspec_fallback(
    *,
    context: ToolContext,
    intent_result: IntentClassification,
    attempt: _McpMainAttempt,
) -> AsyncGenerator[AgentEvent, None]:
    detail = {
        "phase": "mcp_main",
        "reason": attempt.reason or "mcp_main_failed",
        "fallback_reason": attempt.reason or "mcp_main_failed",
        "fallback_trace_event": FALLBACK_TRIGGERED_EVENT,
        "original_error": _queryspec_original_error(attempt.original_error),
        "fallback_mode": "queryspec",
        "chain_mode": MCP_MAIN_QUERYSPEC_FALLBACK_CHAIN_MODE,
        "intent_classifier": intent_result.to_dict(),
    }
    logger.warning(
        "%s mcp_main_queryspec_fallback trace_id=%s reason=%s original_error=%s",
        FALLBACK_TRIGGERED_EVENT,
        context.trace_id,
        detail["reason"],
        detail["original_error"],
    )
    yield AgentEvent(type="tool_call", content={
        "tool": "mcp_main_queryspec_fallback",
        "params": {
            "event": FALLBACK_TRIGGERED_EVENT,
            "phase": "mcp_main",
            "reason": detail["reason"],
            "fallback_mode": "queryspec",
        },
    })
    yield AgentEvent(type="tool_result", content={
        "tool": "mcp_main_queryspec_fallback",
        "result": {
            "success": True,
            "event": FALLBACK_TRIGGERED_EVENT,
            "data": detail,
        },
    })


async def _run_queryspec_mcp_fallback(
    *,
    question: str,
    context: ToolContext,
    intent_result: IntentClassification,
    datasource: Mapping[str, Any],
    queryable_fields: list[str],
    analysis_context: Optional[Mapping[str, Any]],
    llm: LLMService,
    phase: str,
    reason: str,
    original_error: Any,
    error_code: str,
    message: str,
    user_hint: str,
    failure_fallback_type: str = "query_plan_rejected",
) -> AsyncGenerator[AgentEvent, None]:
    from services.data_agent import mcp_proxy_main
    from services.data_agent.mcp_args_guardrail import (
        MCP_ARGS_GUARDRAIL_PASS,
        MCP_ARGS_GUARDRAIL_REJECT,
        McpArgsGuardrailInput,
        validate_mcp_args,
    )

    fallback_detail = _queryspec_fallback_detail(
        phase=phase,
        reason=reason,
        original_error=original_error,
        fallback_mode="mcp_proxy",
    )
    fallback_detail["metrics"] = _queryspec_trace_metrics(
        main_path_success=False,
        fallback_triggered=True,
        fallback_mode="mcp_proxy",
        fallback_reason=reason,
    )

    yield AgentEvent(type="tool_call", content={
        "tool": "queryspec_mcp_fallback",
        "params": {
            "event": FALLBACK_TRIGGERED_EVENT if _queryspec_mcp_fallback_enabled() else WARN_EVENT,
            "phase": phase,
            "reason": reason,
            "fallback_mode": "mcp_proxy",
        },
    })

    if not _queryspec_mcp_fallback_enabled():
        disabled_detail = dict(fallback_detail)
        disabled_detail["fallback_disabled"] = True
        disabled_detail["fallback_trace_event"] = WARN_EVENT
        logger.warning(
            "%s queryspec_mcp_fallback disabled trace_id=%s phase=%s reason=%s original_error=%s",
            WARN_EVENT,
            context.trace_id,
            phase,
            reason,
            disabled_detail.get("original_error"),
        )
        yield AgentEvent(type="tool_result", content={
            "tool": "queryspec_mcp_fallback",
            "result": {
                "success": False,
                "event": WARN_EVENT,
                "error": "queryspec_mcp_fallback_disabled",
                "data": disabled_detail,
            },
        })
        yield AgentEvent(type="error", content=_fallback_payload(
            error_code,
            message,
            user_hint,
            context.trace_id,
            intent_result,
            fallback_type=failure_fallback_type,
            detail=disabled_detail,
        ))
        return

    logger.warning(
        "%s queryspec_mcp_fallback trace_id=%s phase=%s reason=%s original_error=%s",
        FALLBACK_TRIGGERED_EVENT,
        context.trace_id,
        phase,
        reason,
        fallback_detail.get("original_error"),
    )
    yield AgentEvent(type="tool_result", content={
        "tool": "queryspec_mcp_fallback",
        "result": {
            "success": True,
            "event": FALLBACK_TRIGGERED_EVENT,
            "data": fallback_detail,
        },
    })

    tool_description = mcp_proxy_main._mcp_tool_description(datasource, queryable_fields)
    tool_schema = mcp_proxy_main._query_datasource_tool_schema()
    current_datasource_context = mcp_proxy_main._current_datasource(datasource, context)
    yield AgentEvent(type="tool_call", content={
        "tool": "mcp_tool_description_loader",
        "params": {
            "tool": mcp_proxy_main.MCP_TOOL_NAME,
            "datasource": {"name": datasource.get("name"), "luid": datasource.get("luid")},
            "field_count": len(queryable_fields),
            "chain_mode": QUERYSPEC_MCP_FALLBACK_CHAIN_MODE,
        },
    })
    yield AgentEvent(type="tool_result", content={
        "tool": "mcp_tool_description_loader",
        "result": {"data": _redact_large({"description": tool_description, "schema": tool_schema})},
    })

    yield AgentEvent(type="tool_call", content={
        "tool": "llm_mcp_args",
        "params": {
            "tool": mcp_proxy_main.MCP_TOOL_NAME,
            "datasource": {"name": datasource.get("name"), "luid": datasource.get("luid")},
            "chain_mode": QUERYSPEC_MCP_FALLBACK_CHAIN_MODE,
            "fallback_reason": reason,
        },
    })
    llm_result = await _call_llm_json(
        llm,
        mcp_proxy_main._build_mcp_args_prompt(
            question=question,
            tool_description=tool_description,
            tool_schema=tool_schema,
            datasource=datasource,
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
        detail = dict(fallback_detail)
        detail.update({
            "chain_mode": QUERYSPEC_MCP_FALLBACK_CHAIN_MODE,
            "guardrail_decision": "reject",
            "guardrail_repairs": [],
            "llm_error": error[:500],
            "fallback_reason": error_code,
        })
        yield AgentEvent(type="error", content=mcp_proxy_main._guardrail_fallback_payload(
            error_code if error_code.startswith("LLM_") else "MCP_ARGS_LLM_INVALID",
            "LLM 未生成可执行的 MCP tool args。",
            "请换一种更明确的问法，补充指标、时间范围或维度。",
            context.trace_id,
            intent_result,
            detail=detail,
        ))
        return

    raw_args, context_additions = mcp_proxy_main._apply_followup_context_to_mcp_args(
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
                "chain_mode": QUERYSPEC_MCP_FALLBACK_CHAIN_MODE,
                "fallback_reason": reason,
                **({"context_additions": context_additions} if context_additions else {}),
            },
        },
    })

    guardrail = validate_mcp_args(
        McpArgsGuardrailInput(
            question=question,
            tool_name=mcp_proxy_main.MCP_TOOL_NAME,
            tool_schema=tool_schema,
            args=raw_args,
            queryable_fields=queryable_fields,
            current_datasource=current_datasource_context,
            user_context=mcp_proxy_main._user_context(datasource, context),
        )
    )
    guardrail_payload = guardrail.to_dict()
    yield AgentEvent(type="tool_call", content={
        "tool": "mcp_args_guardrail",
        "params": {"tool": mcp_proxy_main.MCP_TOOL_NAME, "chain_mode": QUERYSPEC_MCP_FALLBACK_CHAIN_MODE},
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
        detail = dict(fallback_detail)
        detail.update({
            "chain_mode": QUERYSPEC_MCP_FALLBACK_CHAIN_MODE,
            "guardrail_decision": guardrail.decision,
            "guardrail_repairs": [],
            "raw_args": _redact_large(raw_args),
        })
        yield AgentEvent(type="error", content=mcp_proxy_main._guardrail_fallback_payload(
            guardrail.reject_code or "MCP_ARGS_REJECTED",
            guardrail.message,
            guardrail.user_hint,
            context.trace_id,
            intent_result,
            detail=detail,
        ))
        return

    safe_args = guardrail.args or {}
    yield AgentEvent(type="tool_call", content={
        "tool": "tableau_mcp",
        "params": {
            "mcp_tool": mcp_proxy_main.MCP_TOOL_NAME,
            "datasource_luid": safe_args.get("datasourceLuid"),
            "chain_mode": QUERYSPEC_MCP_FALLBACK_CHAIN_MODE,
            "guardrail_decision": guardrail.decision,
            "guardrail_repairs": [repair.to_dict() for repair in guardrail.repairs],
            "fallback_reason": reason,
        },
    })
    try:
        mcp_result = await mcp_proxy_main._execute_query_datasource_args(safe_args, context)
    except Exception as exc:
        logger.exception("QuerySpec MCP fallback execution failed")
        yield AgentEvent(type="tool_result", content={
            "tool": "tableau_mcp",
            "result": {"success": False, "error": str(exc), "data": {"error": str(exc)}},
        })
        detail = dict(fallback_detail)
        detail.update({
            "chain_mode": QUERYSPEC_MCP_FALLBACK_CHAIN_MODE,
            "guardrail_decision": guardrail.decision,
            "guardrail_repairs": [repair.to_dict() for repair in guardrail.repairs],
        })
        yield AgentEvent(type="error", content=mcp_proxy_main._guardrail_fallback_payload(
            "MCP_PROXY_EXECUTION_FAILED",
            "Tableau MCP 查询失败，本次不输出结论。",
            "请稍后重试；如果持续失败，请带 trace_id 联系管理员排查 Tableau/MCP 执行日志。",
            context.trace_id,
            intent_result,
            detail=detail,
        ))
        return

    response_data = mcp_proxy_main._normalize_response_data(
        mcp_result,
        ds_info=datasource,
        args=safe_args,
        guardrail_payload=guardrail_payload,
    )
    response_data["fallback_chain_mode"] = QUERYSPEC_MCP_FALLBACK_CHAIN_MODE
    response_data["queryspec_fallback"] = fallback_detail
    response_data["queryspec_metrics"] = fallback_detail["metrics"]
    yield AgentEvent(type="tool_result", content={
        "tool": "tableau_mcp",
        "result": {"data": response_data},
    })
    yield AgentEvent(type="answer", content=mcp_proxy_main._render_proxy_answer(response_data))


def _queryspec_fallback_detail(
    *,
    phase: str,
    reason: str,
    original_error: Any,
    fallback_mode: str,
) -> dict[str, Any]:
    return {
        "phase": phase,
        "reason": reason,
        "fallback_reason": reason,
        "fallback_trace_event": FALLBACK_TRIGGERED_EVENT if fallback_mode == "mcp_proxy" else WARN_EVENT,
        "original_error": _queryspec_original_error(original_error),
        "fallback_mode": fallback_mode,
        "chain_mode": QUERYSPEC_MCP_FALLBACK_CHAIN_MODE if fallback_mode == "mcp_proxy" else fallback_mode,
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


def _queryspec_original_error(error: Any) -> Any:
    if isinstance(error, BaseException):
        return {"type": error.__class__.__name__, "message": str(error)[:1000]}
    if isinstance(error, Mapping):
        return _redact_large(dict(error))
    if error is None:
        return None
    return str(error)[:1000]


def _queryspec_trace_metrics(
    *,
    main_path_success: bool,
    fallback_triggered: bool,
    fallback_mode: Optional[str],
    fallback_reason: Optional[str],
) -> dict[str, Any]:
    return {
        "queryspec_main_path_success": main_path_success,
        "queryspec_fallback_triggered": fallback_triggered,
        "queryspec_fallback_mode": fallback_mode,
        "queryspec_fallback_reason": fallback_reason,
    }


def _fallback_payload(
    error_code: str,
    message: str,
    user_hint: str,
    trace_id: str,
    intent_result: IntentClassification,
    *,
    fallback_type: str = "query_plan_unavailable",
    detail: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    tools_used = ["intent_classifier", "llm_queryspec", "queryspec_validator"]
    if fallback_type != "query_plan_rejected":
        tools_used = [
            "intent_classifier",
            "llm_queryspec",
            "queryspec_fallback",
            "queryspec_validator",
            "tableau_mcp",
            "answer_renderer",
        ]
    return {
        "fallback_type": fallback_type,
        "fallback_trace_event": WARN_EVENT,
        "error_code": error_code,
        "message": message,
        "user_hint": user_hint,
        "trace_id": trace_id,
        "retryable": True,
        "suggested_actions": ["请补充指标、时间范围、维度或筛选条件后重试。"],
        "tools_used": tools_used,
        "intent_classifier": intent_result.to_dict(),
        "controlled_chain": {"status": "failed", "detail": detail or {}},
    }


def _queryspec_fallback_enabled() -> bool:
    return str(os.getenv("DATA_AGENT_QUERYSPEC_FALLBACK_ENABLED", "false")).strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def _queryspec_mcp_fallback_enabled() -> bool:
    return str(os.getenv(ENV_QUERYSPEC_MCP_FALLBACK_ENABLED, "true")).strip().lower() not in {
        "0",
        "false",
        "no",
        "off",
    }


def _normalize_queryspec_for_mcp(
    spec: QuerySpec,
    question: str,
    queryable_fields: Optional[list[Any]] = None,
    datasource: Optional[Mapping[str, Any]] = None,
    analysis_context: Optional[Mapping[str, Any]] = None,
) -> QuerySpec:
    normalized = _normalize_mcp_handled_metrics(spec, question, queryable_fields)
    normalized = _normalize_period_calculated_fields(normalized, datasource or {})
    return _inherit_context_dimensions(normalized, question, datasource or {}, analysis_context)


def _normalize_mcp_handled_metrics(
    spec: QuerySpec,
    question: str,
    queryable_fields: Optional[list[Any]] = None,
) -> QuerySpec:
    """Let MCP-owned calculation fields execute without an extra aggregate wrapper."""

    requested = _explicit_mcp_handled_metrics_in_question(question)
    if not requested:
        return spec

    available_fields = [_field_caption(field) for field in queryable_fields or []]
    payload = spec.model_dump(mode="json")
    metrics = list(payload.get("metrics") or [])
    changed = False
    for metric in metrics:
        if not isinstance(metric, dict):
            continue
        field = str(metric.get("field") or "")
        if _mcp_handles_metric_field(field, requested, available_fields):
            if metric.get("aggregation") is not None:
                metric["aggregation"] = None
                changed = True

    if not changed:
        return spec

    payload["metrics"] = metrics
    payload["sort"] = _normalize_mcp_handled_metric_sorts(list(payload.get("sort") or []), requested)
    answer_contract = dict(payload.get("answer_contract") or {})
    must_include = list(answer_contract.get("must_include") or [])
    for name in requested:
        if name not in must_include:
            must_include.append(name)
    answer_contract["must_include"] = must_include
    payload["answer_contract"] = answer_contract
    return QuerySpec.model_validate(payload)


def _normalize_period_calculated_fields(spec: QuerySpec, datasource: Mapping[str, Any]) -> QuerySpec:
    metadata = _field_metadata_by_caption(datasource)
    if not metadata:
        return spec

    payload = spec.model_dump(mode="json")
    changed = False

    changed = _normalize_time_payload(payload.get("time"), metadata) or changed

    dimensions: list[str] = []
    for dimension in payload.get("dimensions") or []:
        period_source = _period_source_for_field(str(dimension), metadata)
        if period_source:
            time_payload = payload.get("time")
            if isinstance(time_payload, dict):
                if _same_period_time(time_payload, period_source):
                    changed = True
                    continue
            else:
                payload["time"] = {
                    "field": period_source["field"],
                    "grain": period_source["grain"],
                    "range": {},
                }
                changed = True
                continue
        dimensions.append(dimension)
    if dimensions != list(payload.get("dimensions") or []):
        payload["dimensions"] = dimensions
        changed = True

    for key in ("universe", "occurred"):
        clause = payload.get(key)
        if isinstance(clause, dict):
            changed = _normalize_time_payload(clause.get("time"), metadata) or changed

    return QuerySpec.model_validate(payload) if changed else spec


def _same_period_time(time_payload: Mapping[str, Any], period_source: Mapping[str, str]) -> bool:
    return (
        _compact_text(time_payload.get("field")) == _compact_text(period_source.get("field"))
        and str(time_payload.get("grain") or "").upper() == str(period_source.get("grain") or "").upper()
    )


def _inherit_context_dimensions(
    spec: QuerySpec,
    question: str,
    datasource: Mapping[str, Any],
    analysis_context: Optional[Mapping[str, Any]],
) -> QuerySpec:
    if spec.effective_operator != "aggregate" or not analysis_context:
        return spec
    if not re.search(r"(继续|拆分|每个|各)", question or ""):
        return spec

    metadata = _field_metadata_by_caption(datasource)
    if not metadata:
        return spec

    payload = spec.model_dump(mode="json")
    dimensions = list(payload.get("dimensions") or [])
    existing = {_compact_text(item) for item in dimensions}
    if payload.get("time"):
        existing.add(_compact_text((payload.get("time") or {}).get("field")))

    inherited: list[str] = []
    for candidate in _context_dimension_names(analysis_context):
        if _compact_text(candidate) in existing:
            continue
        if not _is_safe_context_dimension(candidate, metadata):
            continue
        inherited.append(candidate)
        existing.add(_compact_text(candidate))

    if not inherited:
        return spec

    payload["dimensions"] = [*inherited, *dimensions]
    return QuerySpec.model_validate(payload)


def _context_dimension_names(analysis_context: Mapping[str, Any]) -> list[str]:
    names: list[str] = []
    for key in ("dimension_names", "dimensions"):
        value = analysis_context.get(key)
        if not isinstance(value, list):
            continue
        for item in value:
            if isinstance(item, Mapping):
                name = _field_caption(item)
            else:
                name = str(item or "").strip()
            if name:
                names.append(name)
    return names


def _is_safe_context_dimension(candidate: str, metadata: Mapping[str, Mapping[str, Any]]) -> bool:
    item = metadata.get(_compact_text(candidate))
    if not item:
        return False
    role = _metadata_value(item, "role").upper()
    if role and role != "DIMENSION":
        return False
    return _period_source_for_field(candidate, metadata) is None


def _normalize_time_payload(value: Any, metadata: Mapping[str, Mapping[str, Any]]) -> bool:
    if not isinstance(value, dict):
        return False
    period_source = _period_source_for_field(str(value.get("field") or ""), metadata)
    if not period_source:
        return False
    value["field"] = period_source["field"]
    value["grain"] = value.get("grain") or period_source["grain"]
    return True


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


def _period_source_for_field(
    field: str,
    metadata: Mapping[str, Mapping[str, Any]],
) -> Optional[dict[str, str]]:
    field_metadata = metadata.get(_compact_text(field))
    if not field_metadata:
        return None
    formula = _metadata_value(field_metadata, "formula")
    if not formula:
        return None
    match = re.search(r"\b(YEAR|QUARTER|MONTH|WEEK|DAY)\s*\(\s*\[([^\]]+)\]\s*\)", formula, flags=re.IGNORECASE)
    if not match:
        return None
    grain = match.group(1).upper()
    source_field = match.group(2).strip()
    source_metadata = metadata.get(_compact_text(source_field))
    if not source_metadata or "DATE" not in _metadata_value(source_metadata, "dataType", "data_type").upper():
        return None
    return {"field": _field_caption(source_metadata) or source_field, "grain": grain}


def _metadata_value(metadata: Mapping[str, Any], *keys: str) -> str:
    for key in keys:
        value = metadata.get(key)
        if value is not None:
            return str(value).strip()
    mcp = metadata.get("mcp")
    if isinstance(mcp, Mapping):
        for key in keys:
            value = mcp.get(key)
            if value is not None:
                return str(value).strip()
    return ""


def _explicit_mcp_handled_metrics_in_question(question: str) -> set[str]:
    return derived_metric_names_in_text(question)


def _mcp_handles_metric_field(field: str, requested: set[str], available_fields: list[str]) -> bool:
    if not any(field == available for available in available_fields):
        return False
    normalized_field = _compact_text(field)
    return any(normalized_field == _compact_text(name) for name in requested)


def _field_caption(field: Any) -> str:
    if isinstance(field, Mapping):
        for key in ("caption", "fieldCaption", "name", "field", "label"):
            value = field.get(key)
            if value:
                return str(value)
        return ""
    return str(field or "")


def _compact_text(value: Any) -> str:
    return re.sub(r"\s+", "", str(value or "")).lower()


def _normalize_mcp_handled_metric_sorts(
    sorts: list[Mapping[str, Any]],
    requested: set[str],
) -> list[dict[str, Any]]:
    next_sorts: list[dict[str, Any]] = []
    for sort in sorts:
        item = dict(sort)
        field = str(item.get("field") or "")
        for name in requested:
            if _compact_text(name) in _compact_text(field):
                item["field"] = name
        next_sorts.append(item)
    return next_sorts


def _build_fallback_queryspec(
    *,
    question: str,
    intent_result: IntentClassification,
    datasource: Mapping[str, Any],
    queryable_fields: list[str],
    analysis_context: Optional[Mapping[str, Any]],
    reason: str,
) -> Optional[dict[str, Any]]:
    try:
        return build_fallback_queryspec(
            question=question,
            intent_result=intent_result,
            datasource=datasource,
            queryable_fields=queryable_fields,
            analysis_context=analysis_context,
            reason=reason,
        )
    except Exception:
        logger.warning("deterministic QuerySpec fallback failed", exc_info=True)
        return None


def _queryspec_replacement_reason(
    question: str,
    intent_result: IntentClassification,
    spec: QuerySpec,
    analysis_context: Optional[Mapping[str, Any]],
) -> Optional[str]:
    if spec.source == "deterministic_fallback":
        return None
    if spec.raw_rows or spec.detail_scan or str(spec.result_shape or "").lower() == "detail_table":
        return "llm_queryspec_requested_detail_scan"
    expected_operator = infer_fallback_operator(question, intent_result.intent)
    if spec.effective_operator == "asset_inventory" and expected_operator != "asset_inventory":
        return "llm_queryspec_routed_data_question_to_asset_inventory"
    semantic_expected = {
        "set_difference",
        "trend_condition",
        "all_period_condition",
        "root_cause",
        "customer_record",
        "ranking",
    }
    if expected_operator in semantic_expected and spec.effective_operator != expected_operator:
        return f"llm_queryspec_operator_mismatch:{spec.effective_operator}->{expected_operator}"
    if analysis_context and re.search(r"(继续|拆分|过去|趋势|每年|年份)", question):
        has_context = bool(analysis_context.get("metric_names") or analysis_context.get("dimension_names"))
        if has_context and not spec.time and re.search(r"(过去|趋势|每年|年份)", question):
            return "llm_queryspec_missing_followup_time_context"
    return None


def _should_prefer_deterministic_queryspec(
    question: str,
    intent_result: IntentClassification,
    analysis_context: Optional[Mapping[str, Any]],
) -> bool:
    expected_operator = infer_fallback_operator(question, intent_result.intent)
    if expected_operator != "aggregate":
        return True
    if analysis_context and (
        analysis_context.get("metric_names")
        or analysis_context.get("metrics")
        or analysis_context.get("dimension_names")
        or analysis_context.get("dimensions")
        or analysis_context.get("time")
    ):
        if re.search(r"(继续|拆分|过去|趋势|每年|年份)", question):
            return True
    return False


def _range_years(range_spec: Mapping[str, Any]) -> list[int]:
    start = range_spec.get("start") or range_spec.get("from") or range_spec.get("start_year")
    end = range_spec.get("end") or range_spec.get("to") or range_spec.get("end_year")
    if start is not None and end is not None and str(start).isdigit() and str(end).isdigit():
        return list(range(int(start), int(end) + 1))
    value = range_spec.get("value")
    return [int(value)] if value is not None and str(value).isdigit() else []


def _render_deterministic_answer(mcp_data: Mapping[str, Any], spec: QuerySpec) -> str:
    rows = list(mcp_data.get("rows") or [])
    fields = [_display_field(field) for field in (mcp_data.get("fields") or [])]
    row_count = len(rows)
    if not rows:
        return "当前条件下没有查询到匹配结果。"

    prefix = "" if row_count > 1 else "基于 Tableau MCP 聚合结果，"
    derived = _derived_metric_sentence(fields, rows[0])
    if derived:
        return f"{prefix}{derived}"

    summary = _multirow_summary(fields, rows, spec)
    return f"{prefix}{summary}详细数据见下方表格。"


def _answer_replacement_reason(
    rendered: str,
    mcp_data: Mapping[str, Any],
    spec: QuerySpec,
    question: str,
) -> Optional[str]:
    rows = list(mcp_data.get("rows") or [])
    if rows and any(token in rendered for token in ("无法直接回答", "无法回答", "没有包含", "缺少维度", "请确认查询")):
        return "answer_renderer_contradicts_available_data"
    if spec.answer_contract and spec.answer_contract.must_include:
        missing = [
            item
            for item in spec.answer_contract.must_include
            if item and str(item) not in rendered and _metric_alias(str(item)) not in rendered
        ]
        if missing and rows:
            return "answer_renderer_missed_required_terms"
    return None


def _answer_consistency_check(
    rendered: str,
    mcp_data: Mapping[str, Any],
    spec: QuerySpec,
    question: str,
) -> dict[str, Any]:
    rows = list(mcp_data.get("rows") or [])
    fields = list(mcp_data.get("fields") or [])
    if not rendered:
        return {
            "status": "fail",
            "reason": "answer_renderer_empty",
            "row_count": len(rows),
            "field_count": len(fields),
        }
    reason = _answer_replacement_reason(rendered, mcp_data, spec, question)
    if reason:
        return {
            "status": "fail",
            "reason": reason,
            "row_count": len(rows),
            "field_count": len(fields),
        }
    return {
        "status": "pass",
        "reason": None,
        "row_count": len(rows),
        "field_count": len(fields),
    }


def _metric_alias(value: str) -> str:
    return _clean_metric_name(value)


def _multirow_summary(fields: list[str], rows: list[list[Any]], spec: QuerySpec) -> str:
    operator = spec.effective_operator
    if operator == "aggregate" and spec.time and spec.time.grain:
        return _time_aggregate_summary(fields, rows, spec)
    if operator == "aggregate":
        return _grouped_aggregate_summary(fields, spec)
    if operator == "ranking":
        return _ranking_summary(fields, rows, spec)
    if operator == "set_difference":
        return _set_difference_summary(fields, rows, spec)
    if operator in {"trend_condition", "all_period_condition"}:
        return _condition_summary(fields, rows, operator)
    if operator == "root_cause":
        return _root_cause_summary(fields, rows)
    return ""


def _grouped_aggregate_summary(fields: list[str], spec: QuerySpec) -> str:
    dimensions = spec.dimensions or [
        field for field in fields if not _is_metric_field(field) and field not in _requested_derived_metrics(spec)
    ]
    metrics = [_clean_metric_name(field) for field in fields if _is_metric_field(field)]
    for derived in _requested_derived_metrics(spec):
        if any(derived in field for field in fields) and derived not in metrics:
            metrics.append(derived)
    if not dimensions or not metrics:
        return ""
    return f"已按{'、'.join(dimensions)}汇总{'、'.join(metrics)}。"


def _time_aggregate_summary(fields: list[str], rows: list[list[Any]], spec: QuerySpec) -> str:
    time_idx = _time_index(fields)
    metric_idx = _primary_metric_index(fields, spec)
    if time_idx is None or metric_idx is None:
        return ""

    points: list[tuple[Any, float]] = []
    for row in rows:
        if len(row) <= max(time_idx, metric_idx):
            continue
        value = _numeric(row[metric_idx])
        if value is not None:
            points.append((row[time_idx], value))
    if len(points) < 2:
        return ""

    points.sort(key=lambda item: item[0])
    first_period, first_value = points[0]
    last_period, last_value = points[-1]
    peak_period, peak_value = max(points, key=lambda item: item[1])
    metric_name = _clean_metric_name(fields[metric_idx])
    direction = "上升" if last_value >= first_value else "下降"
    delta = last_value - first_value
    return (
        f"{metric_name}从 {first_period} 年的 {_format_value(first_value)} "
        f"{direction}到 {last_period} 年的 {_format_value(last_value)}，"
        f"变化 {_format_value(delta)}；最高年份是 {peak_period} 年，"
        f"达到 {_format_value(peak_value)}。"
    )


def _ranking_summary(fields: list[str], rows: list[list[Any]], spec: QuerySpec) -> str:
    if not rows or not fields:
        return ""
    dimension_idx = _first_dimension_index(fields)
    metric_idx = _primary_metric_index(fields, spec)
    if dimension_idx is None or metric_idx is None:
        return ""
    snippets = []
    for row in rows[:3]:
        if len(row) <= max(dimension_idx, metric_idx):
            continue
        snippets.append(f"{row[dimension_idx]}（{_format_value(row[metric_idx])}）")
    return f"Top{len(snippets)} 为：" + "、".join(snippets) + "。" if snippets else ""


def _set_difference_summary(fields: list[str], rows: list[list[Any]], spec: QuerySpec) -> str:
    target = spec.universe.target_dimension if spec.universe else (fields[0] if fields else "对象")
    values = [str(row[0]) for row in rows[:10] if row]
    if len(rows) <= 10 and values:
        return f"共有 {len(rows)} 个{target}满足条件：" + "、".join(values) + "。"
    return f"共有 {len(rows)} 个{target}满足条件。"


def _condition_summary(fields: list[str], rows: list[list[Any]], operator: str) -> str:
    dimension_idx = _field_index(fields, "dimension")
    if dimension_idx is None:
        dimension_idx = 0 if fields else None
    if dimension_idx is None:
        return ""
    values = [str(row[dimension_idx]) for row in rows[:10] if len(row) > dimension_idx]
    label = "持续趋势条件" if operator == "trend_condition" else "每期条件"
    if len(rows) <= 10 and values:
        return f"共有 {len(rows)} 个对象满足{label}：" + "、".join(values) + "。"
    return f"共有 {len(rows)} 个对象满足{label}。"


def _root_cause_summary(fields: list[str], rows: list[list[Any]]) -> str:
    if not rows:
        return ""
    dimension_idx = _field_index(fields, "dimension")
    segment_idx = _field_index(fields, "segment")
    metric_idx = _last_numeric_index(fields, rows)
    if dimension_idx is None or segment_idx is None or metric_idx is None:
        return ""
    snippets = []
    for row in rows[:3]:
        if len(row) <= max(dimension_idx, segment_idx, metric_idx):
            continue
        snippets.append(f"{row[dimension_idx]}={row[segment_idx]}（{_format_value(row[metric_idx])}）")
    return "主要贡献项为：" + "、".join(snippets) + "。" if snippets else ""


def _derived_metric_sentence(fields: list[str], row: list[Any]) -> str:
    if len(fields) > 1 and len(row) == len(fields) and any(not _is_metric_field(field) for field in fields):
        return ""
    if any(not _is_metric_field(field) for field in fields):
        return ""
    if len(row) != len(fields):
        return ""
    parts: list[str] = []
    for index, field in enumerate(fields):
        value = _numeric(row[index])
        if value is not None:
            parts.append(f"{_clean_metric_name(field)} {_format_value(value)}")
    return "，".join(parts) + "。" if parts else ""


def _is_metric_field(field: str) -> bool:
    normalized = field.upper()
    return any(token in normalized for token in ("SUM(", "AVG(", "COUNT", "MIN(", "MAX(", "MEDIAN("))


def _time_index(fields: list[str]) -> Optional[int]:
    for index, field in enumerate(fields):
        if any(token in field.upper() for token in ("YEAR(", "QUARTER(", "MONTH(", "WEEK(", "DAY(")):
            return index
    return None


def _primary_metric_index(fields: list[str], spec: QuerySpec) -> Optional[int]:
    metric_fields = [metric.field for metric in spec.metrics]
    for metric_name in metric_fields:
        for index, field in enumerate(fields):
            if metric_name and metric_name in field and _is_metric_field(field):
                return index
    return _last_numeric_metric_field_index(fields)


def _last_numeric_metric_field_index(fields: list[str]) -> Optional[int]:
    for index in range(len(fields) - 1, -1, -1):
        if _is_metric_field(fields[index]):
            return index
    return None


def _last_numeric_index(fields: list[str], rows: list[list[Any]]) -> Optional[int]:
    max_len = max((len(row) for row in rows), default=0)
    for index in range(min(len(fields), max_len) - 1, -1, -1):
        if any(len(row) > index and _numeric(row[index]) is not None for row in rows[:5]):
            return index
    return None


def _first_dimension_index(fields: list[str]) -> Optional[int]:
    for index, field in enumerate(fields):
        if not _is_metric_field(field) and index != _time_index(fields):
            return index
    return None


def _field_index(fields: list[str], expected: str) -> Optional[int]:
    expected_norm = expected.casefold()
    for index, field in enumerate(fields):
        if expected_norm in field.casefold():
            return index
    return None


def _clean_metric_name(field: str) -> str:
    match = re.match(r"^\s*(SUM|AVG|COUNT|COUNTD|MIN|MAX|MEDIAN)\((.+)\)\s*$", field, flags=re.IGNORECASE)
    return match.group(2) if match else field


def _first_numeric_by_token(values: Mapping[str, Any], token: str) -> Optional[float]:
    for field, value in values.items():
        if token in field:
            return _numeric(value)
    return None


def _numeric(value: Any) -> Optional[float]:
    if isinstance(value, (int, float)):
        return float(value)
    try:
        return float(str(value).replace(",", "").replace("%", ""))
    except (TypeError, ValueError):
        return None


def _format_value(value: Any) -> str:
    number = _numeric(value)
    if number is None:
        return str(value)
    if abs(number) >= 100:
        return f"{number:,.2f}"
    return f"{number:.4g}"


def _display_field(field: Any) -> str:
    if isinstance(field, Mapping):
        return str(field.get("name") or field.get("fieldAlias") or field.get("fieldCaption") or "")
    return str(field or "")


def _redact_large(value: Any) -> Any:
    try:
        encoded = json.dumps(value, ensure_ascii=False)
    except TypeError:
        return str(value)[:1000]
    if len(encoded) <= 2000:
        return value
    return {"truncated": True, "preview": encoded[:2000]}

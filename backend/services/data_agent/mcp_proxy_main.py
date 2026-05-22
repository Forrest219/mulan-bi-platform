"""Transparent MCP proxy chain for Data Agent data questions."""

from __future__ import annotations

import inspect
import json
import logging
import os
import re
import time
from copy import deepcopy
from dataclasses import dataclass, replace
from typing import Any, AsyncGenerator, Mapping, Optional

from services.data_agent.intent_classifier import IntentClassification
from services.data_agent.mcp_args_guardrail import (
    MCP_ARGS_GUARDRAIL_PASS,
    MCP_ARGS_GUARDRAIL_REJECT,
    query_datasource_tool_schema,
)
from services.data_agent.mcp_host.builtins import MULAN_LIST_TABLEAU_ASSETS_TOOL_NAME
from services.data_agent.mcp_first_main import (
    _queryable_fields,
    _resolve_datasource,
)
from services.data_agent.response import AgentEvent
from services.data_agent.semantic_contract import (
    ANSWER_QUALITY_BUSINESS_SUCCESS,
    ANSWER_QUALITY_SEMANTIC_VALIDATION_FAILED,
    SEMANTIC_CONTRACT_VERSION,
    PlanValidator,
    ResultVerifier,
    SemanticCheckResult,
    infer_semantic_operator,
)
from services.data_agent.tableau_mcp_plan_compiler import CompileResult, DeterministicPlanCompiler
from services.data_agent.tableau_mcp_planner import TableauMcpLlmPlanner, TableauMcpPlannerRequest
from services.data_agent.tableau_mcp_response import (
    RESPONSE_ASSET_CANDIDATES,
    RESPONSE_ASSET_METADATA,
    RESPONSE_ASSET_NOT_FOUND,
    RESPONSE_TOOL_UNAVAILABLE,
    TableauMcpResponseNormalizer,
)
from services.data_agent.tableau_mcp_guardrail import TableauMcpGuardrailRequest, TableauMcpGuardrailService
from services.data_agent.tableau_mcp_cache import TableauMcpCacheFacade
from services.data_agent.tableau_mcp_resolver import DatasourceCandidateResolver
from services.data_agent.tableau_mcp_telemetry import (
    build_compiler_unsupported_planner_reason_payload,
    build_strict_trace_payload,
)
from services.data_agent.tool_base import ToolContext
from services.llm.service import LLMService

logger = logging.getLogger(__name__)

CHAIN_MODE = "mcp_proxy"
MCP_TOOL_NAME = "query-datasource"
MCP_LIST_DATASOURCES_TOOL_NAME = "list-datasources"
MCP_GET_DATASOURCE_METADATA_TOOL_NAME = "get-datasource-metadata"
_FOLLOWUP_REFERENCE_RE = re.compile(r"(这个|这些|上述|上面|上一[轮次]|该|继续)")
_FOLLOWUP_BREAKDOWN_RE = re.compile(
    r"(继续|再按|拆分|拆解|分解|细分|每年|每月|每周|每日|年份|月份|季度|趋势|by\s+(year|month|quarter|week|day|time))",
    re.IGNORECASE,
)
_AGGREGATE_FIELD_RE = re.compile(r"^\s*(SUM|AVG|COUNT|COUNTD|MIN|MAX|MEDIAN|ATTR)\s*\(\s*(.+?)\s*\)\s*$", re.IGNORECASE)
_METRIC_FUNCTIONS = {"SUM", "AVG", "COUNT", "COUNTD", "MIN", "MAX", "MEDIAN", "ATTR"}
_RESPONSE_NORMALIZER = TableauMcpResponseNormalizer()
_PLAN_COMPILER = DeterministicPlanCompiler()
_MCP_CACHE = TableauMcpCacheFacade()
_PLAN_VALIDATOR = PlanValidator()
_RESULT_VERIFIER = ResultVerifier(detail_scan_row_cap=100)


@dataclass(frozen=True)
class _CompilerRuntimeOutcome:
    events: list[AgentEvent]
    handled: bool
    advisory: dict[str, Any] | None
    result: CompileResult


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

    analysis_context = _analysis_context_with_router_advisory(context, analysis_context)
    router_advisory = _router_advisory_from_analysis_context(analysis_context)
    yield AgentEvent(type="thinking", content="已进入 MCP Host 代理链路。")
    yield AgentEvent(type="tool_result", content={
        "tool": "mainline_trace",
        "result": {
            "success": True,
            "data": build_strict_trace_payload(
                actual_entry="mcp_proxy_main",
                extra_trace={
                    "chain_mode": CHAIN_MODE,
                    "planner_received_route_advisory": bool(router_advisory),
                    "route_advisory": router_advisory,
                },
            ),
        },
    })

    if _is_datasource_list_request(question):
        async for event in _run_list_datasources_path(question=question, context=context, intent_result=intent_result):
            yield event
        return

    if _is_datasource_metadata_request(question, intent_result):
        async for event in _run_datasource_metadata_path(question=question, context=context, intent_result=intent_result):
            yield event
        return

    ds_info = thin_mcp._resolve_explicit_datasource(
        context=context,
        datasource_name_hint=datasource_name_hint,
        analysis_context=analysis_context,
    )
    if not ds_info:
        if router_advisory:
            yield AgentEvent(type="tool_call", content={
                "tool": "context_resolver",
                "params": {"chain_mode": CHAIN_MODE, "intent": intent_result.intent, "router_advisory": True},
            })
            yield AgentEvent(type="tool_result", content={
                "tool": "context_resolver",
                "result": {"data": _context_trace_payload(question, analysis_context)},
            })
            planned_events = await _run_llm_planner_path(
                question=question,
                context=context,
                intent_result=intent_result,
                datasource={},
                analysis_context=analysis_context,
                llm_service=llm_service,
                compiler_advisory=None,
                compiler_result=None,
            )
            for event in planned_events:
                yield event
            return
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

    compiler_outcome = await _try_deterministic_plan_compiler(
        question=question,
        context=context,
        intent_result=intent_result,
        datasource=ds_info,
        analysis_context=analysis_context,
    )
    for event in compiler_outcome.events:
        yield event
    if compiler_outcome.handled:
        return

    planned_events = await _run_llm_planner_path(
        question=question,
        context=context,
        intent_result=intent_result,
        datasource=ds_info,
        analysis_context=analysis_context,
        llm_service=llm_service,
        compiler_advisory=compiler_outcome.advisory,
        compiler_result=compiler_outcome.result,
    )
    for event in planned_events:
        yield event
    return


async def _run_list_datasources_path(
    *,
    question: str,
    context: ToolContext,
    intent_result: IntentClassification,
) -> AsyncGenerator[AgentEvent, None]:
    if context.connection_id is None:
        yield AgentEvent(type="error", content=_guardrail_fallback_payload(
            "MCP_PROXY_CONNECTION_REQUIRED",
            "请先选择一个 Tableau 连接后再查看数据源。",
            "当前请求缺少 connection_id，无法限定 Tableau MCP 查询范围。",
            context.trace_id,
            intent_result,
            detail={"chain_mode": CHAIN_MODE, "response_type": RESPONSE_TOOL_UNAVAILABLE},
        ))
        return
    if not _connection_is_accessible(context):
        yield AgentEvent(type="error", content=_guardrail_fallback_payload(
            "MCP_PROXY_CONNECTION_FORBIDDEN",
            "当前用户无权访问该 Tableau 连接。",
            "请切换到有权限的 Tableau 连接后再查询。",
            context.trace_id,
            intent_result,
            detail={"chain_mode": CHAIN_MODE, "response_type": RESPONSE_TOOL_UNAVAILABLE},
        ))
        return

    args = {"connectionId": int(context.connection_id), "limit": 50}
    guardrail = _validate_tableau_mcp_tool(
        question=question,
        tool_name=MCP_LIST_DATASOURCES_TOOL_NAME,
        args=args,
        context=context,
        current_datasource={"connection_id": context.connection_id},
        strict_connection_access=True,
    )
    yield AgentEvent(type="tool_call", content={
        "tool": "mcp_args_guardrail",
        "params": {"tool": MCP_LIST_DATASOURCES_TOOL_NAME, "chain_mode": CHAIN_MODE},
    })
    yield AgentEvent(type="tool_result", content={
        "tool": "mcp_args_guardrail",
        "result": {
            "success": guardrail.decision != "reject",
            "event": MCP_ARGS_GUARDRAIL_REJECT if guardrail.decision == "reject" else MCP_ARGS_GUARDRAIL_PASS,
            "data": guardrail.to_dict(),
        },
    })
    if guardrail.decision == "reject":
        yield AgentEvent(type="error", content=_guardrail_fallback_payload(
            guardrail.reject_code or "MCP_ARGS_REJECTED",
            guardrail.message,
            guardrail.user_hint,
            context.trace_id,
            intent_result,
            detail={"chain_mode": CHAIN_MODE, "response_type": RESPONSE_TOOL_UNAVAILABLE},
        ))
        return

    yield AgentEvent(type="tool_call", content={
        "tool": "tableau_mcp",
        "params": {"mcp_tool": MCP_LIST_DATASOURCES_TOOL_NAME, "chain_mode": CHAIN_MODE},
    })
    try:
        result = await _execute_mcp_host_tool(
            tool_name=MCP_LIST_DATASOURCES_TOOL_NAME,
            args=guardrail.args or args,
            context=context,
        )
    except Exception as exc:
        logger.exception("MCP list-datasources execution failed")
        response_data = _tool_unavailable_response(
            code="MCP_PROXY_LIST_DATASOURCES_FAILED",
            message="Tableau MCP 数据源列表读取失败。",
            user_hint="请稍后重试；如果持续失败，请带 trace_id 联系管理员排查 MCP Gateway。",
            detail={"error": str(exc), "chain_mode": CHAIN_MODE},
        )
        yield AgentEvent(type="tool_result", content={
            "tool": "tableau_mcp",
            "result": {"success": False, "error": str(exc), "data": response_data},
        })
        yield AgentEvent(type="answer", content=_render_proxy_answer(response_data))
        return

    candidates = _datasource_candidates_from_mcp_result(result)
    source = "mcp"
    if not candidates:
        candidates = _load_local_datasource_assets(int(context.connection_id))
        source = "catalog_cache"

    response_data = _asset_candidates_response(
        candidates=candidates,
        query=question,
        source=source,
        reason="list_datasources",
        message=(
            "已从 Tableau MCP 读取当前连接的数据源列表。"
            if source == "mcp"
            else "Tableau MCP 未返回数据源列表，以下为本地 catalog cache 缓存清单。"
        ),
        candidate_limit=50,
    )
    yield AgentEvent(type="tool_result", content={
        "tool": "tableau_mcp",
        "result": {"data": response_data},
    })
    yield AgentEvent(type="answer", content=_render_proxy_answer(response_data))


async def _run_datasource_metadata_path(
    *,
    question: str,
    context: ToolContext,
    intent_result: IntentClassification,
) -> AsyncGenerator[AgentEvent, None]:
    yield AgentEvent(type="tool_call", content={
        "tool": "datasource_candidate_resolver",
        "params": {"chain_mode": CHAIN_MODE, "strategy": "normalize_exact_then_contains"},
    })
    candidates = _resolve_datasource_candidates(question, context)
    yield AgentEvent(type="tool_result", content={
        "tool": "datasource_candidate_resolver",
        "result": {"data": {"candidate_count": len(candidates), "candidates": candidates[:5], "chain_mode": CHAIN_MODE}},
    })

    if not candidates:
        response_data = _RESPONSE_NORMALIZER.asset_not_found(
            query=question,
            message="当前 Tableau 连接下未找到匹配的数据源。",
            chain_mode=CHAIN_MODE,
        ).to_dict()
        yield AgentEvent(type="tool_result", content={
            "tool": "datasource_candidate_resolver",
            "result": {"data": response_data},
        })
        yield AgentEvent(type="answer", content=_render_proxy_answer(response_data))
        return

    if len(candidates) > 1:
        response_data = _asset_candidates_response(
            candidates=candidates,
            query=question,
            source="catalog_cache",
            reason="multiple_candidates",
            message="找到多个可能的数据源，请选择一个后继续。",
        )
        yield AgentEvent(type="tool_result", content={
            "tool": "datasource_candidate_resolver",
            "result": {"data": response_data},
        })
        yield AgentEvent(type="answer", content=_render_proxy_answer(response_data))
        return

    candidate = candidates[0]
    datasource_luid = str(candidate.get("datasource_luid") or "")
    args = {"datasourceLuid": datasource_luid, "connectionId": int(context.connection_id or 0)}
    guardrail = _validate_tableau_mcp_tool(
        question=question,
        tool_name=MCP_GET_DATASOURCE_METADATA_TOOL_NAME,
        args=args,
        current_datasource=_current_datasource(candidate, context),
        context=context,
    )
    yield AgentEvent(type="tool_call", content={
        "tool": "mcp_args_guardrail",
        "params": {"tool": MCP_GET_DATASOURCE_METADATA_TOOL_NAME, "chain_mode": CHAIN_MODE},
    })
    yield AgentEvent(type="tool_result", content={
        "tool": "mcp_args_guardrail",
        "result": {
            "success": guardrail.decision != "reject",
            "event": MCP_ARGS_GUARDRAIL_REJECT if guardrail.decision == "reject" else MCP_ARGS_GUARDRAIL_PASS,
            "data": guardrail.to_dict(),
        },
    })
    if guardrail.decision == "reject":
        response_data = _tool_unavailable_response(
            code=guardrail.reject_code or "MCP_ARGS_REJECTED",
            message=guardrail.message,
            user_hint=guardrail.user_hint,
            detail={"chain_mode": CHAIN_MODE, "datasource_luid": datasource_luid},
        )
        yield AgentEvent(type="tool_result", content={
            "tool": "mcp_args_guardrail",
            "result": {"success": False, "data": response_data},
        })
        yield AgentEvent(type="answer", content=_render_proxy_answer(response_data))
        return

    yield AgentEvent(type="tool_call", content={
        "tool": "tableau_mcp",
        "params": {
            "mcp_tool": MCP_GET_DATASOURCE_METADATA_TOOL_NAME,
            "datasource_luid": datasource_luid,
            "chain_mode": CHAIN_MODE,
        },
    })
    try:
        result = await _execute_mcp_host_tool(
            tool_name=MCP_GET_DATASOURCE_METADATA_TOOL_NAME,
            args=guardrail.args or args,
            context=context,
            datasource_luid=datasource_luid,
        )
        response_data = _asset_metadata_response_from_mcp(result, candidate)
        yield AgentEvent(type="tool_result", content={
            "tool": "tableau_mcp",
            "result": {"data": response_data},
        })
        yield AgentEvent(type="answer", content=_render_proxy_answer(response_data))
        return
    except Exception as exc:
        logger.warning("MCP metadata unavailable; checking catalog cache", exc_info=True)
        yield AgentEvent(type="tool_result", content={
            "tool": "tableau_mcp",
            "result": {
                "success": False,
                "error": str(exc),
                "data": {"chain_mode": CHAIN_MODE, "datasource_luid": datasource_luid},
            },
        })
        cache_response = _asset_metadata_response_from_catalog_cache(candidate, context)
        if cache_response:
            yield AgentEvent(type="tool_result", content={
                "tool": "catalog_cache",
                "result": {"data": cache_response},
            })
            yield AgentEvent(type="answer", content=_render_proxy_answer(cache_response))
            return

        response_data = _tool_unavailable_response(
            code="MCP_PROXY_METADATA_UNAVAILABLE",
            message="Tableau MCP metadata 不可用，且本地字段缓存不完整。",
            user_hint="请稍后重试，或先同步 Tableau catalog cache 后再查询该数据源。",
            detail={"error": str(exc), "chain_mode": CHAIN_MODE, "datasource_luid": datasource_luid},
        )
        yield AgentEvent(type="tool_result", content={
            "tool": "catalog_cache",
            "result": {"success": False, "data": response_data},
        })
        yield AgentEvent(type="answer", content=_render_proxy_answer(response_data))


def _query_datasource_tool_schema() -> dict[str, Any]:
    return query_datasource_tool_schema()


def _semantic_contract_telemetry(
    *,
    operator: str,
    plan_validation: SemanticCheckResult | None = None,
    result_verification: SemanticCheckResult | None = None,
    answer_quality_status: str | None = None,
    **extra: Any,
) -> dict[str, Any]:
    plan_payload = plan_validation.to_dict() if plan_validation else None
    result_payload = result_verification.to_dict() if result_verification else None
    violations = list((plan_payload or {}).get("violations") or []) + list((result_payload or {}).get("violations") or [])
    return {
        "semantic_contract_version": SEMANTIC_CONTRACT_VERSION,
        "semantic_operator": operator,
        "answer_quality_status": (
            answer_quality_status
            or (ANSWER_QUALITY_BUSINESS_SUCCESS if not violations else ANSWER_QUALITY_SEMANTIC_VALIDATION_FAILED)
        ),
        "plan_validation": plan_payload,
        "result_verification": result_payload,
        "detail_scan_violation": any(item.get("code") == "detail_scan_violation" for item in violations if isinstance(item, Mapping)),
        "hidden_fallback": False,
        "planner_contract_violation": any(
            item.get("code", "").startswith("planner_") for item in violations if isinstance(item, Mapping)
        ),
        **extra,
    }


def _semantic_contract_event(
    *,
    tool: str,
    check: SemanticCheckResult,
    stage: str,
    strategy: str,
) -> AgentEvent:
    return AgentEvent(type="tool_result", content={
        "tool": tool,
        "result": {
            "success": check.ok,
            "data": {
                "stage": stage,
                "strategy": strategy,
                **check.to_dict(),
            },
        },
    })


def _semantic_validation_failed_response(
    check: SemanticCheckResult,
    *,
    stage: str,
    strategy: str,
    execution_source: str,
    detail: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    telemetry = _semantic_contract_telemetry(
        operator=check.operator,
        plan_validation=check if stage == "plan_validation" else None,
        result_verification=check if stage == "result_verification" else None,
        answer_quality_status=ANSWER_QUALITY_SEMANTIC_VALIDATION_FAILED,
        stage=stage,
        strategy=strategy,
        execution_source=execution_source,
    )
    return {
        "response_type": ANSWER_QUALITY_SEMANTIC_VALIDATION_FAILED,
        "response_data": {
            "source": "semantic_contract",
            "chain_mode": CHAIN_MODE,
            "status": ANSWER_QUALITY_SEMANTIC_VALIDATION_FAILED,
            "error_code": check.error_code or "SEMANTIC_VALIDATION_FAILED",
            "message": "查询计划或结果未通过语义校验，已阻止错误成功。",
            "user_hint": "请补充更明确的指标、维度、筛选条件或分析口径后重试。",
            "stage": stage,
            "strategy": strategy,
            "execution_source": execution_source,
            "operator": check.operator,
            "reason": check.reason,
            "violations": [violation.to_dict() for violation in check.violations],
            "detail": dict(detail or {}),
            "telemetry": telemetry,
        },
    }


async def _try_deterministic_plan_compiler(
    *,
    question: str,
    context: ToolContext,
    intent_result: IntentClassification,
    datasource: Mapping[str, Any],
    analysis_context: Optional[Mapping[str, Any]] = None,
) -> _CompilerRuntimeOutcome:
    started_at = time.monotonic()
    queryable_fields, metadata_fields = _compiler_field_context(datasource, context)
    compile_result = _PLAN_COMPILER.compile(
        question,
        metadata_fields=metadata_fields,
        queryable_fields=queryable_fields,
        datasource_context=datasource,
        analysis_context=analysis_context,
    )
    compile_result = replace(
        compile_result,
        compiler_advisory=_compiler_advisory_with_analysis_context(
            compile_result.compiler_advisory,
            analysis_context=analysis_context,
        ),
    )
    compile_ms = max(0, int((time.monotonic() - started_at) * 1000))
    events: list[AgentEvent] = [
        AgentEvent(type="tool_call", content={
            "tool": "deterministic_plan_compiler",
            "params": {
                "chain_mode": CHAIN_MODE,
                "strategy": "simple_tableau_aggregate",
                "field_count": len(queryable_fields) or len(metadata_fields),
                "intent": intent_result.intent,
            },
        }),
        AgentEvent(type="tool_result", content={
            "tool": "deterministic_plan_compiler",
            "result": {
                "success": compile_result.status == "matched_executable",
                "data": _compile_trace_payload(compile_result, compile_ms),
            },
        }),
    ]

    if compile_result.status == "unsupported":
        return _CompilerRuntimeOutcome(
            events=events,
            handled=False,
            advisory=compile_result.compiler_advisory or {},
            result=compile_result,
        )

    if compile_result.status == "ambiguous" and compile_result.ambiguity_level == "soft":
        return _CompilerRuntimeOutcome(
            events=events,
            handled=False,
            advisory=compile_result.compiler_advisory or {},
            result=compile_result,
        )

    if compile_result.status == "ambiguous":
        clarification = compile_result.clarification or {}
        response_data = _RESPONSE_NORMALIZER.clarification(
            message=str(clarification.get("message") or "请补充更明确的字段后继续。"),
            chain_mode=CHAIN_MODE,
            reason=compile_result.compile_reason,
            candidates=clarification.get("candidates") if isinstance(clarification.get("candidates"), list) else [],
            detail={
                "compiler_status": compile_result.status,
                "ambiguity_level": compile_result.ambiguity_level,
                "compile_confidence": compile_result.compile_confidence,
                "pattern": compile_result.pattern,
            },
            telemetry={"compile_ms": compile_ms, "strategy": "deterministic_plan_compiler"},
        ).to_dict()
        events.append(AgentEvent(type="tool_result", content={
            "tool": "deterministic_plan_compiler",
            "result": {"success": False, "data": response_data},
        }))
        events.append(AgentEvent(type="answer", content=_render_proxy_answer(response_data)))
        return _CompilerRuntimeOutcome(events=events, handled=True, advisory=None, result=compile_result)

    query_start = time.monotonic()
    events.append(AgentEvent(type="tool_call", content={
        "tool": "tableau_mcp",
        "params": {
            "mcp_tool": MCP_TOOL_NAME,
            "chain_mode": CHAIN_MODE,
            "strategy": "deterministic_plan_compiler",
            "execution_source": "compiler_fast_path",
            "pattern": compile_result.pattern,
        },
    }))
    try:
        execution = await _execute_mcp_host_tool(
            tool_name=MCP_TOOL_NAME,
            args=compile_result.query_args or {},
            context=context,
            datasource_luid=str((compile_result.query_args or {}).get("datasourceLuid") or ""),
            question=question,
            current_datasource=_current_datasource(datasource, context),
            queryable_fields=queryable_fields,
            execution_source="compiler_fast_path",
            compiler_status=compile_result.status,
            compiler_reason=compile_result.compile_reason,
            compiler_advisory=compile_result.compiler_advisory,
            return_guardrail=True,
        )
        result, guardrail_payload = _unpack_execution_result(execution)
    except Exception as exc:
        logger.exception("Deterministic Tableau MCP query execution failed")
        guardrail_payload = _guardrail_payload_from_exception(exc)
        response_data = _execution_error_response(
            exc,
            default_code="MCP_PROXY_QUERY_FAILED",
            message="Tableau MCP 查询执行失败。",
            strategy="deterministic_plan_compiler",
            execution_source="compiler_fast_path",
            detail={"compile_reason": compile_result.compile_reason},
        )
        events.append(AgentEvent(type="tool_result", content={
            "tool": "tableau_mcp",
            "result": {"success": False, "error": str(exc), "data": response_data},
        }))
        events.append(_guardrail_event_from_payload(guardrail_payload, tool_name=MCP_TOOL_NAME, strategy="deterministic_plan_compiler"))
        events.append(AgentEvent(type="answer", content=_render_proxy_answer(response_data)))
        return _CompilerRuntimeOutcome(events=events, handled=True, advisory=None, result=compile_result)

    events.append(_guardrail_event_from_payload(guardrail_payload, tool_name=MCP_TOOL_NAME, strategy="deterministic_plan_compiler"))

    if _query_result_too_large_for_renderer(result):
        events.append(AgentEvent(type="error", content={
            "error_code": "DETAIL_SCAN_BLOCKED",
            "message": "Tableau MCP 返回结果行数超过受控展示上限，本次不输出明细结果。",
            "fallback_type": "query_result_too_large",
            "chain_mode": CHAIN_MODE,
            "strategy": "deterministic_plan_compiler",
        }))
        return _CompilerRuntimeOutcome(events=events, handled=True, advisory=None, result=compile_result)

    query_ms = max(0, int((time.monotonic() - query_start) * 1000))
    response_data = _normalize_response_data(
        result,
        ds_info=datasource,
        args=compile_result.query_args or {},
        guardrail_payload=guardrail_payload,
    )
    response_data["response_type"] = "query_result"
    response_data["strategy"] = "deterministic_plan_compiler"
    response_data["execution_source"] = "compiler_fast_path"
    response_data["compiler_status"] = compile_result.status
    response_data["compiler_reason"] = compile_result.compile_reason
    response_data["compiler_advisory"] = compile_result.compiler_advisory or {}
    response_data["mcp_tool_name"] = MCP_TOOL_NAME
    response_data["compile"] = {
        "status": compile_result.status,
        "pattern": compile_result.pattern,
        "compile_reason": compile_result.compile_reason,
        "compile_confidence": compile_result.compile_confidence,
        "matched_fields": compile_result.matched_fields or {},
        "compiler_advisory": compile_result.compiler_advisory or {},
    }
    response_data["telemetry"] = {"compile_ms": compile_ms, "query_ms": query_ms, "strategy": "deterministic_plan_compiler"}
    events.append(AgentEvent(type="tool_result", content={
        "tool": "tableau_mcp",
        "result": {"success": True, "data": response_data},
    }))
    events.append(AgentEvent(type="tool_call", content={
        "tool": "mcp_host_final_response",
        "params": {
            "chain_mode": CHAIN_MODE,
            "strategy": "deterministic_plan_compiler",
            "row_count": len(response_data.get("rows") or []),
            "mcp_tool": MCP_TOOL_NAME,
        },
    }))
    events.append(AgentEvent(type="tool_result", content={
        "tool": "mcp_host_final_response",
        "result": {"success": True, "data": response_data, "calculation_performed": False},
    }))
    events.append(AgentEvent(type="answer", content=_render_proxy_answer(response_data)))
    return _CompilerRuntimeOutcome(events=events, handled=True, advisory=None, result=compile_result)


async def _run_llm_planner_path(
    *,
    question: str,
    context: ToolContext,
    intent_result: IntentClassification,
    datasource: Mapping[str, Any],
    analysis_context: Optional[Mapping[str, Any]],
    llm_service: Optional[LLMService],
    compiler_advisory: Optional[Mapping[str, Any]] = None,
    compiler_result: Optional[CompileResult] = None,
) -> list[AgentEvent]:
    started_at = time.monotonic()
    queryable_fields, metadata_fields = _compiler_field_context(datasource, context)
    router_advisory = _router_advisory_from_analysis_context(analysis_context)
    handoff = build_compiler_unsupported_planner_reason_payload(
        compiler_reason=(compiler_result.compile_reason if compiler_result else "deterministic_compiler_unsupported"),
        planner_reason="planner_can_select_mcp_tool",
        detail={
            "intent": intent_result.intent,
            "field_count": len(queryable_fields) or len(metadata_fields),
            "compiler_status": compiler_result.status if compiler_result else "unsupported",
            "ambiguity_level": compiler_result.ambiguity_level if compiler_result else None,
            "compiler_advisory": dict(compiler_advisory or {}),
            "planner_received_route_advisory": bool(router_advisory),
            "route_advisory": router_advisory,
        },
    )
    events: list[AgentEvent] = [
        AgentEvent(type="tool_call", content={
            "tool": "tableau_mcp_llm_planner",
            "params": {
                "chain_mode": CHAIN_MODE,
                "strategy": "llm_planner",
                "reason": handoff["planner"]["reason"],
            },
        }),
        AgentEvent(type="tool_result", content={
            "tool": "deterministic_plan_compiler",
            "result": {"success": False, "data": handoff},
        }),
    ]
    planner = TableauMcpLlmPlanner(llm_service=llm_service)
    plan = await planner.plan(
        TableauMcpPlannerRequest(
            question=question,
            datasource=_current_datasource(datasource, context),
            metadata_fields=metadata_fields,
            queryable_fields=queryable_fields,
            context=context,
            analysis_context=analysis_context,
            compiler_reason=(compiler_result.compile_reason if compiler_result else "deterministic_compiler_unsupported"),
            compiler_advisory=compiler_advisory,
        )
    )
    planner_ms = max(0, int((time.monotonic() - started_at) * 1000))
    plan_payload = plan.to_dict()
    plan_payload["telemetry"] = {"planner_ms": planner_ms, "strategy": "llm_planner"}
    plan_payload["planner_received_route_advisory"] = bool(router_advisory)
    plan_payload["route_advisory"] = router_advisory
    events.append(AgentEvent(type="tool_result", content={
        "tool": "tableau_mcp_llm_planner",
        "result": {"success": plan.is_executable, "data": plan_payload},
    }))

    if plan.status == "clarification":
        clarification = plan.clarification if isinstance(plan.clarification, Mapping) else {}
        response_data = _RESPONSE_NORMALIZER.clarification(
            message=str(clarification.get("message") or "请补充更明确的信息后继续。"),
            chain_mode=CHAIN_MODE,
            reason=plan.reason,
            candidates=clarification.get("candidates") if isinstance(clarification.get("candidates"), list) else [],
            detail={
                "planner_status": plan.status,
                "planner_confidence": plan.confidence,
                "planner_reason": plan.reason,
                "planner_received_route_advisory": bool(router_advisory),
                "route_advisory": router_advisory,
            },
            telemetry={"planner_ms": planner_ms, "strategy": "llm_planner"},
        ).to_dict()
        events.append(AgentEvent(type="answer", content=_render_proxy_answer(response_data)))
        return events

    if not plan.is_executable:
        if plan.error_code == "PLANNER_CONTRACT_FAILURE":
            detail = plan.raw.get("detail") if isinstance(plan.raw, Mapping) else {}
            response_data = _RESPONSE_NORMALIZER.clarification(
                message="抱歉，我不太理解您的意图。您是想查询业务数据，还是想查找 Tableau 看板、视图或数据源？",
                chain_mode=CHAIN_MODE,
                reason="planner_contract_failure",
                candidates=[],
                detail={
                    "planner_status": plan.status,
                    "planner_error_code": plan.error_code,
                    "planner_retry_attempted": bool(isinstance(detail, Mapping) and detail.get("planner_retry_attempted")),
                    "planner_retry_success": bool(isinstance(detail, Mapping) and detail.get("planner_retry_success")),
                    "planner_validation_error": detail,
                    "planner_received_route_advisory": bool(router_advisory),
                    "route_advisory": router_advisory,
                },
                telemetry={"planner_ms": planner_ms, "strategy": "llm_planner"},
            ).to_dict()
            response_data["response_data"]["source"] = "llm_planner"
            response_data["response_data"]["error_code"] = "PLANNER_CONTRACT_FAILURE"
            events.append(AgentEvent(type="tool_result", content={
                "tool": "tableau_mcp_llm_planner",
                "result": {"success": False, "data": response_data},
            }))
            events.append(AgentEvent(type="answer", content=_render_proxy_answer(response_data)))
            return events
        response_data = _tool_unavailable_response(
            code=plan.error_code or "TABLEAU_MCP_PLANNER_UNAVAILABLE",
            message="Tableau MCP Planner 未能生成可执行计划。",
            user_hint="请补充更明确的数据源、字段、筛选条件或分析口径后重试。",
            detail={
                "chain_mode": CHAIN_MODE,
                "strategy": "llm_planner",
                "plan": plan_payload,
                "planner_received_route_advisory": bool(router_advisory),
                "route_advisory": router_advisory,
            },
        )
        events.append(AgentEvent(type="answer", content=_render_proxy_answer(response_data)))
        return events

    events.append(AgentEvent(type="tool_call", content={
        "tool": "tableau_mcp",
        "params": {"mcp_tool": plan.tool_name, "chain_mode": CHAIN_MODE, "strategy": "llm_planner", "execution_source": "llm_planner"},
    }))
    query_start = time.monotonic()
    try:
        current_datasource = _current_datasource(datasource, context)
        execution = await _execute_mcp_host_tool(
            tool_name=str(plan.tool_name),
            args=plan.args,
            context=context,
            datasource_luid=str(plan.args.get("datasourceLuid") or current_datasource.get("datasource_luid") or ""),
            question=question,
            current_datasource=current_datasource,
            queryable_fields=queryable_fields if plan.tool_name == MCP_TOOL_NAME else None,
            strict_connection_access=plan.tool_name == MCP_LIST_DATASOURCES_TOOL_NAME,
            execution_source="llm_planner",
            compiler_status=compiler_result.status if compiler_result else None,
            compiler_reason=compiler_result.compile_reason if compiler_result else None,
            compiler_advisory=compiler_advisory,
            return_guardrail=True,
        )
        result, guardrail_payload = _unpack_execution_result(execution)
    except Exception as exc:
        logger.exception("LLM-planned Tableau MCP tool execution failed")
        guardrail_payload = _guardrail_payload_from_exception(exc)
        response_data = _execution_error_response(
            exc,
            default_code="MCP_PROXY_PLANNED_TOOL_FAILED",
            message="Tableau MCP 工具执行失败。",
            strategy="llm_planner",
            execution_source="llm_planner",
            detail={"tool": plan.tool_name, "planner_reason": plan.reason},
        )
        events.append(AgentEvent(type="tool_result", content={
            "tool": "tableau_mcp",
            "result": {"success": False, "error": str(exc), "data": response_data},
        }))
        events.append(_guardrail_event_from_payload(guardrail_payload, tool_name=str(plan.tool_name), strategy="llm_planner"))
        events.append(AgentEvent(type="answer", content=_render_proxy_answer(response_data)))
        return events

    events.append(_guardrail_event_from_payload(guardrail_payload, tool_name=str(plan.tool_name), strategy="llm_planner"))

    if _query_result_too_large_for_renderer(result):
        events.append(AgentEvent(type="error", content={
            "error_code": "DETAIL_SCAN_BLOCKED",
            "message": "Tableau MCP 返回结果行数超过受控展示上限，本次不输出明细结果。",
            "fallback_type": "query_result_too_large",
            "chain_mode": CHAIN_MODE,
            "strategy": "llm_planner",
        }))
        return events

    query_ms = max(0, int((time.monotonic() - query_start) * 1000))
    response_data = _normalize_planner_tool_response(
        result=result,
        tool_name=str(plan.tool_name),
        datasource=datasource,
        context=context,
        args=guardrail_payload.get("args") or plan.args,
        guardrail_payload=guardrail_payload,
        planner_payload=plan_payload,
        planner_ms=planner_ms,
        query_ms=query_ms,
    )
    if str(plan.tool_name) == MCP_TOOL_NAME:
        response_data["response_type"] = "query_result"
    response_data["execution_source"] = "llm_planner"
    response_data["compiler_status"] = compiler_result.status if compiler_result else None
    response_data["compiler_reason"] = compiler_result.compile_reason if compiler_result else None
    response_data["compiler_advisory"] = dict(compiler_advisory or {})
    response_data["route_advisory"] = router_advisory
    response_data["planner_received_route_advisory"] = bool(router_advisory)
    response_data["mcp_tool_name"] = str(plan.tool_name)
    events.append(AgentEvent(type="tool_result", content={
        "tool": "tableau_mcp",
        "result": {"success": True, "data": response_data},
    }))
    events.append(AgentEvent(type="answer", content=_render_proxy_answer(response_data)))
    return events


def _query_result_too_large_for_renderer(result: Any, *, max_rows: int = 200) -> bool:
    if not isinstance(result, Mapping):
        return False
    rows = result.get("rows")
    return isinstance(rows, list) and len(rows) > max_rows


def _normalize_planner_tool_response(
    *,
    result: Any,
    tool_name: str,
    datasource: Mapping[str, Any],
    context: ToolContext,
    args: Mapping[str, Any],
    guardrail_payload: Mapping[str, Any],
    planner_payload: Mapping[str, Any],
    planner_ms: int,
    query_ms: int,
) -> dict[str, Any]:
    if tool_name == MCP_LIST_DATASOURCES_TOOL_NAME:
        candidates = _datasource_candidates_from_mcp_result(result)
        response_data = _asset_candidates_response(
            candidates=candidates,
            query="",
            source="mcp",
            reason="list_datasources",
            message="已从 Tableau MCP 读取当前连接的数据源列表。",
            candidate_limit=50,
        )
    elif tool_name == MCP_GET_DATASOURCE_METADATA_TOOL_NAME:
        response_data = _asset_metadata_response_from_mcp(result, _current_datasource(datasource, context))
    elif tool_name == MULAN_LIST_TABLEAU_ASSETS_TOOL_NAME and isinstance(result, Mapping):
        response_data = dict(result)
    else:
        response_data = _normalize_response_data(
            result,
            ds_info=datasource,
            args=args,
            guardrail_payload=guardrail_payload,
        )
    response_data["strategy"] = "llm_planner"
    response_data["planner"] = dict(planner_payload)
    response_data["telemetry"] = {
        **(response_data.get("telemetry") if isinstance(response_data.get("telemetry"), Mapping) else {}),
        "planner_ms": planner_ms,
        "query_ms": query_ms,
        "strategy": "llm_planner",
    }
    return response_data


def _compiler_field_context(datasource: Mapping[str, Any], context: ToolContext) -> tuple[list[Any], list[Mapping[str, Any]]]:
    queryable_fields = list(datasource.get("queryable_fields") or [])
    metadata_raw = datasource.get("metadata_fields") or datasource.get("fields") or []
    metadata_fields = [dict(item) for item in metadata_raw if isinstance(item, Mapping)]
    if not queryable_fields:
        try:
            queryable_fields = _queryable_fields(datasource, context.connection_id)
        except Exception:
            logger.debug("deterministic compiler queryable field lookup failed", exc_info=True)
            queryable_fields = []
    metadata_raw = datasource.get("metadata_fields") or datasource.get("fields") or metadata_fields
    metadata_fields = [dict(item) for item in metadata_raw if isinstance(item, Mapping)]
    if not queryable_fields and metadata_fields:
        queryable_fields = [
            str(item.get("caption") or item.get("fieldCaption") or item.get("name") or item.get("fieldName") or "").strip()
            for item in metadata_fields
            if str(item.get("caption") or item.get("fieldCaption") or item.get("name") or item.get("fieldName") or "").strip()
        ]
    return queryable_fields, metadata_fields


def _compile_trace_payload(result: CompileResult, compile_ms: int) -> dict[str, Any]:
    return {
        "chain_mode": CHAIN_MODE,
        "status": result.status,
        "ambiguity_level": result.ambiguity_level,
        "pattern": result.pattern,
        "compile_reason": result.compile_reason,
        "compile_confidence": result.compile_confidence,
        "tool_name": result.tool_name,
        "matched_fields": result.matched_fields or {},
        "clarification": result.clarification or {},
        "compiler_advisory": result.compiler_advisory or {},
        "compile_ms": compile_ms,
    }


def _compiler_advisory_with_analysis_context(
    advisory: Mapping[str, Any] | None,
    *,
    analysis_context: Optional[Mapping[str, Any]],
) -> dict[str, Any]:
    payload = dict(advisory or {})
    if not isinstance(analysis_context, Mapping) or not analysis_context:
        payload.setdefault("analysis_context_summary", {})
        payload.setdefault("unresolved_references", False)
        return payload
    requested_metrics = list(analysis_context.get("requested_metrics") or [])
    requested_dimensions = list(analysis_context.get("requested_dimensions") or [])
    requested_filters = list(analysis_context.get("requested_filters") or [])
    unresolved = bool(analysis_context.get("unresolved_references"))
    payload["analysis_context_summary"] = {
        "is_follow_up": bool(analysis_context.get("is_follow_up") or analysis_context.get("is_followup")),
        "unresolved_references": unresolved,
        "requested_metrics": requested_metrics,
        "requested_dimensions": requested_dimensions,
        "requested_filter_count": len(requested_filters),
        "has_previous_successful_mcp_call": bool(
            analysis_context.get("previous_successful_mcp_call_ref") or analysis_context.get("mcp_args")
        ),
    }
    payload["unresolved_references"] = unresolved
    return payload


def _unpack_execution_result(execution: Any) -> tuple[Any, dict[str, Any]]:
    if isinstance(execution, tuple) and len(execution) == 2 and isinstance(execution[1], Mapping):
        return execution[0], dict(execution[1])
    return execution, {"decision": "allow", "args": None, "repairs": [], "tool_name": MCP_TOOL_NAME}


def _guardrail_event_from_payload(payload: Mapping[str, Any] | None, *, tool_name: str, strategy: str) -> AgentEvent:
    data = dict(payload or {})
    decision = str(data.get("decision") or "allow")
    return AgentEvent(type="tool_result", content={
        "tool": "mcp_args_guardrail",
        "result": {
            "success": decision != "reject",
            "event": MCP_ARGS_GUARDRAIL_REJECT if decision == "reject" else MCP_ARGS_GUARDRAIL_PASS,
            "data": {**data, "tool_name": data.get("tool_name") or tool_name, "execution_strategy": strategy},
        },
    })


def _guardrail_payload_from_exception(exc: Exception) -> dict[str, Any]:
    details = getattr(exc, "details", None)
    if isinstance(details, Mapping):
        guardrail = details.get("guardrail_decision") or details.get("guardrail")
        if isinstance(guardrail, Mapping):
            return dict(guardrail)
    return {"decision": "error", "args": None, "repairs": [], "tool_name": MCP_TOOL_NAME, "message": str(exc)}


def _execution_error_response(
    exc: Exception,
    *,
    default_code: str,
    message: str,
    strategy: str,
    execution_source: str,
    detail: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    details = getattr(exc, "details", None)
    guardrail = _guardrail_payload_from_exception(exc)
    code = str(
        guardrail.get("reject_code")
        or (details.get("code") if isinstance(details, Mapping) else "")
        or getattr(exc, "code", "")
        or default_code
    )
    return _tool_unavailable_response(
        code=code,
        message=str(guardrail.get("message") or message),
        user_hint=str(guardrail.get("user_hint") or "请稍后重试；如果持续失败，请带 trace_id 联系管理员排查 MCP Gateway。"),
        detail={
            "error": str(exc),
            "chain_mode": CHAIN_MODE,
            "strategy": strategy,
            "execution_source": execution_source,
            "guardrail_decision": guardrail,
            **dict(detail or {}),
        },
    )


def _validate_tableau_mcp_tool(
    *,
    question: str,
    tool_name: str,
    args: Mapping[str, Any],
    context: ToolContext,
    current_datasource: Mapping[str, Any] | None = None,
    queryable_fields: list[str] | None = None,
    strict_connection_access: bool = False,
) -> Any:
    """Validate Tableau MCP tool args through the unified service.

    Existing proxy tests use monkeypatched in-module access checks without a
    database.  The injected resolver keeps that behavior while moving business
    validation behind `TableauMcpGuardrailService`.
    """

    def _access_checker(connection_id: int, user_id: int | None, user_role: str | None) -> bool:
        if strict_connection_access:
            return _connection_is_accessible(context)
        return True

    resolver = DatasourceCandidateResolver(
        connection_access_checker=_access_checker,
        datasource_connection_checker=lambda datasource_luid, connection_id: True,
    )
    service = TableauMcpGuardrailService(resolver=resolver)
    return service.validate(
        TableauMcpGuardrailRequest(
            question=question,
            tool_name=tool_name,
            args=args,
            context=context,
            current_datasource=current_datasource,
            queryable_fields=queryable_fields,
        )
    )


def _is_datasource_list_request(question: str) -> bool:
    text = str(question or "")
    return bool(re.search(r"(有哪些|列出|查看|所有|可用).{0,8}数据(?:源|资产)|数据(?:源|资产).{0,8}(列表|清单|有哪些)", text))


def _is_datasource_metadata_request(question: str, intent_result: IntentClassification) -> bool:
    text = str(question or "")
    if _is_datasource_list_request(text):
        return False
    if bool(re.search(r"(介绍|说明|元数据|字段|表结构|数据结构|有哪些字段|包含哪些字段|有哪些列)", text)) and "数据源" in text:
        return True
    return bool(intent_result.is_asset_inventory)


async def _execute_mcp_host_tool(
    *,
    tool_name: str,
    args: Mapping[str, Any],
    context: ToolContext,
    datasource_luid: str | None = None,
    question: str | None = None,
    current_datasource: Mapping[str, Any] | None = None,
    queryable_fields: list[Any] | None = None,
    strict_connection_access: bool = False,
    execution_source: str | None = None,
    compiler_status: str | None = None,
    compiler_reason: str | None = None,
    compiler_advisory: Mapping[str, Any] | None = None,
    return_guardrail: bool = False,
) -> Any:
    from services.data_agent.mcp_host.runtime import MCPHostRuntime
    from services.tableau.mcp_client import get_tableau_mcp_client

    metadata_cache_key = _metadata_cache_key(tool_name=tool_name, context=context, datasource_luid=datasource_luid)
    if metadata_cache_key is not None:
        cached = _MCP_CACHE.get_datasource_metadata(
            connection_id=str(context.connection_id),
            datasource_luid=metadata_cache_key["datasource_luid"],
            schema_version=metadata_cache_key["schema_version"],
        )
        if cached.cache_hit:
            return cached.value

    trace_events: list[dict[str, Any]] = []
    client = get_tableau_mcp_client(connection_id=context.connection_id)
    runtime = MCPHostRuntime(
        client,
        connection_id=context.connection_id,
        datasource_luid=datasource_luid,
        timeout=30,
        trace=trace_events,
    )
    result = runtime.call_tool(
        tool_name,
        dict(args),
        timeout=30,
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
    if inspect.isawaitable(result):
        result = await result
    if metadata_cache_key is not None:
        payload = _RESPONSE_NORMALIZER.unwrap_mcp_result(result)
        _MCP_CACHE.set_datasource_metadata(
            connection_id=str(context.connection_id),
            datasource_luid=metadata_cache_key["datasource_luid"],
            schema_version=metadata_cache_key["schema_version"],
            value=result if isinstance(result, Mapping) else {"raw_result": result},
            ttl_seconds=_metadata_cache_ttl_seconds(),
            source="mcp",
            metadata_freshness=payload.get("metadata_freshness") or payload.get("synced_at"),
        )
    if return_guardrail:
        return result, _last_guardrail_trace(trace_events)
    return result


def _last_guardrail_trace(trace_events: list[dict[str, Any]]) -> dict[str, Any]:
    for event in reversed(trace_events):
        if event.get("event") == "mcp_host.guardrail" and isinstance(event.get("payload"), Mapping):
            payload = dict(event["payload"])
            decision = payload.get("guardrail_decision")
            if isinstance(decision, Mapping):
                return dict(decision)
            return payload
    return {"decision": "allow", "args": None, "repairs": [], "tool_name": MCP_TOOL_NAME}


def _metadata_cache_key(*, tool_name: str, context: ToolContext, datasource_luid: str | None) -> dict[str, str] | None:
    if tool_name != MCP_GET_DATASOURCE_METADATA_TOOL_NAME or not context.connection_id or not datasource_luid:
        return None
    return {
        "datasource_luid": str(datasource_luid),
        "schema_version": str(os.getenv("TABLEAU_MCP_METADATA_SCHEMA_VERSION", "default")).strip() or "default",
    }


def _metadata_cache_ttl_seconds() -> int:
    try:
        return max(1, int(str(os.getenv("TABLEAU_MCP_METADATA_CACHE_TTL_SECONDS", "1800")).strip()))
    except (TypeError, ValueError):
        return 1800


def _resolve_datasource_candidates(question: str, context: ToolContext) -> list[dict[str, Any]]:
    resolver = DatasourceCandidateResolver(
        datasource_asset_loader=lambda connection_id: _load_local_datasource_assets(connection_id),
        connection_access_checker=lambda connection_id, user_id, user_role: _connection_is_accessible(context),
        datasource_connection_checker=lambda datasource_luid, connection_id: True,
    )
    return resolver.resolve(question, context)


def _connection_is_accessible(context: ToolContext) -> bool:
    try:
        from app.core.database import SessionLocal
        from services.tableau.models import TableauConnection

        session = SessionLocal()
        try:
            connection = (
                session.query(TableauConnection)
                .filter(TableauConnection.id == context.connection_id)
                .first()
            )
            if not connection:
                return False
            if getattr(context, "user_role", None) == "admin":
                return True
            return getattr(connection, "owner_id", None) == context.user_id
        finally:
            session.close()
    except Exception:
        logger.debug("connection access check skipped", exc_info=True)
        return False


def _load_local_datasource_assets(connection_id: int) -> list[dict[str, Any]]:
    try:
        from app.core.database import SessionLocal
        from services.tableau.models import TableauAsset

        session = SessionLocal()
        try:
            rows = (
                session.query(TableauAsset)
                .filter(
                    TableauAsset.connection_id == connection_id,
                    TableauAsset.asset_type == "datasource",
                    TableauAsset.is_deleted == False,  # noqa: E712
                )
                .order_by(TableauAsset.synced_at.desc())
                .all()
            )
            return [_asset_candidate_from_row(row) for row in rows]
        finally:
            session.close()
    except Exception:
        logger.debug("local datasource resolver lookup failed", exc_info=True)
        return []


def _asset_candidate_from_row(row: Any) -> dict[str, Any]:
    return {
        "asset_id": getattr(row, "id", None),
        "connection_id": getattr(row, "connection_id", None),
        "datasource_luid": getattr(row, "tableau_id", None),
        "luid": getattr(row, "tableau_id", None),
        "name": getattr(row, "name", None),
        "project_name": getattr(row, "project_name", None),
        "description": getattr(row, "description", None),
        "field_count": getattr(row, "field_count", None),
        "synced_at": _serialize_datetime(getattr(row, "synced_at", None)),
    }


def _asset_candidates_response(
    *,
    candidates: list[Mapping[str, Any]],
    query: str,
    source: str,
    reason: str,
    message: str,
    candidate_limit: int | None = 5,
) -> dict[str, Any]:
    return _RESPONSE_NORMALIZER.asset_candidates(
        candidates=candidates,
        query=query,
        source=source,
        reason=reason,
        message=message,
        chain_mode=CHAIN_MODE,
        candidate_limit=candidate_limit,
    ).to_dict()


def _candidate_payload(candidate: Mapping[str, Any]) -> dict[str, Any]:
    return _RESPONSE_NORMALIZER.candidate(candidate)


def _asset_metadata_response_from_mcp(result: Any, candidate: Mapping[str, Any]) -> dict[str, Any]:
    payload = _unwrap_mcp_result(result)
    fields = _metadata_fields_from_payload(payload)
    expected_field_count = _metadata_expected_field_count(payload, candidate)
    metadata_quality = _metadata_quality(fields, expected_field_count)
    return _RESPONSE_NORMALIZER.asset_metadata(
        source="mcp",
        chain_mode=CHAIN_MODE,
        datasource_luid=candidate.get("datasource_luid") or candidate.get("luid"),
        datasource_name=candidate.get("name") or payload.get("name"),
        project_name=candidate.get("project_name") or payload.get("project_name"),
        description=payload.get("description") or payload.get("datasourceDescription") or candidate.get("description"),
        fields=fields,
        field_count=len(fields),
        raw_field_count=expected_field_count,
        field_groups=_metadata_field_groups(fields),
        analysis_suggestions=_metadata_analysis_suggestions(fields),
        metadata_quality=metadata_quality,
        metadata_freshness=payload.get("metadata_freshness") or payload.get("synced_at"),
    ).to_dict()


def _asset_metadata_response_from_catalog_cache(candidate: Mapping[str, Any], context: ToolContext) -> dict[str, Any] | None:
    asset_id = candidate.get("asset_id")
    datasource_luid = candidate.get("datasource_luid") or candidate.get("luid")
    if not asset_id or not datasource_luid:
        return None
    try:
        from app.core.database import SessionLocal
        from services.tableau.models import TableauAsset, TableauDatasourceField

        session = SessionLocal()
        try:
            asset = (
                session.query(TableauAsset)
                .filter(
                    TableauAsset.id == asset_id,
                    TableauAsset.connection_id == context.connection_id,
                    TableauAsset.tableau_id == datasource_luid,
                    TableauAsset.is_deleted == False,  # noqa: E712
                )
                .first()
            )
            if not asset:
                return None
            rows = (
                session.query(TableauDatasourceField)
                .filter(
                    TableauDatasourceField.asset_id == asset.id,
                    TableauDatasourceField.datasource_luid == datasource_luid,
                )
                .all()
            )
            fields = [
                row.to_dict()
                for row in rows
                if str(getattr(row, "field_name", "") or getattr(row, "field_caption", "") or "").strip()
            ]
            if not fields:
                return None
            freshness = _max_datetime(
                [getattr(asset, "synced_at", None)]
                + [getattr(row, "fetched_at", None) for row in rows]
                + [getattr(row, "mcp_checked_at", None) for row in rows]
            )
            return _RESPONSE_NORMALIZER.asset_metadata(
                source="catalog_cache",
                chain_mode=CHAIN_MODE,
                datasource_luid=datasource_luid,
                datasource_name=asset.name,
                project_name=asset.project_name,
                description=asset.description,
                fields=fields,
                field_count=len(fields),
                raw_field_count=len(fields),
                field_groups=_metadata_field_groups(fields),
                analysis_suggestions=_metadata_analysis_suggestions(fields),
                metadata_quality=_metadata_quality(fields, len(fields)),
                metadata_freshness=_serialize_datetime(freshness),
            ).to_dict()
        finally:
            session.close()
    except Exception:
        logger.debug("catalog cache metadata fallback failed", exc_info=True)
        return None


def _datasource_candidates_from_mcp_result(result: Any) -> list[dict[str, Any]]:
    payload = _unwrap_mcp_result(result)
    raw_items: Any = payload
    if isinstance(payload, Mapping):
        raw_items = payload.get("datasources") or payload.get("items") or payload.get("results") or []
    if not isinstance(raw_items, list):
        return []
    candidates: list[dict[str, Any]] = []
    for item in raw_items[:50]:
        if not isinstance(item, Mapping):
            continue
        candidates.append({
            "datasource_luid": item.get("datasource_luid") or item.get("luid") or item.get("id"),
            "name": item.get("name") or item.get("caption"),
            "project_name": item.get("project_name") or item.get("projectName"),
            "field_count": item.get("field_count") or item.get("fieldCount"),
            "synced_at": item.get("synced_at") or item.get("updatedAt"),
        })
    return candidates


def _unwrap_mcp_result(result: Any) -> dict[str, Any]:
    return _RESPONSE_NORMALIZER.unwrap_mcp_result(result)


def _payload_from_mcp_content(content: list[Any]) -> dict[str, Any]:
    return _RESPONSE_NORMALIZER.payload_from_mcp_content(content)


def _metadata_fields_from_payload(payload: Mapping[str, Any]) -> list[dict[str, Any]]:
    raw_fields: list[Any] = []

    def add_fields(value: Any) -> None:
        if isinstance(value, list):
            raw_fields.extend(value)

    def add_group_fields(groups: Any) -> None:
        if not isinstance(groups, list):
            return
        for group in groups:
            if not isinstance(group, Mapping):
                continue
            add_fields(group.get("fields"))

    add_fields(payload.get("fields"))
    add_group_fields(payload.get("fieldGroups"))
    datasource = payload.get("datasource")
    if isinstance(datasource, Mapping):
        add_fields(datasource.get("fields"))
        add_group_fields(datasource.get("fieldGroups"))
    raw = payload.get("raw")
    if isinstance(raw, Mapping):
        add_fields(raw.get("fields"))
        add_group_fields(raw.get("fieldGroups"))

    fields: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for item in raw_fields:
        if isinstance(item, Mapping):
            name = item.get("name") or item.get("field_name") or item.get("fieldName")
            caption = item.get("caption") or item.get("field_caption") or item.get("fieldCaption")
            if name or caption:
                payload_item = dict(item)
                key = _metadata_field_dedupe_key(payload_item)
                if key not in seen:
                    seen.add(key)
                    fields.append(payload_item)
        elif str(item or "").strip():
            payload_item = {"name": str(item).strip()}
            key = _metadata_field_dedupe_key(payload_item)
            if key not in seen:
                seen.add(key)
                fields.append(payload_item)
    return fields


def _metadata_field_dedupe_key(field: Mapping[str, Any]) -> tuple[str, str]:
    display_name = _field_caption(field)
    identity = (
        field.get("logicalTableId")
        or field.get("logical_table_id")
        or field.get("fullyQualifiedName")
        or field.get("fieldId")
        or field.get("id")
        or ""
    )
    return (_compact_text(display_name), str(identity or "").strip())


def _metadata_expected_field_count(payload: Mapping[str, Any], candidate: Mapping[str, Any]) -> int | None:
    for source in (payload, payload.get("datasource"), payload.get("raw"), candidate):
        if not isinstance(source, Mapping):
            continue
        for key in ("field_count", "fieldCount", "metadata_field_count", "metadataFieldCount"):
            value = source.get(key)
            if isinstance(value, int) and value >= 0:
                return value
            if isinstance(value, str) and value.isdigit():
                return int(value)
    return None


def _metadata_quality(fields: list[Mapping[str, Any]], expected_field_count: int | None) -> dict[str, Any]:
    field_count = len(fields)
    if field_count == 0:
        return {
            "status": "empty",
            "field_count": 0,
            "expected_field_count": expected_field_count,
            "message": "未从 Tableau MCP metadata payload 中解析到字段。",
        }
    if expected_field_count is not None and expected_field_count != field_count:
        return {
            "status": "partial",
            "field_count": field_count,
            "expected_field_count": expected_field_count,
            "message": f"已解析 {field_count} 个字段，与元数据声明的 {expected_field_count} 个字段不一致。",
        }
    return {
        "status": "complete",
        "field_count": field_count,
        "expected_field_count": expected_field_count if expected_field_count is not None else field_count,
        "message": f"已解析 {field_count} 个字段。",
    }


def _metadata_field_groups(fields: list[Mapping[str, Any]]) -> list[dict[str, Any]]:
    definitions = [
        ("measures", "指标字段", lambda item: _metadata_field_is_measure(item)),
        ("dimensions", "维度字段", lambda item: _metadata_field_is_dimension(item) and not _metadata_field_is_time(item)),
        ("time", "时间字段", _metadata_field_is_time),
        ("calculations", "计算字段", _metadata_field_is_calculation),
    ]
    groups: list[dict[str, Any]] = []
    for group_id, label, predicate in definitions:
        group_fields = [_metadata_field_summary(item) for item in fields if predicate(item)]
        if group_fields:
            groups.append({
                "id": group_id,
                "name": group_id,
                "label": label,
                "count": len(group_fields),
                "fields": group_fields,
            })
    return groups


def _metadata_field_summary(field: Mapping[str, Any]) -> dict[str, Any]:
    summary: dict[str, Any] = {"name": _field_caption(field)}
    for key in (
        "caption",
        "fieldCaption",
        "dataType",
        "data_type",
        "role",
        "defaultAggregation",
        "aggregation",
        "formula",
        "logicalTableId",
    ):
        value = field.get(key)
        if value is not None and value != "":
            summary[key] = value
    return summary


def _metadata_analysis_suggestions(fields: list[Mapping[str, Any]]) -> list[dict[str, Any]]:
    captions = [_field_caption(field) for field in fields if _field_caption(field)]
    measures = [_field_caption(field) for field in fields if _metadata_field_is_measure(field)]
    dimensions = [_field_caption(field) for field in fields if _metadata_field_is_dimension(field)]
    time_fields = [_field_caption(field) for field in fields if _metadata_field_is_time(field)]

    def find_field(*keywords: str) -> str | None:
        for caption in captions:
            normalized = _compact_text(caption)
            if all(_compact_text(keyword) in normalized for keyword in keywords):
                return caption
        return None

    budget_amount = find_field("预算", "金额")
    restored_amount = find_field("还原", "金额")
    budget_ratio = find_field("预算比") or find_field("与预算比")
    finance_period = find_field("财务", "期间") or find_field("期间")
    company_name = find_field("公司", "名称") or find_field("公司")

    suggestions: list[dict[str, Any]] = []

    if finance_period and (budget_amount or restored_amount or budget_ratio):
        fields_used = _ordered_present([finance_period, budget_amount, restored_amount, budget_ratio])
        suggestions.append({
            "analysis_type": "time_trend",
            "title": "按财务期间跟踪预算执行趋势",
            "question": f"按{finance_period}查看{_join_field_names(fields_used[1:])}的趋势。",
            "fields": fields_used,
        })

    if company_name and (budget_amount or restored_amount or budget_ratio):
        fields_used = _ordered_present([company_name, budget_amount, restored_amount, budget_ratio])
        suggestions.append({
            "analysis_type": "dimension_comparison",
            "title": "按公司比较预算与实际还原金额",
            "question": f"按{company_name}比较{_join_field_names(fields_used[1:])}。",
            "fields": fields_used,
        })

    if budget_amount and restored_amount:
        fields_used = _ordered_present([budget_amount, restored_amount, budget_ratio, finance_period, company_name])
        suggestions.append({
            "analysis_type": "budget_variance",
            "title": "分析预算金额与还原后金额差异",
            "question": f"分析{budget_amount}和{restored_amount}的差异，并结合{_join_field_names(fields_used[2:])}定位原因。",
            "fields": fields_used,
        })

    if not suggestions and time_fields and measures:
        fields_used = _ordered_present([time_fields[0], *measures[:3]])
        suggestions.append({
            "analysis_type": "time_trend",
            "title": "查看核心指标趋势",
            "question": f"按{time_fields[0]}查看{_join_field_names(measures[:3])}的趋势。",
            "fields": fields_used,
        })

    if not suggestions and dimensions and measures:
        fields_used = _ordered_present([dimensions[0], *measures[:3]])
        suggestions.append({
            "analysis_type": "dimension_comparison",
            "title": "按维度比较核心指标",
            "question": f"按{dimensions[0]}比较{_join_field_names(measures[:3])}。",
            "fields": fields_used,
        })

    return _dedupe_suggestions(suggestions)[:5]


def _ordered_present(values: list[str | None]) -> list[str]:
    output: list[str] = []
    seen: set[str] = set()
    for value in values:
        if not value:
            continue
        normalized = _compact_text(value)
        if normalized and normalized not in seen:
            seen.add(normalized)
            output.append(value)
    return output


def _join_field_names(values: list[str]) -> str:
    names = [value for value in values if value]
    return "、".join(names) if names else "相关字段"


def _dedupe_suggestions(suggestions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    seen: set[tuple[str, tuple[str, ...]]] = set()
    for suggestion in suggestions:
        key = (
            str(suggestion.get("analysis_type") or ""),
            tuple(_compact_text(field) for field in suggestion.get("fields") or []),
        )
        if key in seen:
            continue
        seen.add(key)
        output.append(suggestion)
    return output


def _metadata_field_is_measure(field: Mapping[str, Any]) -> bool:
    role = _metadata_string(field, "role", "semanticRole").casefold()
    if role == "measure":
        return True
    if _metadata_raw_value(field, "defaultAggregation", "aggregation") is not None:
        return True
    data_type = _metadata_string(field, "dataType", "data_type", "type").casefold()
    return any(token in data_type for token in ("int", "real", "float", "double", "decimal", "number", "numeric"))


def _metadata_field_is_dimension(field: Mapping[str, Any]) -> bool:
    role = _metadata_string(field, "role", "semanticRole").casefold()
    if role == "dimension":
        return True
    return not _metadata_field_is_measure(field)


def _metadata_field_is_time(field: Mapping[str, Any]) -> bool:
    data_type = _metadata_string(field, "dataType", "data_type", "type").casefold()
    caption = _field_caption(field)
    normalized = _compact_text(caption)
    return (
        "date" in data_type
        or "time" in data_type
        or any(token in normalized for token in ("日期", "时间", "期间", "年月", "月份", "季度", "年度", "财务期间"))
    )


def _metadata_field_is_calculation(field: Mapping[str, Any]) -> bool:
    column_class = _metadata_string(field, "columnClass", "column_class").casefold()
    return (
        bool(_metadata_string(field, "formula"))
        or bool(_metadata_raw_value(field, "isCalculated", "is_calculated", "calculated"))
        or column_class == "calculation"
    )


def _tool_unavailable_response(
    *,
    code: str,
    message: str,
    user_hint: str,
    detail: Mapping[str, Any],
) -> dict[str, Any]:
    return _RESPONSE_NORMALIZER.tool_unavailable(
        code=code,
        message=message,
        user_hint=user_hint,
        chain_mode=CHAIN_MODE,
        detail=detail,
    ).to_dict()


def _max_datetime(values: list[Any]) -> Any:
    comparable = [value for value in values if value is not None]
    return max(comparable) if comparable else None


def _serialize_datetime(value: Any) -> Any:
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return value


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
    return _RESPONSE_NORMALIZER.query_result(
        result=result,
        datasource=ds_info,
        args=args,
        chain_mode=CHAIN_MODE,
        guardrail_payload=guardrail_payload,
    ).response_data


def _metric_names_from_args(args: Mapping[str, Any]) -> list[str]:
    return _RESPONSE_NORMALIZER.metric_names_from_args(args)


def _render_proxy_answer(response_data: Mapping[str, Any]) -> str:
    response_type = response_data.get("response_type")
    payload = response_data.get("response_data") if isinstance(response_data.get("response_data"), Mapping) else response_data
    if response_type == RESPONSE_ASSET_METADATA:
        name = payload.get("datasource_name") or "该数据源"
        field_count = payload.get("field_count") or len(payload.get("fields") or [])
        fields = payload.get("fields") if isinstance(payload.get("fields"), list) else []
        field_names = [_field_caption(field) for field in fields[:8] if _field_caption(field)]
        suggestions = payload.get("analysis_suggestions") if isinstance(payload.get("analysis_suggestions"), list) else []
        suggestion_titles = [
            str(item.get("title"))
            for item in suggestions[:3]
            if isinstance(item, Mapping) and item.get("title")
        ]
        detail_parts = []
        if field_names:
            detail_parts.append(f"字段示例：{'、'.join(field_names)}。")
        if suggestion_titles:
            detail_parts.append(f"可做分析：{'；'.join(suggestion_titles)}。")
        detail = "".join(detail_parts)
        if payload.get("source") == "catalog_cache":
            return f"Tableau MCP metadata 暂不可用，以下是基于本地 catalog cache 的缓存元数据：{name}，共 {field_count} 个字段。{detail}"
        return f"已通过 Tableau MCP 读取数据源元数据：{name}，共 {field_count} 个字段。{detail}"
    if response_type == RESPONSE_ASSET_CANDIDATES:
        candidates = payload.get("candidates") if isinstance(payload, Mapping) else []
        if payload.get("reason") == "asset_inventory":
            total = payload.get("total_count") or len(candidates or [])
            names = "、".join(str(item.get("name")) for item in candidates if isinstance(item, Mapping) and item.get("name"))
            return f"当前连接可见的 Tableau 资产共 {total} 个：{names}。" if names else "当前连接下没有匹配的 Tableau 资产。"
        if payload.get("reason") == "list_datasources":
            total = payload.get("total_count") or len(candidates or [])
            names = "、".join(str(item.get("name")) for item in candidates if isinstance(item, Mapping) and item.get("name"))
            prefix = "Tableau MCP 未返回数据源列表，以下为本地 catalog cache 缓存清单" if payload.get("source") == "catalog_cache" else "当前连接的数据源清单"
            return f"{prefix}，共 {total} 个：{names}。" if names else f"{prefix}为空。"
        names = "、".join(str(item.get("name")) for item in candidates if isinstance(item, Mapping) and item.get("name"))
        return f"找到多个可能的数据源：{names}。请指定其中一个后继续。" if names else "找到多个可能的数据源，请指定一个后继续。"
    if response_type == RESPONSE_ASSET_NOT_FOUND:
        return str(payload.get("message") or "当前连接下未找到匹配的数据源。")
    if response_type == RESPONSE_TOOL_UNAVAILABLE:
        return str(payload.get("message") or "Tableau MCP 工具暂不可用。")
    if response_type == "clarification":
        return str(payload.get("message") or "请补充更明确的信息后继续。")
    rows = response_data.get("rows") if isinstance(response_data, Mapping) else []
    row_count = len(rows) if isinstance(rows, list) else 0
    if row_count == 0:
        return "查询已完成，未返回数据行。"
    return f"查询已完成，返回 {row_count} 行结果。"


def _current_datasource(ds_info: Mapping[str, Any], context: ToolContext) -> dict[str, Any]:
    datasource_luid = ds_info.get("luid") or ds_info.get("datasource_luid") or ds_info.get("tableau_id")
    payload = {
        "name": ds_info.get("name"),
        "luid": datasource_luid,
        "datasource_luid": datasource_luid,
        "connection_id": context.connection_id,
    }
    field_metadata = _datasource_field_metadata(ds_info)
    if field_metadata:
        payload["fields"] = field_metadata
    for key in ("catalog_fields", "queryable_fields", "catalog_only_fields"):
        if isinstance(ds_info.get(key), list):
            payload[key] = list(ds_info[key])
    if isinstance(ds_info.get("field_capability_summary"), Mapping):
        payload["field_capability_summary"] = dict(ds_info["field_capability_summary"])
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
    datasource_luid = ds_info.get("luid") or ds_info.get("datasource_luid") or ds_info.get("tableau_id")
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
    datasource_luid = ds_info.get("luid") or ds_info.get("datasource_luid") or ds_info.get("tableau_id")
    if datasource_luid:
        payload["accessible_datasource_luids"] = [datasource_luid]
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
    router_advisory = _router_advisory_from_analysis_context(context)
    return {
        "status": "unresolved" if unresolved else ("resolved" if context else "empty"),
        "datasource_name": context.get("datasource_name"),
        "metric_names": list(context.get("metric_names") or []),
        "dimension_names": list(context.get("dimension_names") or []),
        "requested_metrics": list(context.get("requested_metrics") or []),
        "requested_dimensions": list(context.get("requested_dimensions") or []),
        "filter_names": list(context.get("filter_names") or []),
        "requested_filters": list(context.get("requested_filters") or []),
        "unresolved_references": unresolved,
        "calculation_performed": False,
        "planner_received_route_advisory": bool(router_advisory),
        "route_advisory": router_advisory,
    }


def _analysis_context_with_router_advisory(
    context: ToolContext,
    analysis_context: Optional[Mapping[str, Any]],
) -> dict[str, Any]:
    merged = dict(analysis_context or {})
    context_analysis = getattr(context, "analysis_context", None)
    if isinstance(context_analysis, Mapping):
        advisory = context_analysis.get("router_advisory")
        if isinstance(advisory, Mapping) and advisory:
            merged["router_advisory"] = dict(advisory)
    if merged:
        context.analysis_context = dict(merged)
    return merged


def _router_advisory_from_analysis_context(analysis_context: Optional[Mapping[str, Any]]) -> dict[str, Any]:
    if not isinstance(analysis_context, Mapping):
        return {}
    advisory = analysis_context.get("router_advisory")
    if isinstance(advisory, Mapping):
        return dict(advisory)
    return {}

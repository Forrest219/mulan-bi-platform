"""Data Agent Runner — observability wrapper around ReActEngine.run()

Iterates engine events, persists BiAgentRun / BiAgentStep records, and
yields raw AgentEvent objects (SSE serialisation is the caller's job).

No web framework dependency: only SQLAlchemy + pure Python.
"""

import asyncio
import logging
import json
import re
import time
import uuid as uuid_lib
from typing import Any, AsyncGenerator, Dict, List, Optional

from sqlalchemy import func as sa_func
from sqlalchemy.orm import Session

from services.agent_observability.structured_error import StructuredBIError, persist_structured_error

from .chain_selector import select_data_agent_chain
from .engine import ReActEngine
from .intent_classifier import IntentClassification, classify_intent
from .mcp_first_main import run_mcp_first_main_path
from .mcp_proxy_main import run_mcp_proxy_main_path
from .models import BiAgentRun, BiAgentStep
from .result_transform import can_transform_previous_result, transform_previous_result
from .response import AgentEvent, normalize_table_response, table_data_event_from_response
from .router_guardrail import RouteDecision
from .session import AgentSession, SessionManager
from .tableau_mcp_telemetry import build_fallback_audit_payload
from .intent.keyword_match import is_direct_query, is_chart_request
from .tool_base import ToolContext
from .engine import _infer_col_types, _build_chart_data

logger = logging.getLogger(__name__)

_SCHEMA_ASSET_PATTERN = re.compile(r"数据(?:资产|源)\s+\*\*([^*]+)\*\*")
_FOLLOWUP_METRIC_PATTERN = re.compile(r"(这个|这些|上述|上面|该)\s*(指标|数据|结果)?")
_AGGREGATE_CONTEXT_FUNCTIONS = {"SUM", "AVG", "COUNT", "COUNTD", "MIN", "MAX", "MEDIAN", "ATTR"}
_TIME_CONTEXT_FUNCTIONS = {"YEAR", "QUARTER", "MONTH", "WEEK", "DAY"}
_AGENT_PERSISTENCE_FAILED = "AGENT_PERSISTENCE_FAILED"


def _rollback_after_persistence_error(db: Session) -> None:
    rollback = getattr(db, "rollback", None)
    if rollback is None:
        return
    try:
        rollback()
    except Exception:
        logger.warning("Failed to rollback after agent persistence error", exc_info=True)


def _log_final_telemetry_failure(
    exc: Exception,
    *,
    conversation_id: str,
    trace_id: str,
    run_id: Optional[uuid_lib.UUID],
    user_id: Optional[int],
    response_type: str,
    error_code: str,
) -> None:
    logger.exception(
        "Agent final response telemetry persistence failed",
        extra={
            "conversation_id": conversation_id,
            "trace_id": trace_id,
            "run_id": str(run_id) if run_id else None,
            "user_id": user_id,
            "response_type": response_type,
            "error_code": error_code,
            "exception_type": type(exc).__name__,
        },
    )


def _persistence_failed_event(*, trace_id: str, run_id: Optional[uuid_lib.UUID]) -> AgentEvent:
    return AgentEvent(
        type="error",
        content={
            "error_code": _AGENT_PERSISTENCE_FAILED,
            "message": "回答生成成功但保存失败，请重试。",
            "trace_id": trace_id,
            "run_id": str(run_id) if run_id else "",
            "retryable": True,
        },
    )


async def run_agent(
    engine: ReActEngine,
    context: ToolContext,
    session_mgr: SessionManager,
    session: AgentSession,
    question: str,
    trace_id: str,
    current_user: Dict,
    db: Session,
    connection_id: Optional[int] = None,
    route_decision: Optional[RouteDecision] = None,
    intent_result: Optional[IntentClassification] = None,
    enforce_controlled_data_path: bool = False,
) -> AsyncGenerator[AgentEvent, None]:
    """Execute the ReAct engine with full observability.

    Yields:
        AgentEvent objects (metadata, thinking, tool_call, tool_result,
        answer, error).  The caller is responsible for serialising them
        to SSE or any other transport format.
    """
    conversation_id_str = str(session.conversation_id)
    total_start = time.monotonic()
    last_step_at = total_start
    pending_tool_start: Optional[float] = None
    tools_used: List[str] = []
    steps_count = 0
    last_tool_result: Dict = {}
    table_response: Optional[dict] = None
    table_data_emitted = False
    run_id: Optional[uuid_lib.UUID] = None
    step_number = 0

    try:
        # Create bi_agent_runs record
        run = BiAgentRun(
            conversation_id=uuid_lib.UUID(conversation_id_str),
            user_id=current_user["id"],
            question=question,
            connection_id=connection_id,
            status="running",
        )
        db.add(run)
        db.commit()
        db.refresh(run)
        run_id = run.id

        # metadata event
        yield AgentEvent(
            type="metadata",
            content={
                "conversation_id": conversation_id_str,
                "run_id": str(run_id),
            },
        )

        def _elapsed_ms(start: float, end: Optional[float] = None) -> int:
            return max(0, int(((end or time.monotonic()) - start) * 1000))

        intent_start = time.monotonic()
        intent_result = intent_result or classify_intent(
            question,
            connection_type=getattr(context, "connection_type", None),
        )
        step_number += 1
        db.add(
            BiAgentStep(
                run_id=run_id,
                step_number=step_number,
                step_type="thinking",
                tool_name="intent_classifier",
                content=json.dumps(intent_result.to_dict(), ensure_ascii=False)[:500],
                execution_time_ms=_elapsed_ms(intent_start),
            )
        )
        db.commit()

        previous_result = resolve_recent_query_result(session_mgr, session, current_user["id"])
        if can_transform_previous_result(question, previous_result):
            transform_start = time.monotonic()
            tools_used.append("previous_result_transform")
            steps_count += 1
            step_number += 1
            tool_params = {"source": "previous_query_result", "operation": "table_transform"}
            db.add(BiAgentStep(
                run_id=run_id,
                step_number=step_number,
                step_type="tool_call",
                tool_name="previous_result_transform",
                tool_params=tool_params,
                execution_time_ms=0,
            ))
            db.commit()
            yield AgentEvent(type="tool_call", content={"tool": "previous_result_transform", "params": tool_params})

            response_data = transform_previous_result(question, previous_result)
            event_at = time.monotonic()
            step_number += 1
            db.add(BiAgentStep(
                run_id=run_id,
                step_number=step_number,
                step_type="tool_result",
                tool_name="previous_result_transform",
                tool_result_summary=str({
                    "source": response_data.get("source"),
                    "fields": response_data.get("fields"),
                    "row_count": len(response_data.get("rows") or []),
                    "transformations": response_data.get("transformations"),
                })[:500],
                execution_time_ms=_elapsed_ms(transform_start, event_at),
            ))
            db.commit()
            yield AgentEvent(type="tool_result", content={
                "tool": "previous_result_transform",
                "result": {
                    "success": True,
                    "data": {
                        "source": response_data.get("source"),
                        "field_count": len(response_data.get("fields") or []),
                        "row_count": len(response_data.get("rows") or []),
                        "transformations": response_data.get("transformations") or [],
                    },
                },
            })

            row_count = len(response_data.get("rows") or [])
            transform_count = len(response_data.get("transformations") or [])
            answer_text = f"已基于上一条结果追加 {transform_count} 个派生列，返回 {row_count} 行结果。"
            execution_time_ms = _elapsed_ms(total_start)
            step_number += 1
            try:
                db.add(BiAgentStep(
                    run_id=run_id,
                    step_number=step_number,
                    step_type="answer",
                    tool_name="answer_renderer",
                    content=answer_text[:500],
                    execution_time_ms=_elapsed_ms(event_at),
                ))
                db.query(BiAgentRun).filter(BiAgentRun.id == run_id).update(
                    {
                        BiAgentRun.status: "completed",
                        BiAgentRun.steps_count: steps_count,
                        BiAgentRun.tools_used: tools_used,
                        BiAgentRun.response_type: "query_result",
                        BiAgentRun.execution_time_ms: execution_time_ms,
                        BiAgentRun.completed_at: sa_func.now(),
                    },
                    synchronize_session=False,
                )
                db.commit()
            except Exception as exc:
                _rollback_after_persistence_error(db)
                _log_final_telemetry_failure(
                    exc,
                    conversation_id=conversation_id_str,
                    trace_id=trace_id,
                    run_id=run_id,
                    user_id=current_user.get("id"),
                    response_type="query_result",
                    error_code="AGENT_TELEMETRY_PERSISTENCE_FAILED",
                )
            try:
                session_mgr.persist_message(
                    session=session,
                    role="assistant",
                    content=answer_text,
                    response_type="query_result",
                    response_data=response_data,
                    tools_used=tools_used,
                    trace_id=trace_id,
                    steps_count=steps_count,
                    execution_time_ms=execution_time_ms,
                    sources_count=1 if context.connection_id else 0,
                    top_sources=[context.connection_name] if context.connection_id and context.connection_name else [],
                )
            except Exception as exc:
                _rollback_after_persistence_error(db)
                logger.exception(
                    "Agent assistant message persistence failed",
                    extra={
                        "conversation_id": conversation_id_str,
                        "trace_id": trace_id,
                        "run_id": str(run_id) if run_id else None,
                        "user_id": current_user.get("id"),
                        "response_type": "query_result",
                        "error_code": _AGENT_PERSISTENCE_FAILED,
                        "exception_type": type(exc).__name__,
                    },
                )
                yield _persistence_failed_event(trace_id=trace_id, run_id=run_id)
                return
            normalized = normalize_table_response(response_data)
            if normalized is not None:
                yield AgentEvent(type="table_data", content=table_data_event_from_response(normalized))
            yield AgentEvent(type="done", content={
                "answer": answer_text,
                "trace_id": trace_id,
                "run_id": str(run_id),
                "tools_used": tools_used,
                "response_type": "query_result",
                "response_data": response_data,
                "steps_count": steps_count,
                "execution_time_ms": execution_time_ms,
                "sources_count": 1 if context.connection_id else 0,
                "top_sources": [context.connection_name] if context.connection_id and context.connection_name else [],
            })
            return

        chain_selection = select_data_agent_chain()
        force_tableau_mcp_proxy = _is_tableau_mcp_context(context)
        controlled_asset_intent = (chain_selection.is_mcp_proxy or force_tableau_mcp_proxy) and (
            intent_result.is_asset_inventory
            or bool(route_decision and route_decision.is_asset_question)
        )
        if enforce_controlled_data_path and (intent_result.is_data_intent or controlled_asset_intent):
            followup_context = resolve_recent_query_context(session_mgr, session, current_user["id"])
            if chain_selection.is_fallback and not force_tableau_mcp_proxy:
                logger.warning("Data Agent chain mode fallback: %s", chain_selection.trace_detail())
                fallback_message = chain_selection.fallback_message()
                if fallback_message:
                    yield AgentEvent(type="thinking", content=fallback_message)
            if force_tableau_mcp_proxy and not chain_selection.is_mcp_proxy:
                fallback_audit = build_fallback_audit_payload(
                    actual_entry="runner",
                    fallback_attempted=True,
                    fallback_blocked=True,
                    fallback_target="run_mcp_first_main_path",
                    fallback_blocked_reason="tableau_mcp_strict_chain",
                    extra_trace=chain_selection.trace_detail(),
                )
                logger.error(
                    "Blocked Tableau MCP hidden fallback to legacy chain: %s",
                    fallback_audit,
                )
                yield AgentEvent(
                    type="thinking",
                    content="已识别为 Tableau MCP 场景，阻止回退到 legacy QuerySpec 链路，改用 MCP Proxy 主干。",
                )
                yield AgentEvent(type="tool_result", content={
                    "tool": "fallback_audit",
                    "result": {"success": True, "data": fallback_audit},
                })
            controlled_path = (
                run_mcp_proxy_main_path
                if chain_selection.is_mcp_proxy or force_tableau_mcp_proxy
                else run_mcp_first_main_path
            )
            async for event in controlled_path(
                question=question,
                context=context,
                intent_result=intent_result,
                datasource_name_hint=resolve_recent_schema_asset_name(session_mgr, session, current_user["id"]),
                analysis_context=followup_context,
            ):
                event_at = time.monotonic()
                if event.type == "thinking":
                    step_number += 1
                    db.add(BiAgentStep(
                        run_id=run_id,
                        step_number=step_number,
                        step_type="thinking",
                        content=str(event.content)[:500],
                        execution_time_ms=_elapsed_ms(last_step_at, event_at),
                    ))
                    db.commit()
                    last_step_at = event_at
                    yield event
                elif event.type == "tool_call":
                    tool_name = event.content.get("tool", "")
                    if tool_name and tool_name not in tools_used:
                        tools_used.append(tool_name)
                    steps_count += 1
                    step_number += 1
                    db.add(BiAgentStep(
                        run_id=run_id,
                        step_number=step_number,
                        step_type="tool_call",
                        tool_name=tool_name,
                        tool_params=event.content.get("params", {}),
                        execution_time_ms=0,
                    ))
                    db.commit()
                    pending_tool_start = event_at
                    last_step_at = event_at
                    yield event
                elif event.type == "tool_result":
                    tool_name = event.content.get("tool", "")
                    result_data = event.content.get("result", {})
                    summary = result_data.get("data") if isinstance(result_data, dict) else result_data
                    step_number += 1
                    db.add(BiAgentStep(
                        run_id=run_id,
                        step_number=step_number,
                        step_type="tool_result",
                        tool_name=tool_name,
                        tool_result_summary=str(summary)[:500] if summary else "",
                        execution_time_ms=_elapsed_ms(pending_tool_start or last_step_at, event_at),
                    ))
                    db.commit()
                    pending_tool_start = None
                    last_step_at = event_at
                    last_tool_result = result_data
                    yield event
                    data = result_data.get("data") if isinstance(result_data, dict) else None
                    normalized = normalize_table_response(data)
                    if normalized is not None:
                        table_response = normalized
                        table_data_emitted = True
                        yield AgentEvent(type="table_data", content=table_data_event_from_response(table_response))
                elif event.type == "table_data":
                    normalized = normalize_table_response(event.content)
                    if normalized is not None:
                        table_response = normalized
                        table_data_emitted = True
                        yield AgentEvent(type="table_data", content=table_data_event_from_response(table_response))
                    else:
                        yield event
                elif event.type == "answer":
                    answer_text = str(event.content or "")
                    execution_time_ms = _elapsed_ms(total_start, event_at)
                    response_type = "text"
                    response_data = None
                    data = last_tool_result.get("data") if isinstance(last_tool_result, dict) else None
                    if table_response is not None:
                        response_data = table_response
                        response_type = "query_result" if chain_selection.is_mcp_proxy else "table"
                    elif isinstance(data, dict):
                        if isinstance(data.get("response_type"), str) and isinstance(data.get("response_data"), dict):
                            response_type = data["response_type"]
                            response_data = data["response_data"]
                        else:
                            response_data = data
                            has_table_shape = "rows" in data and "fields" in data
                            if chain_selection.is_mcp_proxy and has_table_shape:
                                response_type = "query_result"
                            elif has_table_shape:
                                response_type = "table"
                            else:
                                response_type = "text"
                    step_number += 1
                    try:
                        db.add(BiAgentStep(
                            run_id=run_id,
                            step_number=step_number,
                            step_type="answer",
                            tool_name="answer_renderer",
                            content=answer_text[:500],
                            execution_time_ms=_elapsed_ms(last_step_at, event_at),
                        ))
                        db.query(BiAgentRun).filter(BiAgentRun.id == run_id).update(
                            {
                                BiAgentRun.status: "completed",
                                BiAgentRun.steps_count: steps_count,
                                BiAgentRun.tools_used: tools_used if tools_used else None,
                                BiAgentRun.response_type: response_type,
                                BiAgentRun.execution_time_ms: execution_time_ms,
                                BiAgentRun.completed_at: sa_func.now(),
                            },
                            synchronize_session=False,
                        )
                        db.commit()
                    except Exception as exc:
                        _rollback_after_persistence_error(db)
                        _log_final_telemetry_failure(
                            exc,
                            conversation_id=conversation_id_str,
                            trace_id=trace_id,
                            run_id=run_id,
                            user_id=current_user.get("id"),
                            response_type=response_type,
                            error_code="AGENT_TELEMETRY_PERSISTENCE_FAILED",
                        )
                    try:
                        session_mgr.persist_message(
                            session=session,
                            role="assistant",
                            content=answer_text,
                            response_type=response_type,
                            response_data=response_data,
                            tools_used=tools_used,
                            trace_id=trace_id,
                            steps_count=steps_count,
                            execution_time_ms=execution_time_ms,
                            sources_count=1 if context.connection_id else 0,
                            top_sources=[context.connection_name] if context.connection_id and context.connection_name else [],
                        )
                    except Exception as exc:
                        _rollback_after_persistence_error(db)
                        logger.exception(
                            "Agent assistant message persistence failed",
                            extra={
                                "conversation_id": conversation_id_str,
                                "trace_id": trace_id,
                                "run_id": str(run_id) if run_id else None,
                                "user_id": current_user.get("id"),
                                "response_type": response_type,
                                "error_code": _AGENT_PERSISTENCE_FAILED,
                                "exception_type": type(exc).__name__,
                            },
                        )
                        yield _persistence_failed_event(trace_id=trace_id, run_id=run_id)
                        return
                    if response_type == "table" and table_response is not None and not table_data_emitted:
                        table_data_emitted = True
                        yield AgentEvent(type="table_data", content=table_data_event_from_response(table_response))
                    yield AgentEvent(type="done", content={
                        "answer": answer_text,
                        "trace_id": trace_id,
                        "run_id": str(run_id),
                        "tools_used": tools_used,
                        "response_type": response_type,
                        "response_data": response_data,
                        "steps_count": steps_count,
                        "execution_time_ms": execution_time_ms,
                        "sources_count": 1 if context.connection_id else 0,
                        "top_sources": [context.connection_name] if context.connection_id and context.connection_name else [],
                    })
                elif event.type == "error":
                    error_content = event.content if isinstance(event.content, dict) else {"message": str(event.content)}
                    err_code = str(error_content.get("error_code") or "AGENT_003")[:16]
                    execution_time_ms = _elapsed_ms(total_start, event_at)
                    response_type = "fallback" if error_content.get("fallback_type") else "error"
                    step_number += 1
                    db.add(BiAgentStep(
                        run_id=run_id,
                        step_number=step_number,
                        step_type="error",
                        tool_name="controlled_main",
                        content=str(error_content.get("message") or "")[:500],
                        execution_time_ms=_elapsed_ms(last_step_at, event_at),
                    ))
                    db.query(BiAgentRun).filter(BiAgentRun.id == run_id).update(
                        {
                            BiAgentRun.status: "failed",
                            BiAgentRun.error_code: err_code,
                            BiAgentRun.steps_count: steps_count,
                            BiAgentRun.tools_used: tools_used if tools_used else None,
                            BiAgentRun.response_type: response_type,
                            BiAgentRun.execution_time_ms: execution_time_ms,
                            BiAgentRun.completed_at: sa_func.now(),
                        },
                        synchronize_session=False,
                    )
                    db.commit()
                    session_mgr.persist_message(
                        session=session,
                        role="assistant",
                        content=str(error_content.get("message") or "Agent 执行失败"),
                        response_type=response_type,
                        response_data=error_content,
                        tools_used=tools_used if tools_used else None,
                        trace_id=trace_id,
                        steps_count=steps_count,
                        execution_time_ms=execution_time_ms,
                        sources_count=1 if context.connection_id else 0,
                        top_sources=[context.connection_name] if context.connection_id and context.connection_name else [],
                    )
                    yield event
            return

        # 直接查询快速路径：跳过 LLM Think 首步，直接执行 QueryTool
        force_first_tool = None
        force_first_params = None
        should_force_query = bool(route_decision and route_decision.is_data_question) or is_direct_query(question)
        if should_force_query:
            force_first_tool = "query"
            force_first_params = {"question": question}
            force_first_params.update(_infer_analysis_params(question))
            followup_context = resolve_recent_query_context(session_mgr, session, current_user["id"])
            followup_datasource_name = (
                followup_context.get("datasource_name")
                or resolve_recent_schema_asset_name(session_mgr, session, current_user["id"])
            )
            if followup_datasource_name:
                force_first_params["datasource_name"] = followup_datasource_name
            metric_names = followup_context.get("metric_names") or []
            if metric_names and _FOLLOWUP_METRIC_PATTERN.search(question):
                force_first_params["question"] = f"{'、'.join(metric_names)} {question}"
            dimension_names = followup_context.get("dimension_names") or []
            if (metric_names or dimension_names) and re.search(r"(继续|拆分|再按|每个年份|每年|年份)", question):
                hints = list(dimension_names) + list(metric_names)
                force_first_params["question"] = f"{'、'.join(hints)} {question}"
            logger.info("fast_path: is_direct_query=True, force_first_tool=query, question=%s", question[:80])

        async for event in engine.run(
            query=question,
            context=context,
            session=session,
            force_first_tool=force_first_tool,
            force_first_params=force_first_params,
            route_decision=route_decision,
        ):
            event_at = time.monotonic()
            if event.type == "thinking":
                step_number += 1
                step = BiAgentStep(
                    run_id=run_id,
                    step_number=step_number,
                    step_type="thinking",
                    content=event.content[:500] if event.content else None,
                    execution_time_ms=_elapsed_ms(last_step_at, event_at),
                )
                db.add(step)
                db.commit()
                last_step_at = event_at
                yield event

            elif event.type == "tool_call":
                tool_name = event.content.get("tool", "")
                if tool_name not in tools_used:
                    tools_used.append(tool_name)
                steps_count += 1
                step_number += 1
                # 从 engine 的 active_skill_versions 获取版本 ID（Track B LLM 集成）
                _version_id_str = getattr(engine, "_active_skill_versions", {}).get(tool_name)
                _skill_version_id = None
                if _version_id_str:
                    try:
                        import uuid as _uuid_mod
                        _skill_version_id = _uuid_mod.UUID(_version_id_str)
                    except (ValueError, AttributeError):
                        pass
                step = BiAgentStep(
                    run_id=run_id,
                    step_number=step_number,
                    step_type="tool_call",
                    tool_name=tool_name,
                    tool_params=event.content.get("params", {}),
                    skill_version_id=_skill_version_id,
                    execution_time_ms=0,
                )
                db.add(step)
                db.commit()
                pending_tool_start = event_at
                last_step_at = event_at
                yield event

            elif event.type == "tool_result":
                tool_name = event.content.get("tool", "")
                result_data = event.content.get("result", {})
                structured_error = None
                if isinstance(result_data, dict) and (
                    result_data.get("success") is False or result_data.get("error")
                ):
                    summary = (
                        result_data.get("error")
                        or result_data.get("message")
                        or result_data.get("error_message")
                        or result_data
                    )
                    structured_error = StructuredBIError.from_message(
                        summary,
                        error_type=str(result_data.get("error_type") or "ToolError"),
                        error_code=result_data.get("error_code"),
                    )
                else:
                    summary = result_data.get("data") if isinstance(result_data, dict) else result_data
                summary_str = str(summary)[:500] if summary else ""
                step_number += 1
                step = BiAgentStep(
                    run_id=run_id,
                    step_number=step_number,
                    step_type="tool_result",
                    tool_name=tool_name,
                    tool_result_summary=summary_str,
                    execution_time_ms=_elapsed_ms(pending_tool_start or last_step_at, event_at),
                )
                db.add(step)
                db.commit()
                if structured_error is not None:
                    persist_structured_error(db, "bi_agent_steps", getattr(step, "id", None), structured_error)
                pending_tool_start = None
                last_step_at = event_at
                last_tool_result = result_data
                yield event
                data = result_data.get("data") if isinstance(result_data, dict) else None
                normalized = normalize_table_response(data)
                if normalized is not None:
                    table_response = normalized

            elif event.type == "table_data":
                normalized = normalize_table_response(event.content)
                if normalized is not None:
                    table_response = normalized
                    table_data_emitted = True
                    yield AgentEvent(type="table_data", content=table_data_event_from_response(table_response))
                else:
                    yield event

            elif event.type == "chart_data":
                # Pass chart data through to the API layer unchanged
                yield event

            elif event.type == "answer":
                answer_text = event.content
                answer_step_ms = _elapsed_ms(last_step_at, event_at)
                execution_time_ms = _elapsed_ms(total_start, event_at)

                response_type = "text"
                response_data = None
                if table_response is not None:
                    response_type = "table"
                    response_data = table_response
                elif last_tool_result and isinstance(last_tool_result, dict):
                    data = last_tool_result.get("data")
                    if isinstance(data, dict):
                        if data.get("field_unavailable"):
                            response_type = "text"
                        elif "rows" in data and "fields" in data:
                            response_type = "table"
                            response_data = data
                        elif "value" in data:
                            response_type = "number"
                            response_data = data
                        elif "metrics" in data:
                            response_type = "table"
                            response_data = data

                # Record answer telemetry. If telemetry fails, preserve the user-visible answer.
                step_number += 1
                try:
                    step = BiAgentStep(
                        run_id=run_id,
                        step_number=step_number,
                        step_type="answer",
                        content=answer_text[:500] if answer_text else None,
                        execution_time_ms=answer_step_ms,
                    )
                    db.add(step)

                    db.query(BiAgentRun).filter(BiAgentRun.id == run_id).update(
                        {
                            BiAgentRun.status: "completed",
                            BiAgentRun.steps_count: steps_count,
                            BiAgentRun.tools_used: tools_used if tools_used else None,
                            BiAgentRun.response_type: response_type,
                            BiAgentRun.execution_time_ms: execution_time_ms,
                            BiAgentRun.completed_at: sa_func.now(),
                        },
                        synchronize_session=False,
                    )
                    db.commit()
                except Exception as exc:
                    _rollback_after_persistence_error(db)
                    _log_final_telemetry_failure(
                        exc,
                        conversation_id=conversation_id_str,
                        trace_id=trace_id,
                        run_id=run_id,
                        user_id=current_user.get("id"),
                        response_type=response_type,
                        error_code="AGENT_TELEMETRY_PERSISTENCE_FAILED",
                    )

                # Build sources metadata from connection context
                sources_count = 1 if context.connection_id else 0
                top_sources = [context.connection_name] if context.connection_id and context.connection_name else []

                # Emit chart_data if question requests a chart and we have tabular results
                _is_chart, _chart_type = is_chart_request(question)
                if _is_chart and response_type == "table" and response_data:
                    _fields = response_data.get("fields", [])
                    _rows = response_data.get("rows", [])
                    if _fields and _rows:
                        _col_types = _infer_col_types(_fields, _rows)
                        yield AgentEvent(
                            type="chart_data",
                                content=_build_chart_data(_fields, _rows, _col_types, _chart_type),
                        )

                # Persist assistant message
                try:
                    session_mgr.persist_message(
                        session=session,
                        role="assistant",
                        content=answer_text,
                        response_type=response_type,
                        response_data=response_data,
                        tools_used=tools_used,
                        trace_id=trace_id,
                        steps_count=steps_count,
                        execution_time_ms=execution_time_ms,
                        sources_count=sources_count,
                        top_sources=top_sources,
                    )
                except Exception as exc:
                    _rollback_after_persistence_error(db)
                    logger.exception(
                        "Agent assistant message persistence failed",
                        extra={
                            "conversation_id": conversation_id_str,
                            "trace_id": trace_id,
                            "run_id": str(run_id) if run_id else None,
                            "user_id": current_user.get("id"),
                            "response_type": response_type,
                            "error_code": _AGENT_PERSISTENCE_FAILED,
                            "exception_type": type(exc).__name__,
                        },
                    )
                    yield _persistence_failed_event(trace_id=trace_id, run_id=run_id)
                    return

                if response_type == "table" and table_response is not None and not table_data_emitted:
                    table_data_emitted = True
                    yield AgentEvent(type="table_data", content=table_data_event_from_response(table_response))

                # Yield a synthetic "done" event only after assistant history is durable.
                yield AgentEvent(
                    type="done",
                    content={
                        "answer": answer_text,
                        "trace_id": trace_id,
                        "run_id": str(run_id),
                        "tools_used": tools_used,
                        "response_type": response_type,
                        "response_data": response_data,
                        "steps_count": steps_count,
                        "execution_time_ms": execution_time_ms,
                        "sources_count": sources_count,
                        "top_sources": top_sources,
                    },
                )

            elif event.type == "error":
                error_content = event.content if isinstance(event.content, dict) else {"message": str(event.content)}
                err_code = error_content.get("error_code", "AGENT_003")
                response_type = "fallback" if error_content.get("fallback_type") else "error"
                execution_time_ms = _elapsed_ms(total_start, event_at)

                step_number += 1
                step = BiAgentStep(
                    run_id=run_id,
                    step_number=step_number,
                    step_type="error",
                    content=error_content.get("message", "")[:500],
                    execution_time_ms=_elapsed_ms(last_step_at, event_at),
                )
                db.add(step)
                structured_error = error_content.get("structured_error") or StructuredBIError.from_message(
                    error_content.get("message", ""),
                    error_type=str(error_content.get("error_type") or "AgentError"),
                    error_code=err_code,
                )
                db.query(BiAgentRun).filter(BiAgentRun.id == run_id).update(
                    {
                        BiAgentRun.status: "failed",
                        BiAgentRun.error_code: err_code,
                        BiAgentRun.response_type: response_type,
                        BiAgentRun.execution_time_ms: execution_time_ms,
                        BiAgentRun.completed_at: sa_func.now(),
                    },
                    synchronize_session=False,
                )
                db.commit()
                persist_structured_error(db, "bi_agent_steps", getattr(step, "id", None), structured_error)
                session_mgr.persist_message(
                    session=session,
                    role="assistant",
                    content=str(error_content.get("message") or "Agent 执行失败"),
                    response_type=response_type,
                    response_data=error_content,
                    tools_used=tools_used if tools_used else None,
                    trace_id=trace_id,
                    steps_count=steps_count,
                    execution_time_ms=execution_time_ms,
                    sources_count=1 if context.connection_id else 0,
                    top_sources=[context.connection_name] if context.connection_id and context.connection_name else [],
                )

                yield AgentEvent(type="error", content=error_content)

    except asyncio.CancelledError:
        logger.info("Agent runner cancelled trace_id=%s run_id=%s", trace_id, run_id)
        if run_id:
            try:
                execution_time_ms = max(0, int((time.monotonic() - total_start) * 1000))
                message = "请求连接已中断，Agent 运行已取消。"
                error_content = {
                    "error_code": "AGENT_CANCELLED",
                    "message": message,
                    "error_type": "client_disconnected",
                    "retryable": True,
                }
                step = BiAgentStep(
                    run_id=run_id,
                    step_number=step_number + 1,
                    step_type="error",
                    content=message[:500],
                    execution_time_ms=execution_time_ms,
                )
                db.add(step)
                db.query(BiAgentRun).filter(BiAgentRun.id == run_id).update(
                    {
                        BiAgentRun.status: "failed",
                        BiAgentRun.error_code: "AGENT_CANCELLED",
                        BiAgentRun.steps_count: steps_count,
                        BiAgentRun.tools_used: tools_used if tools_used else None,
                        BiAgentRun.response_type: "error",
                        BiAgentRun.execution_time_ms: execution_time_ms,
                        BiAgentRun.completed_at: sa_func.now(),
                    },
                    synchronize_session=False,
                )
                db.commit()
                try:
                    session_mgr.persist_message(
                        session=session,
                        role="assistant",
                        content=message,
                        response_type="error",
                        response_data=error_content,
                        tools_used=tools_used if tools_used else None,
                        trace_id=trace_id,
                        steps_count=steps_count,
                        execution_time_ms=execution_time_ms,
                        sources_count=1 if context.connection_id else 0,
                        top_sources=[context.connection_name] if context.connection_id and context.connection_name else [],
                    )
                except Exception:
                    logger.warning("Failed to persist assistant cancellation message")
            except Exception:
                logger.warning("Failed to update run status on cancellation", exc_info=True)
        raise

    except Exception as e:
        logger.exception("Agent runner exception")
        if run_id:
            try:
                execution_time_ms = max(0, int((time.monotonic() - total_start) * 1000))
                structured_error = StructuredBIError.from_exception(e, error_code="AGENT_003")
                step = BiAgentStep(
                    run_id=run_id,
                    step_number=step_number + 1,
                    step_type="error",
                    content=structured_error.message[:500],
                    execution_time_ms=execution_time_ms,
                )
                db.add(step)
                db.query(BiAgentRun).filter(BiAgentRun.id == run_id).update(
                    {
                        BiAgentRun.status: "failed",
                        BiAgentRun.error_code: "AGENT_003",
                        BiAgentRun.execution_time_ms: execution_time_ms,
                        BiAgentRun.completed_at: sa_func.now(),
                    },
                    synchronize_session=False,
                )
                db.commit()
                persist_structured_error(db, "bi_agent_steps", getattr(step, "id", None), structured_error)
                try:
                    session_mgr.persist_message(
                        session=session,
                        role="assistant",
                        content=structured_error.message,
                        response_type="error",
                        response_data={
                            "error_code": "AGENT_003",
                            "message": structured_error.message,
                            "error_type": structured_error.error_type,
                        },
                        tools_used=tools_used if tools_used else None,
                        trace_id=trace_id,
                        steps_count=steps_count,
                        execution_time_ms=execution_time_ms,
                        sources_count=1 if context.connection_id else 0,
                        top_sources=[context.connection_name] if context.connection_id and context.connection_name else [],
                    )
                except Exception:
                    logger.warning("Failed to persist assistant error message on exception")
            except Exception:
                logger.warning("Failed to update run status on exception")
        yield AgentEvent(
            type="error",
            content={"error_code": "AGENT_003", "message": "Agent 执行异常"},
        )


def resolve_recent_schema_asset_name(session_mgr: SessionManager, session: AgentSession, user_id: int) -> Optional[str]:
    """Return the most recent schema asset mentioned in the conversation."""
    try:
        messages = session_mgr.get_conversation_messages(
            conversation_id=session.conversation_id,
            user_id=user_id,
            limit=20,
        )
    except Exception:
        return None

    for message in reversed(messages):
        if getattr(message, "role", None) != "assistant":
            continue
        tools_used = getattr(message, "tools_used", None) or []
        if "schema" not in tools_used:
            continue
        content = getattr(message, "content", "") or ""
        match = _SCHEMA_ASSET_PATTERN.search(content)
        if match:
            return match.group(1).strip()
    return None


def _is_tableau_mcp_context(context: ToolContext) -> bool:
    """Return whether controlled data path must stay on the Tableau MCP mainline."""
    connection_type = str(getattr(context, "connection_type", "") or "").strip().lower()
    if connection_type == "tableau":
        return True
    return bool(getattr(context, "selected_datasource_luid", None) and getattr(context, "connection_id", None))


def resolve_recent_query_context(session_mgr: SessionManager, session: AgentSession, user_id: int) -> Dict[str, object]:
    """Return datasource and metric hints from the most recent query result in a conversation."""
    try:
        messages = session_mgr.get_conversation_messages(
            conversation_id=session.conversation_id,
            user_id=user_id,
            limit=20,
        )
    except Exception:
        return {}

    for message in reversed(messages):
        if getattr(message, "role", None) != "assistant":
            continue
        response_data = getattr(message, "response_data", None)
        if not isinstance(response_data, dict):
            continue

        datasource_context = _extract_datasource_context(response_data)
        tools_used = getattr(message, "tools_used", None) or []
        if datasource_context and "schema" in tools_used:
            return datasource_context
        if "query" not in tools_used and "tableau_mcp" not in tools_used:
            if datasource_context:
                return datasource_context
            continue
        datasource_name = response_data.get("datasource_name")
        context_fields = _extract_query_context_field_roles(response_data)
        metric_names = context_fields["metric_names"] or _extract_metric_names(response_data.get("fields") or [])
        dimension_names = context_fields["dimension_names"] or _extract_dimension_names(response_data.get("fields") or [])
        context: Dict[str, object] = {
            "is_follow_up": True,
            "unresolved_references": False,
            "datasource_name": datasource_name,
            "metric_names": metric_names,
            "dimension_names": dimension_names,
            "requested_metrics": metric_names,
            "requested_dimensions": dimension_names,
            "requested_filters": _extract_query_context_filters(response_data),
            "previous_successful_query_summary": {
                "fields": list(response_data.get("fields") or []),
                "metric_names": metric_names,
                "dimension_names": dimension_names,
            },
        }
        mcp_args = response_data.get("mcp_args")
        if isinstance(mcp_args, dict):
            context["mcp_args"] = mcp_args
            context["previous_successful_mcp_call_ref"] = {
                "tool_name": response_data.get("mcp_tool_name") or "query-datasource",
                "datasource_luid": mcp_args.get("datasourceLuid") or response_data.get("datasource_luid"),
            }
        context.update(datasource_context)
        return context
    return {}


def resolve_recent_query_result(session_mgr: SessionManager, session: AgentSession, user_id: int) -> Dict[str, Any]:
    """Return the most recent assistant query_result/table response data."""

    try:
        messages = session_mgr.get_conversation_messages(
            conversation_id=session.conversation_id,
            user_id=user_id,
            limit=20,
        )
    except Exception:
        return {}

    for message in reversed(messages):
        if getattr(message, "role", None) != "assistant":
            continue
        response_type = str(getattr(message, "response_type", "") or "")
        if response_type not in {"query_result", "table"}:
            continue
        response_data = getattr(message, "response_data", None)
        if not isinstance(response_data, dict):
            continue
        if isinstance(response_data.get("fields"), list) and isinstance(response_data.get("rows"), list):
            return dict(response_data)
    return {}


def _extract_datasource_context(response_data: Dict[str, object]) -> Dict[str, object]:
    """Extract an explicit datasource payload from prior assistant response data."""
    candidates: List[object] = []
    for key in ("selected_datasource", "datasource"):
        value = response_data.get(key)
        if isinstance(value, dict):
            candidates.append(value)
    candidates.append(response_data)

    analysis_context = response_data.get("analysis_context")
    if isinstance(analysis_context, dict):
        for key in ("selected_datasource", "datasource"):
            value = analysis_context.get(key)
            if isinstance(value, dict):
                candidates.append(value)
        scope = analysis_context.get("scope")
        if isinstance(scope, dict):
            for key in ("selected_datasource", "datasource"):
                value = scope.get(key)
                if isinstance(value, dict):
                    candidates.append(value)
            candidates.append(scope)

    matched_asset = response_data.get("matched_asset")
    if isinstance(matched_asset, dict):
        candidates.append(matched_asset)

    for candidate in candidates:
        payload = _datasource_context_from_mapping(candidate)
        if payload:
            return payload
    return {}


def _datasource_context_from_mapping(candidate: object) -> Dict[str, object]:
    if not isinstance(candidate, dict):
        return {}
    datasource_luid = str(
        candidate.get("luid")
        or candidate.get("datasource_luid")
        or candidate.get("selected_datasource_luid")
        or candidate.get("tableau_datasource_luid")
        or candidate.get("tableau_id")
        or ""
    ).strip()
    if not datasource_luid:
        return {}

    datasource_name = str(
        candidate.get("name")
        or candidate.get("datasource_name")
        or candidate.get("caption")
        or datasource_luid
    ).strip()
    asset_id = candidate.get("asset_id")
    connection_id = candidate.get("connection_id")
    selected_datasource = {
        "luid": datasource_luid,
        "datasource_luid": datasource_luid,
        "tableau_datasource_luid": datasource_luid,
        "name": datasource_name,
        "datasource_name": datasource_name,
        "asset_id": asset_id,
        "connection_id": connection_id,
    }
    return {
        "datasource_luid": datasource_luid,
        "tableau_datasource_luid": datasource_luid,
        "selected_datasource": selected_datasource,
        "datasource_name": datasource_name,
    }


def _extract_metric_names(fields: list) -> list[str]:
    metric_names: list[str] = []
    seen: set[str] = set()
    for field in fields:
        name = ""
        if isinstance(field, dict):
            name = str(field.get("fieldAlias") or field.get("name") or field.get("fieldCaption") or "")
        else:
            name = str(field or "")
        if not name:
            continue
        if not re.search(r"(SUM|AVG|COUNT|COUNTD|MIN|MAX)\(", name, flags=re.IGNORECASE):
            continue
        cleaned = re.sub(r"^[A-Z]+\((.+)\)$", r"\1", name, flags=re.IGNORECASE).strip()
        if cleaned in seen:
            continue
        seen.add(cleaned)
        metric_names.append(cleaned)
    return metric_names[:5]


def _extract_dimension_names(fields: list) -> list[str]:
    dimension_names: list[str] = []
    seen: set[str] = set()
    for field in fields:
        name = ""
        if isinstance(field, dict):
            name = str(field.get("fieldAlias") or field.get("name") or field.get("fieldCaption") or "")
        else:
            name = str(field or "")
        if not name:
            continue
        if re.search(r"(SUM|AVG|COUNT|COUNTD|MIN|MAX|YEAR|MONTH|QUARTER)\(", name, flags=re.IGNORECASE):
            continue
        if name in seen:
            continue
        seen.add(name)
        dimension_names.append(name)
    return dimension_names[:5]


def _extract_query_context_field_roles(response_data: Dict[str, object]) -> Dict[str, List[str]]:
    """Infer reusable planning field roles from a previous MCP query result.

    This is a current-turn hint builder for the runner boundary.  It does not
    create business facts and does not make compiler stateful.
    """

    metric_names: List[str] = []
    dimension_names: List[str] = []
    display_columns = _table_display_columns(response_data)
    mcp_fields = _mcp_query_fields(response_data.get("mcp_args"))
    if mcp_fields:
        for index, field in enumerate(mcp_fields):
            caption = _context_field_caption(field)
            if not caption:
                continue
            function = str(field.get("function") or field.get("aggregation") or "").strip().upper()
            semantic_type = _display_semantic_type(display_columns, index=index, caption=caption)
            if function in _AGGREGATE_CONTEXT_FUNCTIONS or semantic_type in {"metric", "derived_metric"}:
                _append_unique(metric_names, caption)
            elif function in _TIME_CONTEXT_FUNCTIONS or semantic_type in {"dimension", "date", "time"}:
                _append_unique(dimension_names, caption)
            else:
                _append_unique(dimension_names, caption)
        return {"metric_names": metric_names[:8], "dimension_names": dimension_names[:8]}

    fields = response_data.get("fields") or []
    if not isinstance(fields, list):
        return {"metric_names": [], "dimension_names": []}
    for index, field in enumerate(fields):
        caption = _context_field_caption(field)
        if not caption:
            continue
        aggregate = re.match(r"^\s*([A-Z][A-Z0-9_]*)\s*\((.+)\)\s*$", caption, flags=re.IGNORECASE)
        semantic_type = _display_semantic_type(display_columns, index=index, caption=caption)
        if aggregate and aggregate.group(1).upper() in _AGGREGATE_CONTEXT_FUNCTIONS:
            _append_unique(metric_names, aggregate.group(2).strip())
        elif semantic_type in {"metric", "derived_metric"}:
            _append_unique(metric_names, caption)
        else:
            _append_unique(dimension_names, caption)
    return {"metric_names": metric_names[:8], "dimension_names": dimension_names[:8]}


def _mcp_query_fields(args: object) -> List[Dict[str, object]]:
    if not isinstance(args, dict):
        return []
    query = args.get("query")
    if not isinstance(query, dict):
        return []
    fields = query.get("fields")
    if not isinstance(fields, list):
        return []
    return [dict(field) for field in fields if isinstance(field, dict)]


def _extract_query_context_filters(response_data: Dict[str, object]) -> List[object]:
    mcp_args = response_data.get("mcp_args")
    if not isinstance(mcp_args, dict):
        return []
    query = mcp_args.get("query")
    if not isinstance(query, dict):
        return []
    filters = query.get("filters")
    return list(filters) if isinstance(filters, list) else []


def _table_display_columns(response_data: Dict[str, object]) -> List[Dict[str, object]]:
    table_display = response_data.get("table_display")
    if not isinstance(table_display, dict):
        return []
    columns = table_display.get("columns")
    if not isinstance(columns, list):
        return []
    return [dict(column) for column in columns if isinstance(column, dict)]


def _display_semantic_type(columns: List[Dict[str, object]], *, index: int, caption: str) -> str:
    candidates: List[Dict[str, object]] = []
    if 0 <= index < len(columns):
        candidates.append(columns[index])
    compact_caption = _compact_context_text(caption)
    candidates.extend(
        column
        for column in columns
        if compact_caption
        and compact_caption
        in {
            _compact_context_text(column.get("key")),
            _compact_context_text(column.get("label")),
            _compact_context_text(column.get("name")),
        }
    )
    for column in candidates:
        semantic_type = str(column.get("semantic_type") or "").strip().lower()
        if semantic_type:
            return semantic_type
    return ""


def _context_field_caption(value: object) -> str:
    if isinstance(value, dict):
        for key in ("fieldCaption", "field_alias", "fieldAlias", "caption", "label", "name", "key"):
            raw = value.get(key)
            if raw:
                return str(raw).strip()
        return ""
    return str(value or "").strip()


def _append_unique(values: List[str], value: str) -> None:
    cleaned = str(value or "").strip()
    if cleaned and cleaned not in values:
        values.append(cleaned)


def _compact_context_text(value: object) -> str:
    return re.sub(r"\s+", "", str(value or "")).casefold()


def _infer_analysis_params(question: str) -> Dict[str, object]:
    """Infer bounded semantic-operator parameters for high-confidence BI phrases."""
    params: Dict[str, object] = {}
    year_match = re.search(r"(\d{4})\s*年", question)
    year = int(year_match.group(1)) if year_match else None

    compact = question.replace(" ", "")
    if "没有" in compact and "子类别" in compact and ("销售记录" in compact or "记录" in compact) and year:
        params.update({
            "analysis_intent": "set_difference",
            "target_dimension": "子类别",
            "exclude_filters": [_year_date_filter("发货日期", year)],
        })

    if any(token in compact for token in ("为什么", "原因", "导致", "归因")) and any(token in compact for token in ("亏", "巨亏", "亏损")):
        province_values = _extract_named_values(
            question,
            [
                "北京", "天津", "河北", "山西", "内蒙古", "辽宁", "吉林", "黑龙江",
                "上海", "江苏", "浙江", "安徽", "福建", "江西", "山东", "河南",
                "湖北", "湖南", "广东", "广西", "海南", "重庆", "四川", "贵州",
                "云南", "西藏", "陕西", "甘肃", "青海", "宁夏", "新疆",
            ],
        )
        filters = []
        if province_values:
            filters.append({"field": {"fieldCaption": "省/自治区"}, "filterType": "SET", "values": province_values})
        if year:
            filters.append(_year_date_filter("发货日期", year))
        params.update({
            "analysis_intent": "root_cause",
            "target_metric": {"fieldCaption": "利润", "function": "SUM"},
            "breakdown_dimensions": ["类别", "子类别", "客户名称"],
            "filters": filters,
            "sort_direction": "ASC",
            "limit": 10,
        })
    return params


def _year_date_filter(date_caption: str, year: int) -> dict:
    return {
        "field": {"fieldCaption": date_caption},
        "filterType": "QUANTITATIVE_DATE",
        "quantitativeFilterType": "RANGE",
        "minDate": f"{year}-01-01",
        "maxDate": f"{year}-12-31",
    }


def _extract_named_values(text: str, candidates: list[str]) -> list[str]:
    values = []
    for candidate in candidates:
        if candidate in text and candidate not in values:
            values.append(candidate)
    return values

"""Data Agent Runner — observability wrapper around ReActEngine.run()

Iterates engine events, persists BiAgentRun / BiAgentStep records, and
yields raw AgentEvent objects (SSE serialisation is the caller's job).

No web framework dependency: only SQLAlchemy + pure Python.
"""

import logging
import json
import re
import time
import uuid as uuid_lib
from typing import AsyncGenerator, Dict, List, Optional

from sqlalchemy import func as sa_func
from sqlalchemy.orm import Session

from services.agent_observability.structured_error import StructuredBIError, persist_structured_error

from .chain_selector import select_data_agent_chain
from .engine import ReActEngine
from .intent_classifier import IntentClassification, classify_intent
from .mcp_first_main import run_mcp_first_main_path
from .mcp_proxy_main import run_mcp_proxy_main_path
from .models import BiAgentRun, BiAgentStep
from .response import AgentEvent
from .router_guardrail import RouteDecision
from .session import AgentSession, SessionManager
from .intent.keyword_match import is_direct_query, is_chart_request
from .tool_base import ToolContext
from .engine import _infer_col_types, _build_chart_data

logger = logging.getLogger(__name__)

_SCHEMA_ASSET_PATTERN = re.compile(r"数据(?:资产|源)\s+\*\*([^*]+)\*\*")
_FOLLOWUP_METRIC_PATTERN = re.compile(r"(这个|这些|上述|上面|该)\s*(指标|数据|结果)?")


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
    run_id: Optional[uuid_lib.UUID] = None

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

        step_number = 0

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

        if enforce_controlled_data_path and intent_result.is_data_intent:
            followup_context = resolve_recent_query_context(session_mgr, session, current_user["id"])
            chain_selection = select_data_agent_chain()
            if chain_selection.is_fallback:
                logger.warning("Data Agent chain mode fallback: %s", chain_selection.trace_detail())
                fallback_message = chain_selection.fallback_message()
                if fallback_message:
                    yield AgentEvent(type="thinking", content=fallback_message)
            controlled_path = run_mcp_proxy_main_path if chain_selection.is_mcp_proxy else run_mcp_first_main_path
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
                elif event.type == "answer":
                    answer_text = str(event.content or "")
                    execution_time_ms = _elapsed_ms(total_start, event_at)
                    response_type = "text"
                    response_data = None
                    data = last_tool_result.get("data") if isinstance(last_tool_result, dict) else None
                    if isinstance(data, dict):
                        response_data = data
                        response_type = "table" if "rows" in data and "fields" in data else "text"
                    step_number += 1
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
                            BiAgentRun.response_type: "fallback",
                            BiAgentRun.execution_time_ms: execution_time_ms,
                            BiAgentRun.completed_at: sa_func.now(),
                        },
                        synchronize_session=False,
                    )
                    db.commit()
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

            elif event.type == "table_data":
                # Pass structured table data through to the API layer unchanged
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
                if last_tool_result and isinstance(last_tool_result, dict):
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

                # Record answer step
                step_number += 1
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

                # Yield a synthetic "done" event that carries all metadata
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

                # Persist assistant message
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

            elif event.type == "error":
                error_content = event.content if isinstance(event.content, dict) else {"message": str(event.content)}
                err_code = error_content.get("error_code", "AGENT_003")
                response_type = "fallback" if error_content.get("fallback_type") else "error"

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
                execution_time_ms = _elapsed_ms(total_start, event_at)
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

                yield AgentEvent(type="error", content=error_content)

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
        tools_used = getattr(message, "tools_used", None) or []
        if "query" not in tools_used and "tableau_mcp" not in tools_used:
            continue
        response_data = getattr(message, "response_data", None)
        if not isinstance(response_data, dict):
            continue
        datasource_name = response_data.get("datasource_name")
        metric_names = _extract_metric_names(response_data.get("fields") or [])
        dimension_names = _extract_dimension_names(response_data.get("fields") or [])
        return {
            "datasource_name": datasource_name,
            "metric_names": metric_names,
            "dimension_names": dimension_names,
        }
    return {}


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

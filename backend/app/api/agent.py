"""Data Agent API — Spec 36 §5 FastAPI 路由

端点：
  POST /api/agent/stream        — SSE 流式对话（ReAct 引擎驱动）
  GET  /api/agent/conversations — 用户会话列表
  GET  /api/agent/conversations/{id}/messages — 会话消息
  DELETE /api/agent/conversations/{id} — 归档会话
  POST /api/agent/feedback      — 提交反馈（thumbs up/down）
  GET  /api/agent/mode          — 获取 HOMEPAGE_AGENT_MODE（Spec 36 §15）
  POST /api/agent/mode          — 设置 HOMEPAGE_AGENT_MODE（admin only）
"""

import asyncio
from contextlib import suppress
import json
import logging
import time
import uuid as uuid_lib
from datetime import datetime, timezone
from typing import AsyncGenerator, Any, Dict, List, Optional

from fastapi import APIRouter, Body, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import func, text
from sqlalchemy.orm import Session

from app.core.database import get_db, get_db_context
from app.core.dependencies import get_current_user

from services.data_agent.factory import create_engine, create_engine_with_skills
from services.data_agent.deterministic import (
    DeterministicRouteResult,
    build_schema_inventory_tool_params,
    detect_deterministic_route,
    run_schema_inventory_route,
)
from services.data_agent.models import (
    AgentConversation,
    AgentConversationMessage,
    BiAgentRun,
    BiAgentStep,
    BiAgentFeedback,
)
from services.data_agent.chain_selector import select_data_agent_chain
from services.data_agent.runner import run_agent
from services.data_agent.response import normalize_table_response, table_data_event_from_response
from services.data_agent.session import SessionManager, AgentSession
from services.data_agent.tool_base import ToolContext, ToolRegistry
from services.data_agent.context import build_session_context
from services.data_agent.fallback import StandardFallback, make_clarification_fallback
from services.data_agent.intent_classifier import classify_intent
from services.data_agent.router_guardrail import classify_homepage_question
from services.data_agent.analysis_context import AnalysisContext, build_response_data_with_context
from services.llm.models import log_nlq_query
from services.llm.service import llm_user_id_var
from services.tableau.models import TableauConnection
# Spec 36 §15: Agent 驱动首页相关导入
from services.agent.dual_write import (
    HomepageAgentMode,
    execute_dual_write,
    get_homepage_agent_mode,
    check_and_trigger_auto_rollback,
)
from services.data_agent.intent import IntentRecognizer
from services.skills.service import get_active_skill_version

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/agent", tags=["Data Agent"])
MCP_VIRTUAL_CONNECTION_OFFSET = 10000


# ============================================================================
# Schema
# ============================================================================


async def _generate_short_title(question: str, conversation_id: str, user_id: int) -> None:
    """Best-effort: generate a 4-8 char title via LLM and update the conversation."""
    try:
        from services.llm.service import LLMService
        llm = LLMService()
        result = await llm.complete(
            prompt=f"用4-8个中文字为以下问题生成简洁标题，只输出标题本身，不加任何标点或引号：\n{question[:200]}",
            system="你是标题生成助手，只输出简洁的中文短语，禁止输出任何解释或符号。",
            timeout=8,
        )
        raw = (result.get("content") or "").strip().strip('。，、.,"\'"」「').strip()[:20]
        if len(raw) >= 2:
            with get_db_context() as db:
                mgr = SessionManager(db)
                mgr.update_title(uuid_lib.UUID(conversation_id), raw, user_id)
    except Exception:
        pass


class StreamRequest(BaseModel):
    question: str = Field(..., min_length=1, description="用户自然语言问题")
    conversation_id: Optional[str] = Field(None, description="续接的会话 ID")
    connection_id: Optional[int] = Field(None, description="数据源连接 ID")
    datasource_luid: Optional[str] = Field(None, description="前端已选择的 Tableau 数据源 LUID")
    datasource_name: Optional[str] = Field(None, description="前端已选择的 Tableau 数据源名称")


class ConversationItem(BaseModel):
    id: str
    title: Optional[str]
    connection_id: Optional[int]
    status: str
    message_count: int = 0
    created_at: str
    updated_at: str


class ConversationUpdateRequest(BaseModel):
    title: str = Field(..., min_length=1, max_length=256, description="会话标题")


def _resolve_conversation_title(stored_title: Optional[str], first_user_message: Optional[str]) -> Optional[str]:
    """Return a useful display title; default placeholders should not leak to the sidebar."""
    title = (stored_title or "").strip()
    if title and title != "新对话":
        return title
    message = (first_user_message or "").strip()
    if message:
        return message[:50]
    return stored_title


class MessageItem(BaseModel):
    id: int
    role: str
    content: str
    response_type: Optional[str]
    response_data: Optional[Any] = None
    run_id: Optional[str] = None
    error_detail: Optional[Any] = None
    explainability: Optional[Any] = None
    tools_used: Optional[List[str]]
    trace_id: Optional[str]
    steps_count: Optional[int]
    execution_time_ms: Optional[int]
    sources_count: Optional[int] = None
    top_sources: Optional[List[str]] = None
    created_at: str


class FeedbackRequest(BaseModel):
    run_id: str = Field(..., description="Agent 运行 ID")
    rating: str = Field(..., pattern="^(up|down)$", description="up 或 down")
    comment: Optional[str] = Field(None, max_length=1000, description="可选文字反馈")


class FeedbackV2Request(BaseModel):
    """扩展反馈请求（支持 run_id 映射到 conversation_id）"""
    run_id: Optional[str] = Field(None, description="Agent 运行 ID")
    rating: str = Field(..., pattern="^(up|down)$", description="up 或 down")
    conversation_id: Optional[str] = Field(None, description="会话 ID")
    message_index: Optional[int] = Field(None, description="消息索引")
    question: Optional[str] = Field(None, max_length=2000, description="用户问题")
    answer_summary: Optional[str] = Field(None, max_length=500, description="回答摘要")


# Spec 36 §15: HOMEPAGE_AGENT_MODE 端点 Schema
class ModeStatusResponse(BaseModel):
    mode: str  # "legacy_only" | "agent_with_fallback" | "agent_only" | "dual_write"
    description: str
    can_rollback: bool  # 是否可以触发自动回滚
    failure_tracker_active: bool  # 失败率跟踪器是否启用


class ModeUpdateRequest(BaseModel):
    mode: str = Field(..., description="HOMEPAGE_AGENT_MODE 四态之一")
    user_override: Optional[Dict[int, str]] = Field(
        None,
        description="单用户 override 映射 {user_id: mode}",
    )


# ============================================================================
# SSE 流式端点
# ============================================================================


def _require_agent_role(role: str) -> None:
    if role not in ("analyst", "data_admin", "admin"):
        raise HTTPException(
            status_code=403,
            detail={"error_code": "AGENT_005", "message": "无权限使用 Agent"},
        )


def _sse_data(payload: dict) -> str:
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"


_SSE_STREAM_DONE = object()
_SSE_HEARTBEAT_INTERVAL_SECONDS = 15.0
_AGENT_PERSISTENCE_FAILED = "AGENT_PERSISTENCE_FAILED"


class AgentPersistenceError(RuntimeError):
    """Raised when a user-visible assistant response cannot be persisted."""

    def __init__(self, *, trace_id: str, run_id: str, conversation_id: str):
        super().__init__("assistant message persistence failed")
        self.trace_id = trace_id
        self.run_id = run_id
        self.conversation_id = conversation_id


def _rollback_after_persistence_error(db: Session) -> None:
    rollback = getattr(db, "rollback", None)
    if rollback is None:
        return
    try:
        rollback()
    except Exception:
        logger.warning("Failed to rollback after agent persistence error", exc_info=True)


def _persistence_failed_sse(*, trace_id: str, run_id: str) -> str:
    return _sse_data({
        "type": "error",
        "error_code": _AGENT_PERSISTENCE_FAILED,
        "message": "回答生成成功但保存失败，请重试。",
        "trace_id": trace_id,
        "run_id": run_id,
        "retryable": True,
    })


async def _stream_with_keepalive(
    source: AsyncGenerator[str, None],
    *,
    heartbeat_interval_seconds: float = _SSE_HEARTBEAT_INTERVAL_SECONDS,
) -> AsyncGenerator[str, None]:
    """Proxy an SSE async generator and emit comment heartbeats during long awaits."""

    queue: asyncio.Queue[object] = asyncio.Queue()

    async def _produce() -> None:
        try:
            async for chunk in source:
                await queue.put(chunk)
        except BaseException as exc:
            await queue.put(exc)
        finally:
            await queue.put(_SSE_STREAM_DONE)

    producer = asyncio.create_task(_produce())
    try:
        while True:
            try:
                item = await asyncio.wait_for(queue.get(), timeout=heartbeat_interval_seconds)
            except asyncio.TimeoutError:
                yield f": ping {int(time.time())}\n\n"
                continue

            if item is _SSE_STREAM_DONE:
                break
            if isinstance(item, BaseException):
                raise item
            yield str(item)
    finally:
        if not producer.done():
            producer.cancel()
            with suppress(asyncio.CancelledError):
                await producer


def _intent_explainability_payload(route_decision) -> dict:
    intent = "ambiguous"
    guardrail_decision = "fallback"
    if route_decision.is_asset_question:
        intent = "schema_inventory"
        guardrail_decision = "allow"
    elif route_decision.is_data_question:
        intent = "query"
        guardrail_decision = "allow"
    return {
        "intent": intent,
        "confidence": route_decision.confidence,
        "strategy": "router_guardrail",
        "guardrail": {
            "decision": guardrail_decision,
            "reason_code": route_decision.reason,
            "message": route_decision.reason,
        },
    }


def _fallback_explainability_payload(fallback: StandardFallback, *, final_source: str = "fallback") -> dict:
    return {
        "occurred": True,
        "chain": [
            {
                "from": "router_guardrail",
                "to": "error",
                "reason_code": fallback.fallback_type,
                "message": fallback.message,
            }
        ],
        "final_source": final_source,
        "user_visible_message": fallback.answer,
    }


def _explainability_snapshot(
    *,
    trace_id: str,
    route_decision,
    run_id: Optional[str] = None,
    response_type: Optional[str] = None,
    row_count: Optional[int] = None,
    fallback: Optional[StandardFallback] = None,
) -> dict:
    phases: Dict[str, Any] = {
        "intent": _intent_explainability_payload(route_decision),
    }
    if response_type:
        phases["postprocess"] = {
            "response_type": response_type,
            "row_count": row_count,
            "displayed_row_count": row_count,
            "formatting": ["markdown_summary"],
        }
    if fallback:
        phases["fallback"] = _fallback_explainability_payload(fallback)
    return {
        "schema_version": "p0.1",
        "run_id": run_id or "",
        "trace_id": trace_id,
        "phases": phases,
    }


def _uuid_or_none(value: Any) -> Optional[uuid_lib.UUID]:
    if not value:
        return None
    if isinstance(value, uuid_lib.UUID):
        return value
    try:
        return uuid_lib.UUID(str(value))
    except (TypeError, ValueError):
        return None


def _schema_inventory_response_data_with_context(
    *,
    response_data: dict[str, Any],
    run_id: uuid_lib.UUID,
    conversation_id: str,
    trace_id: str,
    connection_id: Optional[int],
) -> dict[str, Any]:
    """Attach follow-up datasource context for schema field lookups."""
    if not isinstance(response_data, dict) or response_data.get("mode") != "fields":
        return response_data

    matched_asset = response_data.get("matched_asset")
    if not isinstance(matched_asset, dict):
        return response_data

    datasource_luid = str(matched_asset.get("tableau_id") or "").strip()
    datasource_name = str(matched_asset.get("name") or "").strip()
    if not datasource_luid:
        return response_data

    asset_id = matched_asset.get("asset_id")
    selected_datasource = {
        "luid": datasource_luid,
        "datasource_luid": datasource_luid,
        "tableau_datasource_luid": datasource_luid,
        "name": datasource_name or datasource_luid,
        "datasource_name": datasource_name or datasource_luid,
        "asset_id": asset_id,
        "connection_id": connection_id,
    }
    queryable_fields = [
        field.get("display_name") or field.get("caption") or field.get("name")
        for field in response_data.get("fields") or []
        if isinstance(field, dict) and (field.get("display_name") or field.get("caption") or field.get("name"))
    ]
    analysis_context = AnalysisContext.new(
        conversation_id=conversation_id,
        run_id=str(run_id),
        trace_id=trace_id,
        turn_no=0,
        scope={
            "connection_id": connection_id,
            "datasource_luid": datasource_luid,
            "tableau_datasource_luid": datasource_luid,
            "datasource_name": datasource_name or datasource_luid,
            "asset_id": asset_id,
            "selected_datasource": selected_datasource,
        },
        query_plan={
            "subject": datasource_name or datasource_luid,
            "metrics": [],
            "dimensions": [],
            "filters": [],
        },
        analysis_type="schema_inventory",
        confidence=1.0,
        source="schema_inventory",
        is_followup=False,
    )
    enriched = build_response_data_with_context(response_data, analysis_context=analysis_context)
    enriched["datasource_luid"] = datasource_luid
    enriched["datasource_name"] = datasource_name or datasource_luid
    enriched["selected_datasource"] = selected_datasource
    enriched["queryable_fields"] = queryable_fields
    return enriched


def _write_schema_inventory_success(
    *,
    db: Session,
    run_id: uuid_lib.UUID,
    session: AgentSession,
    session_mgr: SessionManager,
    current_user: dict,
    context: ToolContext,
    question: str,
    connection_id: Optional[int],
    result: DeterministicRouteResult,
    execution_time_ms: int,
    step_durations_ms: Optional[Dict[int, int]] = None,
) -> None:
    skill_version_uuid = _uuid_or_none(result.skill_version_id)
    step_durations_ms = step_durations_ms or {}
    response_data = _schema_inventory_response_data_with_context(
        response_data=result.response_data,
        run_id=run_id,
        conversation_id=str(session.conversation_id),
        trace_id=context.trace_id,
        connection_id=connection_id,
    )
    result.response_data = response_data

    try:
        run = BiAgentRun(
            id=run_id,
            conversation_id=session.conversation_id,
            user_id=current_user["id"],
            connection_id=connection_id,
            question=question,
            status="completed",
            steps_count=result.steps_count,
            tools_used=result.tools_used,
            response_type=result.response_type,
            execution_time_ms=execution_time_ms,
            completed_at=func.now(),
        )
        db.add(run)
        db.flush()
        db.add_all([
            BiAgentStep(
                run_id=run_id,
                step_number=1,
                step_type="thinking",
                content="识别为数据源清单问题，准备读取当前连接的 schema 信息。",
                execution_time_ms=step_durations_ms.get(1),
            ),
            BiAgentStep(
                run_id=run_id,
                step_number=2,
                step_type="tool_call",
                tool_name=result.tool_name,
                tool_params=result.tool_params,
                skill_version_id=skill_version_uuid,
                execution_time_ms=step_durations_ms.get(2),
            ),
            BiAgentStep(
                run_id=run_id,
                step_number=3,
                step_type="tool_result",
                tool_name=result.tool_name,
                tool_result_summary=result.tool_result_summary[:500],
                execution_time_ms=step_durations_ms.get(3),
            ),
            BiAgentStep(
                run_id=run_id,
                step_number=4,
                step_type="answer",
                content=result.answer[:500],
                execution_time_ms=step_durations_ms.get(4),
            ),
        ])
        db.commit()
    except Exception as exc:
        _rollback_after_persistence_error(db)
        logger.exception(
            "Agent schema inventory telemetry persistence failed",
            extra={
                "conversation_id": str(session.conversation_id),
                "trace_id": context.trace_id,
                "run_id": str(run_id),
                "user_id": current_user.get("id"),
                "response_type": result.response_type,
                "error_code": "AGENT_TELEMETRY_PERSISTENCE_FAILED",
                "exception_type": type(exc).__name__,
            },
        )

    try:
        session_mgr.persist_message(
            session=session,
            role="assistant",
            content=result.answer,
            trace_id=context.trace_id,
            response_type=result.response_type,
            response_data=result.response_data,
            tools_used=result.tools_used,
            steps_count=result.steps_count,
            execution_time_ms=execution_time_ms,
        )
    except Exception as exc:
        _rollback_after_persistence_error(db)
        logger.exception(
            "Agent schema inventory assistant message persistence failed",
            extra={
                "conversation_id": str(session.conversation_id),
                "trace_id": context.trace_id,
                "run_id": str(run_id),
                "user_id": current_user.get("id"),
                "response_type": result.response_type,
                "error_code": _AGENT_PERSISTENCE_FAILED,
                "exception_type": type(exc).__name__,
            },
        )
        raise AgentPersistenceError(
            trace_id=context.trace_id,
            run_id=str(run_id),
            conversation_id=str(session.conversation_id),
        ) from exc


def _write_schema_inventory_error_run(
    *,
    db: Session,
    run_id: uuid_lib.UUID,
    session: AgentSession,
    current_user: dict,
    question: str,
    connection_id: Optional[int],
    error_code: str,
    message: str,
    execution_time_ms: int,
) -> None:
    run = BiAgentRun(
        id=run_id,
        conversation_id=session.conversation_id,
        user_id=current_user["id"],
        connection_id=connection_id,
        question=question,
        status="failed",
        error_code=error_code,
        steps_count=0,
        tools_used=["schema"],
        response_type="error",
        execution_time_ms=execution_time_ms,
        completed_at=func.now(),
    )
    db.add(run)
    db.flush()
    db.add(
        BiAgentStep(
            run_id=run_id,
            step_number=1,
            step_type="error",
            tool_name="schema",
            content=message[:500],
            execution_time_ms=execution_time_ms,
        )
    )
    db.commit()


def _write_standard_fallback_run(
    *,
    db: Session,
    run_id: uuid_lib.UUID,
    session: AgentSession,
    session_mgr: SessionManager,
    current_user: dict,
    question: str,
    connection_id: Optional[int],
    fallback: StandardFallback,
    execution_time_ms: int,
) -> None:
    payload = fallback.to_dict()
    try:
        run = BiAgentRun(
            id=run_id,
            conversation_id=session.conversation_id,
            user_id=current_user["id"],
            connection_id=connection_id,
            question=question,
            status="completed",
            error_code=fallback.error_code,
            steps_count=1,
            tools_used=fallback.tools_used,
            response_type="fallback",
            execution_time_ms=execution_time_ms,
            completed_at=func.now(),
        )
        db.add(run)
        db.flush()
        db.add(
            BiAgentStep(
                run_id=run_id,
                step_number=1,
                step_type="answer",
                content=fallback.answer[:500],
                execution_time_ms=execution_time_ms,
            )
        )
        db.commit()
    except Exception as exc:
        _rollback_after_persistence_error(db)
        logger.exception(
            "Agent fallback telemetry persistence failed",
            extra={
                "conversation_id": str(session.conversation_id),
                "trace_id": fallback.trace_id,
                "run_id": str(run_id),
                "user_id": current_user.get("id"),
                "response_type": "fallback",
                "error_code": fallback.error_code,
                "exception_type": type(exc).__name__,
            },
        )

    try:
        session_mgr.persist_message(
            session=session,
            role="assistant",
            content=fallback.answer,
            trace_id=fallback.trace_id,
            response_type="fallback",
            response_data=payload,
            tools_used=fallback.tools_used,
            steps_count=1,
            execution_time_ms=execution_time_ms,
        )
    except Exception as exc:
        _rollback_after_persistence_error(db)
        logger.exception(
            "Agent fallback assistant message persistence failed",
            extra={
                "conversation_id": str(session.conversation_id),
                "trace_id": fallback.trace_id,
                "run_id": str(run_id),
                "user_id": current_user.get("id"),
                "response_type": "fallback",
                "error_code": _AGENT_PERSISTENCE_FAILED,
                "exception_type": type(exc).__name__,
            },
        )
        raise AgentPersistenceError(
            trace_id=fallback.trace_id,
            run_id=str(run_id),
            conversation_id=str(session.conversation_id),
        ) from exc


def _validate_connection_access(
    connection_id: Optional[int],
    current_user: dict,
    db: Session,
) -> None:
    """校验用户对 Tableau 连接的访问权限。

    - connection_id 为 None 时跳过（下游工具自行处理）
    - Tableau 连接不存在或已停用 → 404 AGENT_004
    - admin / data_admin 可访问任意活跃 Tableau 连接
    - analyst 仅可访问 owner_id == 自身 ID 的 Tableau 连接
    - 其他情况 → 403 AGENT_005
    """
    if connection_id is None:
        return

    tc = db.query(TableauConnection).filter(
        TableauConnection.id == connection_id,
        TableauConnection.is_active == True,  # noqa: E712
    ).first()
    if tc:
        role = current_user.get("role", "user")
        if role in ("admin", "data_admin"):
            return
        if tc.owner_id != current_user["id"]:
            raise HTTPException(
                status_code=403,
                detail={"error_code": "AGENT_005", "message": "无权限访问该连接"},
            )
        return

    raise HTTPException(
        status_code=404,
        detail={"error_code": "AGENT_004", "message": "Tableau 连接不存在或已停用"},
    )


def _find_compatible_active_tableau_connection(
    db: Session,
    *,
    name: Optional[str] = None,
    server_url: Optional[str] = None,
    site: Optional[str] = None,
) -> Optional[TableauConnection]:
    active_query = db.query(TableauConnection).filter(
        TableauConnection.is_active == True,  # noqa: E712
    )

    if server_url and site and name:
        matched = active_query.filter(
            TableauConnection.server_url == server_url,
            TableauConnection.site == site,
            TableauConnection.name == name,
        ).order_by(TableauConnection.id.asc()).first()
        if matched:
            return matched

    active_connections = active_query.order_by(TableauConnection.id.asc()).all()
    if len(active_connections) == 1:
        return active_connections[0]

    return None


def _resolve_agent_connection_id(
    connection_id: Optional[int],
    db: Session,
) -> tuple[Optional[int], Optional[Any]]:
    """Resolve AskBar connection IDs before access validation.

    /api/tableau/connections exposes active Tableau MCP configs as virtual IDs
    (10000 + mcp_servers.id) when no bridged tableau_connections row exists.
    The Data Agent cannot use that virtual ID directly, so it must resolve to
    an active real Tableau connection before access validation.
    """
    if connection_id is None:
        return None, None

    if connection_id < MCP_VIRTUAL_CONNECTION_OFFSET:
        direct_tableau = db.query(TableauConnection).filter(
            TableauConnection.id == connection_id,
            TableauConnection.is_active == True,  # noqa: E712
        ).first()
        if direct_tableau:
            return connection_id, None

        historical_tableau = db.query(TableauConnection).filter(
            TableauConnection.id == connection_id,
        ).first()
        compatible = _find_compatible_active_tableau_connection(
            db,
            name=getattr(historical_tableau, "name", None),
            server_url=getattr(historical_tableau, "server_url", None),
            site=getattr(historical_tableau, "site", None),
        )
        if compatible:
            logger.info(
                "Resolved stale Tableau connection_id=%s to active Tableau connection_id=%s",
                connection_id,
                compatible.id,
            )
            return compatible.id, None

        return connection_id, None

    try:
        from services.mcp.models import McpServer
    except Exception:
        logger.exception("Failed to import McpServer while resolving connection_id=%s", connection_id)
        return connection_id, None

    mcp_id = connection_id - MCP_VIRTUAL_CONNECTION_OFFSET
    mcp_server = db.query(McpServer).filter(
        McpServer.id == mcp_id,
        McpServer.type == "tableau",
        McpServer.is_active == True,  # noqa: E712
    ).first()
    if not mcp_server:
        return connection_id, None

    credentials = mcp_server.credentials or {}
    bridged = db.query(TableauConnection).filter(
        TableauConnection.is_active == True,  # noqa: E712
        TableauConnection.server_url == (credentials.get("tableau_server") or mcp_server.server_url),
        TableauConnection.site == (credentials.get("site_name") or mcp_server.site_name or ""),
        TableauConnection.name == mcp_server.name,
    ).first()
    if bridged:
        return bridged.id, mcp_server

    compatible = _find_compatible_active_tableau_connection(
        db,
        name=mcp_server.name,
        server_url=credentials.get("tableau_server") or mcp_server.server_url,
        site=credentials.get("site_name") or mcp_server.site_name,
    )
    if compatible:
        logger.info(
            "Resolved virtual MCP connection_id=%s to active Tableau connection_id=%s",
            connection_id,
            compatible.id,
        )
        return compatible.id, mcp_server

    return connection_id, mcp_server


@router.post("/stream")
async def agent_stream(
    req: StreamRequest,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Data Agent SSE 流式对话端点（Spec 36 §5 POST /api/agent/stream）。
    认证：analyst+ 角色。
    """
    _require_agent_role(current_user.get("role", "user"))
    effective_connection_id, virtual_mcp_server = _resolve_agent_connection_id(req.connection_id, db)
    _validate_connection_access(effective_connection_id, current_user, db)

    llm_user_id_var.set(current_user["id"])  # 为 token 消耗日志注入用户上下文
    session_mgr = SessionManager(db)
    trace_id = f"t-{uuid_lib.uuid4().hex[:8]}"

    # 创建或续接会话
    if req.conversation_id:
        try:
            conv_uuid = uuid_lib.UUID(req.conversation_id)
        except ValueError:
            raise HTTPException(status_code=400, detail={"error_code": "AGENT_007", "message": "无效的会话 ID"})

        session = session_mgr.resume_session(conv_uuid, current_user["id"])
        if not session:
            raise HTTPException(status_code=404, detail={"error_code": "AGENT_004", "message": "会话不存在"})
        is_new_session = False
    else:
        session = session_mgr.create_session(
            user_id=current_user["id"],
            connection_id=effective_connection_id,
        )
        is_new_session = True

    conversation_id_str = str(session.conversation_id)

    # 解析连接名称和类型（用于 LLM prompt 上下文）
    conn_name: Optional[str] = None
    conn_type: Optional[str] = None
    if effective_connection_id:
        tc = db.query(TableauConnection).filter(TableauConnection.id == effective_connection_id).first()
        if tc:
            conn_name = tc.name
            conn_type = "tableau"
    elif virtual_mcp_server:
        conn_name = virtual_mcp_server.name
        conn_type = "tableau_mcp"

    # 构建 ToolContext
    context = ToolContext(
        session_id=conversation_id_str,
        user_id=current_user["id"],
        connection_id=effective_connection_id,
        connection_name=conn_name,
        connection_type=conn_type,
        trace_id=trace_id,
        tenant_id=str(current_user["tenant_id"]) if current_user.get("tenant_id") else None,
        selected_datasource_luid=req.datasource_luid,
        datasource_name=req.datasource_name,
        user_role=current_user.get("role"),
    )

    # 构建丰富的会话上下文（工具可通过此获取用户信息、数据源列表等）
    session_context = build_session_context(
        session_id=conversation_id_str,
        trace_id=trace_id,
        current_user=current_user,
        connection_id=effective_connection_id,
        db=db,
    )

    # 构建引擎（含 DB skill meta 覆盖）
    engine, _registry = await create_engine_with_skills(db)

    # 保存用户消息
    session_mgr.persist_message(
        session=session,
        role="user",
        content=req.question,
        trace_id=trace_id,
    )

    async def event_generator() -> AsyncGenerator[str, None]:
        _t0 = time.monotonic()
        intent_result = classify_intent(req.question, connection_type=context.connection_type)
        route_decision = classify_homepage_question(req.question)
        yield _sse_data({"type": "intent_classifier", **intent_result.to_dict()})
        yield _sse_data({"type": "route_decision", **route_decision.to_dict()})
        yield _sse_data({
            "type": "explainability",
            "phase": "intent",
            "status": "completed",
            "payload": {
                **_intent_explainability_payload(route_decision),
                "intent_classifier": intent_result.to_dict(),
            },
        })

        if (
            route_decision.needs_clarification
            and not intent_result.is_data_intent
            and not intent_result.is_asset_inventory
        ):
            run_id = uuid_lib.uuid4()
            fallback = make_clarification_fallback(trace_id=trace_id, route_decision=route_decision)
            explainability = _explainability_snapshot(
                trace_id=trace_id,
                run_id=str(run_id),
                route_decision=route_decision,
                response_type="fallback",
                fallback=fallback,
            )
            execution_time_ms = int((time.monotonic() - _t0) * 1000)
            try:
                _write_standard_fallback_run(
                    db=db,
                    run_id=run_id,
                    session=session,
                    session_mgr=session_mgr,
                    current_user=current_user,
                    question=req.question,
                    connection_id=effective_connection_id,
                    fallback=fallback,
                    execution_time_ms=execution_time_ms,
                )
            except AgentPersistenceError:
                yield _persistence_failed_sse(trace_id=trace_id, run_id=str(run_id))
                return
            yield _sse_data({
                "type": "done",
                "answer": fallback.answer,
                "trace_id": trace_id,
                "run_id": str(run_id),
                "tools_used": [],
                "response_type": "fallback",
                "response_data": fallback.to_dict(),
                "steps_count": 1,
                "execution_time_ms": execution_time_ms,
                "sources_count": 0,
                "top_sources": [],
                "fallback": explainability["phases"]["fallback"],
                "explainability": explainability,
            })
            return

        # ── Deterministic route：稳定回答连接 schema / 数据源清单问题 ────────────
        deterministic_route = detect_deterministic_route(req.question, context.connection_type)
        chain_selection = select_data_agent_chain()
        tableau_mcp_strict_context = (
            str(getattr(context, "connection_type", "") or "").strip().lower() == "tableau"
            or bool(getattr(context, "selected_datasource_luid", None) and getattr(context, "connection_id", None))
        )
        schema_inventory_should_defer_to_mcp_proxy = (chain_selection.is_mcp_proxy or tableau_mcp_strict_context) and (
            intent_result.is_asset_inventory
            or route_decision.is_asset_question
            or deterministic_route == "schema_inventory"
        )
        if (
            not schema_inventory_should_defer_to_mcp_proxy
            and (
                intent_result.is_asset_inventory
                or route_decision.is_asset_question
                or deterministic_route == "schema_inventory"
            )
        ):
            run_id = uuid_lib.uuid4()
            active_skill_version = get_active_skill_version(db, "schema")
            yield _sse_data({
                "type": "metadata",
                "conversation_id": conversation_id_str,
                "run_id": str(run_id),
                "trace_id": trace_id,
                "contract_version": "p0.1",
            })

            if (
                active_skill_version.get("is_configured")
                and active_skill_version.get("is_enabled") is False
            ):
                error_code = "AGENT_003"
                message = "schema 工具已禁用，无法生成数据源清单。请联系管理员在 Skills Center 启用 schema 工具。"
                execution_time_ms = int((time.monotonic() - _t0) * 1000)
                try:
                    _write_schema_inventory_error_run(
                        db=db,
                        run_id=run_id,
                        session=session,
                        current_user=current_user,
                        question=req.question,
                        connection_id=effective_connection_id,
                        error_code=error_code,
                        message=message,
                        execution_time_ms=execution_time_ms,
                    )
                except Exception as e:
                    logger.warning("[DETERMINISTIC] failed to write disabled schema run: %s", e)
                yield _sse_data({
                    "type": "error",
                    "error_code": error_code,
                    "message": message,
                })
                log_nlq_query(
                    user_id=current_user.get("id"),
                    question=req.question,
                    intent="schema_inventory",
                    datasource_luid=context.selected_datasource_luid,
                    execution_time_ms=execution_time_ms,
                    error_code=error_code,
                )
                return

            version_for_route = active_skill_version if active_skill_version.get("version_id") else None
            thinking_text = "识别为数据源清单问题，准备读取当前连接的 schema 信息。"
            schema_tool_params = build_schema_inventory_tool_params(req.question)
            yield _sse_data({"type": "thinking", "content": thinking_text})
            yield _sse_data({"type": "tool_call", "tool": "schema", "params": schema_tool_params})

            try:
                route_start = time.monotonic()
                result = await run_schema_inventory_route(
                    _registry,
                    context,
                    active_skill_version=version_for_route,
                    question=req.question,
                )
                route_ms = max(0, int((time.monotonic() - route_start) * 1000))
                execution_time_ms = int((time.monotonic() - _t0) * 1000)
                _write_schema_inventory_success(
                    db=db,
                    run_id=run_id,
                    session=session,
                    session_mgr=session_mgr,
                    current_user=current_user,
                    context=context,
                    question=req.question,
                    connection_id=effective_connection_id,
                    result=result,
                    execution_time_ms=execution_time_ms,
                    step_durations_ms={
                        1: 0,
                        2: 0,
                        3: route_ms,
                        4: max(0, execution_time_ms - route_ms),
                    },
                )
            except AgentPersistenceError:
                yield _persistence_failed_sse(trace_id=trace_id, run_id=str(run_id))
                return
            except Exception as e:
                logger.exception("[DETERMINISTIC] schema inventory route failed: %s", e)
                error_code = "AGENT_003"
                message = "生成数据源清单失败，请稍后重试。"
                execution_time_ms = int((time.monotonic() - _t0) * 1000)
                try:
                    _write_schema_inventory_error_run(
                        db=db,
                        run_id=run_id,
                        session=session,
                        current_user=current_user,
                        question=req.question,
                        connection_id=effective_connection_id,
                        error_code=error_code,
                        message=message,
                        execution_time_ms=execution_time_ms,
                    )
                except Exception as write_error:
                    logger.warning("[DETERMINISTIC] failed to write schema error run: %s", write_error)
                yield _sse_data({
                    "type": "error",
                    "error_code": error_code,
                    "message": message,
                })
                log_nlq_query(
                    user_id=current_user.get("id"),
                    question=req.question,
                    intent="schema_inventory",
                    datasource_luid=context.selected_datasource_luid,
                    execution_time_ms=execution_time_ms,
                    error_code=error_code,
                )
                return

            yield _sse_data({
                "type": "tool_result",
                "tool": result.tool_name,
                "summary": result.tool_result_summary[:200],
            })
            token_text = result.answer
            yield _sse_data({"type": "token", "content": token_text})
            explainability = _explainability_snapshot(
                trace_id=trace_id,
                run_id=str(run_id),
                route_decision=route_decision,
                response_type=result.response_type,
                row_count=(
                    len(result.response_data.get("tables", []))
                    if isinstance(result.response_data, dict)
                    else None
                ),
            )
            done_payload = {
                "type": "done",
                "answer": token_text,
                "trace_id": trace_id,
                "run_id": str(run_id),
                "tools_used": result.tools_used,
                "response_type": result.response_type,
                "response_data": result.response_data,
                "steps_count": result.steps_count,
                "execution_time_ms": execution_time_ms,
                "sources_count": 0,
                "top_sources": [],
                "explainability": explainability,
            }
            yield _sse_data(done_payload)
            log_nlq_query(
                user_id=current_user.get("id"),
                question=req.question,
                intent="schema_inventory",
                datasource_luid=context.selected_datasource_luid,
                response_type=result.response_type,
                execution_time_ms=execution_time_ms,
                error_code=None,
            )
            if is_new_session:
                asyncio.create_task(
                    _generate_short_title(req.question, conversation_id_str, current_user["id"])
                )
            return

        # ── 标准 ReAct 路径 ──────────────────────────────────────────────────
        async for event in run_agent(
            engine=engine,
            context=context,
            session_mgr=session_mgr,
            session=session,
            question=req.question,
            trace_id=trace_id,
            current_user=current_user,
            db=db,
            connection_id=effective_connection_id,
            route_decision=route_decision,
            intent_result=intent_result,
            enforce_controlled_data_path=True,
        ):
            if event.type == "metadata":
                yield f"data: {json.dumps({'type': 'metadata', 'conversation_id': event.content['conversation_id'], 'run_id': event.content['run_id'], 'trace_id': trace_id, 'contract_version': 'p0.1'}, ensure_ascii=False)}\n\n"

            elif event.type == "thinking":
                yield f"data: {json.dumps({'type': 'thinking', 'content': event.content}, ensure_ascii=False)}\n\n"

            elif event.type == "tool_call":
                yield f"data: {json.dumps({'type': 'tool_call', 'tool': event.content.get('tool', ''), 'params': event.content.get('params', {})}, ensure_ascii=False)}\n\n"

            elif event.type == "tool_result":
                result_data = event.content.get("result", {})
                summary = result_data.get("data") if isinstance(result_data, dict) else result_data
                summary_str = str(summary)[:200] if summary else ""
                yield f"data: {json.dumps({'type': 'tool_result', 'tool': event.content.get('tool', ''), 'summary': summary_str}, ensure_ascii=False)}\n\n"

            elif event.type == "table_data":
                table_response = normalize_table_response(event.content)
                if table_response is not None:
                    yield _sse_data(table_data_event_from_response(table_response))
                else:
                    yield f"data: {json.dumps({'type': 'table_data', 'fields': event.content.get('fields', []), 'rows': event.content.get('rows', []), 'col_types': event.content.get('col_types', [])}, ensure_ascii=False)}\n\n"

            elif event.type == "chart_data":
                yield f"data: {json.dumps({'type': 'chart_data', 'chart_type': event.content.get('chart_type', 'bar'), 'x_field': event.content.get('x_field'), 'y_fields': event.content.get('y_fields', []), 'series_field': event.content.get('series_field'), 'data': event.content.get('data', [])}, ensure_ascii=False)}\n\n"

            elif event.type == "done":
                # Emit per-char tokens before the done event
                answer_text = event.content.get("answer", "")
                for char in answer_text:
                    yield f"data: {json.dumps({'type': 'token', 'content': char}, ensure_ascii=False)}\n\n"
                    await asyncio.sleep(0.01)
                response_type = event.content.get('response_type', 'text')
                response_data = event.content.get('response_data')
                if response_type == "table":
                    response_data = normalize_table_response(response_data) or response_data
                row_count = (
                    len(response_data.get("rows", []))
                    if isinstance(response_data, dict) and isinstance(response_data.get("rows"), list)
                    else None
                )
                explainability = _explainability_snapshot(
                    trace_id=event.content.get('trace_id', trace_id),
                    run_id=event.content.get('run_id', ''),
                    route_decision=route_decision,
                    response_type=response_type,
                    row_count=row_count,
                )
                yield f"data: {json.dumps({'type': 'done', 'answer': answer_text, 'trace_id': event.content.get('trace_id', ''), 'run_id': event.content.get('run_id', ''), 'tools_used': event.content.get('tools_used', []), 'response_type': response_type, 'response_data': response_data, 'steps_count': event.content.get('steps_count', 0), 'execution_time_ms': event.content.get('execution_time_ms', 0), 'sources_count': event.content.get('sources_count', 0), 'top_sources': event.content.get('top_sources', []), 'explainability': explainability}, ensure_ascii=False)}\n\n"
                log_nlq_query(
                    user_id=current_user.get("id"),
                    question=req.question,
                    intent=intent_result.intent if intent_result else None,
                    datasource_luid=context.selected_datasource_luid,
                    response_type=event.content.get("response_type"),
                    execution_time_ms=event.content.get("execution_time_ms") or int((time.monotonic() - _t0) * 1000),
                    error_code=None,
                )
                if is_new_session:
                    asyncio.create_task(
                        _generate_short_title(req.question, conversation_id_str, current_user["id"])
                    )

            elif event.type == "error":
                error_content = event.content if isinstance(event.content, dict) else {"message": str(event.content)}
                err_code = error_content.get("error_code", "AGENT_003")
                payload: dict = {
                    "type": "error",
                    "error_code": err_code,
                    "message": error_content.get("message", "未知错误"),
                }
                for key in (
                    "fallback_type",
                    "trace_id",
                    "run_id",
                    "retryable",
                    "suggested_actions",
                    "tools_used",
                    "route_decision",
                    "intent_classifier",
                    "controlled_chain",
                ):
                    if key in error_content:
                        payload[key] = error_content[key]
                if error_content.get("user_hint"):
                    payload["user_hint"] = error_content["user_hint"]
                if error_content.get("fallback_type"):
                    fallback = StandardFallback(
                        fallback_type=str(error_content.get("fallback_type")),
                        error_code=str(error_content.get("error_code") or err_code),
                        message=str(error_content.get("message") or "工具执行失败"),
                        user_hint=str(error_content.get("user_hint") or ""),
                        trace_id=str(error_content.get("trace_id") or trace_id),
                        retryable=bool(error_content.get("retryable", True)),
                        suggested_actions=list(error_content.get("suggested_actions") or []),
                        route_decision=error_content.get("route_decision"),
                        tools_used=list(error_content.get("tools_used") or []),
                    )
                    explainability = _explainability_snapshot(
                        trace_id=trace_id,
                        route_decision=route_decision,
                        response_type="fallback",
                        fallback=fallback,
                    )
                    payload["fallback"] = explainability["phases"]["fallback"]
                    payload["explainability"] = explainability
                yield f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"
                log_nlq_query(
                    user_id=current_user.get("id"),
                    question=req.question,
                    intent=intent_result.intent if intent_result else None,
                    datasource_luid=context.selected_datasource_luid,
                    execution_time_ms=int((time.monotonic() - _t0) * 1000),
                    error_code=err_code,
                )

    return StreamingResponse(
        _stream_with_keepalive(event_generator()),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


# ============================================================================
# 会话管理
# ============================================================================


@router.get("/conversations")
def list_conversations(
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """列出当前用户的会话（按 updated_at DESC）"""
    _require_agent_role(current_user.get("role", "user"))
    session_mgr = SessionManager(db)
    convs = session_mgr.get_user_conversations(
        user_id=current_user["id"],
        status="active",
        limit=limit,
        offset=offset,
    )
    message_counts = {
        str(row._mapping["conversation_id"]): row._mapping["count"]
        for row in (
            db.query(
                AgentConversationMessage.conversation_id,
                func.count(AgentConversationMessage.id).label("count"),
            )
            .filter(AgentConversationMessage.conversation_id.in_([c.id for c in convs]))
            .group_by(AgentConversationMessage.conversation_id)
            .all()
        )
    } if convs else {}
    first_user_messages: dict[str, str] = {}
    if convs:
        rows = (
            db.query(
                AgentConversationMessage.conversation_id,
                AgentConversationMessage.content,
            )
            .filter(AgentConversationMessage.conversation_id.in_([c.id for c in convs]))
            .filter(AgentConversationMessage.role == "user")
            .order_by(
                AgentConversationMessage.conversation_id.asc(),
                AgentConversationMessage.created_at.asc(),
            )
            .all()
        )
        for row in rows:
            conv_id = str(row._mapping["conversation_id"])
            if conv_id not in first_user_messages:
                first_user_messages[conv_id] = row._mapping["content"]
    return [
        ConversationItem(
            id=str(c.id),
            title=_resolve_conversation_title(c.title, first_user_messages.get(str(c.id))),
            connection_id=c.connection_id,
            status=c.status,
            message_count=message_counts.get(str(c.id), 0),
            created_at=c.created_at.isoformat() if c.created_at else "",
            updated_at=c.updated_at.isoformat() if c.updated_at else "",
        )
        for c in convs
    ]


@router.patch("/conversations/{conversation_id}", response_model=ConversationItem)
def update_conversation(
    conversation_id: str,
    body: ConversationUpdateRequest,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """更新 Data Agent 会话标题（校验归属）"""
    _require_agent_role(current_user.get("role", "user"))

    try:
        conv_uuid = uuid_lib.UUID(conversation_id)
    except ValueError:
        raise HTTPException(status_code=400, detail={"error_code": "AGENT_007", "message": "无效的会话 ID"})

    title = body.title.strip()
    if not title:
        raise HTTPException(status_code=400, detail={"error_code": "AGENT_007", "message": "标题不能为空"})

    session_mgr = SessionManager(db)
    conv = session_mgr.update_title(conv_uuid, title, current_user["id"])
    if not conv:
        raise HTTPException(status_code=404, detail={"error_code": "AGENT_004", "message": "会话不存在"})

    message_count = (
        db.query(func.count(AgentConversationMessage.id))
        .filter(AgentConversationMessage.conversation_id == conv_uuid)
        .scalar()
        or 0
    )
    return ConversationItem(
        id=str(conv.id),
        title=conv.title or "",
        connection_id=conv.connection_id,
        status=conv.status,
        message_count=int(message_count),
        created_at=conv.created_at.isoformat() if conv.created_at else "",
        updated_at=conv.updated_at.isoformat() if conv.updated_at else "",
    )


@router.get("/conversations/{conversation_id}")
def get_conversation(
    conversation_id: str,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """获取单个会话元数据（含 connection_id）"""
    _require_agent_role(current_user.get("role", "user"))

    try:
        conv_uuid = uuid_lib.UUID(conversation_id)
    except ValueError:
        raise HTTPException(status_code=400, detail={"error_code": "AGENT_007", "message": "无效的会话 ID"})

    conv = db.query(AgentConversation).filter(
        AgentConversation.id == conv_uuid,
        AgentConversation.user_id == current_user["id"],
    ).first()
    if not conv:
        raise HTTPException(status_code=404, detail={"error_code": "AGENT_004", "message": "会话不存在"})

    return ConversationItem(
        id=str(conv.id),
        title=conv.title or "",
        connection_id=conv.connection_id,
        status=conv.status,
        message_count=0,
        created_at=conv.created_at.isoformat() if conv.created_at else "",
        updated_at=conv.updated_at.isoformat() if conv.updated_at else "",
    )


@router.get("/conversations/{conversation_id}/messages")
def get_conversation_messages(
    conversation_id: str,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """获取会话消息（校验归属）"""
    _require_agent_role(current_user.get("role", "user"))

    try:
        conv_uuid = uuid_lib.UUID(conversation_id)
    except ValueError:
        raise HTTPException(status_code=400, detail={"error_code": "AGENT_007", "message": "无效的会话 ID"})

    session_mgr = SessionManager(db)
    # 先校验会话存在且归属当前用户
    session = session_mgr.resume_session(conv_uuid, current_user["id"])
    if not session:
        raise HTTPException(status_code=404, detail={"error_code": "AGENT_004", "message": "会话不存在"})

    msgs = session_mgr.get_conversation_messages(conv_uuid, user_id=current_user["id"], limit=limit, offset=offset)
    runs = (
        db.query(BiAgentRun)
        .filter(BiAgentRun.conversation_id == conv_uuid)
        .order_by(BiAgentRun.created_at.asc())
        .all()
    )
    run_id_by_message_id: Dict[int, str] = {}
    run_index = 0
    for msg in msgs:
        if msg.role != "assistant" or run_index >= len(runs):
            continue
        run_id_by_message_id[msg.id] = str(runs[run_index].id)
        run_index += 1

    return [
        MessageItem(
            id=m.id,
            role=m.role,
            content=m.content,
            response_type=m.response_type,
            response_data=m.response_data,
            run_id=run_id_by_message_id.get(m.id),
            error_detail=m.response_data if m.response_type in ("error", "fallback") else None,
            explainability=(
                m.response_data.get("explainability")
                if isinstance(m.response_data, dict)
                else None
            ),
            tools_used=m.tools_used,
            trace_id=m.trace_id,
            steps_count=m.steps_count,
            execution_time_ms=m.execution_time_ms,
            sources_count=m.sources_count,
            top_sources=m.top_sources,
            created_at=m.created_at.isoformat() if m.created_at else "",
        )
        for m in msgs
    ]


@router.delete("/conversations/{conversation_id}")
def archive_conversation(
    conversation_id: str,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """归档会话"""
    _require_agent_role(current_user.get("role", "user"))

    try:
        conv_uuid = uuid_lib.UUID(conversation_id)
    except ValueError:
        raise HTTPException(status_code=400, detail={"error_code": "AGENT_007", "message": "无效的会话 ID"})

    session_mgr = SessionManager(db)
    # 校验归属
    session = session_mgr.resume_session(conv_uuid, current_user["id"])
    if not session:
        raise HTTPException(status_code=404, detail={"error_code": "AGENT_004", "message": "会话不存在"})

    session_mgr.archive_session(conv_uuid, user_id=current_user["id"])
    return {"status": "archived", "conversation_id": conversation_id}


@router.delete("/conversations")
def clear_all_conversations(
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """清空当前用户所有会话（硬删除）"""
    _require_agent_role(current_user.get("role", "user"))

    session_mgr = SessionManager(db)
    convs = session_mgr.get_user_conversations(user_id=current_user["id"], status="active", limit=1000)
    deleted_count = 0
    for conv in convs:
        session_mgr.archive_session(conv.id, user_id=current_user["id"])
        deleted_count += 1

    return {"deleted_count": deleted_count}


# ============================================================================
# 工具动态发现
# ============================================================================


@router.get("/tools")
def list_available_tools(
    category: Optional[str] = None,
    current_user: dict = Depends(get_current_user),
):
    """
    GET /api/agent/tools — 列出所有可用工具及其元数据

    返回每个工具的 name、description、parameters_schema、category、version、
    dependencies、tags。可选 ?category= 筛选。
    """
    _require_agent_role(current_user.get("role", "user"))

    _engine, registry = create_engine()

    if category:
        tools = registry.get_tools_by_category(category)
        return [t.get_full_metadata() for t in tools]

    return registry.get_tools_metadata()


# ============================================================================
# 反馈
# ============================================================================


@router.post("/feedback")
def submit_feedback(
    req: FeedbackRequest,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """提交 Agent 运行反馈（thumbs up/down）"""
    _require_agent_role(current_user.get("role", "user"))

    try:
        run_uuid = uuid_lib.UUID(req.run_id)
    except ValueError:
        raise HTTPException(
            status_code=400,
            detail={"error_code": "AGENT_007", "message": "无效的运行 ID"},
        )

    run = db.query(BiAgentRun).filter(BiAgentRun.id == run_uuid).first()
    if not run:
        raise HTTPException(
            status_code=404,
            detail={"error_code": "AGENT_004", "message": "运行记录不存在"},
        )

    existing = db.query(BiAgentFeedback).filter(
        BiAgentFeedback.run_id == run_uuid,
        BiAgentFeedback.user_id == current_user["id"],
    ).first()
    if existing:
        existing.rating = req.rating
        existing.comment = req.comment
        db.commit()
        return {"status": "updated", "feedback_id": existing.id}

    feedback = BiAgentFeedback(
        run_id=run_uuid,
        user_id=current_user["id"],
        rating=req.rating,
        comment=req.comment,
    )
    db.add(feedback)
    db.commit()
    db.refresh(feedback)
    return {"status": "created", "feedback_id": feedback.id}


def _upsert_run_feedback(
    db: Session,
    run_uuid: uuid_lib.UUID,
    user_id: int,
    rating: str,
    comment: Optional[str] = None,
) -> tuple[BiAgentFeedback, str]:
    existing = db.query(BiAgentFeedback).filter(
        BiAgentFeedback.run_id == run_uuid,
        BiAgentFeedback.user_id == user_id,
    ).first()
    if existing:
        existing.rating = rating
        existing.comment = comment
        return existing, "updated"

    feedback = BiAgentFeedback(
        run_id=run_uuid,
        user_id=user_id,
        rating=rating,
        comment=comment,
    )
    db.add(feedback)
    return feedback, "created"


@router.post("/feedback/v2")
async def submit_agent_feedback_v2(
    run_id: Optional[str] = Body(None),
    rating: str = Body(..., pattern="^(up|down)$"),
    conversation_id: Optional[str] = Body(None),
    message_index: Optional[int] = Body(None),
    question: Optional[str] = Body(None),
    answer_summary: Optional[str] = Body(None),
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    扩展反馈端点（Spec 25 Gap 1）。

    支持两种调用方式：
    1. run_id 方式：通过 run_id 查询 BiAgentRun 获取 conversation_id
    2. 直接方式：直接传入 conversation_id、message_index 等字段

    run_id 方式写入 run 级反馈表；legacy message_feedback 仅用于无 run_id 的调用。
    """
    _require_agent_role(current_user.get("role", "user"))

    # 如果没有 run_id 但有 conversation_id，直接转发
    if not run_id and conversation_id:
        pass  # 直接使用传入的参数
    elif run_id:
        # run_id -> conversation_id 映射
        try:
            run_uuid = uuid_lib.UUID(run_id)
        except ValueError:
            raise HTTPException(
                status_code=400,
                detail={"error_code": "AGENT_007", "message": "无效的运行 ID"},
            )

        run = db.query(BiAgentRun).filter(BiAgentRun.id == run_uuid).first()
        if not run:
            raise HTTPException(
                status_code=404,
                detail={"error_code": "AGENT_004", "message": "运行记录不存在"},
            )

        _feedback, run_feedback_status = _upsert_run_feedback(
            db=db,
            run_uuid=run_uuid,
            user_id=current_user["id"],
            rating=rating,
        )
        try:
            db.commit()
            logger.info(
                "Agent run 反馈已记录（v2） user_id=%s rating=%s run_id=%s",
                current_user["id"], rating, run_id,
            )
            return {"ok": True, "status": run_feedback_status or "created"}
        except Exception as exc:
            db.rollback()
            logger.error("写入 run 级反馈失败（v2）: %s", exc, exc_info=True)
            raise HTTPException(
                status_code=500,
                detail={"error_code": "AGENT_008", "message": "反馈写入失败"},
            )
    else:
        raise HTTPException(
            status_code=400,
            detail={"error_code": "AGENT_007", "message": "必须提供 run_id 或 conversation_id"},
        )

    from datetime import datetime, timezone

    try:
        db.execute(
            text(
                "INSERT INTO message_feedback "
                "(user_id, username, conversation_id, message_index, question, answer_summary, rating, created_at) "
                "VALUES (:user_id, :username, :conversation_id, :message_index, :question, :answer_summary, :rating, :created_at)"
            ),
            {
                "user_id": current_user["id"],
                "username": current_user.get("username") or "",
                "conversation_id": conversation_id,
                "message_index": message_index,
                "question": question,
                "answer_summary": answer_summary[:100] if answer_summary else None,
                "rating": rating,
                "created_at": datetime.now(timezone.utc),
            },
        )
        db.commit()
        logger.info(
            "反馈已记录（v2） user_id=%s rating=%s conversation_id=%s run_id=%s",
            current_user["id"], rating, conversation_id, run_id,
        )
        return {"ok": True, "status": "created"}
    except Exception as exc:
        db.rollback()
        logger.error("写入反馈失败（v2）: %s", exc, exc_info=True)
        raise HTTPException(
            status_code=500,
            detail={"error_code": "AGENT_008", "message": "反馈写入失败"},
        )


@router.get("/feedback")
def get_agent_feedback(
    run_id: Optional[str] = Query(None),
    conversation_id: Optional[str] = Query(None),
    message_index: Optional[int] = Query(None),
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """GET /api/agent/feedback — 查询当前用户对指定消息的已有评分"""
    _require_agent_role(current_user.get("role", "user"))
    if run_id:
        try:
            run_uuid = uuid_lib.UUID(run_id)
        except ValueError:
            raise HTTPException(
                status_code=400,
                detail={"error_code": "AGENT_007", "message": "无效的运行 ID"},
            )

        feedback = db.query(BiAgentFeedback).filter(
            BiAgentFeedback.run_id == run_uuid,
            BiAgentFeedback.user_id == current_user["id"],
        ).first()
        if feedback:
            return {"rating": feedback.rating}

        return {"rating": None}

    if conversation_id is None or message_index is None:
        raise HTTPException(
            status_code=400,
            detail={"error_code": "AGENT_007", "message": "必须提供 run_id 或 conversation_id/message_index"},
        )

    row = db.execute(
        text(
            "SELECT rating FROM message_feedback "
            "WHERE user_id = :user_id AND conversation_id = :conversation_id "
            "AND message_index = :message_index "
            "ORDER BY created_at DESC LIMIT 1"
        ),
        {
            "user_id": current_user["id"],
            "conversation_id": conversation_id,
            "message_index": message_index,
        },
    ).fetchone()
    return {"rating": row[0] if row else None}


# ============================================================================
# Spec 36 §15: HOMEPAGE_AGENT_MODE 端点（GET/POST /api/agent/mode）
# ============================================================================


@router.get("/mode", response_model=ModeStatusResponse)
def get_agent_mode(
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    GET /api/agent/mode — 获取当前 HOMEPAGE_AGENT_MODE 状态。

    认证：analyst+ 角色可读。
    返回当前模式和描述。
    """
    _require_agent_role(current_user.get("role", "user"))

    mode = get_homepage_agent_mode(db, user_id=current_user.get("id"))

    descriptions = {
        "legacy_only": "仅 NLQ 直连（/api/search/query）",
        "agent_with_fallback": "Agent 优先，失败 fallback NLQ（默认）",
        "agent_only": "仅 Agent，NLQ 入口下线",
        "dual_write": "Agent + NLQ 并发，以 Agent 结果为准",
    }

    return ModeStatusResponse(
        mode=mode.value,
        description=descriptions.get(mode.value, "未知模式"),
        can_rollback=True,
        failure_tracker_active=True,
    )


@router.post("/mode", response_model=ModeStatusResponse)
def update_agent_mode(
    req: ModeUpdateRequest,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    POST /api/agent/mode — 设置 HOMEPAGE_AGENT_MODE（admin only）。

    Spec 36 §15 约束：
    - 仅 admin 可修改模式
    - 修改自动写入 audit log（actor=system）
    """
    if current_user.get("role") != "admin":
        raise HTTPException(
            status_code=403,
            detail={"error_code": "AGENT_006", "message": "仅 admin 可修改 Agent 模式"},
        )

    if not HomepageAgentMode.is_valid(req.mode):
        raise HTTPException(
            status_code=400,
            detail={
                "error_code": "AGENT_007",
                "message": f"无效模式: {req.mode}，有效值: legacy_only, agent_with_fallback, agent_only, dual_write",
            },
        )

    from services.platform_settings import PlatformSettingsService
    svc = PlatformSettingsService(db)

    # 更新全局模式
    svc.set("homepage_agent_mode", req.mode)

    # 更新单用户 override（若有）
    if req.user_override:
        import json
        svc.set("homepage_agent_mode_user_override", json.dumps(req.user_override))

    # 写审计日志
    from services.agent.dual_write import write_system_audit_log
    write_system_audit_log(
        db,
        event_type="mode_change",
        detail=f" HOMEPAGE_AGENT_MODE changed to {req.mode} by admin {current_user['id']}",
        actor="system",
    )

    logger.warning(
        "HOMEPAGE_AGENT_MODE changed to %s by admin %s",
        req.mode, current_user["id"],
    )

    mode = HomepageAgentMode(req.mode)
    descriptions = {
        "legacy_only": "仅 NLQ 直连（/api/search/query）",
        "agent_with_fallback": "Agent 优先，失败 fallback NLQ（默认）",
        "agent_only": "仅 Agent，NLQ 入口下线",
        "dual_write": "Agent + NLQ 并发，以 Agent 结果为准",
    }

    return ModeStatusResponse(
        mode=mode.value,
        description=descriptions.get(mode.value, "未知模式"),
        can_rollback=True,
        failure_tracker_active=True,
    )

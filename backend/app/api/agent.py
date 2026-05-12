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
import json
import logging
import time
import uuid as uuid_lib
from datetime import datetime, timezone
from typing import AsyncGenerator, Any, Dict, List, Optional

from fastapi import APIRouter, Body, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import func, text
from sqlalchemy.orm import Session

from app.core.database import get_db, get_db_context
from app.core.dependencies import get_current_user

from services.data_agent.factory import create_engine, create_engine_with_skills
from services.data_agent.models import (
    AgentConversation,
    AgentConversationMessage,
    BiAgentRun,
    BiAgentStep,
    BiAgentFeedback,
)
from services.data_agent.runner import run_agent
from services.data_agent.session import SessionManager, AgentSession
from services.data_agent.tool_base import ToolContext, ToolRegistry
from services.data_agent.context import build_session_context
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
from services.data_agent.intent.keyword_match import is_direct_query

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


class ConversationItem(BaseModel):
    id: str
    title: Optional[str]
    connection_id: Optional[int]
    status: str
    message_count: int = 0
    created_at: str
    updated_at: str


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


# ─── Fast-path 可观测性事件 ───────────────────────────────────────────
_FAST_ATTEMPTED = "FAST_ATTEMPTED"   # 快通尝试
_FAST_FAILED = "FAST_FAILED"          # 快通失败（fallback 到 ReAct）
_FAST_SUCCESS = "FAST_SUCCESS"        # 快通成功
_SLOW_FALLBACK = "SLOW_FALLBACK"     # 跳过快通或失败后走 ReAct

# 仅对可恢复错误触发 fallback（不走快通的场景不算错）
# 不包括：NLQ_009/010/011（认证/权限/限流），这些走快通反而会漏安全问题
_FAST_RECOVERABLE_ERRORS = frozenset([
    "NLQ_006",   # VizQL 执行失败
    "NLQ_007",   # 查询超时
    "NLQ_008",   # 数据源路由失败
    "MCP_010",   # MCP 连接异常
    "QUERY_001", # 字段不匹配
])


async def try_fast_mcp_stream(
    question: str,
    context: ToolContext,
    current_user: dict,
    req_connection_id: Optional[int],
    db: Session,
    session,  # AgentSession from session_mgr
    session_mgr,  # SessionManager instance
) -> Optional[tuple[Optional[uuid_lib.UUID], AsyncGenerator[str, None]]]:
    """
    快通 MCP 路径：绕过 ReAct 引擎，直接 route → VizQL → MCP 查询 → SSE。

    返回 None 表示不满足快通条件（应 fallback 到 run_agent）。
    返回 (run_id, generator) 时 generator 正常时应 yield 完整 SSE 事件流（含 done / error）。

    可恢复错误（_FAST_RECOVERABLE_ERRORS）不向上抛，直接返回 None 触发 fallback。
    其他错误（认证/权限/限流/未知）向上抛，不触发 fallback。
    """
    from services.llm.nlq_service import route_datasource, get_datasource_fields_cached
    from services.llm.query_executor import execute_query, QueryExecutorError
    from services.tableau.mcp_client import TableauMCPError

    logger.info("[FAST_ATTEMPTED] question=%s, trace=%s", question[:80], context.trace_id)

    # 1. 数据源路由（已有 Redis 缓存，<10ms）
    try:
        ds_info = route_datasource(question, connection_id=req_connection_id)
    except Exception as e:
        logger.warning("[FAST_FAILED] route_datasource error=%s, trace=%s", e, context.trace_id)
        # 路由异常走 ReAct，不算快通失败
        return None

    if not ds_info:
        logger.info("[SLOW_FALLBACK] route_datasource returned None, trace=%s", context.trace_id)
        return None

    datasource_luid = ds_info.get("luid")
    datasource_name = ds_info.get("name")
    asset_id = ds_info.get("asset_id")

    if not datasource_luid:
        logger.info("[SLOW_FALLBACK] no datasource_luid, trace=%s", context.trace_id)
        return None

    # 2. 获取字段列表（Redis 缓存）
    field_captions: List[str] = []
    try:
        field_captions = get_datasource_fields_cached(asset_id) if asset_id else []
    except Exception:
        pass

    # 3. 构建直接 VizQL（无 LLM，<1ms）
    from services.data_agent.tools.query_tool import _build_direct_vizql

    vizql_json = _build_direct_vizql(question, field_captions)
    if not vizql_json:
        logger.info("[SLOW_FALLBACK] _build_direct_vizql returned None, trace=%s", context.trace_id)
        return None

    # 4. 通过 execute_query 走 MCP 执行（阻塞，~300-800ms）
    try:
        result = execute_query(
            datasource_luid=datasource_luid,
            vizql_json=vizql_json,
            limit=1000,
            connection_id=req_connection_id,
        )
    except (TableauMCPError, QueryExecutorError) as e:
        code = getattr(e, "code", None) or (getattr(e, "error_code", None) if hasattr(e, "error_code") else None)
        if code in _FAST_RECOVERABLE_ERRORS:
            logger.warning(
                "[FAST_FAILED] recoverable error code=%s message=%s trace=%s",
                code, getattr(e, "message", str(e)), context.trace_id,
            )
            return None
        # 认证/权限/限流错误不 fallback，直接抛给上层
        raise
    except Exception as e:
        logger.warning("[FAST_FAILED] execute_query unexpected error=%s trace=%s", e, context.trace_id)
        return None

    # 5. 格式化结果为 SSE stream
    fields = result.get("fields", [])
    rows = result.get("rows", [])

    logger.info("[FAST_SUCCESS] datasource=%s rows=%d trace=%s", datasource_luid, len(rows), context.trace_id)

    run_id: Optional[uuid_lib.UUID] = None

    async def fast_event_generator() -> AsyncGenerator[str, None]:
        # fast_event_generator accesses run_id from enclosing function scope
        t0 = time.monotonic()
        # 构造回答文本（L2 修复：使用 fields 和 datasource_name）
        answer_text = _build_fast_answer(question, fields, rows, datasource_name or datasource_luid)

        # H4 修复：持久化 assistant 回复到会话历史
        try:
            session_mgr.persist_message(
                session=session,
                role="assistant",
                content=answer_text,
                trace_id=context.trace_id,
                response_type="table",
                response_data={"fields": fields, "rows": rows},
                tools_used=["query"],
                steps_count=1,
            )
        except Exception as e:
            logger.warning("[FAST] persist_message assistant failed: %s", e)

        # H5 修复：写入 BiAgentRun 记录（可观测性 + 反馈可用）
        # 使用 ORM 实际字段：question/status/steps_count/tools_used/response_type/execution_time_ms
        try:
            run_id = uuid_lib.uuid4()
            with get_db_context() as _db:
                run = BiAgentRun(
                    id=run_id,
                    conversation_id=uuid_lib.UUID(context.session_id),
                    user_id=current_user["id"],
                    connection_id=req_connection_id,
                    question=question,
                    status="completed",
                    steps_count=1,
                    tools_used=["query"],
                    response_type="table",
                    execution_time_ms=int((time.monotonic() - t0) * 1000),
                    completed_at=datetime.now(timezone.utc),
                )
                _db.add(run)
                _db.commit()
        except Exception as e:
            logger.warning("[FAST] BiAgentRun write failed: %s", e)
            run_id = None

        # 流式输出 table_data
        table_payload = json.dumps({'type': 'table_data', 'fields': fields, 'rows': rows, 'col_types': []}, ensure_ascii=False)
        yield f"data: {table_payload}\n\n"
        # 流式输出 token
        for char in answer_text:
            yield f"data: {json.dumps({'type': 'token', 'content': char}, ensure_ascii=False)}\n\n"
            await asyncio.sleep(0.01)
        # done（L1 修复：直接使用外层 run_id 变量，不再用 dir() 检测）
        done_payload = json.dumps({
            'type': 'done',
            'answer': answer_text,
            'trace_id': context.trace_id,
            'run_id': str(run_id) if run_id else '',
            'tools_used': ['query'],
            'response_type': 'table',
            'response_data': {'fields': fields, 'rows': rows},
            'steps_count': 1,
            'execution_time_ms': int((time.monotonic() - t0) * 1000),
            'sources_count': 0,
            'top_sources': [],
        }, ensure_ascii=False)
        yield f"data: {done_payload}\n\n"
        # 可观测性日志（log_nlq_query）
        log_nlq_query(
            user_id=current_user.get("id"),
            question=question,
            response_type="table",
            execution_time_ms=int((time.monotonic() - t0) * 1000),
            error_code=None,
        )

    return (run_id, fast_event_generator())


def _build_fast_answer(question: str, fields: List, rows: List, datasource_name: str) -> str:
    """根据查询结果生成自然语言回答。"""
    if not rows:
        return f"没有找到符合「{question}」的数据。"
    row_count = len(rows)
    if row_count == 1:
        vals = ", ".join(str(r) for r in rows[0] if str(r) not in ('', 'None'))
        return f"「{question}」的结果是：{vals}。"
    # 前3行预览
    preview = "; ".join(
        ", ".join(str(v) for v in row[:3] if str(v) not in ('', 'None'))
        for row in rows[:3]
    )
    more = f"（共 {row_count} 条）" if row_count > 3 else ""
    return f"「{question}」共有 {row_count} 条结果，前几名为：{preview}{more}。"


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

        # ── 快通 MCP 路径：意图命中的简单问数直连 VizQL ──────────────────────
        if is_direct_query(req.question):
            logger.info("[FAST_ATTEMPTED] question=%s, trace=%s", req.question[:80], trace_id)
            run_id: Optional[uuid_lib.UUID] = None
            try:
                fast_result = await try_fast_mcp_stream(
                    question=req.question,
                    context=context,
                    current_user=current_user,
                    req_connection_id=effective_connection_id,
                    db=db,
                    session=session,
                    session_mgr=session_mgr,
                )
                if fast_result is not None:
                    run_id, fast_gen = fast_result
                    # 先发 metadata（含 conversation_id），run_id 等 BiAgentRun commit 后再补
                    yield f"data: {json.dumps({'type': 'metadata', 'conversation_id': conversation_id_str, 'run_id': str(run_id) if run_id else ''}, ensure_ascii=False)}\n\n"
                    async for chunk in fast_gen:
                        yield chunk
                    return
            except Exception:
                # H2 修复：外层仅捕获已知的、可恢复的错误；
                # 认证/权限/限流（NLQ_009/010/011）不应 fallback 到 ReAct，
                # 而是让其继续到标准 SSE 错误处理（event_generator 外层）。
                logger.warning("[FAST_FALLBACK] 快通异常 fallback 到 run_agent, trace=%s", trace_id)

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
        ):
            if event.type == "metadata":
                yield f"data: {json.dumps({'type': 'metadata', 'conversation_id': event.content['conversation_id'], 'run_id': event.content['run_id']}, ensure_ascii=False)}\n\n"

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
                yield f"data: {json.dumps({'type': 'table_data', 'fields': event.content.get('fields', []), 'rows': event.content.get('rows', []), 'col_types': event.content.get('col_types', [])}, ensure_ascii=False)}\n\n"

            elif event.type == "chart_data":
                yield f"data: {json.dumps({'type': 'chart_data', 'chart_type': event.content.get('chart_type', 'bar'), 'x_field': event.content.get('x_field'), 'y_fields': event.content.get('y_fields', []), 'series_field': event.content.get('series_field'), 'data': event.content.get('data', [])}, ensure_ascii=False)}\n\n"

            elif event.type == "done":
                # Emit per-char tokens before the done event
                answer_text = event.content.get("answer", "")
                for char in answer_text:
                    yield f"data: {json.dumps({'type': 'token', 'content': char}, ensure_ascii=False)}\n\n"
                    await asyncio.sleep(0.01)
                yield f"data: {json.dumps({'type': 'done', 'answer': answer_text, 'trace_id': event.content.get('trace_id', ''), 'run_id': event.content.get('run_id', ''), 'tools_used': event.content.get('tools_used', []), 'response_type': event.content.get('response_type', 'text'), 'response_data': event.content.get('response_data'), 'steps_count': event.content.get('steps_count', 0), 'execution_time_ms': event.content.get('execution_time_ms', 0), 'sources_count': event.content.get('sources_count', 0), 'top_sources': event.content.get('top_sources', [])}, ensure_ascii=False)}\n\n"
                log_nlq_query(
                    user_id=current_user.get("id"),
                    question=req.question,
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
                if error_content.get("user_hint"):
                    payload["user_hint"] = error_content["user_hint"]
                yield f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"
                log_nlq_query(
                    user_id=current_user.get("id"),
                    question=req.question,
                    execution_time_ms=int((time.monotonic() - _t0) * 1000),
                    error_code=err_code,
                )

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# ============================================================================
# 会话管理
# ============================================================================


@router.get("/conversations")
def list_conversations(
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """列出当前用户的会话（按 updated_at DESC）"""
    _require_agent_role(current_user.get("role", "user"))
    session_mgr = SessionManager(db)
    convs = session_mgr.get_user_conversations(
        user_id=current_user["id"],
        status="active",
        limit=20,
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

    msgs = session_mgr.get_conversation_messages(conv_uuid, user_id=current_user["id"], limit=50, offset=0)
    return [
        MessageItem(
            id=m.id,
            role=m.role,
            content=m.content,
            response_type=m.response_type,
            response_data=m.response_data,
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

    转发到 feedback service（/api/feedback）写入 message_feedback 表。
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

        # 从 run 记录获取 conversation_id
        resolved_conversation_id = str(run.conversation_id) if run.conversation_id else conversation_id
        if conversation_id is None:
            conversation_id = resolved_conversation_id
    else:
        raise HTTPException(
            status_code=400,
            detail={"error_code": "AGENT_007", "message": "必须提供 run_id 或 conversation_id"},
        )

    # 转发到 feedback service
    from app.api.feedback import submit_feedback as forward_feedback
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
    conversation_id: str,
    message_index: int,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """GET /api/agent/feedback — 查询当前用户对指定消息的已有评分"""
    _require_agent_role(current_user.get("role", "user"))
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

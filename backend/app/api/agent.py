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
import uuid as uuid_lib
from typing import AsyncGenerator, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.dependencies import get_current_user

from services.data_agent.factory import create_engine
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
from services.datasources.models import DataSource

# Spec 36 §15: Agent 驱动首页相关导入
from services.agent.dual_write import (
    HomepageAgentMode,
    execute_dual_write,
    get_homepage_agent_mode,
    check_and_trigger_auto_rollback,
)
from services.data_agent.intent import IntentRecognizer

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/agent", tags=["Data Agent"])


# ============================================================================
# Schema
# ============================================================================


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


class MessageItem(BaseModel):
    id: int
    role: str
    content: str
    response_type: Optional[str]
    tools_used: Optional[List[str]]
    trace_id: Optional[str]
    steps_count: Optional[int]
    execution_time_ms: Optional[int]
    created_at: str


class FeedbackRequest(BaseModel):
    run_id: str = Field(..., description="Agent 运行 ID")
    rating: str = Field(..., pattern="^(up|down)$", description="up 或 down")
    comment: Optional[str] = Field(None, max_length=1000, description="可选文字反馈")


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


def _validate_connection_access(
    connection_id: Optional[int],
    current_user: dict,
    db: Session,
) -> None:
    """校验用户对数据源的访问权限。

    - connection_id 为 None 时跳过（下游工具自行处理）
    - 数据源不存在或已停用 → 404 AGENT_004
    - admin / data_admin 可访问任意活跃数据源
    - analyst 仅可访问 owner_id == 自身 ID 的数据源
    - 其他情况 → 403 AGENT_005
    """
    if connection_id is None:
        return

    ds = db.query(DataSource).filter(
        DataSource.id == connection_id,
        DataSource.is_active == True,  # noqa: E712
    ).first()

    if ds is None:
        raise HTTPException(
            status_code=404,
            detail={"error_code": "AGENT_004", "message": "数据源不存在或已停用"},
        )

    role = current_user.get("role", "user")
    if role in ("admin", "data_admin"):
        return

    if ds.owner_id != current_user["id"]:
        raise HTTPException(
            status_code=403,
            detail={"error_code": "AGENT_005", "message": "无权限访问该数据源"},
        )


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
    _validate_connection_access(req.connection_id, current_user, db)

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
    else:
        session = session_mgr.create_session(
            user_id=current_user["id"],
            connection_id=req.connection_id,
        )

    conversation_id_str = str(session.conversation_id)

    # 构建 ToolContext
    context = ToolContext(
        session_id=conversation_id_str,
        user_id=current_user["id"],
        connection_id=req.connection_id,
        trace_id=trace_id,
        tenant_id=str(current_user["tenant_id"]) if current_user.get("tenant_id") else None,
    )

    # 构建丰富的会话上下文（工具可通过此获取用户信息、数据源列表等）
    session_context = build_session_context(
        session_id=conversation_id_str,
        trace_id=trace_id,
        current_user=current_user,
        connection_id=req.connection_id,
        db=db,
    )

    # 构建引擎
    engine, _registry = create_engine()

    # 保存用户消息
    session_mgr.persist_message(
        session=session,
        role="user",
        content=req.question,
        trace_id=trace_id,
    )

    async def event_generator() -> AsyncGenerator[str, None]:
        async for event in run_agent(
            engine=engine,
            context=context,
            session_mgr=session_mgr,
            session=session,
            question=req.question,
            trace_id=trace_id,
            current_user=current_user,
            db=db,
            connection_id=req.connection_id,
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

            elif event.type == "done":
                # Emit per-char tokens before the done event
                answer_text = event.content.get("answer", "")
                for char in answer_text:
                    yield f"data: {json.dumps({'type': 'token', 'content': char}, ensure_ascii=False)}\n\n"
                    await asyncio.sleep(0.01)
                yield f"data: {json.dumps({'type': 'done', 'answer': answer_text, 'trace_id': event.content.get('trace_id', ''), 'run_id': event.content.get('run_id', ''), 'tools_used': event.content.get('tools_used', []), 'response_type': event.content.get('response_type', 'text'), 'response_data': event.content.get('response_data'), 'steps_count': event.content.get('steps_count', 0), 'execution_time_ms': event.content.get('execution_time_ms', 0)}, ensure_ascii=False)}\n\n"

            elif event.type == "error":
                error_content = event.content if isinstance(event.content, dict) else {"message": str(event.content)}
                err_code = error_content.get("error_code", "AGENT_003")
                yield f"data: {json.dumps({'type': 'error', 'error_code': err_code, 'message': error_content.get('message', '未知错误')}, ensure_ascii=False)}\n\n"

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
    return [
        ConversationItem(
            id=str(c.id),
            title=c.title,
            connection_id=c.connection_id,
            status=c.status,
            message_count=message_counts.get(str(c.id), 0),
            created_at=c.created_at.isoformat() if c.created_at else "",
            updated_at=c.updated_at.isoformat() if c.updated_at else "",
        )
        for c in convs
    ]


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
            tools_used=m.tools_used,
            trace_id=m.trace_id,
            steps_count=m.steps_count,
            execution_time_ms=m.execution_time_ms,
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

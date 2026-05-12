"""Help Agent API — Spec 45 P0.

This module intentionally queries only ``help_agent_*`` tables. Help Agent
conversations must not reuse Data Agent conversation tables.
"""

import json
import logging
import inspect
import uuid
from typing import Any, AsyncGenerator, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import text
from sqlalchemy.exc import ProgrammingError
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.dependencies import get_current_user

try:  # Task A/B may land this service after the API task.
    from services.help_agent.service import HelpAgentService  # type: ignore
except Exception:  # pragma: no cover - exercised by compatibility tests
    HelpAgentService = None  # type: ignore


logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/help-agent", tags=["Help Agent"])

ENTRY_POINTS = {"global_drawer", "inline_panel", "route_page"}
ADMIN_ROLES = {"admin", "data_admin"}


class HelpAgentStreamRequest(BaseModel):
    question: str = Field("", max_length=4000)
    conversation_id: Optional[str] = None
    entry_point: str = "global_drawer"
    page_context: Optional[Dict[str, Any]] = None

    @field_validator("entry_point")
    @classmethod
    def validate_entry_point(cls, value: str) -> str:
        if value not in ENTRY_POINTS:
            raise ValueError("entry_point must be global_drawer, inline_panel, or route_page")
        return value


class HelpConversationItem(BaseModel):
    id: str
    title: Optional[str] = None
    status: str
    last_page_path: Optional[str] = None
    message_count: int = 0
    created_at: str
    updated_at: str


class HelpMessageItem(BaseModel):
    id: int
    role: str
    content: str
    response_type: Optional[str] = None
    response_data: Optional[Any] = None
    tools_used: Optional[list[str]] = None
    trace_id: Optional[str] = None
    steps_count: Optional[int] = None
    execution_time_ms: Optional[int] = None
    sources_count: Optional[int] = None
    top_sources: Optional[Any] = None
    created_at: str


def _is_admin(user: dict) -> bool:
    return user.get("role") in ADMIN_ROLES


def _sse_data(payload: dict) -> str:
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"


def _sse_error(
    error_code: str,
    message: str,
    user_hint: Optional[str] = None,
) -> str:
    payload = {
        "type": "error",
        "error_code": error_code,
        "message": message,
    }
    if user_hint:
        payload["user_hint"] = user_hint
    return _sse_data(payload)


def _normalize_sse_chunk(chunk: Any) -> str:
    """Accept service dict events or already-framed SSE strings."""
    if isinstance(chunk, bytes):
        chunk = chunk.decode("utf-8")
    if isinstance(chunk, str):
        return chunk if chunk.startswith(("data:", "event:", ":")) else _sse_data({"type": "token", "content": chunk})
    if isinstance(chunk, dict):
        return _sse_data(chunk)
    return _sse_data({"type": "token", "content": str(chunk)})


def _service_accepts_current_user(service: Any) -> bool:
    try:
        signature = inspect.signature(service.stream)
    except (TypeError, ValueError):
        return True
    return "current_user" in signature.parameters


def _map_stream_exception(exc: Exception) -> tuple[str, str, str]:
    error_code = (
        getattr(exc, "error_code", None)
        or getattr(exc, "code", None)
        or ("HLP_005" if exc.__class__.__name__.lower().find("llm") >= 0 else "HLP_004")
    )
    if error_code not in {"HLP_001", "HLP_002", "HLP_003", "HLP_004", "HLP_005", "HLP_006"}:
        error_code = "HLP_004"

    default_messages = {
        "HLP_003": "没有权限查看该诊断对象。",
        "HLP_004": "诊断工具执行失败，请稍后重试。",
        "HLP_005": "LLM 服务暂时不可用，请稍后重试。",
    }
    message = getattr(exc, "message", None) or default_messages.get(error_code) or str(exc) or "Help Agent 执行失败"
    user_hint = getattr(exc, "user_hint", None) or (
        "请确认对象是否属于你的会话，或联系管理员查看。"
        if error_code == "HLP_003"
        else "这不会影响其他页面功能，你可以稍后重新发起诊断。"
    )
    return str(error_code), str(message), str(user_hint)


def _row_iso(row: Any, key: str) -> str:
    value = row._mapping.get(key)
    return value.isoformat() if hasattr(value, "isoformat") else (str(value) if value is not None else "")


def _parse_uuid_or_400(value: str) -> uuid.UUID:
    try:
        return uuid.UUID(value)
    except ValueError:
        raise HTTPException(status_code=400, detail={"error_code": "HLP_001", "message": "无效的会话 ID"})


def _get_conversation_owner(db: Session, conversation_id: uuid.UUID) -> Optional[int]:
    row = db.execute(
        text("SELECT user_id FROM help_agent_conversations WHERE id = :id AND status != 'archived'"),
        {"id": str(conversation_id)},
    ).first()
    return int(row._mapping["user_id"]) if row else None


def _ensure_conversation_access(db: Session, conversation_id: uuid.UUID, user: dict) -> None:
    owner_id = _get_conversation_owner(db, conversation_id)
    if owner_id is None:
        raise HTTPException(status_code=404, detail={"error_code": "HLP_002", "message": "会话不存在"})
    if owner_id != int(user["id"]) and not _is_admin(user):
        raise HTTPException(status_code=403, detail={"error_code": "HLP_003", "message": "无权限访问该会话"})


@router.post("/stream")
async def stream_help_agent(
    req: HelpAgentStreamRequest,
    current_user: dict = Depends(get_current_user),
):
    """Help Agent SSE endpoint.

    No request-scoped DB dependency is held here; the service must open short
    database scopes around persistence/tool reads.
    """
    if not req.question.strip() and req.entry_point != "inline_panel":
        raise HTTPException(status_code=400, detail={"error_code": "HLP_001", "message": "question 不能为空"})
    if req.conversation_id:
        _parse_uuid_or_400(req.conversation_id)

    request_payload = req.model_dump()
    user_payload = dict(current_user)

    async def event_generator() -> AsyncGenerator[str, None]:
        if HelpAgentService is None:
            # TODO(Task A/B): remove this compatibility branch once
            # services.help_agent.service.HelpAgentService is always present.
            yield _sse_error(
                "HLP_005",
                "Help Agent 服务尚未完成初始化。",
                "请稍后重试；该错误不会影响其他页面功能。",
            )
            return

        try:
            service = HelpAgentService()  # type: ignore[operator]
            stream = (
                service.stream(request_payload, current_user=user_payload)
                if _service_accepts_current_user(service)
                else service.stream(request_payload, user_payload)
            )
            async for chunk in stream:
                yield _normalize_sse_chunk(chunk)
        except Exception as exc:
            logger.exception("Help Agent stream failed: %s", exc)
            error_code, message, user_hint = _map_stream_exception(exc)
            yield _sse_error(error_code, message, user_hint)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.get("/conversations", response_model=list[HelpConversationItem])
def list_help_conversations(
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """List current user's active Help Agent conversations."""
    try:
        rows = db.execute(
            text(
                """
                SELECT
                    c.id::text AS id,
                    c.title,
                    c.status,
                    c.last_page_path,
                    c.created_at,
                    c.updated_at,
                    COUNT(m.id)::int AS message_count
                FROM help_agent_conversations c
                LEFT JOIN help_agent_messages m ON m.conversation_id = c.id
                WHERE c.user_id = :user_id AND c.status = 'active'
                GROUP BY c.id, c.title, c.status, c.last_page_path, c.created_at, c.updated_at
                ORDER BY c.updated_at DESC
                LIMIT 50
                """
            ),
            {"user_id": int(current_user["id"])},
        ).all()
    except ProgrammingError as exc:
        logger.warning("Help Agent tables are not available yet: %s", exc)
        db.rollback()
        return []

    return [
        HelpConversationItem(
            id=row._mapping["id"],
            title=row._mapping["title"],
            status=row._mapping["status"],
            last_page_path=row._mapping["last_page_path"],
            message_count=row._mapping["message_count"],
            created_at=_row_iso(row, "created_at"),
            updated_at=_row_iso(row, "updated_at"),
        )
        for row in rows
    ]


@router.get("/conversations/{conversation_id}/messages", response_model=list[HelpMessageItem])
def get_help_conversation_messages(
    conversation_id: str,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    conv_uuid = _parse_uuid_or_400(conversation_id)
    _ensure_conversation_access(db, conv_uuid, current_user)

    rows = db.execute(
        text(
            """
            SELECT
                id,
                role,
                content,
                response_type,
                response_data,
                tools_used,
                trace_id::text AS trace_id,
                steps_count,
                execution_time_ms,
                sources_count,
                top_sources,
                created_at
            FROM help_agent_messages
            WHERE conversation_id = :conversation_id
            ORDER BY created_at ASC, id ASC
            LIMIT 200
            """
        ),
        {"conversation_id": str(conv_uuid)},
    ).all()

    return [
        HelpMessageItem(
            id=row._mapping["id"],
            role=row._mapping["role"],
            content=row._mapping["content"],
            response_type=row._mapping["response_type"],
            response_data=row._mapping["response_data"],
            tools_used=row._mapping["tools_used"],
            trace_id=row._mapping["trace_id"],
            steps_count=row._mapping["steps_count"],
            execution_time_ms=row._mapping["execution_time_ms"],
            sources_count=row._mapping["sources_count"],
            top_sources=row._mapping["top_sources"],
            created_at=_row_iso(row, "created_at"),
        )
        for row in rows
    ]


@router.delete("/conversations/{conversation_id}")
def delete_help_conversation(
    conversation_id: str,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    conv_uuid = _parse_uuid_or_400(conversation_id)
    _ensure_conversation_access(db, conv_uuid, current_user)
    db.execute(
        text(
            """
            UPDATE help_agent_conversations
            SET status = 'archived', updated_at = NOW()
            WHERE id = :conversation_id
            """
        ),
        {"conversation_id": str(conv_uuid)},
    )
    db.commit()
    return {"status": "archived", "conversation_id": str(conv_uuid)}

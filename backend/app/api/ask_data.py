"""
POST /api/ask-data — SSE 智能问数端点
POST /api/ask-data/feedback — 问数结果点赞/踩
SSE 协议严格遵循 frontend/src/api/ask_data_contract.ts

Phase 2 改造：
- 直接调用 Data Agent ReActEngine（通过 factory + runner，无 httpx 自环回）
- Agent 事件映射至 ask_data SSE 格式
- fallback 至 POST /api/search/query（Phase 1 逻辑）

event 格式（text/event-stream）：
  data: {"type":"metadata","sources_count":N,"top_sources":[...]}\n\n
  data: {"type":"token","content":"..."}\n\n
  data: {"type":"done","answer":"...","trace_id":"..."}\n\n
  data: {"type":"error","code":"MCP_003","message":"..."}\n\n

MCP 错误码依照 Spec 01 §5.10 映射（NLQ_006/007/009 → MCP_003/004）。

性能优化：per-user intent 结果缓存 5 分钟，规避重复 classify_meta_intent 开销。
"""
import asyncio
import hashlib
import json
import logging
import os
import uuid
from datetime import datetime, timezone
from typing import AsyncGenerator, Optional

import httpx
from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.dependencies import get_current_user

try:
    from services.common.redis_cache import RedisCache as _RedisCache
except ImportError:
    _RedisCache = None  # type: ignore[assignment]

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/ask-data", tags=["智能问数"])

_INTERNAL_BASE = os.environ.get("INTERNAL_API_BASE", "http://localhost:8000")

# NLQ error code → (Spec 01 error_code, 面向用户中文消息)
_MCP_CODE_MAP: dict = {
    "NLQ_006": ("MCP_003", "MCP 服务不可用，请检查 Tableau MCP Server 是否运行"),
    "NLQ_007": ("MCP_004", "MCP 查询超时（30s），数据量过大或服务响应慢"),
    "NLQ_009": ("MCP_003", "MCP 连接无效，请确认 Tableau 连接配置正确"),
}

# Intent cache TTL: 5 minutes
_INTENT_CACHE_TTL = 300
_INTENT_NONE_SENTINEL = "__none__"


class AskDataRequest(BaseModel):
    question: str = Field(..., min_length=1)
    connection_id: Optional[int] = None
    conversation_id: Optional[str] = None


class FeedbackRequest(BaseModel):
    trace_id: str
    rating: str
    question: Optional[str] = None

    @field_validator("rating")
    @classmethod
    def validate_rating(cls, v: str) -> str:
        if v not in ("up", "down"):
            raise ValueError("rating 必须为 'up' 或 'down'")
        return v


class _NLQError(Exception):
    def __init__(self, code: str, message: str):
        self.code = code
        self.message = message


def _sse(event: dict) -> str:
    return f"data: {json.dumps(event, ensure_ascii=False)}\n\n"


async def _stream_via_agent_direct(
    question: str,
    connection_id: Optional[int],
    conversation_id: Optional[str],
    current_user: dict,
    db: Session,
) -> AsyncGenerator[str, None]:
    """
    Call the Data Agent engine in-process and yield ask_data-format SSE strings.
    """
    import uuid as uuid_lib
    from services.data_agent.factory import create_engine
    from services.data_agent.runner import run_agent
    from services.data_agent.session import SessionManager
    from services.data_agent.tool_base import ToolContext

    session_mgr = SessionManager(db)
    trace_id = f"t-{uuid_lib.uuid4().hex[:8]}"

    # 创建或续接会话
    if conversation_id:
        try:
            conv_uuid = uuid_lib.UUID(conversation_id)
        except ValueError:
            yield _sse({"type": "error", "code": "AGENT_007", "message": "无效的会话 ID"})
            return

        session = session_mgr.resume_session(conv_uuid, current_user["id"])
        if not session:
            yield _sse({"type": "error", "code": "AGENT_004", "message": "会话不存在"})
            return
    else:
        session = session_mgr.create_session(
            user_id=current_user["id"],
            connection_id=connection_id,
        )

    context = ToolContext(
        session_id=str(session.conversation_id),
        user_id=current_user["id"],
        connection_id=connection_id,
        trace_id=trace_id,
    )

    engine, _registry = create_engine()

    session_mgr.persist_message(
        session=session,
        role="user",
        content=question,
        trace_id=trace_id,
    )

    async for event in run_agent(
        engine=engine,
        context=context,
        session_mgr=session_mgr,
        session=session,
        question=question,
        trace_id=trace_id,
        current_user=current_user,
        db=db,
        connection_id=connection_id,
    ):
        if event.type == "metadata":
            content = event.content if isinstance(event.content, dict) else {}
            yield _sse({
                "type": "metadata",
                "sources_count": 0,
                "top_sources": [],
                "conversation_id": content.get("conversation_id", ""),
            })
        elif event.type == "done":
            content = event.content if isinstance(event.content, dict) else {}
            # Emit per-char tokens before the done event
            answer = content.get("answer", "")
            for char in answer:
                yield _sse({"type": "token", "content": char})
                await asyncio.sleep(0.01)
            yield _sse({
                "type": "done",
                "answer": answer,
                "trace_id": content.get("trace_id", ""),
            })
        elif event.type == "error":
            error_content = event.content if isinstance(event.content, dict) else {"message": str(event.content)}
            error_code = error_content.get("error_code", "AGENT_003")
            if error_code.startswith("AGENT_"):
                code = error_code
            else:
                code = "SYS_001"
            yield _sse({
                "type": "error",
                "code": code,
                "message": error_content.get("message", str(error_content)),
            })
        # thinking, tool_call, tool_result → skip


def _intent_cache_key(user_id: int, question: str) -> str:
    q_hash = hashlib.md5(question.lower().encode()).hexdigest()[:16]
    return f"nlq:intent:{user_id}:{q_hash}"


def _get_cached_intent(user_id: int, question: str) -> Optional[str]:
    """Return cached intent or None; returns None on cache miss or Redis unavailable."""
    if _RedisCache is None:
        return None
    try:
        raw = _RedisCache.get(_intent_cache_key(user_id, question))
        if raw is None:
            return None
        return None if raw == _INTENT_NONE_SENTINEL else raw
    except Exception:
        return None


def _set_cached_intent(user_id: int, question: str, intent: Optional[str]) -> None:
    if _RedisCache is None:
        return
    try:
        value = _INTENT_NONE_SENTINEL if intent is None else intent
        _RedisCache.set(_intent_cache_key(user_id, question), value, ttl=_INTENT_CACHE_TTL)
    except Exception:
        pass


def _extract_answer_and_trace(data: dict) -> tuple:
    """从 search/query 响应中提取 (answer_text, trace_id)"""
    trace_id = data.get("trace_id", "")
    rt = data.get("response_type", "text")

    if rt == "number":
        label = data.get("label", "")
        value = data.get("formatted") or str(data.get("value", ""))
        unit = data.get("unit", "")
        answer = f"{label}：{value}{unit}".strip("：") if label else f"{value}{unit}"
        extra = data.get("content", "")
        if extra and extra != answer:
            answer = extra
    elif rt in ("table", "auto"):
        rows = data.get("rows") or []
        cols = data.get("columns") or []
        if cols and rows:
            header = "  ".join(c.get("label", c.get("name", "?")) for c in cols)
            lines = [header]
            for row in rows[:20]:
                lines.append("  ".join(str(v) for v in row))
            if len(rows) > 20:
                lines.append(f"… （共 {len(rows)} 行）")
            answer = "\n".join(lines)
        else:
            answer = data.get("content") or "查询结果为空。"
    else:
        answer = (
            data.get("content")
            or data.get("answer")
            or data.get("message")
            or "（无结果）"
        )

    return str(answer).strip() or "（无结果）", trace_id


def _extract_metadata_event(data: dict) -> Optional[dict]:
    """从 search/query 响应中提取数据源 metadata，构造 type:metadata event。"""
    sources = data.get("sources") or data.get("datasources") or []
    if not sources and data.get("intent", "").startswith("meta_datasource"):
        # META 路径：从 content 无法提取结构化 sources，跳过
        return None
    if not sources:
        return None
    top_sources = [
        s.get("name") or s.get("label") or str(s)
        for s in sources[:5]
        if isinstance(s, dict)
    ]
    return {
        "type": "metadata",
        "sources_count": len(sources),
        "top_sources": top_sources,
    }


async def _call_search(
    question: str,
    connection_id: Optional[int],
    conversation_id: Optional[str],
    authorization: Optional[str],
    cookie: Optional[str],
    trace_id: str,
    user_id: Optional[int] = None,
) -> dict:
    """内部转发至 POST /api/search/query，保留原始鉴权上下文和 trace 链路。"""
    headers: dict = {
        "Content-Type": "application/json",
        "X-Trace-ID": trace_id,
    }
    if authorization:
        headers["Authorization"] = authorization
    if cookie:
        headers["Cookie"] = cookie

    body: dict = {"question": question}
    if connection_id is not None:
        body["connection_id"] = connection_id
    if conversation_id:
        body["conversation_id"] = conversation_id

    # Pass cached intent to skip redundant classification in search pipeline
    if user_id is not None:
        cached = _get_cached_intent(user_id, question)
        # cached==None could be cache-miss OR genuine None; only inject on positive hit
        # We store sentinel so we can distinguish: no further action needed here —
        # the cache is consumed by the search service if it reads X-Intent-Hint header.
        # For now, we use the cached value to short-circuit locally via hint header.
        if cached is not None:
            headers["X-Intent-Hint"] = cached

    async with httpx.AsyncClient(timeout=65.0) as client:
        resp = await client.post(
            f"{_INTERNAL_BASE}/api/search/query",
            json=body,
            headers=headers,
        )

    data = resp.json()
    if resp.status_code >= 400:
        code = data.get("code") or data.get("error_code") or "SYS_001"
        message = data.get("message", "查询失败")
        raise _NLQError(code=code, message=message)

    # Cache the intent result for future requests
    if user_id is not None:
        intent = data.get("intent")
        _set_cached_intent(user_id, question, intent)

    return data


async def _generate_events(
    question: str,
    connection_id: Optional[int],
    conversation_id: Optional[str],
    authorization: Optional[str],
    cookie: Optional[str],
    user_id: Optional[int] = None,
    current_user: Optional[dict] = None,
    db: Optional[Session] = None,
) -> AsyncGenerator[str, None]:
    trace_id = str(uuid.uuid4())

    # Phase 2: 优先走 Agent 直连（需要 current_user 和 db）
    agent_success = False
    if current_user is not None and db is not None:
        try:
            async for event in _stream_via_agent_direct(
                question, connection_id, conversation_id,
                current_user, db,
            ):
                yield event
                agent_success = True
            if agent_success:
                return  # Agent stream succeeded
        except Exception as agent_exc:
            logger.debug("Agent direct call failed for ask-data (%s), falling back to search", agent_exc)

    # Phase 1 fallback: 走 search/query + word-chunk pseudo-stream
    try:
        data = await _call_search(
            question, connection_id, conversation_id,
            authorization, cookie, trace_id, user_id,
        )
        answer, trace_id = _extract_answer_and_trace(data)

        # Emit metadata event before tokens if datasource info is available
        meta_event = _extract_metadata_event(data)
        if meta_event:
            yield _sse(meta_event)

        # word-chunk 伪流式：3词/chunk，40ms间隔 ≈ 25 chunks/s
        words = answer.split(" ")
        chunk_size = 3
        for i in range(0, len(words), chunk_size):
            chunk = " ".join(words[i : i + chunk_size])
            if i + chunk_size < len(words):
                chunk += " "
            yield _sse({"type": "token", "content": chunk})
            await asyncio.sleep(0.04)

        yield _sse({"type": "done", "answer": answer, "trace_id": trace_id})

    except _NLQError as e:
        mapped_code, mapped_msg = _MCP_CODE_MAP.get(e.code, (e.code, e.message))
        yield _sse({"type": "error", "code": mapped_code, "message": mapped_msg})

    except asyncio.CancelledError:
        logger.debug("ask-data SSE cancelled (question=%r)", question[:50])
        return

    except Exception as exc:
        logger.warning("ask-data stream error: %s", exc, exc_info=True)
        yield _sse({"type": "error", "code": "SYS_001", "message": "服务器内部错误，请稍后重试"})


@router.post("")
async def ask_data(
    body: AskDataRequest,
    request: Request,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    POST /api/ask-data — 智能问数 SSE 流（Spec 22 Ask Data Architecture）

    鉴权要求：analyst+ 角色（与 /api/search/query 对齐）
    """
    return StreamingResponse(
        _generate_events(
            question=body.question,
            connection_id=body.connection_id,
            conversation_id=body.conversation_id,
            authorization=request.headers.get("Authorization"),
            cookie=request.headers.get("Cookie"),
            user_id=current_user.get("id"),
            current_user=current_user,
            db=db,
        ),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


@router.post("/feedback")
async def ask_data_feedback(
    body: FeedbackRequest,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """
    POST /api/ask-data/feedback — 问数结果点赞/踩

    接收 trace_id + rating('up'|'down')，写入 query_feedback 表。
    user_id 和 username 从 JWT 解析，不接受前端传入。
    """
    user_id = current_user["id"]
    username = current_user.get("username") or ""

    try:
        db.execute(
            text(
                "INSERT INTO query_feedback "
                "(user_id, username, trace_id, rating, question, created_at) "
                "VALUES (:user_id, :username, :trace_id, :rating, :question, :created_at)"
            ),
            {
                "user_id": user_id,
                "username": username,
                "trace_id": body.trace_id,
                "rating": body.rating,
                "question": body.question,
                "created_at": datetime.now(timezone.utc),
            },
        )
        db.commit()
        logger.info("ask-data 反馈 user_id=%s trace_id=%s rating=%s", user_id, body.trace_id, body.rating)
        return {"ok": True}
    except Exception as exc:
        db.rollback()
        logger.error("写入 query_feedback 失败: %s", exc, exc_info=True)
        raise

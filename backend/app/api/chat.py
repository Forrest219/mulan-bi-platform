"""
Streaming SSE chat endpoint — Gap-05 (§8.5 + §11 陷阱6)

Phase 2 改造：
- 直接调用 Data Agent ReActEngine（通过 factory + runner，无 httpx 自环回）
- Agent 事件映射至 chat SSE 格式：{"type":"token","content":"..."} → {"token":"..."}
- fallback 至 POST /api/search/query（Phase 1 逻辑）
"""
import asyncio
import json
import logging
import os
from typing import AsyncGenerator, Optional

import httpx
from fastapi import APIRouter, Cookie, Depends, Header, Query, Request
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.dependencies import get_current_user

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/chat", tags=["chat"])

# 内部 API base URL — still needed for Phase 1 fallback (_resolve_answer)
from app.core.config import get_settings as _get_settings
_INTERNAL_BASE = _get_settings().INTERNAL_API_BASE


async def _stream_via_agent_direct(
    question: str,
    connection_id: Optional[int],
    current_user: dict,
    db: Session,
) -> AsyncGenerator[str, None]:
    """
    Call the Data Agent engine in-process and yield chat-format SSE strings.
    """
    import uuid as uuid_lib
    from services.data_agent.factory import create_engine
    from services.data_agent.runner import run_agent
    from services.data_agent.session import SessionManager
    from services.data_agent.tool_base import ToolContext

    session_mgr = SessionManager(db)
    trace_id = f"t-{uuid_lib.uuid4().hex[:8]}"

    session = session_mgr.create_session(
        user_id=current_user["id"],
        connection_id=connection_id,
    )

    context = ToolContext(
        session_id=str(session.conversation_id),
        user_id=current_user["id"],
        connection_id=connection_id,
        trace_id=trace_id,
        tenant_id=str(current_user["tenant_id"]) if current_user.get("tenant_id") else None,
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
        if event.type == "done":
            # Emit per-char tokens then a done signal
            answer = event.content.get("answer", "")
            for char in answer:
                yield f"data: {json.dumps({'token': char}, ensure_ascii=False)}\n\n"
                await asyncio.sleep(0.01)
            yield f"data: {json.dumps({'done': True}, ensure_ascii=False)}\n\n"
        elif event.type == "error":
            error_content = event.content if isinstance(event.content, dict) else {"message": str(event.content)}
            message = error_content.get("message", str(error_content))
            yield f"data: {json.dumps({'error': message}, ensure_ascii=False)}\n\n"
        # metadata, thinking, tool_call, tool_result → skip (chat format doesn't use them)


async def _resolve_answer(
    question: str,
    connection_id: Optional[int],
    authorization: Optional[str],
    cookie: Optional[str],
) -> str:
    """
    向内部 POST /api/search/query 转发请求，返回纯文本 answer 字符串。
    使用调用方原始 Authorization header 和 Cookie，保证鉴权一致。
    (Phase 1 fallback)
    """
    headers: dict = {"Content-Type": "application/json"}
    if authorization:
        headers["Authorization"] = authorization
    if cookie:
        headers["Cookie"] = cookie

    payload: dict = {"question": question}
    if connection_id is not None:
        payload["connection_id"] = connection_id

    url = f"{_INTERNAL_BASE}/api/search/query"

    async with httpx.AsyncClient(timeout=60.0) as client:
        resp = await client.post(url, json=payload, headers=headers)

    if resp.status_code != 200:
        # 尝试解析错误详情
        try:
            err = resp.json()
            detail = err.get("detail") or err.get("message") or resp.text
            if isinstance(detail, dict):
                detail = detail.get("message", str(detail))
        except Exception:
            detail = resp.text or f"HTTP {resp.status_code}"
        raise RuntimeError(detail)

    data = resp.json()

    # 提取可读文本（兼容 text / number / table 三种 response_type）
    response_type = data.get("response_type") or data.get("type", "text")

    if response_type == "text":
        answer = (
            data.get("answer")
            or data.get("content")
            or data.get("message")
            or str(data)
        )
    elif response_type == "number":
        label = data.get("label", "")
        value = data.get("formatted") or str(data.get("value", ""))
        unit = data.get("unit", "")
        answer = f"{label}：{value}{unit}".strip("：") if label else f"{value}{unit}"
        # 补充 content 文本（如有）
        content_text = data.get("content", "")
        if content_text and content_text != answer:
            answer = content_text
    elif response_type in ("table", "auto"):
        # table：提示用户查看下方表格
        rows = data.get("rows") or []
        cols = data.get("columns") or []
        if cols and rows:
            answer = f"查询返回 {len(rows)} 行 × {len(cols)} 列数据。"
        else:
            answer = data.get("content") or data.get("answer") or str(data)
    else:
        answer = (
            data.get("content")
            or data.get("answer")
            or data.get("message")
            or str(data)
        )

    return str(answer) if answer else "（无结果）"


async def _stream_llm_response(
    question: str,
    connection_id: Optional[int],
    authorization: Optional[str],
    cookie: Optional[str],
    current_user: Optional[dict] = None,
    db: Optional[Session] = None,
) -> AsyncGenerator[str, None]:
    """
    Generator：先尝试 Agent 流，失败则 fallback 至 Phase 1 word-chunk 逻辑。

    chunk_size=3 words / 50ms → ~20 chunks/s。
    前端通过 requestAnimationFrame (~16ms) 批量 flush，约 1 帧消费 1 chunk。
    """
    # Phase 2: 优先走 Agent 直连（需要 current_user 和 db）
    if current_user is not None and db is not None:
        try:
            async for event in _stream_via_agent_direct(question, connection_id, current_user, db):
                yield event
            return  # Agent stream succeeded
        except Exception as agent_exc:
            logger.debug("Agent direct call failed (%s), falling back to search", agent_exc)

    # Phase 1 fallback: 走 search/query + word-chunk pseudo-stream
    try:
        answer = await _resolve_answer(question, connection_id, authorization, cookie)

        # 按行切分，保留换行符，每行再按词切 chunk
        lines = answer.split("\n")
        chunk_size = 3

        for line_idx, line in enumerate(lines):
            words = line.split(" ") if line.strip() else [""]
            for i in range(0, len(words), chunk_size):
                chunk_words = words[i : i + chunk_size]
                chunk = " ".join(chunk_words)
                # 非行末追加空格；每行结束追加换行
                is_last_chunk = (i + chunk_size >= len(words))
                is_last_line = (line_idx == len(lines) - 1)
                if not is_last_chunk:
                    chunk += " "
                elif not is_last_line:
                    chunk += "\n"
                payload = json.dumps({"token": chunk}, ensure_ascii=False)
                yield f"data: {payload}\n\n"
                await asyncio.sleep(0.05)

        yield f"data: {json.dumps({'done': True})}\n\n"

    except asyncio.CancelledError:
        # 客户端断开连接，正常退出
        logger.debug("SSE stream cancelled by client (question=%r)", question[:50])
        return

    except Exception as exc:
        logger.warning("SSE stream error: %s", exc)
        payload = json.dumps({"error": "服务器内部错误，请稍后重试"}, ensure_ascii=False)
        yield f"data: {payload}\n\n"


@router.post("/stream")
async def chat_stream_post(
    request: Request,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    POST /api/chat/stream — Phase 1b 内部转发到 Data Agent

    兼容现有前端，同时暴露新架构能力。
    内部转发到 /api/agent/stream，使用 httpx 直连（不走 HTTP）。
    """
    body = await request.json()
    question = body.get("q", body.get("question", ""))

    if not question:
        return StreamingResponse(
            iter([f"data: {json.dumps({'error': '问题不能为空'}, ensure_ascii=False)}\n\n"]),
            media_type="text/event-stream",
        )

    return StreamingResponse(
        _stream_via_agent_direct(
            question=question,
            connection_id=body.get("connection_id"),
            current_user=current_user,
            db=db,
        ),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


@router.get("/stream")
async def chat_stream_get(
    request: Request,
    q: str = Query(..., description="用户问题"),
    connection_id: Optional[int] = Query(None, description="连接 ID"),
    authorization: Optional[str] = Header(None, alias="Authorization"),
    cookie: Optional[str] = Header(None, alias="Cookie"),
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    GET /api/chat/stream — Streaming SSE chat endpoint (Gap-05)

    响应格式（text/event-stream）：
      data: {"token": "部分文字 "}\\n\\n   ← 中间 token
      data: {"done": true}\\n\\n           ← 流结束信号
      data: {"error": "..."}\\n\\n         ← 错误信号（不抛 HTTP 500）

    前端通过 fetch + ReadableStream 消费，useRef buffer + rAF batch flush。
    AskBar 状态隔离：streaming content 存在 useStreamingChat hook，不污染 AskBar state。
    """
    return StreamingResponse(
        _stream_llm_response(
            q, connection_id, authorization, cookie,
            current_user=current_user, db=db,
        ),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )

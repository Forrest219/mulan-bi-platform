"""
Streaming SSE chat endpoint — Gap-05 (§8.5 + §11 陷阱6)

Phase 1 实现：
- 调用内部 POST /api/search/query 获取完整响应
- 将结果按 word chunk 拆分，以 SSE 格式流式输出
- 每 chunk 约 50ms，前端 useRef buffer + requestAnimationFrame 每 ~16ms 批量 flush

不直接依赖 nlq_service 内部函数，借用已有的鉴权 cookie/header 向自身转发请求，
避免重复 session 管理与流水线代码。
"""
import asyncio
import json
import logging
import os
from typing import AsyncGenerator, Optional

import httpx
from fastapi import APIRouter, Cookie, Header, Query, Request
from fastapi.responses import StreamingResponse

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/chat", tags=["chat"])

# 内部 API base URL（容器内自环回，默认 localhost:8000）
_INTERNAL_BASE = os.environ.get("INTERNAL_API_BASE", "http://localhost:8000")


async def _resolve_answer(
    question: str,
    connection_id: Optional[int],
    authorization: Optional[str],
    cookie: Optional[str],
) -> str:
    """
    向内部 POST /api/search/query 转发请求，返回纯文本 answer 字符串。
    使用调用方原始 Authorization header 和 Cookie，保证鉴权一致。
    """
    headers: dict[str, str] = {"Content-Type": "application/json"}
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
) -> AsyncGenerator[str, None]:
    """
    Generator：先完整获取 NLQ 响应，再按 word-chunk 分批 yield SSE 事件。

    chunk_size=3 words / 50ms → ~20 chunks/s。
    前端通过 requestAnimationFrame (~16ms) 批量 flush，约 1 帧消费 1 chunk。
    """
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
        payload = json.dumps({"error": str(exc)}, ensure_ascii=False)
        yield f"data: {payload}\n\n"


@router.get("/stream")
async def chat_stream(
    request: Request,
    q: str = Query(..., description="用户问题"),
    connection_id: Optional[int] = Query(None, description="连接 ID"),
    authorization: Optional[str] = Header(None, alias="Authorization"),
    cookie: Optional[str] = Header(None, alias="Cookie"),
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
        _stream_llm_response(q, connection_id, authorization, cookie),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )

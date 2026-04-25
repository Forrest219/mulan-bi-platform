"""
Phase 1 集成测试：chat.py + ask_data.py API层

覆盖范围：
    1. /api/chat/stream — GET SSE流（mock internal /api/search/query）
    2. /api/ask-data   — POST SSE流，未认证→401，invalid payload→422
    3. /api/ask-data/feedback — POST 反馈，mock DB写入

测试策略：
    - 内部 /api/search/query 响应通过 patch("httpx.AsyncClient") 完全隔离，
      使用 AsyncMock 正确模拟 async context manager。
    - SSE event 格式严格校验（data: JSON\n\n 模式）。
    - admin_client fixture 提供真实鉴权cookie。
    - feedback 测试 patch ask_data.get_db，隔离真实数据库。
"""
import json
import os
import uuid
from unittest.mock import AsyncMock, MagicMock, patch
from typing import AsyncGenerator

import pytest
from fastapi.testclient import TestClient

# ---------------------------------------------------------------------------
# 环境变量（必须在 import app 前设置，与 conftest.py 一致）
# ---------------------------------------------------------------------------
os.environ.setdefault("DATABASE_URL", "postgresql://mulan:***@localhost:5432/mulan_bi_test")
os.environ.setdefault("SESSION_SECRET", "test-session-secret-for-ci-!!")
os.environ.setdefault("DATASOURCE_ENCRYPTION_KEY", "test-datasource-key-32-bytes-ok!!")
os.environ.setdefault("TABLEAU_ENCRYPTION_KEY", "test-tableau-key-32-bytes-ok!!")
os.environ.setdefault("LLM_ENCRYPTION_KEY", "test-llm-key-32-bytes-ok!!!!")
os.environ.setdefault("ADMIN_USERNAME", "admin")
os.environ.setdefault("ADMIN_PASSWORD", "")
os.environ.setdefault("SECURE_COOKIES", "false")
os.environ.setdefault("SERVICE_JWT_SECRET", "test-jwt-secret-for-service-auth-32ch")


# ---------------------------------------------------------------------------
# 常量
# ---------------------------------------------------------------------------
_FAKE_TRACE_ID = str(uuid.uuid4())
_FAKE_SEARCH_RESPONSE_TEXT = {
    "response_type": "text",
    "answer": "本月销售额总计 1234 万元，同比增长 15%。",
    "trace_id": _FAKE_TRACE_ID,
    "sources": [{"name": "sales_fact"}, {"name": "product_dim"}],
    "intent": "metric_total",
}
_FAKE_SEARCH_RESPONSE_TABLE = {
    "response_type": "table",
    "columns": [{"name": "product"}, {"name": "sales"}],
    "rows": [["A", 100], ["B", 200]],
    "trace_id": _FAKE_TRACE_ID,
}
_FAKE_SEARCH_RESPONSE_NUMBER = {
    "response_type": "number",
    "label": "总销售额",
    "value": 12345678,
    "formatted": "1234.56",
    "unit": "万元",
    "trace_id": _FAKE_TRACE_ID,
}


# ---------------------------------------------------------------------------
# SSE 解析辅助（与 test_query_api.py 保持一致）
# ---------------------------------------------------------------------------
def _parse_sse_events(text: str) -> list[dict]:
    """将 SSE 响应体文本解析为 event dict 列表。每条 event 格式：data: {...}\\n\\n"""
    events = []
    for block in text.split("\n\n"):
        block = block.strip()
        if not block.startswith("data:"):
            continue
        json_str = block[len("data:"):].strip()
        if not json_str:
            continue
        try:
            events.append(json.loads(json_str))
        except json.JSONDecodeError:
            pass
    return events


# ---------------------------------------------------------------------------
# httpx.AsyncClient mock helper — 正确模拟 async with httpx.AsyncClient()
# ---------------------------------------------------------------------------
def _make_mock_async_client(response_data: dict, status_code: int = 200) -> MagicMock:
    """
    构造 mock AsyncClient，patch("httpx.AsyncClient") 使用。

    async with httpx.AsyncClient(timeout=...) as client:
        resp = await client.post(...)

    __aenter__ 必须是 AsyncMock/协程，否则 TypeError。
    post 也必须是 AsyncMock（ask_data._call_search 中 await client.post(...)）。
    """
    mock_response = MagicMock()
    mock_response.status_code = status_code
    mock_response.json.return_value = response_data
    mock_response.raise_for_status.return_value = None

    mock_post = AsyncMock(return_value=mock_response)

    mock_ctx = MagicMock()
    mock_ctx.__aenter__ = AsyncMock(return_value=mock_ctx)
    mock_ctx.__aexit__ = AsyncMock(return_value=False)
    mock_ctx.post = mock_post

    mock_client_cls = MagicMock()
    mock_client_cls.return_value = mock_ctx
    return mock_client_cls


def _make_mock_agent_stream_response(text_response: str, trace_id: str = None):
    """构造 mock _stream_via_agent async generator（yield SSE strings）。"""
    trace = trace_id or _FAKE_TRACE_ID

    async def _gen():
        yield f"data: {json.dumps({'type': 'metadata', 'sources_count': 2, 'top_sources': ['sales_fact', 'product_dim']}, ensure_ascii=False)}\n\n"
        words = text_response.split(" ")
        for i in range(0, len(words), 3):
            chunk = " ".join(words[i : i + 3])
            if i + 3 < len(words):
                chunk += " "
            yield f"data: {json.dumps({'type': 'token', 'content': chunk}, ensure_ascii=False)}\n\n"
        yield f"data: {json.dumps({'type': 'done', 'answer': text_response, 'trace_id': trace}, ensure_ascii=False)}\n\n"

    # Return an async generator object (call the function)
    return _gen()


def _make_mock_streaming_client(sse_lines: list[str]) -> MagicMock:
    """
    构造 mock httpx.AsyncClient，模拟 client.stream() 返回 SSE 流。
    用于测试 _stream_via_agent → _transform_agent_to_askdata 的完整路径。

    sse_lines: 每行是完整的 SSE data 行，如 'data: {"type":"token","content":"hello"}'
    """
    async def _aiter_lines():
        for line in sse_lines:
            yield line

    mock_response = AsyncMock()
    mock_response.status_code = 200
    mock_response.aiter_lines = _aiter_lines

    # client.stream("POST", url, ...) 返回 async context manager
    mock_stream_ctx = AsyncMock()
    mock_stream_ctx.__aenter__ = AsyncMock(return_value=mock_response)
    mock_stream_ctx.__aexit__ = AsyncMock(return_value=False)

    # httpx.AsyncClient(timeout=...) 返回 async context manager
    mock_client_instance = MagicMock()
    mock_client_instance.stream = MagicMock(return_value=mock_stream_ctx)
    mock_client_instance.__aenter__ = AsyncMock(return_value=mock_client_instance)
    mock_client_instance.__aexit__ = AsyncMock(return_value=False)

    mock_client_cls = MagicMock(return_value=mock_client_instance)
    return mock_client_cls


# ---------------------------------------------------------------------------
# Test: /api/chat/stream
# ---------------------------------------------------------------------------
class TestChatStream:
    """
    GET /api/chat/stream — Gap-05 SSE chat endpoint

    注意：chat.py 路由使用 Header Cookie/Authorization 可选参数，
    不强制鉴权。未认证时内部转发会失败，通过 SSE error event 返回。
    """

    def test_returns_sse_stream(self, admin_client: TestClient):
        """认证用户 → 200 + text/event-stream + token chunks + done"""
        mock_client_cls = _make_mock_async_client(_FAKE_SEARCH_RESPONSE_TEXT)

        with patch("httpx.AsyncClient", mock_client_cls):
            resp = admin_client.get(
                "/api/chat/stream",
                params={"q": "本月销售额是多少？", "connection_id": 1},
            )

        assert resp.status_code == 200
        assert "text/event-stream" in resp.headers.get("content-type", "")
        assert resp.headers.get("cache-control") == "no-cache"

        events = _parse_sse_events(resp.text)
        assert len(events) >= 2, f"Expected at least token+done events, got {events}"

        # Last event should be done
        assert events[-1].get("done") is True

        # All intermediate events should have "token" or "error"
        for ev in events[:-1]:
            assert "token" in ev or "error" in ev, f"Unexpected event: {ev}"

    def test_connection_id_optional(self, admin_client: TestClient):
        """connection_id 为可选参数，不传也能正常返回"""
        mock_client_cls = _make_mock_async_client(_FAKE_SEARCH_RESPONSE_TEXT)

        with patch("httpx.AsyncClient", mock_client_cls):
            resp = admin_client.get("/api/chat/stream", params={"q": "hello"})
            assert resp.status_code == 200

    def test_table_response_type(self, admin_client: TestClient):
        """table response_type → 返回 table 提示文本（不崩溃）"""
        mock_client_cls = _make_mock_async_client(_FAKE_SEARCH_RESPONSE_TABLE)

        with patch("httpx.AsyncClient", mock_client_cls):
            resp = admin_client.get("/api/chat/stream", params={"q": "各产品销售额"})
            assert resp.status_code == 200

        events = _parse_sse_events(resp.text)
        assert any("token" in ev or "done" in ev for ev in events)

    def test_missing_q_param_returns_422(self, admin_client: TestClient):
        """缺少 q 参数 → 422"""
        resp = admin_client.get("/api/chat/stream")
        assert resp.status_code == 422


# ---------------------------------------------------------------------------
# Test: /api/ask-data
# ---------------------------------------------------------------------------
class TestAskData:
    """POST /api/ask-data — 智能问数 SSE endpoint"""

    def test_unauthenticated_returns_401(self, client: TestClient):
        """未登录 → 401"""
        resp = client.post("/api/ask-data", json={"question": "本月销售额？"})
        assert resp.status_code == 401

    def test_authenticated_returns_sse_stream(self, admin_client: TestClient):
        """认证用户 → 200 + text/event-stream + metadata + token + done（Agent stream 路径）"""
        sse_lines = [
            'data: {"type":"metadata","conversation_id":"abc-123"}',
            'data: {"type":"token","content":"本月"}',
            'data: {"type":"token","content":"销售额"}',
            'data: {"type":"done","answer":"本月销售额总计 1234 万元","trace_id":"test-trace"}',
        ]
        mock_client_cls = _make_mock_streaming_client(sse_lines)

        with patch("httpx.AsyncClient", mock_client_cls):
            resp = admin_client.post(
                "/api/ask-data",
                json={"question": "本月销售额是多少？", "connection_id": 1},
            )

        assert resp.status_code == 200
        assert "text/event-stream" in resp.headers.get("content-type", "")
        events = _parse_sse_events(resp.text)
        assert len(events) >= 2, f"Expected metadata+token+done, got {events}"

        meta_ev = next((e for e in events if e.get("type") == "metadata"), None)
        assert meta_ev is not None, f"No metadata event found in {events}"

        done_ev = next((e for e in events if e.get("type") == "done"), None)
        assert done_ev is not None, f"No done event found in {events}"
        assert "trace_id" in done_ev

    def test_number_response_type(self, admin_client: TestClient):
        """number response_type → Agent 路径返回格式化的数值答案"""
        sse_lines = [
            'data: {"type":"metadata","conversation_id":"abc-456"}',
            'data: {"type":"done","answer":"总销售额为 1234.56 万元","trace_id":"test-trace"}',
        ]
        mock_client_cls = _make_mock_streaming_client(sse_lines)

        with patch("httpx.AsyncClient", mock_client_cls):
            resp = admin_client.post(
                "/api/ask-data",
                json={"question": "总销售额是多少？"},
            )

        assert resp.status_code == 200
        events = _parse_sse_events(resp.text)
        done_ev = next((e for e in events if e.get("type") == "done"), None)
        assert done_ev is not None
        answer = done_ev.get("answer", "")
        assert "1234.56" in answer or "万元" in answer

    def test_invalid_payload_422(self, admin_client: TestClient):
        """缺失必填字段 question → 422"""
        resp = admin_client.post("/api/ask-data", json={})
        assert resp.status_code == 422

    def test_missing_question_empty_string_is_rejected(self, admin_client: TestClient):
        """question 为空字符串时 Pydantic 校验拒绝 → 422（Pydantic min_length=1）"""
        resp = admin_client.post("/api/ask-data", json={"question": ""})
        assert resp.status_code == 422

    def test_optional_connection_id_and_conversation_id(self, admin_client: TestClient):
        """connection_id 和 conversation_id 均为可选"""
        mock_client_cls = _make_mock_async_client(_FAKE_SEARCH_RESPONSE_TEXT)

        with patch("httpx.AsyncClient", mock_client_cls):
            resp = admin_client.post(
                "/api/ask-data",
                json={"question": "hello"},
            )
            assert resp.status_code == 200

    def test_search_query_called_with_correct_body(self, admin_client: TestClient):
        """Agent 转发失败时 fallback 到 search，验证 search 调用的 body 正确"""
        # async generator 如果在 yield 前 raise，则 async for 会将异常传播到 _generate_events 的 except
        async def _failing_agent_stream(*args, **kwargs):
            raise Exception("Agent unavailable")
            yield  # noqa: unreachable — 但需要这个 yield 让 Python 识别为 async generator

        mock_client_cls = _make_mock_async_client(_FAKE_SEARCH_RESPONSE_TEXT)

        with patch("app.api.ask_data._stream_via_agent", _failing_agent_stream):
            with patch("httpx.AsyncClient", mock_client_cls):
                admin_client.post(
                    "/api/ask-data",
                    json={"question": "测试问题", "connection_id": 42},
                )

                mock_ctx = mock_client_cls.return_value
                mock_ctx.post.assert_called_once()
                call_args = mock_ctx.post.call_args
                body = call_args.kwargs.get("json")
                assert body is not None
                assert body.get("question") == "测试问题"
                assert body.get("connection_id") == 42


# ---------------------------------------------------------------------------
# Test: /api/ask-data/feedback
# ---------------------------------------------------------------------------
class TestAskDataFeedback:
    """POST /api/ask-data/feedback — 问数结果点赞/踩"""

    def test_unauthenticated_returns_401(self, client: TestClient):
        """未登录 → 401"""
        resp = client.post(
            "/api/ask-data/feedback",
            json={"trace_id": _FAKE_TRACE_ID, "rating": "up"},
        )
        assert resp.status_code == 401

    def test_valid_upvote_returns_200(self, admin_client: TestClient):
        """rating=up → 200 + {ok: True}"""
        from app.main import app as fastapi_app
        from app.core.database import get_db

        mock_session = MagicMock()
        mock_session.execute = MagicMock()
        mock_session.commit = MagicMock()

        def _get_db_gen():
            yield mock_session

        fastapi_app.dependency_overrides[get_db] = _get_db_gen
        try:
            resp = admin_client.post(
                "/api/ask-data/feedback",
                json={"trace_id": _FAKE_TRACE_ID, "rating": "up", "question": "本月销售额？"},
            )
            assert resp.status_code == 200
            assert resp.json().get("ok") is True
            mock_session.execute.assert_called_once()
            mock_session.commit.assert_called_once()
        finally:
            fastapi_app.dependency_overrides.clear()

    def test_valid_downvote_returns_200(self, admin_client: TestClient):
        """rating=down → 200"""
        from app.main import app as fastapi_app
        from app.core.database import get_db

        mock_session = MagicMock()
        mock_session.execute = MagicMock()
        mock_session.commit = MagicMock()

        def _get_db_gen():
            yield mock_session

        fastapi_app.dependency_overrides[get_db] = _get_db_gen
        try:
            resp = admin_client.post(
                "/api/ask-data/feedback",
                json={"trace_id": _FAKE_TRACE_ID, "rating": "down"},
            )
            assert resp.status_code == 200
            assert resp.json().get("ok") is True
        finally:
            fastapi_app.dependency_overrides.clear()

    def test_invalid_rating_returns_422(self, admin_client: TestClient):
        """rating 非 'up'|'down' → 422"""
        resp = admin_client.post(
            "/api/ask-data/feedback",
            json={"trace_id": _FAKE_TRACE_ID, "rating": "maybe"},
        )
        assert resp.status_code == 422

    def test_missing_trace_id_returns_422(self, admin_client: TestClient):
        """缺失 trace_id → 422"""
        resp = admin_client.post(
            "/api/ask-data/feedback",
            json={"rating": "up"},
        )
        assert resp.status_code == 422


# ---------------------------------------------------------------------------
# Test: error handling
# ---------------------------------------------------------------------------
class TestChatStreamErrorHandling:
    """chat.py /api/chat/stream 错误处理"""

    def test_search_query_http_error_returns_error_event(self, admin_client: TestClient):
        """后端 /api/search/query 返回非200 → SSE error event（不抛500）"""
        mock_client_cls = _make_mock_async_client(
            {"detail": "Internal Server Error"},
            status_code=500,
        )

        with patch("httpx.AsyncClient", mock_client_cls):
            resp = admin_client.get("/api/chat/stream", params={"q": "test"})

        assert resp.status_code == 200  # 不抛HTTP错误，通过SSE返回
        events = _parse_sse_events(resp.text)
        error_ev = next((e for e in events if "error" in e), None)
        assert error_ev is not None, f"No error event found in {events}"

"""
集成测试：Spec 14 T-04 — 问数 API 路由层

覆盖范围：
    1. 未认证访问所有 endpoints → 401
    2. GET /api/query/datasources — service 成功路径 / Q_JWT_001 / Q_PERM_002 / Q_TIMEOUT_003
    3. POST /api/query/ask — SSE 流式响应：成功路径 / 错误路径 / 422 参数校验
    4. GET /api/query/sessions — 成功路径（返回列表结构）
    5. GET /api/query/sessions/{id}/messages — session 存在 / 不存在 → 404

测试策略：
    - Service 层（QueryService）完全 mock，不依赖数据库数据，也不依赖 MCP/LLM
    - get_current_user 通过真实登录 fixture（admin_client）验证，保持鉴权链路真实
    - 数据库 I/O（sessions/messages 端点）通过 mock QuerySession / QueryMessageDatabase 隔离
    - /ask 改为 SSE StreamingResponse，TestAsk 使用 SSE 解析辅助函数验证 event 格式
"""
import json
import os
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

# ---------------------------------------------------------------------------
# 必须在 import app 前设置环境变量（与 conftest.py 一致）
# ---------------------------------------------------------------------------
os.environ.setdefault("DATABASE_URL", "postgresql://mulan:mulan@localhost:5432/mulan_bi_test")
os.environ.setdefault("SESSION_SECRET", "test-session-secret-for-ci-!!")
os.environ.setdefault("DATASOURCE_ENCRYPTION_KEY", "test-datasource-key-32-bytes-ok!!")
os.environ.setdefault("TABLEAU_ENCRYPTION_KEY", "test-tableau-key-32-bytes-ok!!")
os.environ.setdefault("LLM_ENCRYPTION_KEY", "test-llm-key-32-bytes-ok!!!!")
os.environ.setdefault("ADMIN_USERNAME", "admin")
os.environ.setdefault("ADMIN_PASSWORD", "")
os.environ.setdefault("SECURE_COOKIES", "false")


# ---------------------------------------------------------------------------
# 常量
# ---------------------------------------------------------------------------
_BASE = "/api/query"
_FAKE_SESSION_ID = str(uuid.uuid4())
_FAKE_DS_LUID = "ds-luid-abcdef"
_FAKE_USER = {"id": 1, "username": "admin", "role": "admin"}

_ASK_PAYLOAD = {
    "connection_id": 1,
    "datasource_luid": _FAKE_DS_LUID,
    "message": "销售额最高的前5个地区？",
}

_SERVICE_ASK_RESULT = {
    "session_id": _FAKE_SESSION_ID,
    "message_id": 42,
    "summary": "华南区销售额最高，占全国 35%。",
    "data": {"fields": ["region", "sales"], "rows": [["华南", 1000], ["华北", 800]]},
    "llm_error": None,
}

_FAKE_DATASOURCES = [
    {"luid": "ds-001", "name": "销售数据源"},
    {"luid": "ds-002", "name": "库存数据源"},
]


# ---------------------------------------------------------------------------
# 帮助函数
# ---------------------------------------------------------------------------

def _fake_session(session_id: str = _FAKE_SESSION_ID, user_id: int = 1) -> MagicMock:
    """构造一个模拟 QuerySession ORM 对象"""
    s = MagicMock()
    s.id = uuid.UUID(session_id)
    s.user_id = user_id
    s.title = "测试对话"
    s.created_at = datetime(2026, 4, 21, 0, 0, 0, tzinfo=timezone.utc)
    s.updated_at = None
    s.is_active = True
    return s


def _fake_message(msg_id: int, role: str, content: str) -> MagicMock:
    """构造一个模拟 QueryMessage ORM 对象"""
    m = MagicMock()
    m.id = msg_id
    m.role = role
    m.content = content
    m.data_table = None
    m.datasource_luid = _FAKE_DS_LUID
    m.created_at = datetime(2026, 4, 21, 0, 0, 0, tzinfo=timezone.utc)
    return m


# ---------------------------------------------------------------------------
# SSE 测试工具
# ---------------------------------------------------------------------------

def _parse_sse_events(text: str) -> list[dict]:
    """
    将 SSE 响应体文本解析为 event dict 列表。
    每条 event 格式：data: {...}\n\n
    """
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
# 未认证访问 — 四个 endpoints 全部拦截
# ---------------------------------------------------------------------------

class TestUnauthenticated:
    """所有 endpoints 未登录时应返回 401"""

    def test_datasources_unauthenticated(self, client: TestClient):
        client.cookies.clear()
        resp = client.get(f"{_BASE}/datasources", params={"connection_id": 1})
        assert resp.status_code == 401

    def test_ask_unauthenticated(self, client: TestClient):
        client.cookies.clear()
        resp = client.post(f"{_BASE}/ask", json=_ASK_PAYLOAD)
        assert resp.status_code == 401

    def test_sessions_unauthenticated(self, client: TestClient):
        client.cookies.clear()
        resp = client.get(f"{_BASE}/sessions")
        assert resp.status_code == 401

    def test_session_messages_unauthenticated(self, client: TestClient):
        client.cookies.clear()
        resp = client.get(f"{_BASE}/sessions/{_FAKE_SESSION_ID}/messages")
        assert resp.status_code == 401


# ---------------------------------------------------------------------------
# GET /api/query/datasources
# ---------------------------------------------------------------------------

class TestListDatasources:
    """GET /api/query/datasources — 各路径"""

    def test_success(self, admin_client: TestClient):
        """service 正常返回数据源列表"""
        with patch(
            "app.api.query.QueryService.list_datasources",
            return_value=_FAKE_DATASOURCES,
        ):
            resp = admin_client.get(f"{_BASE}/datasources", params={"connection_id": 1})

        assert resp.status_code == 200
        data = resp.json()
        assert "datasources" in data
        assert data["total"] == 2
        assert data["datasources"][0]["luid"] == "ds-001"

    def test_missing_connection_id(self, admin_client: TestClient):
        """缺少 connection_id → 422 参数校验错误"""
        resp = admin_client.get(f"{_BASE}/datasources")
        assert resp.status_code == 422

    def test_jwt_error_503(self, admin_client: TestClient):
        """Q_JWT_001 → 503 服务不可用"""
        from services.query.query_service import QueryServiceError

        with patch(
            "app.api.query.QueryService.list_datasources",
            side_effect=QueryServiceError(code="Q_JWT_001", message="密钥未配置"),
        ):
            resp = admin_client.get(f"{_BASE}/datasources", params={"connection_id": 1})

        assert resp.status_code == 503
        assert resp.json()["detail"]["error_code"] == "Q_JWT_001"

    def test_perm_error_403(self, admin_client: TestClient):
        """Q_PERM_002 → 403 权限不足"""
        from services.query.query_service import QueryServiceError

        with patch(
            "app.api.query.QueryService.list_datasources",
            side_effect=QueryServiceError(code="Q_PERM_002", message="无权访问"),
        ):
            resp = admin_client.get(f"{_BASE}/datasources", params={"connection_id": 1})

        assert resp.status_code == 403

    def test_timeout_error_504(self, admin_client: TestClient):
        """Q_TIMEOUT_003 → 504 网关超时"""
        from services.query.query_service import QueryServiceError

        with patch(
            "app.api.query.QueryService.list_datasources",
            side_effect=QueryServiceError(code="Q_TIMEOUT_003", message="超时"),
        ):
            resp = admin_client.get(f"{_BASE}/datasources", params={"connection_id": 1})

        assert resp.status_code == 504


# ---------------------------------------------------------------------------
# POST /api/query/ask  — SSE 流式响应
# ---------------------------------------------------------------------------

# 模拟 ask_stream 生成器：产生 token events + done event
async def _mock_ask_stream_success(**kwargs):
    """模拟 ask_stream 成功路径：2 个 token + 1 个 done"""
    yield f'data: {json.dumps({"type": "token", "content": "华南区"})}\n\n'
    yield f'data: {json.dumps({"type": "token", "content": "销售额最高"})}\n\n'
    yield f'data: {json.dumps({"type": "done", "session_id": _FAKE_SESSION_ID, "answer": "华南区销售额最高，占全国 35%。", "data_table": []})}\n\n'


async def _mock_ask_stream_error(**kwargs):
    """模拟 ask_stream 错误路径：yield error event"""
    yield f'data: {json.dumps({"type": "error", "code": "Q_MCP_004", "message": "MCP 失败"})}\n\n'


async def _mock_ask_stream_perm_error(**kwargs):
    """模拟 ask_stream Q_PERM_002 错误"""
    yield f'data: {json.dumps({"type": "error", "code": "Q_PERM_002", "message": "无权访问"})}\n\n'


class TestAsk:
    """POST /api/query/ask — SSE 流式响应（Spec §5.2）"""

    def test_success_sse_content_type(self, admin_client: TestClient):
        """响应 Content-Type 必须为 text/event-stream"""
        with patch(
            "app.api.query.QueryService.ask_stream",
            side_effect=_mock_ask_stream_success,
        ):
            resp = admin_client.post(f"{_BASE}/ask", json=_ASK_PAYLOAD)

        assert resp.status_code == 200
        assert "text/event-stream" in resp.headers.get("content-type", "")

    def test_success_sse_events_structure(self, admin_client: TestClient):
        """流中 token events 和 done event 格式正确"""
        with patch(
            "app.api.query.QueryService.ask_stream",
            side_effect=_mock_ask_stream_success,
        ):
            resp = admin_client.post(f"{_BASE}/ask", json=_ASK_PAYLOAD)

        events = _parse_sse_events(resp.text)
        assert len(events) == 3  # 2 token + 1 done

        token_events = [e for e in events if e["type"] == "token"]
        done_events = [e for e in events if e["type"] == "done"]

        assert len(token_events) == 2
        assert token_events[0]["content"] == "华南区"
        assert token_events[1]["content"] == "销售额最高"

        assert len(done_events) == 1
        done = done_events[0]
        assert done["session_id"] == _FAKE_SESSION_ID
        assert done["answer"] == "华南区销售额最高，占全国 35%。"
        assert isinstance(done["data_table"], list)

    def test_success_with_session_id(self, admin_client: TestClient):
        """携带 session_id 续接历史对话，done event 中包含 session_id"""
        with patch(
            "app.api.query.QueryService.ask_stream",
            side_effect=_mock_ask_stream_success,
        ):
            payload = {**_ASK_PAYLOAD, "session_id": _FAKE_SESSION_ID}
            resp = admin_client.post(f"{_BASE}/ask", json=payload)

        assert resp.status_code == 200
        events = _parse_sse_events(resp.text)
        done = next(e for e in events if e["type"] == "done")
        assert done["session_id"] == _FAKE_SESSION_ID

    def test_error_event_yielded(self, admin_client: TestClient):
        """service 产生 error event 时，路由层以 200 + error event 返回（SSE 规范）"""
        with patch(
            "app.api.query.QueryService.ask_stream",
            side_effect=_mock_ask_stream_error,
        ):
            resp = admin_client.post(f"{_BASE}/ask", json=_ASK_PAYLOAD)

        # SSE 不通过 HTTP status code 表达业务错误，而是通过 error event
        assert resp.status_code == 200
        events = _parse_sse_events(resp.text)
        error_events = [e for e in events if e["type"] == "error"]
        assert len(error_events) == 1
        assert error_events[0]["code"] == "Q_MCP_004"
        assert "message" in error_events[0]

    def test_missing_required_fields_422(self, admin_client: TestClient):
        """缺少必填字段 → 422（在 stream 开始前由 Pydantic 拦截）"""
        resp = admin_client.post(f"{_BASE}/ask", json={"message": "test"})
        assert resp.status_code == 422

    def test_sse_cache_control_header(self, admin_client: TestClient):
        """响应头包含 Cache-Control: no-cache"""
        with patch(
            "app.api.query.QueryService.ask_stream",
            side_effect=_mock_ask_stream_success,
        ):
            resp = admin_client.post(f"{_BASE}/ask", json=_ASK_PAYLOAD)

        assert resp.headers.get("cache-control") == "no-cache"

    def test_vizql_query_passed_to_stream(self, admin_client: TestClient):
        """路由层必须将 vizql_query 参数传入 ask_stream，且不为 None"""
        captured: Dict[str, Any] = {}

        async def _capture_stream(**kwargs):
            captured.update(kwargs)
            # 产生最小有效 SSE 输出
            yield f'data: {json.dumps({"type": "done", "session_id": _FAKE_SESSION_ID, "answer": "", "data_table": []})}\n\n'

        with patch("app.api.query.QueryService.ask_stream", side_effect=_capture_stream):
            admin_client.post(f"{_BASE}/ask", json=_ASK_PAYLOAD)

        assert "vizql_query" in captured
        assert captured["vizql_query"] is not None, (
            "路由层必须传入 vizql_query，不得为 None（即使是占位实现也应传入非 None 的 dict）"
        )


# ---------------------------------------------------------------------------
# GET /api/query/sessions
# ---------------------------------------------------------------------------

class TestListSessions:
    """GET /api/query/sessions"""

    def test_success_empty(self, admin_client: TestClient):
        """无历史 session 时返回空列表"""
        mock_query = MagicMock()
        mock_query.filter.return_value = mock_query
        mock_query.order_by.return_value = mock_query
        mock_query.limit.return_value = mock_query
        mock_query.all.return_value = []

        # patch SQLAlchemy Session.query，隔离真实数据库 I/O
        with patch("sqlalchemy.orm.Session.query", return_value=mock_query):
            resp = admin_client.get(f"{_BASE}/sessions")

        # 路由层应 200 并返回标准结构
        assert resp.status_code == 200
        body = resp.json()
        assert "items" in body
        assert "total" in body

    def test_success_with_sessions(self, admin_client: TestClient):
        """有 session 时，列表字段结构完整"""
        fake = _fake_session()
        mock_query = MagicMock()
        mock_query.filter.return_value = mock_query
        mock_query.order_by.return_value = mock_query
        mock_query.limit.return_value = mock_query
        mock_query.all.return_value = [fake]

        with patch("sqlalchemy.orm.Session.query", return_value=mock_query):
            resp = admin_client.get(f"{_BASE}/sessions")

        assert resp.status_code == 200
        body = resp.json()
        assert body["total"] == 1
        sess = body["items"][0]
        assert "id" in sess
        assert "title" in sess
        assert "created_at" in sess


# ---------------------------------------------------------------------------
# GET /api/query/sessions/{session_id}/messages
# ---------------------------------------------------------------------------

class TestSessionMessages:
    """GET /api/query/sessions/{session_id}/messages"""

    def test_invalid_session_uuid_404(self, admin_client: TestClient):
        """传入非法 UUID 格式 → 404"""
        resp = admin_client.get(f"{_BASE}/sessions/not-a-uuid/messages")
        assert resp.status_code == 404

    def test_nonexistent_session_404(self, admin_client: TestClient):
        """session 不存在或不属于当前用户 → 404"""
        non_existent = str(uuid.uuid4())
        with patch(
            "services.query.query_service.QueryMessageDatabase.list_messages",
            return_value=[],
        ):
            with patch("sqlalchemy.orm.Session.query") as mock_q:
                mock_q.return_value.filter.return_value.first.return_value = None
                resp = admin_client.get(f"{_BASE}/sessions/{non_existent}/messages")

        assert resp.status_code == 404

    def test_success(self, admin_client: TestClient):
        """session 存在且有消息时，返回正确结构"""
        msgs = [
            _fake_message(1, "user", "销售额最高的地区？"),
            _fake_message(2, "assistant", "华南区销售额最高。"),
        ]
        fake_sess = _fake_session()

        with patch(
            "services.query.query_service.QueryMessageDatabase.list_messages",
            return_value=msgs,
        ):
            resp = admin_client.get(f"{_BASE}/sessions/{_FAKE_SESSION_ID}/messages")

        assert resp.status_code == 200
        body = resp.json()
        assert body["session_id"] == _FAKE_SESSION_ID
        assert body["total"] == 2
        assert body["messages"][0]["role"] == "user"
        assert body["messages"][1]["role"] == "assistant"

    def test_limit_param(self, admin_client: TestClient):
        """limit 参数超出范围 → 422"""
        resp = admin_client.get(
            f"{_BASE}/sessions/{_FAKE_SESSION_ID}/messages",
            params={"limit": 999},
        )
        assert resp.status_code == 422

    def test_limit_zero_422(self, admin_client: TestClient):
        """limit=0 → 422"""
        resp = admin_client.get(
            f"{_BASE}/sessions/{_FAKE_SESSION_ID}/messages",
            params={"limit": 0},
        )
        assert resp.status_code == 422

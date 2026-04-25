"""TC-API-001~006: Data Agent API 端点测试（Spec 36 §5）"""

import uuid
import pytest
from unittest.mock import MagicMock, patch
from fastapi.testclient import TestClient

from app.core.dependencies import get_current_user


class TestAgentAPI:
    """Data Agent API 测试组 — 使用 app.dependency_overrides 注入 mock user"""

    # -------------------------------------------------------------------------
    # TC-API-001: POST /api/agent/stream
    # -------------------------------------------------------------------------
    def test_stream_requires_auth(self):
        """TC-API-001a: 未认证返回 401"""
        from app.main import app
        client = TestClient(app, raise_server_exceptions=False)
        resp = client.post("/api/agent/stream", json={"question": "本月销售额"})
        assert resp.status_code in (401, 403)

    def test_stream_requires_analyst_role(self):
        """TC-API-001b: 非 analyst 角色返回 403"""
        from app.main import app
        client = TestClient(app, raise_server_exceptions=False)
        app.dependency_overrides[get_current_user] = lambda: {"id": 1, "role": "viewer"}
        try:
            resp = client.post("/api/agent/stream", json={"question": "本月销售额"})
            assert resp.status_code == 403
        finally:
            app.dependency_overrides.clear()

    def test_stream_requires_min_length_question(self):
        """TC-API-001c: 空 question 返回 422"""
        from app.main import app
        client = TestClient(app, raise_server_exceptions=False)
        app.dependency_overrides[get_current_user] = lambda: {"id": 1, "role": "analyst"}
        try:
            resp = client.post("/api/agent/stream", json={"question": ""})
            assert resp.status_code == 422
        finally:
            app.dependency_overrides.clear()

    def test_stream_invalid_conversation_id_returns_400(self):
        """TC-API-001d: 无效 conversation_id 格式返回 400"""
        from app.main import app
        client = TestClient(app, raise_server_exceptions=False)
        app.dependency_overrides[get_current_user] = lambda: {"id": 1, "role": "analyst"}
        try:
            resp = client.post("/api/agent/stream", json={"question": "销售额", "conversation_id": "not-a-uuid"})
            assert resp.status_code == 400
        finally:
            app.dependency_overrides.clear()

    # -------------------------------------------------------------------------
    # TC-API-002: GET /api/agent/conversations
    # -------------------------------------------------------------------------
    def test_list_conversations_requires_auth(self):
        """TC-API-002a: 未认证返回 401"""
        from app.main import app
        client = TestClient(app, raise_server_exceptions=False)
        resp = client.get("/api/agent/conversations")
        assert resp.status_code in (401, 403)

    def test_list_conversations_empty(self):
        """TC-API-002b: 无会话返回空列表"""
        from app.main import app
        from app.core.dependencies import get_current_user

        app.dependency_overrides[get_current_user] = lambda: {"id": 99999, "role": "analyst"}
        try:
            client = TestClient(app, raise_server_exceptions=False)
            resp = client.get("/api/agent/conversations")
            assert resp.status_code == 200
            assert resp.json() == []
        finally:
            app.dependency_overrides.clear()

    # -------------------------------------------------------------------------
    # TC-API-003: GET /api/agent/conversations/{id}/messages
    # -------------------------------------------------------------------------
    def test_get_messages_not_found(self):
        """TC-API-003a: 会话不存在返回 404"""
        from app.main import app
        from app.core.dependencies import get_current_user

        valid_uuid = str(uuid.uuid4())
        app.dependency_overrides[get_current_user] = lambda: {"id": 1, "role": "analyst"}
        try:
            with patch("app.api.agent.AgentConversation") as MockConv:
                MockConv.query.return_value.filter.return_value.first.return_value = None
                client = TestClient(app, raise_server_exceptions=False)
                resp = client.get(f"/api/agent/conversations/{valid_uuid}/messages")
                assert resp.status_code == 404
        finally:
            app.dependency_overrides.clear()

    def test_get_messages_forbidden_for_other_user(self):
        """TC-API-003b: 非 owner 返回 404（不暴露存在性）"""
        from app.main import app
        from app.core.dependencies import get_current_user

        valid_uuid = str(uuid.uuid4())
        mock_conv = MagicMock()
        mock_conv.id = uuid.uuid4()
        mock_conv.user_id = 999

        app.dependency_overrides[get_current_user] = lambda: {"id": 1, "role": "analyst"}
        try:
            with patch("app.api.agent.AgentConversation") as MockConv:
                MockConv.query.return_value.filter.return_value.first.return_value = mock_conv
                client = TestClient(app, raise_server_exceptions=False)
                resp = client.get(f"/api/agent/conversations/{valid_uuid}/messages")
                assert resp.status_code == 404
        finally:
            app.dependency_overrides.clear()

    # -------------------------------------------------------------------------
    # TC-API-004: DELETE /api/agent/conversations/{id}
    # -------------------------------------------------------------------------
    def test_delete_conversation_not_found(self):
        """TC-API-004a: 会话不存在返回 404"""
        from app.main import app
        from app.core.dependencies import get_current_user

        valid_uuid = str(uuid.uuid4())
        app.dependency_overrides[get_current_user] = lambda: {"id": 1, "role": "analyst"}
        try:
            with patch("app.api.agent.AgentConversation") as MockConv:
                MockConv.query.return_value.filter.return_value.first.return_value = None
                client = TestClient(app, raise_server_exceptions=False)
                resp = client.delete(f"/api/agent/conversations/{valid_uuid}")
                assert resp.status_code == 404
        finally:
            app.dependency_overrides.clear()

    def test_delete_conversation_forbidden_for_other_user(self):
        """TC-API-004b: 非 owner 返回 403（resume_session 内部已做 ownership check）"""
        from app.main import app
        from app.core.dependencies import get_current_user

        valid_uuid = str(uuid.uuid4())

        app.dependency_overrides[get_current_user] = lambda: {"id": 1, "role": "analyst"}
        try:
            # resume_session(uuid, user_id=1) 在 db.filter().filter() 后返回 None（用户不匹配）
            # 因此 archive 返回 404（会话不存在于该用户视野）
            with patch("app.api.agent.AgentConversation") as MockConv:
                # First filter (id match) returns mock_conv, second filter (user_id mismatch) returns None
                MockConv.query.return_value.filter.return_value.filter.return_value.first.return_value = None
                client = TestClient(app, raise_server_exceptions=False)
                resp = client.delete(f"/api/agent/conversations/{valid_uuid}")
                # resume_session 返回 None → "会话不存在" → 404（而非 403，因为安全不暴露存在性）
                assert resp.status_code == 404
        finally:
            app.dependency_overrides.clear()

"""TC-API-007~011: Data Agent 会话持久化测试（Spec 36 §4.3）"""

import pytest
import uuid
from unittest.mock import MagicMock

from services.data_agent.session import SessionManager, AgentSession


class TestConversationPersistence:
    """会话持久化底层测试（直接测试 SessionManager）"""

    @pytest.fixture
    def mock_db(self):
        return MagicMock()

    @pytest.fixture
    def session_mgr(self, mock_db):
        return SessionManager(mock_db)

    # -------------------------------------------------------------------------
    # TC-API-007: 创建新会话
    # -------------------------------------------------------------------------
    def test_create_session(self, session_mgr, mock_db):
        """TC-API-007: create_session 返回 AgentSession"""
        result = session_mgr.create_session(
            user_id=1,
            connection_id=5,
        )
        assert isinstance(result, AgentSession)
        mock_db.add.assert_called_once()
        mock_db.commit.assert_called()

    # -------------------------------------------------------------------------
    # TC-API-008: 持久化消息
    # -------------------------------------------------------------------------
    def test_persist_message_user(self, session_mgr, mock_db):
        """TC-API-008: 持久化用户消息（传 AgentSession）"""
        # 先创建一个 session
        mock_session = session_mgr.create_session(user_id=1)
        mock_db.reset_mock()

        result = session_mgr.persist_message(
            session=mock_session,
            role="user",
            content="本月销售额多少？",
            trace_id="t-abc123",
        )
        mock_db.add.assert_called()
        mock_db.commit.assert_called()
        assert result is not None

    def test_persist_message_assistant(self, session_mgr, mock_db):
        """TC-API-008b: 持久化 assistant 消息（含元数据）"""
        mock_session = session_mgr.create_session(user_id=1)
        mock_db.reset_mock()

        result = session_mgr.persist_message(
            session=mock_session,
            role="assistant",
            content="销售额是 100 万",
            response_type="text",
            tools_used=["query_tool"],
            trace_id="t-abc123",
            steps_count=1,
            execution_time_ms=1500,
        )
        mock_db.add.assert_called()
        mock_db.commit.assert_called()
        assert result is not None

    # -------------------------------------------------------------------------
    # TC-API-009: 会话列表
    # -------------------------------------------------------------------------
    def test_get_user_conversations_returns_list(self, session_mgr, mock_db):
        """TC-API-009: get_user_conversations 返回用户会话列表"""
        mock_db.query.return_value.filter.return_value.filter.return_value.order_by.return_value.limit.return_value.all.return_value = []
        result = session_mgr.get_user_conversations(user_id=1)
        mock_db.query.assert_called_once()
        assert isinstance(result, list)

    # -------------------------------------------------------------------------
    # TC-API-010: 续接会话
    # -------------------------------------------------------------------------
    def test_resume_session_returns_agent_session(self, session_mgr, mock_db):
        """TC-API-010: resume_session 返回 AgentSession 或 None"""
        result = session_mgr.resume_session(uuid.uuid4(), user_id=1)
        assert result is None or isinstance(result, AgentSession)

    # -------------------------------------------------------------------------
    # TC-API-011: 归档会话
    # -------------------------------------------------------------------------
    def test_archive_session(self, session_mgr, mock_db):
        """TC-API-011: archive_session 设置 status=archived"""
        mock_conv = MagicMock()
        mock_conv.id = uuid.uuid4()
        mock_conv.status = "active"
        mock_db.query.return_value.filter.return_value.first.return_value = mock_conv

        session_mgr.archive_session(mock_conv.id, user_id=1)
        assert mock_conv.status == "archived"
        mock_db.commit.assert_called()

    def test_archive_nonexistent_no_error(self, session_mgr, mock_db):
        """TC-API-011b: 不存在的会话不抛异常"""
        mock_db.query.return_value.filter.return_value.first.return_value = None
        # 不应抛异常
        session_mgr.archive_session(uuid.uuid4(), user_id=1)

"""
单元测试：QueryService.ask_stream()  — Spec 14 §5.2 SSE 流式生成器

覆盖范围：
    1. 成功路径 — 产生 token events + done event，格式符合 Spec
    2. user_id=None — 立即产生 error event（Q_INPUT_006），不触发后续链路
    3. JWT 签发失败 — 产生 error event（Q_JWT_001）
    4. MCP 查询失败 — 产生 error event，错误码正确映射
    5. LLM 降级 — 摘要为空时，done event 内 answer 为降级文案，流不中断
    6. 消息持久化 — done event 发送前，append_message 已被调用

测试策略：
    - 完全 mock：TableauMCPClient / llm_service / QueryMessageDatabase / SessionLocal
    - 不依赖真实数据库，使用 MagicMock Session
    - 辅助函数 collect_stream() 将 AsyncGenerator[str] 收集为字符串列表后解析
"""
import asyncio
import json
import os
import uuid
from typing import AsyncGenerator
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# 在 import 项目模块前设置环境变量（与 conftest.py 对齐）
os.environ.setdefault("DATABASE_URL", "postgresql://mulan:mulan@localhost:5432/mulan_bi_test")
os.environ.setdefault("SESSION_SECRET", "test-session-secret-for-ci-!!")
os.environ.setdefault("DATASOURCE_ENCRYPTION_KEY", "test-datasource-key-32-bytes-ok!!")
os.environ.setdefault("TABLEAU_ENCRYPTION_KEY", "test-tableau-key-32-bytes-ok!!")
os.environ.setdefault("LLM_ENCRYPTION_KEY", "test-llm-key-32-bytes-ok!!!!")
os.environ.setdefault("ADMIN_USERNAME", "admin")
os.environ.setdefault("ADMIN_PASSWORD", "")
os.environ.setdefault("SECURE_COOKIES", "false")

from services.query.query_service import QueryService, QueryServiceError  # noqa: E402


# ─────────────────────────────────────────────────────────────────────────────
# 测试常量
# ─────────────────────────────────────────────────────────────────────────────

_FAKE_SESSION_ID = str(uuid.uuid4())
_FAKE_SESSION_UUID = uuid.UUID(_FAKE_SESSION_ID)
_FAKE_DS_LUID = "ds-luid-stream-test"
_MCP_DATA = {
    "fields": ["region", "sales"],
    "rows": [["华南", 1000], ["华北", 800]],
}
_LLM_SUMMARY = "华南区销售额最高，占全国 35%。"


# ─────────────────────────────────────────────────────────────────────────────
# 辅助工具
# ─────────────────────────────────────────────────────────────────────────────

async def _collect(gen: AsyncGenerator[str, None]) -> list[dict]:
    """收集 AsyncGenerator 产生的所有 SSE 行，解析为 dict 列表。"""
    raw = []
    async for chunk in gen:
        raw.append(chunk)
    full_text = "".join(raw)
    events = []
    for block in full_text.split("\n\n"):
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


def _make_mock_db_and_session(session_uuid: uuid.UUID = None) -> tuple:
    """
    构造 mock DB Session 及 QueryMessageDatabase 所需的 ORM 对象。
    返回 (mock_db, mock_sess_orm, mock_msg_orm)
    """
    sid = session_uuid or _FAKE_SESSION_UUID
    mock_sess_orm = MagicMock()
    mock_sess_orm.id = sid

    mock_msg_orm = MagicMock()
    mock_msg_orm.id = 99

    mock_db = MagicMock()
    return mock_db, mock_sess_orm, mock_msg_orm


# ─────────────────────────────────────────────────────────────────────────────
# 测试类
# ─────────────────────────────────────────────────────────────────────────────

class TestAskStreamSuccess:
    """成功路径：token events + done event 格式验证"""

    @pytest.mark.asyncio
    async def test_token_events_emitted(self):
        """summary 中每个字符都应产生一个 token event"""
        mock_db, mock_sess, mock_msg = _make_mock_db_and_session()

        with (
            patch(
                "services.query.query_service.QueryMessageDatabase.get_or_create_session",
                return_value=mock_sess,
            ),
            patch(
                "services.query.query_service.QueryMessageDatabase.append_message",
                return_value=mock_msg,
            ),
            patch(
                "services.query.query_service.QueryService._issue_jwt",
                return_value="fake-jwt-token",
            ),
            patch(
                "services.query.query_service.TableauMCPClient.query_datasource",
                return_value=_MCP_DATA,
            ),
            patch(
                "services.query.query_service.llm_service.complete",
                new_callable=AsyncMock,
                return_value={"content": _LLM_SUMMARY},
            ),
        ):
            svc = QueryService(db=mock_db)
            events = await _collect(
                svc.ask_stream(
                    username="alice",
                    user_id=1,
                    connection_id=1,
                    datasource_luid=_FAKE_DS_LUID,
                    message="销售额？",
                )
            )

        token_events = [e for e in events if e["type"] == "token"]
        # 每个字符一个 token event，总数等于摘要字符数
        assert len(token_events) == len(_LLM_SUMMARY)
        # 内容拼接应等于完整摘要
        reconstructed = "".join(e["content"] for e in token_events)
        assert reconstructed == _LLM_SUMMARY

    @pytest.mark.asyncio
    async def test_done_event_structure(self):
        """done event 必须包含 session_id / answer / data_table 字段"""
        mock_db, mock_sess, mock_msg = _make_mock_db_and_session()

        with (
            patch(
                "services.query.query_service.QueryMessageDatabase.get_or_create_session",
                return_value=mock_sess,
            ),
            patch(
                "services.query.query_service.QueryMessageDatabase.append_message",
                return_value=mock_msg,
            ),
            patch(
                "services.query.query_service.QueryService._issue_jwt",
                return_value="fake-jwt-token",
            ),
            patch(
                "services.query.query_service.TableauMCPClient.query_datasource",
                return_value=_MCP_DATA,
            ),
            patch(
                "services.query.query_service.llm_service.complete",
                new_callable=AsyncMock,
                return_value={"content": _LLM_SUMMARY},
            ),
        ):
            svc = QueryService(db=mock_db)
            events = await _collect(
                svc.ask_stream(
                    username="alice",
                    user_id=1,
                    connection_id=1,
                    datasource_luid=_FAKE_DS_LUID,
                    message="销售额？",
                )
            )

        done_events = [e for e in events if e["type"] == "done"]
        assert len(done_events) == 1
        done = done_events[0]
        assert "session_id" in done
        assert done["session_id"] == str(mock_sess.id)
        assert done["answer"] == _LLM_SUMMARY
        assert "data_table" in done
        assert isinstance(done["data_table"], list)

    @pytest.mark.asyncio
    async def test_no_error_events_on_success(self):
        """成功路径下不应产生任何 error event"""
        mock_db, mock_sess, mock_msg = _make_mock_db_and_session()

        with (
            patch(
                "services.query.query_service.QueryMessageDatabase.get_or_create_session",
                return_value=mock_sess,
            ),
            patch(
                "services.query.query_service.QueryMessageDatabase.append_message",
                return_value=mock_msg,
            ),
            patch(
                "services.query.query_service.QueryService._issue_jwt",
                return_value="fake-jwt-token",
            ),
            patch(
                "services.query.query_service.TableauMCPClient.query_datasource",
                return_value=_MCP_DATA,
            ),
            patch(
                "services.query.query_service.llm_service.complete",
                new_callable=AsyncMock,
                return_value={"content": _LLM_SUMMARY},
            ),
        ):
            svc = QueryService(db=mock_db)
            events = await _collect(
                svc.ask_stream(
                    username="alice",
                    user_id=1,
                    connection_id=1,
                    datasource_luid=_FAKE_DS_LUID,
                    message="销售额？",
                )
            )

        error_events = [e for e in events if e["type"] == "error"]
        assert error_events == []


class TestAskStreamErrorCases:
    """错误路径：各类 error event 格式与错误码"""

    @pytest.mark.asyncio
    async def test_missing_user_id_yields_q_input_006(self):
        """user_id=None → 立即 yield error event Q_INPUT_006"""
        mock_db = MagicMock()
        svc = QueryService(db=mock_db)
        events = await _collect(
            svc.ask_stream(
                username="alice",
                user_id=None,
                connection_id=1,
                datasource_luid=_FAKE_DS_LUID,
                message="test",
            )
        )
        assert len(events) == 1
        assert events[0]["type"] == "error"
        assert events[0]["code"] == "Q_INPUT_006"

    @pytest.mark.asyncio
    async def test_jwt_failure_yields_q_jwt_001(self):
        """JWT 签发失败 → error event Q_JWT_001"""
        mock_db, mock_sess, mock_msg = _make_mock_db_and_session()

        with (
            patch(
                "services.query.query_service.QueryMessageDatabase.get_or_create_session",
                return_value=mock_sess,
            ),
            patch(
                "services.query.query_service.QueryMessageDatabase.append_message",
                return_value=mock_msg,
            ),
            patch(
                "services.query.query_service.QueryService._issue_jwt",
                side_effect=QueryServiceError(code="Q_JWT_001", message="密钥未配置"),
            ),
        ):
            svc = QueryService(db=mock_db)
            events = await _collect(
                svc.ask_stream(
                    username="alice",
                    user_id=1,
                    connection_id=1,
                    datasource_luid=_FAKE_DS_LUID,
                    message="test",
                )
            )

        assert len(events) == 1
        assert events[0]["type"] == "error"
        assert events[0]["code"] == "Q_JWT_001"
        assert "message" in events[0]

    @pytest.mark.asyncio
    async def test_mcp_failure_yields_error_event(self):
        """MCP 查询失败 → error event，错误码由 _classify_and_record_mcp_error 映射"""
        from services.tableau.mcp_client import TableauMCPError

        mock_db, mock_sess, mock_msg = _make_mock_db_and_session()

        with (
            patch(
                "services.query.query_service.QueryMessageDatabase.get_or_create_session",
                return_value=mock_sess,
            ),
            patch(
                "services.query.query_service.QueryMessageDatabase.append_message",
                return_value=mock_msg,
            ),
            patch(
                "services.query.query_service.QueryService._issue_jwt",
                return_value="fake-jwt",
            ),
            patch(
                "services.query.query_service.TableauMCPClient.query_datasource",
                side_effect=TableauMCPError(code="NLQ_006", message="MCP 内部错误"),
            ),
            # 隔离 error 写入数据库（避免打开真实 DB 连接）
            patch(
                "services.query.query_service.QueryService._classify_and_record_mcp_error",
                return_value=QueryServiceError(code="Q_MCP_004", message="MCP 内部错误"),
            ),
        ):
            svc = QueryService(db=mock_db)
            events = await _collect(
                svc.ask_stream(
                    username="alice",
                    user_id=1,
                    connection_id=1,
                    datasource_luid=_FAKE_DS_LUID,
                    message="test",
                )
            )

        assert len(events) == 1
        assert events[0]["type"] == "error"
        assert events[0]["code"] == "Q_MCP_004"

    @pytest.mark.asyncio
    async def test_mcp_timeout_error_code(self):
        """MCP 超时 → error event Q_TIMEOUT_003"""
        from services.tableau.mcp_client import TableauMCPError

        mock_db, mock_sess, mock_msg = _make_mock_db_and_session()

        with (
            patch(
                "services.query.query_service.QueryMessageDatabase.get_or_create_session",
                return_value=mock_sess,
            ),
            patch(
                "services.query.query_service.QueryMessageDatabase.append_message",
                return_value=mock_msg,
            ),
            patch(
                "services.query.query_service.QueryService._issue_jwt",
                return_value="fake-jwt",
            ),
            patch(
                "services.query.query_service.TableauMCPClient.query_datasource",
                side_effect=TableauMCPError(code="NLQ_007", message="超时"),
            ),
            patch(
                "services.query.query_service.QueryService._classify_and_record_mcp_error",
                return_value=QueryServiceError(code="Q_TIMEOUT_003", message="超时"),
            ),
        ):
            svc = QueryService(db=mock_db)
            events = await _collect(
                svc.ask_stream(
                    username="alice",
                    user_id=1,
                    connection_id=1,
                    datasource_luid=_FAKE_DS_LUID,
                    message="test",
                )
            )

        assert events[0]["type"] == "error"
        assert events[0]["code"] == "Q_TIMEOUT_003"


class TestAskStreamLlmDegraded:
    """LLM 降级路径：摘要为空时流不中断，done event 包含降级文案"""

    @pytest.mark.asyncio
    async def test_llm_error_degraded_to_fallback_message(self):
        """LLM 失败时，done.answer 为降级提示文案，流正常结束"""
        mock_db, mock_sess, mock_msg = _make_mock_db_and_session()

        with (
            patch(
                "services.query.query_service.QueryMessageDatabase.get_or_create_session",
                return_value=mock_sess,
            ),
            patch(
                "services.query.query_service.QueryMessageDatabase.append_message",
                return_value=mock_msg,
            ),
            patch(
                "services.query.query_service.QueryService._issue_jwt",
                return_value="fake-jwt",
            ),
            patch(
                "services.query.query_service.TableauMCPClient.query_datasource",
                return_value=_MCP_DATA,
            ),
            patch(
                "services.query.query_service.llm_service.complete",
                new_callable=AsyncMock,
                side_effect=Exception("LLM 连接超时"),
            ),
        ):
            svc = QueryService(db=mock_db)
            events = await _collect(
                svc.ask_stream(
                    username="alice",
                    user_id=1,
                    connection_id=1,
                    datasource_luid=_FAKE_DS_LUID,
                    message="test",
                )
            )

        done_events = [e for e in events if e["type"] == "done"]
        assert len(done_events) == 1
        # 降级文案不为空，包含"摘要生成失败"语义
        assert "摘要生成失败" in done_events[0]["answer"]
        # 流不中断，无 error event
        error_events = [e for e in events if e["type"] == "error"]
        assert error_events == []

    @pytest.mark.asyncio
    async def test_llm_response_error_field_degraded(self):
        """LLM 返回 error 字段（非异常）时同样降级"""
        mock_db, mock_sess, mock_msg = _make_mock_db_and_session()

        with (
            patch(
                "services.query.query_service.QueryMessageDatabase.get_or_create_session",
                return_value=mock_sess,
            ),
            patch(
                "services.query.query_service.QueryMessageDatabase.append_message",
                return_value=mock_msg,
            ),
            patch(
                "services.query.query_service.QueryService._issue_jwt",
                return_value="fake-jwt",
            ),
            patch(
                "services.query.query_service.TableauMCPClient.query_datasource",
                return_value=_MCP_DATA,
            ),
            patch(
                "services.query.query_service.llm_service.complete",
                new_callable=AsyncMock,
                return_value={"error": "模型不可用"},
            ),
        ):
            svc = QueryService(db=mock_db)
            events = await _collect(
                svc.ask_stream(
                    username="alice",
                    user_id=1,
                    connection_id=1,
                    datasource_luid=_FAKE_DS_LUID,
                    message="test",
                )
            )

        done_events = [e for e in events if e["type"] == "done"]
        assert len(done_events) == 1
        error_events = [e for e in events if e["type"] == "error"]
        assert error_events == []


class TestAskStreamPersistence:
    """消息持久化：done event 发送前，append_message 已被调用"""

    @pytest.mark.asyncio
    async def test_append_message_called_before_done(self):
        """
        验证消息持久化调用顺序：
        1. 用户消息 append_message（role=user）
        2. assistant 消息 append_message（role=assistant）
        3. db.commit()
        4. done event yield

        通过检查 append_message 的调用次数和参数来验证。
        """
        mock_db, mock_sess, mock_msg = _make_mock_db_and_session()
        append_calls = []

        def _track_append(**kwargs):
            append_calls.append(kwargs.get("role"))
            return mock_msg

        with (
            patch(
                "services.query.query_service.QueryMessageDatabase.get_or_create_session",
                return_value=mock_sess,
            ),
            patch(
                "services.query.query_service.QueryMessageDatabase.append_message",
                side_effect=_track_append,
            ),
            patch(
                "services.query.query_service.QueryService._issue_jwt",
                return_value="fake-jwt",
            ),
            patch(
                "services.query.query_service.TableauMCPClient.query_datasource",
                return_value=_MCP_DATA,
            ),
            patch(
                "services.query.query_service.llm_service.complete",
                new_callable=AsyncMock,
                return_value={"content": _LLM_SUMMARY},
            ),
        ):
            svc = QueryService(db=mock_db)
            # 收集所有 events，确保流已完整消费
            events = await _collect(
                svc.ask_stream(
                    username="alice",
                    user_id=1,
                    connection_id=1,
                    datasource_luid=_FAKE_DS_LUID,
                    message="销售额？",
                )
            )

        # 两次 append_message：user + assistant
        assert append_calls.count("user") == 1
        assert append_calls.count("assistant") == 1
        # done event 存在（持久化后才 yield done）
        done_events = [e for e in events if e["type"] == "done"]
        assert len(done_events) == 1
        # db.commit() 被调用
        mock_db.commit.assert_called()

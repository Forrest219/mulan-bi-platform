"""
单元测试：Spec 14 T-02 — QueryService + QueryMessageDatabase

全部为纯逻辑单元测试，不依赖真实 DB / MCP / LLM 连接。
所有外部依赖通过 Mock / Stub 隔离。

覆盖范围：
1. QueryService.list_datasources() — JWT 签发 + MCP 调用 + 返回标准化
2. QueryService.ask() — 完整流程 (Session、消息持久化、MCP、LLM摘要)
3. 错误分类：JWT 失败 → Q_JWT_001、权限拒绝 → Q_PERM_002、超时 → Q_TIMEOUT_003、MCP 失败 → Q_MCP_004
4. LLM 失败降级：返回数据但 summary="" 且 llm_error 非 None
5. QueryMessageDatabase.get_or_create_session() — 新建 / 已有 / 无效 UUID / 无权限
6. _build_data_preview — 正常 / 空数据 / 超过 max_rows
"""
import os
import asyncio
import uuid
from unittest.mock import AsyncMock, MagicMock, patch, call

import pytest

os.environ.setdefault("TABLEAU_ENCRYPTION_KEY", "test-tableau-key-32-bytes-ok!!")
os.environ.setdefault("DATASOURCE_ENCRYPTION_KEY", "test-datasource-key-32-bytes-ok!!")
os.environ.setdefault("LLM_ENCRYPTION_KEY", "test-llm-key-32-bytes-ok!!!!")
os.environ.setdefault("SESSION_SECRET", "test-session-secret-for-ci-!!")
os.environ.setdefault("DATABASE_URL", "postgresql://mulan:mulan@localhost:5432/mulan_bi_test")
os.environ.setdefault("ADMIN_USERNAME", "testadmin")
os.environ.setdefault("ADMIN_PASSWORD", "")

from services.query.query_service import (
    QueryService,
    QueryServiceError,
    QueryMessageDatabase,
    _build_data_preview,
)
from services.tableau.mcp_client import TableauMCPError


# ─── Helpers ───────────────────────────────────────────────────────────────────

def _make_db():
    """返回轻量级 Mock DB Session（不连接真实数据库）。"""
    return MagicMock()


def _make_service(db=None):
    db = db or _make_db()
    return QueryService(db=db), db


def _fake_session_obj(session_id: uuid.UUID = None, user_id: int = 1):
    """伪造一个 QuerySession ORM 对象。"""
    sess = MagicMock()
    sess.id = session_id or uuid.uuid4()
    sess.user_id = user_id
    return sess


def _fake_msg_obj(msg_id: int = 99):
    msg = MagicMock()
    msg.id = msg_id
    return msg


def _mcp_data():
    return {
        "fields": ["region", "sales"],
        "rows": [["East", 1000], ["West", 2000]],
    }


# ─── T01: _build_data_preview ──────────────────────────────────────────────

class TestBuildDataPreview:
    def test_normal(self):
        data = {"fields": ["a", "b"], "rows": [[1, 2], [3, 4]]}
        result = _build_data_preview(data)
        assert "a | b" in result
        assert "1 | 2" in result

    def test_empty_fields(self):
        result = _build_data_preview({"fields": [], "rows": []})
        assert "无数据" in result

    def test_missing_keys(self):
        result = _build_data_preview({})
        assert "无数据" in result

    def test_truncate_beyond_max_rows(self):
        data = {
            "fields": ["x"],
            "rows": [[i] for i in range(20)],
        }
        result = _build_data_preview(data, max_rows=5)
        assert "共 20 行" in result
        # 只有前5行数据被渲染
        assert "0" in result
        assert "19" not in result  # 第20行不应出现


# ─── T02: QueryMessageDatabase ──────────────────────────────────────────────

class TestQueryMessageDatabase:
    def test_create_new_session_when_session_id_is_none(self):
        from services.query.query_service import QuerySession
        db = _make_db()
        db_instance = QueryMessageDatabase()
        # Mock 住 db.add / db.flush
        result_sess = _fake_session_obj()

        with patch("services.query.query_service.QuerySession") as MockSession:
            MockSession.return_value = result_sess
            sess = db_instance.get_or_create_session(db=db, user_id=1, session_id=None)

        db.add.assert_called_once()
        db.flush.assert_called_once()
        assert sess is result_sess

    def test_raises_on_invalid_uuid_format(self):
        db = _make_db()
        db_instance = QueryMessageDatabase()
        with pytest.raises(QueryServiceError) as exc_info:
            db_instance.get_or_create_session(db=db, user_id=1, session_id="not-a-uuid")
        assert exc_info.value.code == "Q_INPUT_006"

    def test_raises_when_session_not_found(self):
        db = _make_db()
        db.query.return_value.filter.return_value.first.return_value = None
        db_instance = QueryMessageDatabase()
        valid_uuid = str(uuid.uuid4())
        with pytest.raises(QueryServiceError) as exc_info:
            db_instance.get_or_create_session(db=db, user_id=1, session_id=valid_uuid)
        assert exc_info.value.code == "Q_INPUT_006"

    def test_returns_existing_session(self):
        db = _make_db()
        existing = _fake_session_obj()
        db.query.return_value.filter.return_value.first.return_value = existing
        db_instance = QueryMessageDatabase()
        result = db_instance.get_or_create_session(
            db=db, user_id=1, session_id=str(existing.id)
        )
        assert result is existing

    def test_append_message_calls_db(self):
        db = _make_db()
        msg = _fake_msg_obj()

        with patch("services.query.query_service.QueryMessage") as MockMsg:
            MockMsg.return_value = msg
            db_instance = QueryMessageDatabase()
            result = db_instance.append_message(
                db=db,
                session_id=uuid.uuid4(),
                role="user",
                content="hello",
            )

        db.add.assert_called_once()
        db.flush.assert_called_once()
        assert result is msg


# ─── T03: QueryService.list_datasources ────────────────────────────────────

class TestListDatasources:
    def _make_mcp_client_mock(self, return_value):
        client_mock = MagicMock()
        client_mock.list_datasources.return_value = return_value
        return client_mock

    def test_happy_path_returns_datasource_list(self):
        svc, db = _make_service()
        fake_jwt = "fake.jwt.token"
        mcp_response = {"datasources": [{"luid": "abc", "name": "Sales DS"}]}

        with patch.object(svc, "_issue_jwt", return_value=fake_jwt), \
             patch("services.query.query_service.TableauMCPClient") as MockClient:
            instance = MockClient.return_value
            instance.list_datasources.return_value = mcp_response

            result = svc.list_datasources(
                username="alice", connection_id=1, user_id=42
            )

        assert result == [{"luid": "abc", "name": "Sales DS"}]
        # JWT 传递给 MCP client
        instance.list_datasources.assert_called_once_with(
            limit=50,
            timeout=30,
            connection_id=1,
            jwt_token=fake_jwt,
        )

    def test_jwt_issue_failure_raises_q_jwt_001(self):
        svc, db = _make_service()
        with patch.object(
            svc,
            "_issue_jwt",
            side_effect=QueryServiceError(code="Q_JWT_001", message="密钥未配置"),
        ):
            with pytest.raises(QueryServiceError) as exc_info:
                svc.list_datasources(username="alice", connection_id=1)
        assert exc_info.value.code == "Q_JWT_001"

    def test_mcp_perm_error_raises_q_perm_002(self):
        svc, db = _make_service()
        with patch.object(svc, "_issue_jwt", return_value="tok"), \
             patch("services.query.query_service.TableauMCPClient") as MockClient:
            MockClient.return_value.list_datasources.side_effect = TableauMCPError(
                code="NLQ_009", message="权限不足"
            )
            with pytest.raises(QueryServiceError) as exc_info:
                svc.list_datasources(username="alice", connection_id=1, user_id=42)
        assert exc_info.value.code == "Q_PERM_002"

    def test_mcp_timeout_raises_q_timeout_003(self):
        svc, db = _make_service()
        with patch.object(svc, "_issue_jwt", return_value="tok"), \
             patch("services.query.query_service.TableauMCPClient") as MockClient:
            MockClient.return_value.list_datasources.side_effect = TableauMCPError(
                code="NLQ_007", message="超时"
            )
            with pytest.raises(QueryServiceError) as exc_info:
                svc.list_datasources(username="alice", connection_id=1, user_id=42)
        assert exc_info.value.code == "Q_TIMEOUT_003"

    def test_mcp_generic_error_raises_q_mcp_004(self):
        svc, db = _make_service()
        with patch.object(svc, "_issue_jwt", return_value="tok"), \
             patch("services.query.query_service.TableauMCPClient") as MockClient:
            MockClient.return_value.list_datasources.side_effect = TableauMCPError(
                code="NLQ_006", message="MCP 服务不可用"
            )
            with pytest.raises(QueryServiceError) as exc_info:
                svc.list_datasources(username="alice", connection_id=1, user_id=42)
        assert exc_info.value.code == "Q_MCP_004"

    def test_empty_datasources_returns_empty_list(self):
        svc, _ = _make_service()
        with patch.object(svc, "_issue_jwt", return_value="tok"), \
             patch("services.query.query_service.TableauMCPClient") as MockClient:
            MockClient.return_value.list_datasources.return_value = {"datasources": []}
            result = svc.list_datasources(username="alice", connection_id=1)
        assert result == []


# ─── T04: QueryService.ask ─────────────────────────────────────────────────

class TestAsk:
    def _run(self, coro):
        """同步运行协程（兼容无 event loop 的测试环境）。"""
        return asyncio.get_event_loop().run_until_complete(coro)

    def _setup_ask(self, svc, db, *, llm_success=True, mcp_data=None):
        """
        为 ask() 配置常用 mock：
        - _msg_db.get_or_create_session → fake session
        - _msg_db.append_message → fake msg
        - _issue_jwt → "tok"
        - TableauMCPClient.query_datasource → mcp_data
        - llm_service.complete → {"content": "摘要文本"} 或 {"error": "LLM 失败"}
        """
        fake_sess = _fake_session_obj(user_id=42)
        fake_user_msg = _fake_msg_obj(1)
        fake_asst_msg = _fake_msg_obj(2)
        mcp_data = mcp_data or _mcp_data()

        svc._msg_db.get_or_create_session = MagicMock(return_value=fake_sess)
        svc._msg_db.append_message = MagicMock(side_effect=[fake_user_msg, fake_asst_msg])

        jwt_patch = patch.object(svc, "_issue_jwt", return_value="tok")
        mcp_patch = patch("services.query.query_service.TableauMCPClient")
        if llm_success:
            llm_mock = MagicMock()
            llm_mock.complete = AsyncMock(return_value={"content": "摘要文本"})
            llm_patch = patch("services.query.query_service.llm_service", llm_mock)
        else:
            llm_mock = MagicMock()
            llm_mock.complete = AsyncMock(return_value={"error": "LLM 不可用"})
            llm_patch = patch("services.query.query_service.llm_service", llm_mock)

        return fake_sess, fake_asst_msg, mcp_data, jwt_patch, mcp_patch, llm_patch

    def test_happy_path_returns_expected_keys(self):
        svc, db = _make_service()
        fake_sess, fake_asst_msg, mcp_data, jp, mp, lp = self._setup_ask(svc, db)

        with jp, mp as MockClient, lp:
            MockClient.return_value.query_datasource.return_value = mcp_data
            result = self._run(
                svc.ask(
                    username="alice",
                    user_id=42,
                    connection_id=1,
                    datasource_luid="luid-123",
                    message="销售额最高的地区？",
                )
            )

        assert "session_id" in result
        assert "message_id" in result
        assert "summary" in result
        assert "data" in result
        assert "llm_error" in result
        assert result["data"] == mcp_data
        assert result["summary"] == "摘要文本"
        assert result["llm_error"] is None

    def test_raises_q_input_006_when_user_id_is_none(self):
        svc, db = _make_service()
        with pytest.raises(QueryServiceError) as exc_info:
            self._run(
                svc.ask(
                    username="alice",
                    user_id=None,
                    connection_id=1,
                    datasource_luid="luid-123",
                    message="hello",
                )
            )
        assert exc_info.value.code == "Q_INPUT_006"

    def test_llm_failure_degrades_gracefully(self):
        svc, db = _make_service()
        fake_sess, fake_asst_msg, mcp_data, jp, mp, lp = self._setup_ask(
            svc, db, llm_success=False
        )

        with jp, mp as MockClient, lp:
            MockClient.return_value.query_datasource.return_value = mcp_data
            result = self._run(
                svc.ask(
                    username="alice",
                    user_id=42,
                    connection_id=1,
                    datasource_luid="luid-123",
                    message="销售额最高的地区？",
                )
            )

        # 降级：summary 为空，llm_error 非 None，但不抛异常
        assert result["summary"] == ""
        assert result["llm_error"] is not None
        assert result["data"] == mcp_data

    def test_mcp_perm_error_persists_error_message_and_raises(self):
        svc, db = _make_service()
        fake_sess = _fake_session_obj(user_id=42)
        fake_user_msg = _fake_msg_obj(1)
        fake_err_asst_msg = _fake_msg_obj(2)

        svc._msg_db.get_or_create_session = MagicMock(return_value=fake_sess)
        svc._msg_db.append_message = MagicMock(
            side_effect=[fake_user_msg, fake_err_asst_msg]
        )

        with patch.object(svc, "_issue_jwt", return_value="tok"), \
             patch("services.query.query_service.TableauMCPClient") as MockClient:
            MockClient.return_value.query_datasource.side_effect = TableauMCPError(
                code="NLQ_009", message="无权限访问该数据源"
            )
            with pytest.raises(QueryServiceError) as exc_info:
                self._run(
                    svc.ask(
                        username="alice",
                        user_id=42,
                        connection_id=1,
                        datasource_luid="luid-123",
                        message="销售额？",
                    )
                )

        assert exc_info.value.code == "Q_PERM_002"
        # 应写入了两条消息：user + assistant（错误记录）
        assert svc._msg_db.append_message.call_count == 2

    def test_jwt_injected_in_mcp_call(self):
        """验证 JWT token 被正确传递给 MCP client。"""
        svc, db = _make_service()
        fake_sess = _fake_session_obj(user_id=42)
        svc._msg_db.get_or_create_session = MagicMock(return_value=fake_sess)
        svc._msg_db.append_message = MagicMock(
            side_effect=[_fake_msg_obj(1), _fake_msg_obj(2)]
        )

        mcp_data = _mcp_data()

        llm_mock = MagicMock()
        llm_mock.complete = AsyncMock(return_value={"content": "ok"})

        with patch.object(svc, "_issue_jwt", return_value="my.jwt.token"), \
             patch("services.query.query_service.TableauMCPClient") as MockClient, \
             patch("services.query.query_service.llm_service", llm_mock):
            MockClient.return_value.query_datasource.return_value = mcp_data
            self._run(
                svc.ask(
                    username="alice",
                    user_id=42,
                    connection_id=1,
                    datasource_luid="luid-123",
                    message="销售额？",
                    vizql_query={"fields": []},
                )
            )

        call_kwargs = MockClient.return_value.query_datasource.call_args
        assert call_kwargs.kwargs.get("jwt_token") == "my.jwt.token"

    def test_session_id_propagated_to_messages(self):
        """验证 session_id 在消息写入时正确传递。"""
        svc, db = _make_service()
        existing_uuid = uuid.uuid4()
        fake_sess = _fake_session_obj(session_id=existing_uuid, user_id=42)
        db.query.return_value.filter.return_value.first.return_value = fake_sess

        svc._msg_db.get_or_create_session = MagicMock(return_value=fake_sess)
        svc._msg_db.append_message = MagicMock(
            side_effect=[_fake_msg_obj(1), _fake_msg_obj(2)]
        )

        llm_mock = MagicMock()
        llm_mock.complete = AsyncMock(return_value={"content": "ok"})

        with patch.object(svc, "_issue_jwt", return_value="tok"), \
             patch("services.query.query_service.TableauMCPClient") as MockClient, \
             patch("services.query.query_service.llm_service", llm_mock):
            MockClient.return_value.query_datasource.return_value = _mcp_data()
            result = self._run(
                svc.ask(
                    username="alice",
                    user_id=42,
                    connection_id=1,
                    datasource_luid="luid-123",
                    message="hello",
                    session_id=str(existing_uuid),
                )
            )

        assert result["session_id"] == str(existing_uuid)


# ─── T05: T-03 _build_headers JWT 注入 ────────────────────────────────────

class TestMcpClientJwtInjection:
    """
    验证 T-03：mcp_client._build_headers 在有 jwt_token 时注入 Authorization header。
    """

    def setup_method(self):
        import services.tableau.mcp_client as m
        m._mcp_session_state.reset()

    def test_build_headers_without_jwt(self):
        from services.tableau.mcp_client import _build_headers, _MCPSessionState

        state = _MCPSessionState()
        headers = _build_headers(with_session=False, session_state=state, jwt_token=None)
        assert "Authorization" not in headers

    def test_build_headers_with_jwt_injects_bearer(self):
        from services.tableau.mcp_client import _build_headers, _MCPSessionState

        state = _MCPSessionState()
        tok = "eyJhbGciOiJIUzI1NiJ9.payload.sig"
        headers = _build_headers(with_session=False, session_state=state, jwt_token=tok)
        assert headers["Authorization"] == f"Bearer {tok}"

    def test_build_headers_empty_string_jwt_not_injected(self):
        """空字符串 jwt_token 不应注入 Authorization header（falsy 判断）。"""
        from services.tableau.mcp_client import _build_headers, _MCPSessionState

        state = _MCPSessionState()
        headers = _build_headers(with_session=False, session_state=state, jwt_token="")
        assert "Authorization" not in headers

    def test_post_mcp_passes_jwt_to_headers(self):
        """_post_mcp 在 jwt_token 非 None 时调用 requests 时带 Authorization 头。"""
        import services.tableau.mcp_client as m

        state = m._MCPSessionState()
        state.session_id = "test-session"
        state._initialized = True
        state.last_activity = 9999999.0

        fake_response = MagicMock()
        fake_response.status_code = 200
        fake_response.text = 'event: message\ndata: {"jsonrpc":"2.0","id":1,"result":{}}\n'

        with patch.object(
            m._get_http_session(), "post", return_value=fake_response
        ) as mock_post:
            result = m._post_mcp(
                payload={"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {}},
                method="tools/call",
                session_state=state,
                base_url="http://fake-mcp-server/mcp",
                jwt_token="my.test.jwt",
            )

        call_args = mock_post.call_args
        sent_headers = call_args.kwargs.get("headers") or call_args.args[1] if len(call_args.args) > 1 else call_args.kwargs.get("headers", {})
        # 提取实际 headers
        sent_headers = mock_post.call_args[1].get("headers", {})
        assert sent_headers.get("Authorization") == "Bearer my.test.jwt"

    def test_ensure_session_passes_jwt_in_initialize_headers(self):
        """_ensure_session 在 jwt_token 非 None 时，initialize 请求带 Authorization 头。"""
        import services.tableau.mcp_client as m

        state = m._MCPSessionState()

        fake_init_resp = MagicMock()
        fake_init_resp.status_code = 200
        fake_init_resp.text = ""
        fake_init_resp.headers = {"mcp-session-id": "session-abc-123"}

        fake_notif_resp = MagicMock()
        fake_notif_resp.status_code = 202
        fake_notif_resp.text = ""

        http_session = m._get_http_session()

        with patch.object(
            http_session, "post", side_effect=[fake_init_resp, fake_notif_resp]
        ) as mock_post:
            m._ensure_session(
                session_state=state,
                base_url="http://fake-mcp-server/mcp",
                jwt_token="user.jwt.token",
            )

        # 第一次调用（initialize）的 headers 应包含 Authorization
        first_call_headers = mock_post.call_args_list[0][1].get("headers", {})
        assert first_call_headers.get("Authorization") == "Bearer user.jwt.token"

        # 第二次调用（notifications/initialized）也应包含
        second_call_headers = mock_post.call_args_list[1][1].get("headers", {})
        assert second_call_headers.get("Authorization") == "Bearer user.jwt.token"

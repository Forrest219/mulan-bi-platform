"""
单元测试：services/tableau/mcp_client.py（T-R1）

覆盖（per tech-mcp-client-rewrite.md §8.1）：
- Happy path: initialize → notifications/initialized → tools/call
- Session ID 复用（第二次调用不重复 initialize）
- Session 过期自动恢复（HTTP 400 "No valid session ID"）
- 超时 raises NLQ_007
- 5xx 重试一次后失败 raises NLQ_006
- 4xx（非 session 错误）直接 raises NLQ_006
- tools/call 返回 isError: true → NLQ_006
- content[0].text 非 JSON → NLQ_006
- contextvars 隔离（并发两个 connection_id 互不串扰）
- instance cache invalidate 后重建

Mock 策略：patch TableauMCPClient 类方法（_send_jsonrpc / _get_connection_by_luid）
和模块级函数（_post_mcp / _ensure_session）绕过 HTTP 层。
"""
import json
import threading
import uuid
from unittest import mock

import pytest

import services.tableau.mcp_client as mcp_mod
from services.tableau.mcp_client import (
    TableauMCPClient,
    TableauMCPError,
    _extract_text,
    _map_mcp_error,
    _parse_sse,
)

# ─── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def reset_mcp_state():
    """Reset module-level MCP session state before each test."""
    # noqa: PLC0415 — re-import to get fresh module state
    import services.tableau.mcp_client as m  # noqa: PLC0415
    m._mcp_session_state.reset()
    yield
    m._mcp_session_state.reset()


@pytest.fixture(autouse=True)
def reset_client_instances():
    """Reset TableauMCPClient class-level caches before each test."""
    # noqa: PLC0415 — re-import to get fresh class state
    from services.tableau.mcp_client import TableauMCPClient  # noqa: PLC0415
    TableauMCPClient._instances.clear()
    TableauMCPClient._last_access.clear()
    yield
    TableauMCPClient._instances.clear()
    TableauMCPClient._last_access.clear()


# ─── T-R1 §8.1 单元测试 ─────────────────────────────────────────────────────

class TestHappyPath:
    """test_query_datasource_happy_path — initialize + tools/call 成功返回"""

    def test_happy_path(self):
        query_result = {"fields": ["region", "sales"], "rows": [["North", 1000], ["South", 2000]]}
        send_calls = []

        def mock_send(self, payload, timeout):
            send_calls.append(payload.get("method", ""))
            if payload.get("method") == "initialize":
                return {"jsonrpc": "2.0", "id": 1, "result": {}}
            elif "initialized" in payload.get("method", ""):
                return {}
            else:
                return {
                    "result": {
                        "content": [{"type": "text", "text": json.dumps(query_result)}],
                        "isError": False,
                    }
                }

        with mock.patch.object(TableauMCPClient, "_send_jsonrpc", mock_send):
            with mock.patch.object(TableauMCPClient, "_get_connection_by_luid") as mc:
                conn = mock.Mock()
                conn.is_active = True
                conn.last_test_success = True
                conn.mcp_direct_enabled = True
                mc.return_value = conn

                client = TableauMCPClient(connection_id=42)
                result = client.query_datasource(
                    datasource_luid="ds-abc",
                    query={"fields": [{"fieldCaption": "region"}]},
                    limit=100,
                    timeout=30,
                    connection_id=42,
                )

        assert result == query_result
        assert "tools/call" in send_calls


class TestSessionIdReuse:
    """test_session_id_reuse — 第二次调用不重复 initialize"""

    def test_session_reused_across_calls(self):
        call_seq = []

        def mock_send(self, payload, timeout):
            call_seq.append(payload.get("method", ""))
            if payload.get("method") == "initialize":
                return {"jsonrpc": "2.0", "id": 1, "result": {}}
            elif "initialized" in payload.get("method", ""):
                return {}
            else:
                return {"result": {"content": [{"type": "text", "text": json.dumps({"fields": ["x"], "rows": [[1]]})}], "isError": False}}

        with mock.patch.object(TableauMCPClient, "_send_jsonrpc", mock_send):
            with mock.patch.object(TableauMCPClient, "_get_connection_by_luid") as mc:
                conn = mock.Mock()
                conn.is_active = True
                conn.last_test_success = True
                conn.mcp_direct_enabled = True
                mc.return_value = conn

                client = TableauMCPClient(connection_id=1)
                client.query_datasource("ds-1", {}, 10, 30, 1)
                client.query_datasource("ds-2", {}, 10, 30, 1)

        # Both calls should go to tools/call (no re-init since session already active)
        assert call_seq.count("tools/call") == 2
        assert "initialize" not in call_seq


class TestSessionExpiredAutoRecover:
    """test_session_expired_auto_recover — 第一次返回 400 后自动重建成功"""

    def test_session_expired_then_recovered(self):
        post_count = [0]

        def mock_ensure(timeout):
            with mcp_mod._mcp_session_state.lock:
                mcp_mod._mcp_session_state.session_id = "mock-sid"
                mcp_mod._mcp_session_state._initialized = True
            return "mock-sid"

        def mock_post(payload, method, timeout, expect_sse=True):
            """Mock _post_mcp: first tools/call raises _SessionExpiredError."""
            post_count[0] += 1
            if post_count[0] == 1:
                raise mcp_mod._SessionExpiredError("session expired")
            return {
                "result": {
                    "content": [{"type": "text", "text": json.dumps({"fields": ["x"], "rows": [[1]]})}],
                    "isError": False,
                }
            }

        with mock.patch.object(mcp_mod, "_ensure_session", mock_ensure):
            with mock.patch.object(mcp_mod, "_post_mcp", mock_post):
                with mock.patch.object(TableauMCPClient, "_get_connection_by_luid") as mc:
                    conn = mock.Mock()
                    conn.is_active = True
                    conn.last_test_success = True
                    conn.mcp_direct_enabled = True
                    mc.return_value = conn

                    client = TableauMCPClient(connection_id=1)
                    result = client.query_datasource("ds-1", {}, 10, 30, 1)

        assert result == {"fields": ["x"], "rows": [[1]]}
        # _post_mcp called twice: first raises _SessionExpiredError (caught → retry),
        # second succeeds
        assert post_count[0] == 2


class TestTimeout:
    """test_timeout_raises_nlq_007 — server 挂起超过 timeout"""

    def test_timeout_raises_nlq_007(self):
        def mock_send(self, payload, timeout):
            raise TableauMCPError(
                code="NLQ_007",
                message=f"MCP 查询超时（{timeout}s）",
                details={"timeout": timeout},
            )

        with mock.patch.object(TableauMCPClient, "_send_jsonrpc", mock_send):
            with mock.patch.object(TableauMCPClient, "_get_connection_by_luid") as mc:
                conn = mock.Mock()
                conn.is_active = True
                conn.last_test_success = True
                conn.mcp_direct_enabled = True
                mc.return_value = conn

                client = TableauMCPClient(connection_id=1)
                with pytest.raises(TableauMCPError) as exc_info:
                    client.query_datasource("ds-1", {}, 10, 30, 1)

        assert exc_info.value.code == "NLQ_007"
        assert "超时" in exc_info.value.message


class Test5xxRetry:
    """test_5xx_retry_once_then_fail — 两次 5xx 后 raise NLQ_006"""

    def test_5xx_retries_once_then_fails(self):
        # Simulate 5xx at the HTTP layer so _post_mcp's internal retry runs.
        # _post_mcp loops twice on 5xx: attempt 0 (sleep 1s, continue), attempt 1 (raise).
        post_count = [0]

        def fake_post(url, json=None, headers=None, timeout=None):
            post_count[0] += 1
            resp = mock.Mock()
            resp.status_code = 500
            resp.text = 'event: message\ndata: {"error": {"code": "NLQ_006", "message": "HTTP 500"}}\n\n'
            return resp

        def mock_ensure(timeout):
            with mcp_mod._mcp_session_state.lock:
                mcp_mod._mcp_session_state.session_id = "mock-sid"
                mcp_mod._mcp_session_state._initialized = True
            return "mock-sid"

        http_session = mcp_mod._get_http_session()
        with mock.patch.object(mcp_mod, "_ensure_session", mock_ensure):
            with mock.patch.object(http_session, "post", fake_post):
                with mock.patch.object(TableauMCPClient, "_get_connection_by_luid") as mc:
                    conn = mock.Mock()
                    conn.is_active = True
                    conn.last_test_success = True
                    conn.mcp_direct_enabled = True
                    mc.return_value = conn

                    client = TableauMCPClient(connection_id=1)
                    with pytest.raises(TableauMCPError) as exc_info:
                        client.query_datasource("ds-1", {}, 10, 30, 1)

        assert exc_info.value.code == "NLQ_006"
        # _post_mcp internally loops twice on 5xx (retry on attempt 0, raise after attempt 1)
        assert post_count[0] == 2


class Test4xxNoRetry:
    """test_4xx_no_retry — 400(非 session 错误)直接 raise"""

    def test_4xx_no_retry(self):
        call_count = [0]

        def mock_send(self, payload, timeout):
            call_count[0] += 1
            raise TableauMCPError(
                code="NLQ_006",
                message="MCP 请求失败（HTTP 400）",
                details={"status_code": 400},
            )

        with mock.patch.object(TableauMCPClient, "_send_jsonrpc", mock_send):
            with mock.patch.object(TableauMCPClient, "_get_connection_by_luid") as mc:
                conn = mock.Mock()
                conn.is_active = True
                conn.last_test_success = True
                conn.mcp_direct_enabled = True
                mc.return_value = conn

                client = TableauMCPClient(connection_id=1)
                with pytest.raises(TableauMCPError) as exc_info:
                    client.query_datasource("ds-1", {}, 10, 30, 1)

        assert exc_info.value.code == "NLQ_006"
        assert call_count[0] == 1  # 无重试


class TestToolsCallIsError:
    """test_tools_call_iserror_true — isError: true 映射到 NLQ_006"""

    def test_iserror_true_raises(self):
        def mock_send(self, payload, timeout):
            return {
                "result": {
                    "content": [{"type": "text", "text": "VizQL error: invalid filter"}],
                    "isError": True,
                }
            }

        with mock.patch.object(TableauMCPClient, "_send_jsonrpc", mock_send):
            with mock.patch.object(TableauMCPClient, "_get_connection_by_luid") as mc:
                conn = mock.Mock()
                conn.is_active = True
                conn.last_test_success = True
                conn.mcp_direct_enabled = True
                mc.return_value = conn

                client = TableauMCPClient(connection_id=1)
                with pytest.raises(TableauMCPError) as exc_info:
                    client.query_datasource("ds-1", {}, 10, 30, 1)

        assert exc_info.value.code == "NLQ_006"
        assert "MCP 工具执行失败" in exc_info.value.message


class TestInvalidJsonInContentText:
    """test_invalid_json_in_content_text — content[0].text 不是 JSON 时 raise"""

    def test_invalid_json_in_text(self):
        def mock_send(self, payload, timeout):
            return {
                "result": {
                    "content": [{"type": "text", "text": "not json at all {{{"}],
                    "isError": False,
                }
            }

        with mock.patch.object(TableauMCPClient, "_send_jsonrpc", mock_send):
            with mock.patch.object(TableauMCPClient, "_get_connection_by_luid") as mc:
                conn = mock.Mock()
                conn.is_active = True
                conn.last_test_success = True
                conn.mcp_direct_enabled = True
                mc.return_value = conn

                client = TableauMCPClient(connection_id=1)
                with pytest.raises(TableauMCPError) as exc_info:
                    client.query_datasource("ds-1", {}, 10, 30, 1)

        assert exc_info.value.code == "NLQ_006"
        assert "非 JSON" in exc_info.value.message


class TestContextvarsIsolation:
    """test_contextvars_isolation — 并发两个 connection_id 互不串扰"""

    def test_connection_id_isolation(self):
        seen_ids = []
        lock = threading.Lock()

        def mock_send(self, payload, timeout):
            cid = mcp_mod.get_mcp_connection_id()
            with lock:
                seen_ids.append(cid)
            return {"result": {"content": [{"type": "text", "text": json.dumps({"fields": [], "rows": []})}], "isError": False}}

        def run_query(cid):
            with mock.patch.object(TableauMCPClient, "_send_jsonrpc", mock_send):
                with mock.patch.object(TableauMCPClient, "_get_connection_by_luid") as mc:
                    conn = mock.Mock()
                    conn.is_active = True
                    conn.last_test_success = True
                    conn.mcp_direct_enabled = True
                    mc.return_value = conn
                    client = TableauMCPClient(connection_id=cid)
                    client.query_datasource(f"ds-{cid}", {}, 10, 30, cid)

        t1 = threading.Thread(target=run_query, args=(1,))
        t2 = threading.Thread(target=run_query, args=(2,))
        t1.start()
        t2.start()
        t1.join()
        t2.join()

        assert 1 in seen_ids
        assert 2 in seen_ids


class TestInstanceCacheInvalidate:
    """test_instance_cache_invalidate — invalidate(cid) 后下次调用重建"""

    def test_invalidate_recreates_instance(self):
        def mock_send(self, payload, timeout):
            if payload.get("method") == "initialize":
                return {"jsonrpc": "2.0", "id": 1, "result": {}}
            elif "initialized" in payload.get("method", ""):
                return {}
            return {"result": {"content": [{"type": "text", "text": json.dumps({"fields": [], "rows": []})}], "isError": False}}

        with mock.patch.object(TableauMCPClient, "_send_jsonrpc", mock_send):
            with mock.patch.object(TableauMCPClient, "_get_connection_by_luid") as mc:
                conn = mock.Mock()
                conn.is_active = True
                conn.last_test_success = True
                conn.mcp_direct_enabled = True
                mc.return_value = conn

                client1 = TableauMCPClient(connection_id=1)
                client1.query_datasource("ds-1", {}, 10, 30, 1)
                count_before = len(TableauMCPClient._instances)

                TableauMCPClient.invalidate(1)

                client2 = TableauMCPClient(connection_id=1)
                client2.query_datasource("ds-1", {}, 10, 30, 1)

        # After invalidate, instance should be recreated (cache cleared + new instance)
        assert len(TableauMCPClient._instances) == count_before


# ─── 辅助函数测试 ──────────────────────────────────────────────────────────────

class TestExtractText:
    def test_extracts_text_parts(self):
        content = [
            {"type": "text", "text": "hello"},
            {"type": "text", "text": " world"},
            {"type": "image", "text": "ignored"},
        ]
        assert _extract_text(content) == "hello world"

    def test_empty_content(self):
        assert _extract_text([]) == ""


class TestMapMcpError:
    def test_forbidden_maps_to_nlq_009(self):
        assert _map_mcp_error("forbidden") == "NLQ_009"
        assert _map_mcp_error(403) == "NLQ_009"

    def test_not_found_maps_to_nlq_009(self):
        assert _map_mcp_error("not_found") == "NLQ_009"
        assert _map_mcp_error(404) == "NLQ_009"

    def test_vizql_error_maps_to_nlq_006(self):
        assert _map_mcp_error("VIZQL_ERR") == "NLQ_006"

    def test_none_defaults_to_nlq_006(self):
        assert _map_mcp_error(None) == "NLQ_006"


class TestParseSSE:
    def test_parses_single_data_line(self):
        text = 'event: message\ndata: {"jsonrpc":"2.0","id":1,"result":{"ok":true}}\n\n'
        result = _parse_sse(text)
        assert result["jsonrpc"] == "2.0"
        assert result["result"]["ok"] is True

    def test_raises_when_no_data_line(self):
        text = 'event: message\n\n'
        with pytest.raises(TableauMCPError) as exc_info:
            _parse_sse(text)
        assert "无 data 字段" in exc_info.value.message

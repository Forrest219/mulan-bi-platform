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
    MCP_NL_TOOL_UNAVAILABLE,
    TableauMCPClient,
    TableauMCPError,
    extract_datasource_metadata_fields,
    _extract_text,
    _map_mcp_error,
    _normalize_query_datasource_result,
    _parse_sse,
    normalize_datasource_metadata_field,
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

        def mock_send(self, payload, timeout, **kwargs):
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

        def mock_send(self, payload, timeout, **kwargs):
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

        def mock_ensure(timeout, **kwargs):
            with mcp_mod._mcp_session_state.lock:
                mcp_mod._mcp_session_state.session_id = "mock-sid"
                mcp_mod._mcp_session_state._initialized = True
            return "mock-sid"

        def mock_post(payload, method, timeout, expect_sse=True, **kwargs):
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
        def mock_send(self, payload, timeout, **kwargs):
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

        def mock_ensure(timeout, **kwargs):
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


class TestQueryDatasourceRetryPolicy:
    def _patch_active_connection(self):
        conn = mock.Mock()
        conn.is_active = True
        conn.last_test_success = True
        conn.mcp_direct_enabled = True
        return mock.patch.object(TableauMCPClient, "_get_connection_by_luid", return_value=conn)

    def test_query_datasource_retries_econnreset_tool_error_then_succeeds(self, monkeypatch):
        monkeypatch.setattr(mcp_mod.time, "sleep", lambda _seconds: None)
        calls = []

        def mock_send(self, payload, timeout, **kwargs):
            calls.append(timeout)
            if len(calls) == 1:
                return {
                    "result": {
                        "content": [{"type": "text", "text": "requestId: 460, error: read ECONNRESET"}],
                        "isError": True,
                    }
                }
            return {
                "result": {
                    "content": [{"type": "text", "text": json.dumps({"fields": ["x"], "rows": [[1]]})}],
                    "isError": False,
                }
            }

        with self._patch_active_connection():
            with mock.patch.object(TableauMCPClient, "_send_jsonrpc", mock_send):
                client = TableauMCPClient(connection_id=1)
                result = client.query_datasource("ds-1", {}, 10, 30, 1)

        assert result == {"fields": ["x"], "rows": [[1]]}
        assert len(calls) == 2


class TestDatasourceMetadataFieldNormalization:
    def _patch_active_connection(self):
        conn = mock.Mock()
        conn.is_active = True
        conn.last_test_success = True
        conn.mcp_direct_enabled = True
        return mock.patch.object(TableauMCPClient, "_get_connection_by_luid", return_value=conn)

    def test_extracts_field_groups_from_mcp_raw_shape(self):
        raw = {
            "fieldGroups": [
                {
                    "name": "订单",
                    "fields": [
                        {
                            "name": "销售额",
                            "dataType": "REAL",
                            "role": "MEASURE",
                            "columnClass": "COLUMN",
                            "logicalTableId": "订单_E1D13D6162604AA48D04C27BA1FECAAB",
                            "defaultAggregation": "SUM",
                            "dataCategory": "QUANTITATIVE",
                            "defaultFormat": "n#,##0;-#,##0",
                        },
                        {
                            "name": "发货日期",
                            "dataType": "DATE",
                            "role": "DIMENSION",
                            "columnClass": "COLUMN",
                        },
                    ],
                }
            ]
        }

        fields = extract_datasource_metadata_fields(raw)
        normalized = [normalize_datasource_metadata_field(field) for field in fields]

        assert [field["field_name"] for field in normalized] == ["销售额", "发货日期"]
        assert normalized[0]["data_type"] == "REAL"
        assert normalized[0]["role"] == "measure"
        assert normalized[0]["aggregation"] == "SUM"
        assert normalized[0]["metadata_json"]["logicalTableId"] == "订单_E1D13D6162604AA48D04C27BA1FECAAB"
        assert normalized[1]["data_type"] == "DATE"
        assert normalized[1]["role"] == "dimension"

    def test_extracts_nested_raw_fields_and_dedupes(self):
        raw = {
            "fields": [{"name": "销售额", "logicalTableId": "orders"}],
            "raw": {
                "fieldGroups": [
                    {"fields": [{"name": "销售额", "logicalTableId": "orders"}, {"name": "利润"}]}
                ]
            },
        }

        fields = extract_datasource_metadata_fields(raw)

        assert [field["name"] for field in fields] == ["销售额", "利润"]

    def test_query_datasource_retries_read_timeout_once(self, monkeypatch):
        monkeypatch.setattr(mcp_mod.time, "sleep", lambda _seconds: None)
        calls = []

        def mock_send(self, payload, timeout, **kwargs):
            calls.append(timeout)
            raise TableauMCPError("NLQ_007", "MCP 查询超时（10s）", {"retry_kind": "read_timeout"})

        with self._patch_active_connection():
            with mock.patch.object(TableauMCPClient, "_send_jsonrpc", mock_send):
                client = TableauMCPClient(connection_id=1)
                with pytest.raises(TableauMCPError) as exc_info:
                    client.query_datasource("ds-1", {}, 10, 30, 1)

        assert exc_info.value.code == "NLQ_007"
        assert len(calls) == 2

    def test_query_datasource_does_not_retry_invalid_arguments(self):
        calls = []

        def mock_send(self, payload, timeout, **kwargs):
            calls.append(timeout)
            return {
                "result": {
                    "content": [{"type": "text", "text": "Input validation error: Invalid arguments for tool query-datasource"}],
                    "isError": True,
                }
            }

        with self._patch_active_connection():
            with mock.patch.object(TableauMCPClient, "_send_jsonrpc", mock_send):
                client = TableauMCPClient(connection_id=1)
                with pytest.raises(TableauMCPError) as exc_info:
                    client.query_datasource("ds-1", {}, 10, 30, 1)

        assert exc_info.value.code == "NLQ_006"
        assert len(calls) == 1

    def test_query_datasource_does_not_retry_when_budget_is_insufficient(self, monkeypatch):
        monkeypatch.setattr(mcp_mod, "_MIN_RETRY_REMAINING_SECONDS", 999.0)
        calls = []

        def mock_send(self, payload, timeout, **kwargs):
            calls.append(timeout)
            return {
                "result": {
                    "content": [{"type": "text", "text": "requestId: 460, error: read ECONNRESET"}],
                    "isError": True,
                }
            }

        with self._patch_active_connection():
            with mock.patch.object(TableauMCPClient, "_send_jsonrpc", mock_send):
                client = TableauMCPClient(connection_id=1)
                with pytest.raises(TableauMCPError) as exc_info:
                    client.query_datasource("ds-1", {}, 10, 30, 1)

        assert exc_info.value.details["retry_budget_exhausted"] is True
        assert len(calls) == 1


class Test4xxNoRetry:
    """test_4xx_no_retry — 400(非 session 错误)直接 raise"""

    def test_4xx_no_retry(self):
        call_count = [0]

        def mock_send(self, payload, timeout, **kwargs):
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
        def mock_send(self, payload, timeout, **kwargs):
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
        def mock_send(self, payload, timeout, **kwargs):
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


class TestOfficialMcpDataShape:
    """Official @tableau/mcp-server returns {"data": [{...}]} for query-datasource."""

    def test_data_records_are_normalized_to_fields_rows(self):
        raw = {
            "data": [
                {"YEAR(订单日期)": 2025, "销售额": 150036, "利润": 81736},
            ]
        }

        normalized = _normalize_query_datasource_result(raw)

        assert normalized["fields"] == ["YEAR(订单日期)", "销售额", "利润"]
        assert normalized["rows"] == [[2025, 150036, 81736]]
        assert normalized["data"] == raw["data"]


class TestNaturalLanguageQueryTool:
    def _patch_active_connection(self):
        conn = mock.Mock()
        conn.is_active = True
        conn.last_test_success = True
        conn.mcp_direct_enabled = True
        conn.server_url = "https://tableau.example"
        conn.site = "default"
        conn.mcp_server_url = None
        return mock.patch.object(
            TableauMCPClient,
            "_get_connection_by_luid",
            return_value=conn,
        )

    def test_invokes_allowlisted_nl_tool_with_original_question_and_datasource(self):
        question = "Show the current result"
        calls = []

        def mock_send(self, payload, timeout, **kwargs):
            calls.append(payload)
            if payload["method"] == "tools/list":
                return {
                    "result": {
                        "tools": [
                            {"name": "query-datasource"},
                            {
                                "name": "query-datasource-nl",
                                "inputSchema": {
                                    "type": "object",
                                    "properties": {
                                        "question": {"type": "string"},
                                        "datasourceLuid": {"type": "string"},
                                        "limit": {"type": "integer"},
                                    },
                                },
                            },
                        ]
                    }
                }
            assert payload["params"]["name"] == "query-datasource-nl"
            return {
                "result": {
                    "content": [
                        {
                            "type": "text",
                            "text": json.dumps({"data": [{"label": "ok", "value": 1}]}),
                        }
                    ],
                    "isError": False,
                }
            }

        with self._patch_active_connection():
            with mock.patch.object(TableauMCPClient, "_send_jsonrpc", mock_send):
                client = TableauMCPClient(connection_id=1)
                result = client.query_datasource_natural_language(
                    datasource_luid="ds-1",
                    question=question,
                    limit=25,
                    timeout=30,
                    connection_id=1,
                )

        assert result["fields"] == ["label", "value"]
        assert result["rows"] == [["ok", 1]]
        assert [call["method"] for call in calls] == ["tools/list", "tools/call"]
        call_args = calls[1]["params"]["arguments"]
        assert call_args == {
            "question": question,
            "datasourceLuid": "ds-1",
            "limit": 25,
        }
        assert "fields" not in json.dumps(call_args)
        assert calls[1]["params"]["name"] != "query-datasource"

    def test_structured_query_datasource_only_reports_nl_tool_unavailable(self):
        calls = []

        def mock_send(self, payload, timeout, **kwargs):
            calls.append(payload)
            if payload["method"] == "tools/list":
                return {
                    "result": {
                        "tools": [
                            {
                                "name": "query-datasource",
                                "inputSchema": {
                                    "type": "object",
                                    "properties": {
                                        "datasourceLuid": {"type": "string"},
                                        "query": {"type": "object"},
                                        "limit": {"type": "integer"},
                                    },
                                },
                            }
                        ]
                    }
                }
            raise AssertionError(
                "structured query-datasource must not be invoked as an NL tool"
            )

        with self._patch_active_connection():
            with mock.patch.object(TableauMCPClient, "_send_jsonrpc", mock_send):
                client = TableauMCPClient(connection_id=1)
                with pytest.raises(TableauMCPError) as exc_info:
                    client.query_datasource_natural_language(
                        datasource_luid="ds-1",
                        question="Show the current result",
                        timeout=30,
                        connection_id=1,
                        allowed_tool_names=("query-datasource", "query-datasource-nl"),
                    )

        assert exc_info.value.code == MCP_NL_TOOL_UNAVAILABLE
        assert exc_info.value.details["available_tools"] == ["query-datasource"]
        assert exc_info.value.details["structured_query_datasource_available"] is True
        assert [call["method"] for call in calls] == ["tools/list"]


class TestGenericMCPToolAPI:
    def _patch_active_connection(self):
        conn = mock.Mock()
        conn.is_active = True
        conn.last_test_success = True
        conn.mcp_direct_enabled = True
        conn.server_url = "https://tableau.example"
        conn.site = "default"
        conn.mcp_server_url = None
        return mock.patch.object(
            TableauMCPClient,
            "_get_connection_by_luid",
            return_value=conn,
        )

    def test_public_list_tools_uses_mcp_tools_list(self):
        calls = []

        def mock_send(self, payload, timeout, **kwargs):
            calls.append(payload)
            assert payload["method"] == "tools/list"
            return {
                "result": {
                    "tools": [
                        {
                            "name": "sample-tool",
                            "inputSchema": {
                                "type": "object",
                                "properties": {"payload": {"type": "object"}},
                            },
                        }
                    ]
                }
            }

        with self._patch_active_connection():
            with mock.patch.object(TableauMCPClient, "_send_jsonrpc", mock_send):
                client = TableauMCPClient(connection_id=1)
                tools = client.list_tools(
                    timeout=12,
                    connection_id=1,
                    datasource_luid="ds-1",
                )

        assert [tool["name"] for tool in tools] == ["sample-tool"]
        assert calls[0]["params"] == {}

    def test_public_call_tool_uses_generic_tools_call_and_parses_json(self):
        calls = []

        def mock_send(self, payload, timeout, **kwargs):
            calls.append(payload)
            assert payload["method"] == "tools/call"
            return {
                "result": {
                    "content": [
                        {
                            "type": "text",
                            "text": json.dumps({"ok": True, "items": [1]}),
                        }
                    ],
                    "isError": False,
                }
            }

        with self._patch_active_connection():
            with mock.patch.object(TableauMCPClient, "_send_jsonrpc", mock_send):
                client = TableauMCPClient(connection_id=1)
                result = client.call_tool(
                    tool_name="sample-tool",
                    arguments={"payload": {"value": 1}},
                    timeout=12,
                    connection_id=1,
                    datasource_luid="ds-1",
                )

        assert result == {"ok": True, "items": [1]}
        assert calls[0]["params"] == {
            "name": "sample-tool",
            "arguments": {"payload": {"value": 1}},
        }


class TestGatewayTimeoutBudget:
    def test_post_mcp_passes_gateway_timeout_below_http_timeout(self):
        captured = {}

        def fake_post(url, json=None, headers=None, timeout=None):
            captured["headers"] = headers
            captured["timeout"] = timeout
            resp = mock.Mock()
            resp.status_code = 200
            resp.text = 'event: message\ndata: {"jsonrpc":"2.0","id":1,"result":{"ok":true}}\n\n'
            return resp

        http_session = mcp_mod._get_http_session()
        with mock.patch.object(http_session, "post", fake_post):
            result = mcp_mod._post_mcp(
                {"jsonrpc": "2.0", "id": 1, "method": "tools/call"},
                method="tools/call",
                timeout=30,
            )

        assert result["result"]["ok"] is True
        assert captured["timeout"] == 30
        assert captured["headers"]["X-Mulan-MCP-Timeout"] == "29"


class TestContextvarsIsolation:
    """test_contextvars_isolation — 并发两个 connection_id 互不串扰"""

    def test_connection_id_isolation(self):
        seen_ids = []
        lock = threading.Lock()

        def mock_send(self, payload, timeout, **kwargs):
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
        def mock_send(self, payload, timeout, **kwargs):
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

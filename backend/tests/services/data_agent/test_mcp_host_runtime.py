import json

import pytest

from services.data_agent.mcp_host import (
    MCPHostRuntime,
    MCPHostRuntimeError,
    MCPToolCatalog,
    MCPToolExecutor,
)
from services.data_agent.mcp_host.builtins import (
    BuiltInToolExecution,
    MulanBuiltInToolProvider,
    MULAN_LIST_TABLEAU_ASSETS_TOOL_NAME,
    mulan_builtin_mcp_tools,
)
from services.data_agent.mcp_host.runtime import reset_mcp_host_catalog_cache

pytestmark = pytest.mark.skip_db


@pytest.fixture(autouse=True)
def _clear_catalog_cache():
    reset_mcp_host_catalog_cache()
    yield
    reset_mcp_host_catalog_cache()


class FakeMCPClient:
    def __init__(self, tools, result=None):
        self.tools = tools
        self.result = result if result is not None else {"ok": True}
        self.list_calls = []
        self.call_calls = []

    def list_tools(self, **kwargs):
        self.list_calls.append(kwargs)
        return self.tools

    def call_tool(self, **kwargs):
        self.call_calls.append(kwargs)
        return self.result


def test_catalog_discovers_tools_and_mulan_builtins():
    client = FakeMCPClient(
        [
            {
                "name": "metadata-tool",
                "description": "returns metadata",
                "inputSchema": {"type": "object", "properties": {}},
            },
            {
                "name": "execute-tool",
                "inputSchema": {"type": "object", "required": ["payload"]},
            },
        ]
    )
    trace = []

    catalog = MCPToolCatalog.discover(
        client,
        connection_id=7,
        datasource_luid="ds-1",
        timeout=11,
        trace=trace,
    )

    assert catalog.tool_names() == ["metadata-tool", "execute-tool", MULAN_LIST_TABLEAU_ASSETS_TOOL_NAME]
    assert catalog.get("execute-tool").input_schema["required"] == ["payload"]
    assert client.list_calls == [
        {
            "timeout": 11,
            "connection_id": 7,
            "datasource_luid": "ds-1",
            "jwt_token": None,
        }
    ]
    assert trace[0]["event"] == "mcp_host.catalog"
    json.dumps(trace)


def test_executor_rejects_tool_not_in_catalog_before_dispatch():
    client = FakeMCPClient([{"name": "known-tool", "inputSchema": {}}])
    catalog = MCPToolCatalog(client.tools)
    trace = []
    executor = MCPToolExecutor(client, catalog, trace=trace)

    with pytest.raises(MCPHostRuntimeError) as exc_info:
        executor.execute("missing-tool", {})

    assert exc_info.value.code == "MCP_HOST_UNKNOWN_TOOL"
    assert client.call_calls == []
    assert trace[0]["event"] == "mcp_host.tool_rejected"
    json.dumps(trace)


def test_executor_validates_required_top_level_schema_properties():
    client = FakeMCPClient(
        [
            {
                "name": "schema-tool",
                "inputSchema": {
                    "type": "object",
                    "required": ["payload", "limit"],
                    "properties": {
                        "payload": {"type": "object"},
                        "limit": {"type": "integer"},
                    },
                },
            }
        ]
    )
    catalog = MCPToolCatalog(client.tools)
    executor = MCPToolExecutor(client, catalog)

    with pytest.raises(MCPHostRuntimeError) as exc_info:
        executor.execute("schema-tool", {"payload": {}})

    assert exc_info.value.code == "MCP_HOST_MISSING_REQUIRED_ARGUMENTS"
    assert exc_info.value.details["missing_required_properties"] == ["limit"]
    assert client.call_calls == []


def test_query_datasource_executes_through_generic_runtime_executor():
    client = FakeMCPClient(
        [
            {
                "name": "query-datasource",
                "inputSchema": {
                    "type": "object",
                    "required": ["datasourceLuid", "query"],
                    "properties": {
                        "datasourceLuid": {"type": "string"},
                        "query": {"type": "object"},
                        "limit": {"type": "integer"},
                    },
                },
            }
        ],
        result={"data": [{"value": 1}]},
    )
    runtime = MCPHostRuntime(
        client,
        connection_id=42,
        datasource_luid="ds-1",
        timeout=19,
    )

    result = runtime.call_tool(
        "query-datasource",
        {
            "datasourceLuid": "ds-1",
            "query": {"fields": []},
            "limit": 1,
        },
    )

    assert result["data"] == [{"value": 1}]
    assert result["metadata"]["truncated_by_guardrail"] is False
    assert result["metadata"]["guardrail_resource_cap"]["max_rows"] == 1
    assert len(client.list_calls) == 1
    assert client.call_calls == [
        {
            "tool_name": "query-datasource",
            "arguments": {
                "datasourceLuid": "ds-1",
                "query": {"fields": []},
                "limit": 1,
                "max_rows": 1,
                "max_bytes": 5242880,
                "timeout_ms": 30000,
            },
            "timeout": 19,
            "connection_id": 42,
            "datasource_luid": "ds-1",
            "jwt_token": None,
        }
    ]
    assert [event["event"] for event in runtime.trace_events] == [
        "mcp_host.catalog",
        "mcp_host.catalog_cache",
        "mcp_host.tool_call",
        "mcp_host.tool_result",
    ]
    json.dumps(runtime.trace_events)


def test_list_datasources_does_not_pass_transport_connection_as_tool_argument():
    client = FakeMCPClient(
        [
            {
                "name": "list-datasources",
                "inputSchema": {
                    "type": "object",
                    "properties": {"limit": {"type": "integer"}},
                    "additionalProperties": False,
                },
            }
        ],
        result={"datasources": []},
    )
    runtime = MCPHostRuntime(client, connection_id=42, timeout=19)

    result = runtime.call_tool(
        "list-datasources",
        {"connectionId": 42, "limit": 50},
        question="列出数据源",
        context={"connection_id": 42, "user_id": 7},
        current_datasource={"connection_id": 42},
        strict_connection_access=True,
    )

    assert result == {"datasources": []}
    assert client.call_calls == [
        {
            "tool_name": "list-datasources",
            "arguments": {"limit": 50},
            "timeout": 19,
            "connection_id": 42,
            "datasource_luid": None,
            "jwt_token": None,
        }
    ]


def test_runtime_reuses_connection_scoped_catalog_cache_between_sessions():
    tools = [
        {
            "name": "query-datasource",
            "inputSchema": {
                "type": "object",
                "required": ["datasourceLuid", "query"],
                "properties": {"datasourceLuid": {"type": "string"}, "query": {"type": "object"}},
            },
        }
    ]
    first_client = FakeMCPClient(tools)
    first_runtime = MCPHostRuntime(first_client, connection_id=42, datasource_luid="ds-1")
    assert first_runtime.load_catalog().tool_names() == ["query-datasource", MULAN_LIST_TABLEAU_ASSETS_TOOL_NAME]
    assert len(first_client.list_calls) == 1

    second_client = FakeMCPClient(tools)
    second_runtime = MCPHostRuntime(second_client, connection_id=42, datasource_luid="ds-2")
    assert second_runtime.load_catalog().tool_names() == ["query-datasource", MULAN_LIST_TABLEAU_ASSETS_TOOL_NAME]
    assert second_client.list_calls == []
    assert any(
        event["event"] == "mcp_host.catalog_cache" and event.get("payload", {}).get("cache_hit") is True
        for event in second_runtime.trace_events
    )


def test_runtime_executes_mulan_builtin_tool_without_remote_client_call():
    class FakeProvider:
        def __init__(self):
            self.calls = []

        def has_tool(self, tool_name):
            return tool_name == MULAN_LIST_TABLEAU_ASSETS_TOOL_NAME

        def execute(self, tool_name, arguments, *, context=None):
            self.calls.append({"tool_name": tool_name, "arguments": dict(arguments), "context": context})
            return BuiltInToolExecution(
                result={
                    "response_type": "asset_candidates",
                    "response_data": {
                        "source": "tableau_asset_catalog",
                        "connection_id": 7,
                        "reason": "asset_inventory",
                        "candidates": [{"asset_id": 1, "asset_type": "dashboard", "name": "销售看板"}],
                    },
                },
                guardrail_decision={
                    "decision": "allow",
                    "tool_name": MULAN_LIST_TABLEAU_ASSETS_TOOL_NAME,
                    "tool_provider": "mulan_builtin",
                    "connection_id": 7,
                    "args": {"connectionId": 7},
                    "repairs": [],
                },
            )

    provider = FakeProvider()
    client = FakeMCPClient([])
    runtime = MCPHostRuntime(client, connection_id=7, built_in_provider=provider)

    result = runtime.call_tool(
        MULAN_LIST_TABLEAU_ASSETS_TOOL_NAME,
        {"assetTypes": ["dashboard"], "limit": 20},
        context={"connection_id": 7, "user_id": 42},
        execution_source="llm_planner",
    )

    assert result["response_type"] == "asset_candidates"
    assert provider.calls[0]["arguments"]["connectionId"] == 7
    assert client.call_calls == []
    assert any(
        event["event"] == "mcp_host.tool_call"
        and event["payload"]["tool"] == MULAN_LIST_TABLEAU_ASSETS_TOOL_NAME
        and event["payload"]["tool_provider"] == "mulan_builtin"
        for event in runtime.trace_events
    )


def test_mulan_builtin_asset_tool_requires_connection_without_catalog_lookup():
    provider = MulanBuiltInToolProvider(session_factory=lambda: (_ for _ in ()).throw(AssertionError("no db lookup")))

    execution = provider.execute(MULAN_LIST_TABLEAU_ASSETS_TOOL_NAME, {}, context={"user_id": 42})

    assert execution.result["response_type"] == "clarification"
    assert execution.result["response_data"]["reason"] == "connection_required"
    assert execution.guardrail_decision["decision"] == "clarify"


def test_mulan_builtin_asset_tool_scopes_catalog_query_by_connection():
    class Row:
        id = 10
        connection_id = 7
        tableau_id = "dash-1"
        asset_type = "dashboard"
        name = "销售看板"
        project_name = "经营"
        parent_workbook_name = "销售工作簿"
        description = None
        owner_name = "alice"
        web_url = "https://tableau.local/views/dash"
        content_url = None
        view_count = 3
        synced_at = None
        updated_on_server = None

    class Connection:
        id = 7
        owner_id = 42
        is_active = True

    class Query:
        def __init__(self, model):
            self.model = model
            self.filters = []

        def filter(self, *conditions):
            self.filters.extend(conditions)
            return self

        def first(self):
            return Connection()

        def order_by(self, *args):
            return self

        def limit(self, value):
            self.limit_value = value
            return self

        def all(self):
            return [Row()]

    class Session:
        def __init__(self):
            self.queries = []

        def query(self, model):
            query = Query(model)
            self.queries.append(query)
            return query

        def close(self):
            pass

    session = Session()
    provider = MulanBuiltInToolProvider(session_factory=lambda: session)

    execution = provider.execute(
        MULAN_LIST_TABLEAU_ASSETS_TOOL_NAME,
        {"connectionId": 7, "assetTypes": ["dashboard"], "limit": 20},
        context={"user_id": 42},
    )

    assert execution.result["response_type"] == "asset_candidates"
    assert execution.result["response_data"]["connection_id"] == 7
    asset_query = session.queries[1]
    filter_text = " ".join(str(condition) for condition in asset_query.filters)
    assert "tableau_assets.connection_id" in filter_text
    assert "tableau_assets.is_deleted" in filter_text

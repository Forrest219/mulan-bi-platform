import json

import pytest

from services.data_agent.mcp_host import (
    MCPHostRuntime,
    MCPHostRuntimeError,
    MCPToolCatalog,
    MCPToolExecutor,
)

pytestmark = pytest.mark.skip_db


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


def test_catalog_discovers_tools_from_mcp_list_only():
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

    assert catalog.tool_names() == ["metadata-tool", "execute-tool"]
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
        "mcp_host.tool_call",
        "mcp_host.tool_result",
    ]
    json.dumps(runtime.trace_events)

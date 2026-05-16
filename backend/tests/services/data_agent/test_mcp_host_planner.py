import json

import pytest

from services.data_agent.mcp_host.planner import MCP_HOST_PLANNER_PURPOSE
from services.data_agent.mcp_host.planner import MCPHostPlanner
from services.data_agent.mcp_host.planner import MCPHostPlannerError
from services.data_agent.mcp_host.planner import MCPHostPlannerInput
from services.data_agent.mcp_host.planner import build_mcp_host_planner_messages
from services.data_agent.mcp_host.planner import parse_mcp_host_planner_output

pytestmark = pytest.mark.skip_db


class _FakeLLM:
    def __init__(self, payload):
        self.payload = payload
        self.calls = []

    async def complete(self, *, prompt, system=None, timeout=None, purpose=None):
        self.calls.append({"prompt": prompt, "system": system, "timeout": timeout, "purpose": purpose})
        return {"content": json.dumps(self.payload)}


class _CatalogLike:
    def as_mcp_tools(self):
        return _catalog()["tools"]


def _catalog():
    return {
        "tools": [
            {
                "name": "get-datasource-metadata",
                "description": "Return datasource metadata.",
                "inputSchema": {
                    "type": "object",
                    "properties": {"datasourceLuid": {"type": "string"}},
                    "required": ["datasourceLuid"],
                },
            },
            {
                "name": "query-datasource",
                "description": "Run a datasource query.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "datasourceLuid": {"type": "string"},
                        "query": {"type": "object"},
                    },
                    "required": ["datasourceLuid", "query"],
                },
            },
        ]
    }


def _planner_input():
    return MCPHostPlannerInput(
        original_question="Summarize the selected datasource.",
        selected_datasource={"name": "Selected Source", "luid": "ds-1"},
        mcp_tool_schemas=_catalog(),
        datasource_metadata={
            "fields": [
                {"name": "dimension_a", "dataType": "string"},
                {"name": "metric_a", "dataType": "number"},
            ]
        },
        previous_response_data={"columns": ["dimension_a", "metric_a"], "rows": [["x", 1]]},
    )


def test_valid_tool_call_parsing():
    decision = parse_mcp_host_planner_output(
        json.dumps(
            {
                "action": "tool_call",
                "tool": "query-datasource",
                "arguments": {"datasourceLuid": "ds-1", "query": {"fields": []}},
            }
        ),
        _catalog(),
    )

    assert decision.action == "tool_call"
    assert decision.tool == "query-datasource"
    assert decision.arguments == {"datasourceLuid": "ds-1", "query": {"fields": []}}
    assert decision.to_dict()["arguments"] == decision.arguments


def test_rejects_queryspec_shaped_output():
    with pytest.raises(MCPHostPlannerError) as exc_info:
        parse_mcp_host_planner_output(
            json.dumps(
                {
                    "action": "tool_call",
                    "tool": "query-datasource",
                    "arguments": {
                        "intent": "aggregate",
                        "operator": "aggregate",
                        "metrics": [],
                        "dimensions": [],
                        "filters": [],
                    },
                }
            ),
            _catalog(),
        )

    assert exc_info.value.code == "PLANNER_QUERYSPEC_FORBIDDEN"


def test_rejects_tool_not_present_in_catalog():
    with pytest.raises(MCPHostPlannerError) as exc_info:
        parse_mcp_host_planner_output(
            json.dumps(
                {
                    "action": "tool_call",
                    "tool": "missing-tool",
                    "arguments": {},
                }
            ),
            _catalog(),
        )

    assert exc_info.value.code == "PLANNER_TOOL_UNKNOWN"
    assert exc_info.value.detail["available_tools"] == ["get-datasource-metadata", "query-datasource"]


def test_accepts_catalog_like_runtime_object():
    decision = parse_mcp_host_planner_output(
        json.dumps(
            {
                "action": "tool_call",
                "tool": "query-datasource",
                "arguments": {"datasourceLuid": "ds-1", "query": {}},
            }
        ),
        _CatalogLike(),
    )

    assert decision.tool == "query-datasource"


def test_parses_json_after_thinking_or_commentary_text():
    content = """
ThinkingBlock: informal reasoning omitted.
The final planner object is:
```json
{"action":"tool_call","tool":"get-datasource-metadata","arguments":{"datasourceLuid":"ds-1"}}
```
"""

    decision = parse_mcp_host_planner_output(content, _catalog())

    assert decision.action == "tool_call"
    assert decision.tool == "get-datasource-metadata"
    assert decision.arguments == {"datasourceLuid": "ds-1"}


def test_build_messages_include_planner_inputs():
    messages = build_mcp_host_planner_messages(_planner_input())
    payload = json.loads(messages[-1]["content"])

    assert payload["original_question"] == "Summarize the selected datasource."
    assert payload["selected_datasource"] == {"name": "Selected Source", "luid": "ds-1"}
    assert [tool["name"] for tool in payload["mcp_tool_schemas"]] == [
        "get-datasource-metadata",
        "query-datasource",
    ]
    assert payload["datasource_metadata"]["fields"][0]["name"] == "dimension_a"
    assert payload["previous_response_data"]["columns"] == ["dimension_a", "metric_a"]
    assert "planning_skill" not in messages[-1]["content"]


@pytest.mark.asyncio
async def test_planner_calls_llm_and_validates_result():
    llm = _FakeLLM(
        {
            "action": "tool_call",
            "tool": "query-datasource",
            "arguments": {"datasourceLuid": "ds-1", "query": {}},
        }
    )
    planner = MCPHostPlanner(llm)

    decision = await planner.plan(_planner_input())

    assert decision.action == "tool_call"
    assert decision.tool == "query-datasource"
    assert llm.calls[0]["purpose"] == MCP_HOST_PLANNER_PURPOSE
    assert llm.calls[0]["timeout"] == 18
    prompt_payload = json.loads(llm.calls[0]["prompt"])
    assert prompt_payload["selected_datasource"]["luid"] == "ds-1"
    assert prompt_payload["previous_response_data"]["rows"] == [["x", 1]]

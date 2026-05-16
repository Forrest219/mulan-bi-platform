# Mulan Thin MCP Passthrough Validation

Date: 2026-05-16

## Scope

Validated the contracted thin route:

```text
frontend selected datasource + original question -> Tableau MCP NL tool -> response_data -> renderer
```

The live payload included:

- `connection_id`: 2
- `datasource_luid`: `f4290485-26d3-428f-aa8d-ccc33862a411`
- `datasource_name`: `订单+ (示例 - 超市)`

## Unit Tests

Command:

```bash
backend/.venv/bin/python -m pytest backend/tests/services/data_agent/test_mcp_first_main.py backend/tests/services/data_agent/test_mcp_proxy_main.py backend/tests/services/tableau/test_mcp_client.py backend/tests/services/data_agent/test_queryspec_fallback.py backend/tests/services/data_agent/test_dynamic_column_engine.py
```

Result:

```text
86 passed
```

## MCP Capability

Current Tableau MCP tools: 17.

Query-relevant tools:

- `get-datasource-metadata`
- `list-datasources`
- `query-datasource`

No natural-language data-question tool is exposed. `query-datasource` is structured and requires planned fields, so the thin Mulan route must not use it for Q1-Q4.

## Live Q1-Q4

Artifact:

```text
inbox/20260516-01-mulan-thin-mcp-q1-q4-probe.json
```

| QID | Result | Forbidden markers |
| --- | --- | --- |
| Q1 | `MCP_NL_TOOL_UNAVAILABLE` | none |
| Q2 | `MCP_NL_TOOL_UNAVAILABLE` | none |
| Q3 | `MCP_NL_TOOL_UNAVAILABLE` | none |
| Q4 | `MCP_NL_TOOL_UNAVAILABLE` | none |

Checked forbidden markers:

- `llm_mcp_args`
- `llm_queryspec`
- `llm_queryspec_repair`
- `queryspec_mcp_fallback`
- `mcp_main_queryspec_fallback`

## Conclusion

The implementation now follows the contracted thin boundary for Q1-Q4. Because the current MCP server does not expose an NL data-question tool, Mulan correctly fails fast instead of generating QuerySpec, LLM MCP args, or structured `query-datasource` arguments.

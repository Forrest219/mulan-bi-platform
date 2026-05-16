# Mulan Thin MCP Passthrough Plan

Date: 2026-05-16
Status: implemented-and-validated

## Boundary

Mulan is no longer a data-question planning layer.

The main route must be:

```text
frontend selected datasource + original user question
  -> Tableau MCP natural-language query tool
  -> MCP result
  -> Mulan response_data normalization
  -> renderer only restates response_data
```

Mulan must not do:

- datasource inference;
- context interpretation or field completion;
- QuerySpec generation, repair, validation, or execution;
- LLM-generated MCP args;
- deterministic business query construction;
- guardrail boundary checking;
- business calculation or derived metric calculation.

## MCP Capability Finding

The currently running Tableau MCP server at `http://localhost:3927/tableau-mcp` exposes these query-relevant tools:

- `get-datasource-metadata`
- `list-datasources`
- `query-datasource`

It does not expose a natural-language data question tool. `query-datasource` requires structured `query.fields`, so using it for Q1-Q4 would require Mulan to plan fields/aggregations. That is outside the approved boundary.

Therefore:

- If a Tableau MCP natural-language query tool is configured/available, Mulan may pass the original question to it.
- If no such tool exists, Mulan must fail fast with a structured capability error.
- Mulan must not silently fall back to QuerySpec or LLM MCP args.

## Acceptance

- Q1-Q4 must not call `llm_queryspec`, `llm_queryspec_repair`, `llm_mcp_args`, or QuerySpec fallback on the main route.
- Q1-Q4 must either:
  - produce MCP-sourced `response_data` from an MCP NL tool; or
  - return `MCP_NL_TOOL_UNAVAILABLE` when no MCP NL tool exists.
- The live Q1-Q4 probe artifact must be written under `inbox/`.
- No commit unless the user separately approves after seeing the Q1-Q4 result.

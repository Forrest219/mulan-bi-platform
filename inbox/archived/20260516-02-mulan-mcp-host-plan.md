# Mulan MCP Host Plan

Date: 2026-05-16
Status: draft-for-review

## Decision

Mulan will become an MCP Host again, but not by restoring QuerySpec as the main planner.

Main route:

```text
frontend selected datasource + user question
  -> Mulan MCP Host loop
  -> tools/list + datasource metadata + query-datasource
  -> MCP result
  -> response_data normalization
  -> renderer restates response_data
```

## Boundary

Allowed:

- LLM selects MCP tools from actual MCP `tools/list`.
- LLM generates MCP tool-call arguments directly against MCP tool schemas.
- LLM may call metadata before query execution.
- LLM may repair tool-call arguments after MCP validation errors.
- Mulan records trace, tool calls, tool results, and response_data.

Not allowed:

- QuerySpec as the main execution plan.
- Planning skill as a required pre-execution blocker.
- Python hardcoding business field names, metric names, formulas, filters, or benchmark-question mappings.
- Renderer doing business calculation.
- Silent fallback from MCP failure to QuerySpec execution.

## Architecture

1. `MCPToolCatalog`

   Fetch and cache MCP `tools/list` per connection/session. The catalog is the only source for available tool names and input schemas.

2. `DatasourceContext`

   Uses only frontend-selected datasource identity. It may call `get-datasource-metadata` to provide field captions and types to the LLM, but it must not infer the datasource from the question.

3. `MCPHostPlanner`

   A model-native tool-calling loop. The LLM receives:

   - original user question;
   - selected datasource identity;
   - MCP tool schemas;
   - datasource metadata;
   - previous assistant `response_data` for follow-up context.

   It outputs only tool calls or final answer instructions. No QuerySpec object is produced.

4. `MCPToolExecutor`

   Executes only tool calls selected from `MCPToolCatalog`. It validates JSON shape against the MCP tool schema before dispatch and records tool-call traces.

5. `Repair Loop`

   On MCP schema/argument errors, the LLM may retry with the error message and prior tool call. Retry budget should be small and explicit.

6. `Response Contract`

   Final user-visible facts must come from MCP tool results. `response_data` is normalized from MCP outputs. Renderer can summarize or restate but cannot invent derived values.

## Quality Gate

Before commit:

- Q1-Q4 must run through Mulan and not use QuerySpec main path.
- Q1-Q4 must produce MCP-backed `response_data`.
- Q1-Q4 results must be compared against `inbox/20260515-13-abtest-raw.json`.
- Any generated MCP args in trace must be explainable from MCP tool schema plus datasource metadata.
- If Q1-Q4 are worse than direct MCP baseline on correctness, do not commit.

## Implementation Phases

### Phase 1: Host Runtime

- Add MCP tool catalog discovery.
- Add schema-constrained tool-call executor.
- Add trace events for catalog, planner tool call, MCP result, repair, final response.
- Keep existing thin fail-fast path available behind a feature flag until the host path is validated.

### Phase 2: Model-Native Planning

- Replace QuerySpec main path with MCP Host planner.
- Provide datasource metadata to the LLM as structured context.
- Support multi-step calls: metadata -> query -> optional follow-up query.
- Add bounded repair for invalid MCP args.

### Phase 3: Response Contract

- Normalize MCP query results into existing `response_data`.
- Renderer uses only `response_data` and trace summaries.
- Preserve MCP errors as structured errors.

### Phase 4: Baseline Gate

- Run Q1-Q4 live against current Tableau MCP.
- Compare with old direct MCP baseline.
- Save raw trace, response_data, and quality report under `inbox/`.
- Commit only if the gate passes.

## Test Plan

Unit tests:

- catalog discovers real MCP tool schemas;
- planner cannot call tools not in catalog;
- executor rejects schema-invalid args before MCP dispatch;
- repair loop retries only on argument/schema errors;
- renderer does not compute missing business metrics.

Integration tests:

- Q1 aggregate metrics;
- Q2 trend follow-up;
- Q3 grouped metrics;
- Q4 follow-up split by year;
- no QuerySpec main-path trace markers.

Live artifacts:

- `inbox/20260516-02-mulan-mcp-host-q1-q4-trace.json`
- `inbox/20260516-02-mulan-mcp-host-quality-report.json`
- `inbox/20260516-02-mulan-mcp-host-validation.md`

## Key Risk

This moves natural-language understanding back into Mulan. The difference from the previous failed path is that Mulan should behave like a real MCP Host: direct tool schemas, direct tool calls, iterative MCP feedback, and no lossy QuerySpec middle layer.

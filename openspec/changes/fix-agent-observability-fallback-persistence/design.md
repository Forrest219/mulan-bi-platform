# Design: Agent Observability Fallback Persistence

## Current Failure Mode

`/api/agent/stream` persists the user message before routing. For clarification fallback, `_write_standard_fallback_run` writes:

1. `bi_agent_runs`
2. `bi_agent_steps`
3. `agent_conversation_messages` assistant message

If `bi_agent_runs.error_code` rejects `ROUTER_CLARIFY_REQUIRED`, the function exits before the assistant message is persisted. The SSE handler catches the write error and still returns `done`, creating a frontend/backend mismatch.

## Data Contract

`error_code` is an operational identifier, not a UI label. It must preserve full semantic values such as:

- `ROUTER_CLARIFY_REQUIRED`
- `ROUTER_GUARDRAIL_BLOCKED`
- `MCP_PROXY_LIST_DATASOURCES_FAILED`
- `TABLEAU_MCP_CONNECTION_FORBIDDEN`

The production schema should support at least 128 characters for error code values used by Agent and MCP paths.

## Persistence Boundary

Fallback user-facing response persistence must be independent from telemetry persistence.

Recommended behavior:

- Persist assistant fallback message in the same request before returning SSE `done`.
- Write run/step telemetry with full error code.
- If telemetry fails, roll back only telemetry work, then still persist or preserve the assistant message.
- Log telemetry failure with `conversation_id`, `trace_id`, `run_id`, `error_code`, and exception type.

## Observability Source

Agent Monitor remains backed by `bi_agent_runs`. Conversation messages are not a substitute run source because they lack complete execution metadata and would mix user-facing history with operational telemetry.

## Historical Data

The failed run did not persist. Historical repair is optional and must be approved separately. If approved, only a clearly marked standard clarification assistant message may be inserted; no business answer or synthetic MCP run should be fabricated.

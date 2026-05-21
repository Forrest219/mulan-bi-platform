# Proposal: Fix Agent Observability Fallback Persistence

## Problem

A fallback response can be returned to the frontend through `/api/agent/stream` but fail to persist in backend observability and conversation history.

Observed case:

- Conversation: `dddc13f8-8348-404a-a0e5-83a0ffbb5fcb`
- Frontend-visible run id: `e7299b44-fe59-4182-8a11-8be5d17f48d5`
- Question: `你有哪些看板？`
- `bi_agent_runs.error_code` is `varchar(16)`.
- Writing `ROUTER_CLARIFY_REQUIRED` fails with `StringDataRightTruncation`.

Because the fallback run write fails before assistant message persistence, the frontend can temporarily show the SSE response, but after reload only the user question remains. The Agent Monitor page also cannot show the run because no `bi_agent_runs` row was inserted.

## Goals

- Align observability schema with actual error code lengths.
- Ensure fallback responses returned to users are persisted in conversation history.
- Keep Agent Monitor backed by `bi_agent_runs`.
- Preserve full error code semantics; do not truncate error codes.
- Add regression tests for fallback persistence and monitor visibility.

## Non-Goals

- Do not infer or fabricate business query results.
- Do not change Agent Monitor to derive runs from message history.
- Do not introduce a new telemetry registry or action DSL.
- Do not automatically repair historical conversations without explicit approval.

## Scope

- Alembic migration for risky short observability fields.
- Agent fallback persistence transaction boundary.
- Regression tests for stream fallback, run visibility, and schema length.
- Production verification checklist.

## Rollout

1. Apply migration.
2. Deploy backend code.
3. Trigger clarification fallback with `你有哪些看板？`.
4. Confirm assistant message survives reload.
5. Confirm Agent Monitor shows the fallback run.
6. Confirm logs contain no `StringDataRightTruncation`.

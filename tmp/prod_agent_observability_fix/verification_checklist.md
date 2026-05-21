# Agent Observability Fallback Persistence Verification Checklist

## Scope

- Production fix: `ROUTER_CLARIFY_REQUIRED` fallback persistence and assistant message durability.
- Default historical-data policy: do not auto-backfill missing fallback runs or assistant messages.

## Pre-Release Checks

- Confirm `bi_agent_runs.error_code` DB schema and ORM metadata both allow at least 128 chars.
- Confirm fallback assistant message persistence is not inside the telemetry transaction failure boundary.
- Confirm assistant message persistence failure emits an error SSE and does not emit `done`.
- Run targeted regression tests:

```bash
cd backend && .venv/bin/python -m py_compile tests/services/data_agent/test_agent_observability_fallback_persistence.py
cd backend && .venv/bin/python -m pytest tests/services/data_agent/test_agent_observability_fallback_persistence.py -q --no-cov
```

## Staging Verification

- Trigger controlled fallback: `你有哪些看板？`, `connection_id=4`.
- Confirm SSE final event is `done` only when assistant message is persisted.
- Confirm `done.response_data.error_code == ROUTER_CLARIFY_REQUIRED`.
- Refresh or reload the conversation and confirm the assistant fallback message is still visible.
- Confirm Agent Monitor can query the same `run_id` in `/api/admin/agent/runs`.
- Confirm backend logs contain no `StringDataRightTruncation`, `value too long`, `DataError`, or swallowed persistence failure.

## Production Rollout Checks

- Rebuild/restart backend container and confirm the running image tag/digest matches the release artifact.
- After deploy, repeat the controlled fallback with `connection_id=4`.
- Within 15 minutes, check fallback run insert success and assistant message insert success.
- Within 1 hour, compare Agent Monitor run counts with backend fallback logs.
- Within 24 hours, verify no recurrence of `error_code` truncation or assistant-message-loss incidents.

## Historical Data Handling

- Do not automatically backfill `dddc13f8-8348-404a-a0e5-83a0ffbb5fcb`.
- Generate an impact report only:
  - affected time window
  - user id
  - conversation id
  - run id or trace id if available
  - evidence source
  - restore confidence: complete, partial, or not restorable
- Any repair requires separate approval from product/business owner, engineering, and DBA/data owner.
- If repair is approved, create a separate idempotent one-off repair plan with backup or rollback SQL before touching data.

## Rollback Signals

- New `AGENT_PERSISTENCE_FAILED` spikes.
- Fallback `done` emitted without matching assistant message.
- Agent Monitor run count drops below fallback request count.
- New database errors involving `bi_agent_runs.error_code`, `agent_conversation_messages`, or transaction rollback.

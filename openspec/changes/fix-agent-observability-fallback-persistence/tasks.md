# Tasks

## 1. Database Contract

- [ ] Add Alembic migration to expand `bi_agent_runs.error_code` to `varchar(128)`.
- [ ] Review related short observability fields and expand only those with demonstrated production risk.
- [ ] Ensure ORM model length metadata matches migration.
- [ ] Add/adjust tests proving long standard error codes can persist.

## 2. Fallback Persistence

- [ ] Refactor `_write_standard_fallback_run` or caller transaction boundary so assistant fallback message is not lost when telemetry write fails.
- [ ] Preserve full error code in telemetry; do not truncate.
- [ ] Add structured logging for telemetry write failure with conversation/run/trace identifiers.
- [ ] Prevent duplicate assistant message writes on retry or partial failure.

## 3. Runtime Regression Tests

- [ ] Cover `ROUTER_CLARIFY_REQUIRED` path through `/api/agent/stream`.
- [ ] Assert SSE `done` contains fallback response.
- [ ] Assert assistant message is persisted and returned by conversation messages API.
- [ ] Assert `bi_agent_runs` row is visible to Agent Monitor query.

## 4. Production Verification

- [ ] Run py_compile for changed Python files.
- [ ] Run targeted backend tests for agent stream/admin/fallback.
- [ ] Rebuild backend container.
- [ ] Trigger `你有哪些看板？` on `connection=4`.
- [ ] Confirm no `StringDataRightTruncation` in backend logs.
- [ ] Confirm refresh keeps assistant response.
- [ ] Confirm Agent Monitor shows the run.

## 5. Historical Data

- [ ] Do not automatically backfill `dddc13f8-8348-404a-a0e5-83a0ffbb5fcb`.
- [ ] If explicitly approved, create a separate one-off repair plan before touching data.

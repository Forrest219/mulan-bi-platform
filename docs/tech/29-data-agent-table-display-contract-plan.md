# Data Agent Table Display Contract Plan

Updated: 2026-05-14 17:23 CST

## Goal

Build a generic table display contract for Data Agent responses. The backend must describe how each result column should be presented, and the frontend must render the table from that contract.

The current acceptance case is `销售额占比` should be right-aligned, but the implementation must not be hardcoded for this single field or question.

## Problem

Current table responses only provide:

```json
{
  "fields": ["客户名称", "SUM(销售额)", "销售额占比"],
  "rows": [["李丽丽", 181562.11, "1.08%"]]
}
```

The frontend infers column type from sample cell values. Percent strings such as `"1.08%"` are treated as ordinary strings, so they render left-aligned. This is a contract gap: table display semantics are implicit and scattered.

## Target Contract

Keep the existing compatibility shape:

```json
{
  "fields": ["..."],
  "rows": [[...]]
}
```

Add an optional generic display contract:

```json
{
  "table_display": {
    "columns": [
      {
        "key": "raw_field_key",
        "label": "用户可读列名",
        "semantic_type": "dimension | metric | derived_metric | rank | period | flag | text",
        "value_type": "string | number | percent | date | boolean",
        "align": "left | right | center",
        "format": "plain | number | integer | percent | date"
      }
    ]
  }
}
```

Rules:

- `fields/rows` remain the data compatibility layer.
- `table_display.columns` is the formal display contract.
- `table_display.columns[i]` corresponds to `fields[i]`.
- If `table_display` is absent, frontend must keep the existing fallback behavior.
- The display contract must be generic across operators, not specific to ranking.

## Display Rules

- `semantic_type=metric | derived_metric | rank | period` defaults to `align=right`.
- `semantic_type=dimension | text | flag` defaults to `align=left`, unless explicitly overridden.
- `value_type=percent` defaults to `format=percent` and `align=right`.
- Field labels should be user-facing:
  - `SUM(销售额)` should display as `销售额`.
  - `COUNTD(客户名称)` may display as `客户数` if existing context supports that alias; otherwise preserve a safe user-readable label.
- Percent values:
  - If stored as a string like `"1.08%"`, render as-is.
  - If stored as a number like `0.0108`, format as `1.08%`.

## Allowed Files

Subagents may modify only the following files or add files under these exact areas:

Backend:

- `backend/services/data_agent/table_display.py`
- `backend/services/data_agent/query_plan.py`
- `backend/services/data_agent/mcp_first_main.py`
- `backend/services/data_agent/semantic_operators/ranking.py`
- `backend/services/data_agent/semantic_operators/contribution_share.py`
- `backend/services/data_agent/semantic_operators/root_cause.py`
- `backend/tests/services/data_agent/test_table_display.py`
- `backend/tests/services/data_agent/test_semantic_operators.py`
- `backend/tests/services/data_agent/test_queryspec_fallback.py`
- `backend/tests/services/data_agent/test_mcp_first_main.py`

Frontend:

- `frontend/src/hooks/useStreamingChat.ts`
- `frontend/src/pages/home/components/MessageList.tsx`
- `frontend/src/components/chat/QueryResultTable.tsx`
- Related frontend tests under `frontend/tests/` only if needed for this feature.

Docs:

- `docs/specs/36-data-agent-architecture-spec.md`
- `docs/tech/29-data-agent-table-display-contract-plan.md`

## Forbidden Scope

- Do not modify unrelated routes, auth, Tableau sync, metrics governance, assets UI, or MCP client behavior.
- Do not change the meaning of `fields` or `rows`.
- Do not remove existing fallback behavior for historical messages.
- Do not hardcode behavior for a single run id, customer, datasource, field value, or question.
- Do not introduce a new frontend table component unless the existing one cannot support the contract.

## Tasks

### Task 1: Update Spec

Update `docs/specs/36-data-agent-architecture-spec.md` with a new table display contract section.

Acceptance:

- The spec states that backend generates `table_display.columns`.
- The spec states frontend prioritizes `table_display` and falls back to `fields + rows`.
- The spec lists `semantic_type`, `value_type`, `align`, and `format`.
- The spec explicitly says this applies to all Data Agent table responses.

### Task 2: Add `infer_table_display_schema`

Add `backend/services/data_agent/table_display.py`.

Function:

```python
def infer_table_display_schema(
    fields: list[Any],
    rows: list[list[Any]] | None = None,
    *,
    operator: str | None = None,
    metric_names: list[str] | None = None,
) -> dict[str, Any]:
    ...
```

Acceptance:

- Returns `{"columns": [...]}`.
- Infers user-facing `label`.
- Infers `semantic_type`.
- Infers `value_type`.
- Infers `align`.
- Infers `format`.
- Handles aggregate labels such as `SUM(销售额)`.
- Handles percent/rate/share fields generically.
- Has focused backend unit tests.

### Task 3: Extend `OperatorResult`

Update `backend/services/data_agent/query_plan.py`.

Acceptance:

- `OperatorResult` has optional `table_display`.
- `to_tool_data()` includes `table_display` when available.
- Existing `fields/rows` behavior is unchanged.

### Task 4: Wire Backend Operators

Wire `infer_table_display_schema` into:

- `RankingOperator`
- `ContributionShareOperator`
- `RootCauseOperator`
- Normal aggregate MCP data path in `mcp_first_main.py`

Acceptance:

- Operator outputs include `table_display`.
- Existing tests still pass.
- New tests verify `销售额占比` is `value_type=percent`, `format=percent`, `align=right`.
- New tests verify `客户名称` is left-aligned.
- New tests verify `SUM(销售额)` label is user-facing and right-aligned.

### Task 5: Update Frontend Types and History Adapter

Update frontend table data types and history adapters.

Acceptance:

- `TableData` supports optional `table_display`.
- `histTableData()` passes `table_display` through from `response_data`.
- SSE table data path preserves `table_display`.
- Historical messages without `table_display` still render.

### Task 6: Update `QueryResultTable`

Update `frontend/src/components/chat/QueryResultTable.tsx`.

Acceptance:

- If `table_display.columns` exists, table headers use `columns[i].label`.
- Header and cell alignment use `columns[i].align`.
- `format=percent` renders strings as-is and numbers as percentages.
- `format=number` keeps current number formatting.
- If `table_display` is missing, existing `fields + col_types` fallback remains.

### Task 7: Test and Verify

Backend:

```bash
cd backend
/Users/forrest/.local/bin/python3.11 -m pytest \
  tests/services/data_agent/test_table_display.py \
  tests/services/data_agent/test_semantic_operators.py \
  tests/services/data_agent/test_queryspec_fallback.py \
  tests/services/data_agent/test_mcp_first_main.py -q
```

Frontend:

Run the narrowest available frontend test command for `QueryResultTable` or related unit tests. If no targeted test exists, document that limitation and verify TypeScript/build where practical.

Manual acceptance:

- Ask: `Top 10 大客户是谁？请列出客户名称和销售金额及占比`
- Confirm new `response_data.table_display.columns` exists.
- Confirm `销售额占比` has:
  - `semantic_type=derived_metric`
  - `value_type=percent`
  - `align=right`
  - `format=percent`
- Confirm frontend renders:
  - `客户名称` left-aligned
  - `销售额` right-aligned
  - `销售额占比` right-aligned

## Subagent Split

### Worker A: Backend Contract

Owned files:

- `backend/services/data_agent/table_display.py`
- `backend/services/data_agent/query_plan.py`
- `backend/services/data_agent/mcp_first_main.py`
- `backend/services/data_agent/semantic_operators/ranking.py`
- `backend/services/data_agent/semantic_operators/contribution_share.py`
- `backend/services/data_agent/semantic_operators/root_cause.py`
- Backend tests listed above
- `docs/specs/36-data-agent-architecture-spec.md`

### Worker B: Frontend Rendering

Owned files:

- `frontend/src/hooks/useStreamingChat.ts`
- `frontend/src/pages/home/components/MessageList.tsx`
- `frontend/src/components/chat/QueryResultTable.tsx`
- Related frontend tests under `frontend/tests/`

Worker B must wait for or infer the backend contract shape from this document. Do not modify backend files.

## Final Handoff Requirements

Each worker must report:

- Files changed.
- Tests run and results.
- Any contract assumptions.
- Any remaining risks.

# TESTER_FAIL: reconcile-tableau-mcp-fields

> Date: 2026-05-17  
> Role: Tester  
> Result: FAIL

## Findings

### 1. 未校验 / MCP metadata 失败时会把所有 catalog 字段误判为 catalog-only

- Severity: High
- Files:
  - `backend/services/data_agent/mcp_first_main.py:1193`
  - `backend/services/data_agent/mcp_first_main.py:1214`
  - `backend/services/data_agent/mcp_first_main.py:1295`
  - `backend/services/data_agent/mcp_first_main.py:1298`

Actual:

When MCP metadata lookup fails, `_queryable_field_context()` falls back to local capability context and returns only rows with `mcp_queryable is True`. For newly synced or not-yet-reconciled assets, this list can be empty while `catalog_fields` is present. `_catalog_queryable_context()` then computes:

```text
catalog_only = catalog_fields - queryable_fields
```

Because `queryable_fields` is empty, every catalog field becomes catalog-only. A normal question such as “按销售额统计” can be blocked with “字段存在于 Tableau 资产目录，但当前 Agent/MCP 不支持查询：销售额”, even though the field may simply be `unknown` or temporarily unchecked.

Expected:

Only fields with confirmed `mcp_queryable=false` should be treated as `catalog_only`. Unknown/error states must not be converted into catalog-only merely because current queryable metadata is unavailable. If no queryable set is available, Data Agent should return an MCP metadata/unavailable style message or avoid MCP execution, but it must not mislabel the user’s field as unsupported by MCP.

Why this violates SPEC:

- SPEC §5.1 defines `unknown` and `error` as separate states from `catalog_only`.
- Acceptance Criteria 4 applies only when the user asks for a field known to be catalog-only.
- Acceptance Criteria 5 says MCP metadata failures must not delete, hide, or overwrite catalog fields; this implementation effectively hides all fields from Agent execution through a false catalog-only classification.

Suggested fix:

- In `_catalog_queryable_context()`, prefer persisted/explicit `catalog_only_fields` from reconciliation.
- Only compute `catalog_fields - queryable_fields` when the queryable field set is known fresh/non-empty or when reconciliation summary indicates checked capability state.
- Preserve `unknown` and `error` as non-catalog-only states in preflight.
- Add a test for an asset with `catalog_fields=["销售额", "订单日期"]`, empty `queryable_fields`, and no explicit `catalog_only_fields`; `_catalog_only_preflight("按销售额统计", ...)` must not return catalog-only.

### 2. 资产字段页没有展示非 error 的 MCP 状态

- Severity: Medium
- File: `frontend/src/features/tableau-inspector/tabs/FieldsTab.tsx:145`

Actual:

The summary badge renders `fieldMetadata.mcp_status` only when it equals `error`. For `ok` / `partial` / `unknown`, it falls back to `cache_status` labels such as “已缓存”, so a response with `mcp_status="partial"` is displayed as “MCP 状态 已缓存”.

Expected:

The asset page should expose MCP queryability status clearly: `ok` / `partial` / `unknown` / `error`, while cache status remains separate if needed.

Why this violates SPEC:

- SPEC §5.5 requires the frontend to show queryability summary and last MCP check status/error.
- RTMF-06 says the page must display “MCP 状态/异常”.

Suggested fix:

- Add an MCP status label map for `ok` / `partial` / `unknown` / `error`.
- Use `fieldMetadata.mcp_status` for the MCP badge and keep `cache_status` as a separate cache badge if still needed.
- Extend `FieldsTab.test.tsx` to cover `mcp_status="partial"` and assert the UI does not render it as cache status.

### 3. RTMF 交付混入非 RTMF 变更，验收边界不清

- Severity: Medium
- Files include:
  - `backend/app/api/tasks.py`
  - `backend/services/tasks/models.py`
  - `backend/services/tasks/schedule_service.py`
  - `frontend/src/pages/admin/tasks/page.tsx`
  - `frontend/src/router/config.tsx`

Actual:

The current worktree contains task/sync-history routing, backfill, timestamp formatting, and route wildcard changes that are unrelated to `reconcile-tableau-mcp-fields`. `IMPLEMENTATION_NOTES.md` also records these as unrelated non-RTMF modifications.

Expected:

Tester should be able to validate the RTMF change independently. Unrelated feature/fix work should be in a separate change or already committed before RTMF handoff.

Risk:

These files can affect `/system/tasks` behavior, API response timestamps, and route matching. They are outside the RTMF SPEC and make regression attribution ambiguous.

Suggested fix:

- Split unrelated task/sync-history changes out of this handoff, or explicitly add their SPEC/validation scope to the tester request.
- Re-run RTMF validation with a worktree containing only RTMF-related changes.

## Verification Run

Passed:

- `cd backend && ./.venv/bin/python -m pytest tests/test_tableau_field_reconciliation.py tests/services/data_agent/test_tableau_catalog_only_preflight.py tests/services/data_agent/test_mcp_args_guardrail.py -q -o addopts=''`
  - Result: `27 passed`
- `cd frontend && npm run type-check`
  - Result: PASS
- `cd frontend && npm run lint`
  - Result: PASS, 52 existing warnings
- `cd frontend && npm test -- --run src/features/tableau-inspector/tabs/FieldsTab.test.tsx`
  - Result: PASS, 1 test
- `cd backend && ./.venv/bin/python -m compileall app services tests`
  - Result: PASS
- `cd backend && ./.venv/bin/python -m alembic heads`
  - Result: `20260517_030000 (head)`

Notes:

- Running the targeted backend tests with the repository default pytest config passed all behavior assertions but exited non-zero on the global coverage threshold because only the targeted subset was executed.
- The reported full backend failure in `tests/test_agent_conversations.py::TestConversationPersistence::test_get_user_conversations_returns_list` remains treated as existing/unrelated based on coder handoff.

## Required Fixer Actions

1. Fix catalog-only preflight so unknown/error/unavailable MCP metadata does not become catalog-only.
2. Add backend regression coverage for the unknown/unreconciled asset case.
3. Fix the frontend MCP status badge to render `ok` / `partial` / `unknown` / `error`.
4. Add frontend coverage for `mcp_status="partial"`.
5. Clarify or split unrelated task/sync-history changes before re-handoff.

# TESTER_PASS: reconcile-tableau-mcp-fields

> Date: 2026-05-17  
> Role: Tester  
> Result: PASS for RTMF scope

## Scope

This pass supersedes the previous `TESTER_FAIL.md` for the two RTMF blockers:

1. Data Agent must not mislabel unknown/unreconciled fields as catalog-only.
2. Tableau asset field UI must render MCP status separately from cache status.

## Verification

Passed:

- `cd backend && ./.venv/bin/python -m pytest tests/test_tableau_field_reconciliation.py tests/services/data_agent/test_tableau_catalog_only_preflight.py tests/services/data_agent/test_mcp_args_guardrail.py -q -o addopts=''`
  - Result: `29 passed`
- `cd backend && ./.venv/bin/python -m py_compile services/data_agent/mcp_first_main.py services/data_agent/mcp_args_guardrail.py services/data_agent/mcp_proxy_main.py services/tableau/field_reconciliation.py services/tableau/mcp_metadata_fields.py services/tableau/models.py services/tableau/sync_service.py app/api/tableau.py tests/services/data_agent/test_tableau_catalog_only_preflight.py tests/services/data_agent/test_mcp_args_guardrail.py tests/test_tableau_field_reconciliation.py tests/test_tableau.py`
  - Result: PASS
- `cd backend && ./.venv/bin/python -m alembic heads`
  - Result: `20260517_030000 (head)`
- `cd frontend && npm run type-check`
  - Result: PASS
- `cd frontend && npm run lint`
  - Result: PASS, 52 existing warnings
- `cd frontend && npm test -- --run src/features/tableau-inspector/tabs/FieldsTab.test.tsx`
  - Result: PASS, 2 tests
- `cd frontend && npm test -- --run`
  - Result: PASS, 4 files / 12 tests

## Acceptance Check

- Asset field capability storage/API additions are present.
- Reconciliation marks queryable vs catalog-only without deleting catalog fields.
- Catalog-only preflight blocks confirmed catalog-only fields.
- Unknown/unreconciled fields are no longer treated as catalog-only when queryable metadata is unavailable.
- Guardrail returns `MCP_ARGS_CATALOG_ONLY_FIELD` only for confirmed catalog-only fields.
- Frontend shows `缓存状态` and `MCP 状态` independently.
- `mcp_status=partial` renders as `MCP 状态 部分可查询`, not as a cache label.

## Residual Notes

- Backend full test suite was not rerun in this pass because the handoff already reported an existing unrelated failure in `tests/test_agent_conversations.py::TestConversationPersistence::test_get_user_conversations_returns_list`.
- Current worktree still contains non-RTMF changes, including `frontend/nginx.conf`. Those changes are not covered by this RTMF tester pass and should be validated under their own scope before commit/release.

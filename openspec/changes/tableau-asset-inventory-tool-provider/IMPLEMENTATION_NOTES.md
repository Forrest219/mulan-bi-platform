# Implementation Notes: Tableau Asset Inventory Built-in Tool Provider

## Summary

Implemented the approved OpenSpec change as a Mulan built-in MCP tool provider instead of a private `mcp_proxy_main.py` SQL branch.

## Files Changed

- `backend/services/data_agent/mcp_host/builtins.py`
- `backend/services/data_agent/mcp_host/runtime.py`
- `backend/services/data_agent/tableau_mcp_planner.py`
- `backend/services/data_agent/mcp_proxy_main.py`
- `backend/services/data_agent/tableau_mcp_response.py`
- `backend/tests/services/data_agent/test_mcp_host_runtime.py`
- `backend/tests/services/data_agent/test_tableau_mcp_planner.py`
- `backend/tests/services/data_agent/test_mcp_proxy_main.py`
- `openspec/changes/tableau-asset-inventory-tool-provider/tasks.md`

## Design Decisions

1. Added `mulan-list-tableau-assets` as a Mulan built-in MCP tool surfaced through the existing MCP Host catalog.
2. Kept the new dashboard/workbook/view asset inventory catalog lookup inside `MulanBuiltInToolProvider`, not `mcp_proxy_main.py`.
3. Routed built-in tool execution through `MCPToolExecutor.execute()` with `tool_provider=mulan_builtin` trace records.
4. Required asset catalog access to resolve a concrete `connection_id` and verify current user access before querying assets.
5. Scoped catalog lookup by `TableauAsset.connection_id == connection_id` and `TableauAsset.is_deleted == False`.
6. Preserved response boundary: asset inventory returns `asset_candidates` / `asset_not_found` / `tool_unavailable` / `clarification`, never `query_result`.
7. Added Planner retry for `needs_clarification=true` without a valid `clarification` block; retry failure returns a standard clarification with `PLANNER_CONTRACT_FAILURE`, not the model `reason`.

## Verification

- `python3 -m py_compile backend/services/data_agent/mcp_host/builtins.py backend/services/data_agent/mcp_host/runtime.py backend/services/data_agent/tableau_mcp_planner.py backend/services/data_agent/mcp_proxy_main.py backend/services/data_agent/tableau_mcp_response.py backend/tests/services/data_agent/test_mcp_host_runtime.py backend/tests/services/data_agent/test_tableau_mcp_planner.py backend/tests/services/data_agent/test_mcp_proxy_main.py`
- `cd backend && PYTHONPATH=. ./.venv/bin/pytest tests/services/data_agent/test_mcp_host_runtime.py tests/services/data_agent/test_tableau_mcp_planner.py tests/services/data_agent/test_mcp_proxy_main.py -q -o addopts=''`
  - Result: `62 passed`
- `cd backend && PYTHONPATH=. ./.venv/bin/pytest tests/services/data_agent/ -x -q -o addopts=''`
  - Result: `561 passed, 28 skipped`
- `cd backend && PYTHONPATH=. ./.venv/bin/pytest tests/test_chat_ask_data_api.py tests/services/data_agent/test_agent_observability_fallback_persistence.py tests/services/data_agent/test_fallback.py tests/services/data_agent/test_router_guardrail.py -q --import-mode=importlib -o addopts=''`
  - Result: `57 passed`
- `git diff --check`
  - Result: passed for changed files.

## Known Existing Test Collection Issue

Backend full test collection was attempted with:

```bash
cd backend && PYTHONPATH=. ./.venv/bin/pytest tests/ -x -q --import-mode=importlib -o addopts=''
```

It stopped at collection with an existing unrelated import error:

```text
ImportError: cannot import name '_build_fast_answer' from 'app.api.agent'
```

The failure is in `tests/test_agent_fast_answer.py` and was not caused by the new asset inventory tool path.

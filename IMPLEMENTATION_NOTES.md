# IMPLEMENTATION_NOTES

## Scope
Implemented Homepage Data QA guardrails based on Spec 56 and testcase matrix, focusing on backend Coder-owned tasks in required order: BE-002, BE-005, BE-003, BE-004, BE-001, then P1 BE-101/BE-102.

## Implemented

1. Result Guardrail module (BE-002)
- Added `backend/services/data_agent/result_guardrail.py`
- Implemented input/output contract and P0 checks:
  - detail scan block
  - resource-cap truncation block
  - missing required fields -> semantic_fail/review
  - fallback default `needs_review`
- Outputs include:
  - `decision`
  - `semantic_status`
  - `error_code`
  - `checks`

2. Resource Cap injection (BE-005)
- Updated `backend/services/data_agent/mcp_host/runtime.py`
- For `query-datasource` calls, now force-injects:
  - `max_rows` (hard cap <= 1000)
  - `max_bytes` (default 5MB)
  - `timeout_ms` (hard cap <= 30000)
  - adjusted call timeout ceiling to 30s
- Decorates result metadata with:
  - `truncated_by_guardrail`
  - `guardrail_resource_cap`

3. Homepage chain integration (BE-003)
- Updated `backend/services/data_agent/mcp_first_main.py`
- Integrated Result Guardrail after MCP result and before renderer/final answer in:
  - controlled QuerySpec main path
  - MCP Host final response path
  - thin MCP passthrough path
- `decision=block` now prevents renderer summary and returns structured error path.

4. Semantic status + trace fields (BE-004)
- Added `data_qa` metadata enrichment in chain response payload:
  - `semantic_status`
  - `semantic_operator`
  - `fallback_triggered`
  - `result_guardrail_decision`
  - `result_guardrail_error_code`
- Added full `result_guardrail` payload into response for QA traceability.

5. Golden Set harness and first baseline (BE-001)
- Added fixture:
  - `backend/tests/fixtures/data_agent_golden_set/batch2_q0_q10.yaml`
- Added test harness file:
  - `backend/tests/services/data_agent/test_homepage_data_qa_golden_set.py`
- Added Result Guardrail tests:
  - `backend/tests/services/data_agent/test_result_guardrail.py`
- Extended existing tests:
  - `backend/tests/services/data_agent/test_mcp_host_runtime.py`
  - `backend/tests/services/data_agent/test_mcp_proxy_main.py`
- Note: the fixture now contains the real Batch 2 Q0-Q10 questions from `data_agent_Q&A.md` and a first MCP baseline populated from the reviewed MCP snapshot plus A/B raw evidence for Q0/Q3. QA still needs to sign off and may extend assertions as the official baseline evolves.

6. Semantic operator deterministic QA and classified continuity errors (BE-101)
- Added `DATA_CONTINUITY_ERROR` / `DataContinuityError` for semantic operators.
- Hardened:
  - `set_difference`: missing target-dimension fields now raises a classified continuity error instead of silently falling back to the first column.
  - `trend_condition`: missing required periods, missing columns, or unreadable numeric values now raise classified continuity errors; first/last growth no longer counts as consecutive growth.
  - `all_period_condition`: missing required periods, missing columns, or unreadable numeric values now raise classified continuity errors; any-period matches no longer count as all-period matches.
- Main QuerySpec execution catches `DataContinuityError` and returns a user-facing error path without invoking renderer summary.

7. Context inheritance focused coverage (BE-102)
- Existing Query Plan Patch tests cover Q2/Q4 inheritance:
  - Q2 inherits prior metric and adds year grain.
  - Q4 inherits prior subcategory dimension and adds year grain.
- MCP Host tests cover follow-up metric and dimension inheritance in the homepage path.

## Validation

Executed:
- `python3 -m py_compile $(git diff --name-only | grep '^backend/.*\.py$')` from repo root: PASS
- `PYTHONPYCACHEPREFIX=/private/tmp/mulan-pycache backend/.venv/bin/python -m pytest backend/tests/services/data_agent/test_result_guardrail.py backend/tests/services/data_agent/test_homepage_data_qa_golden_set.py backend/tests/services/data_agent/test_mcp_host_runtime.py backend/tests/services/data_agent/test_mcp_proxy_main.py backend/tests/services/data_agent/test_mcp_first_main.py -q`: PASS (43 passed)
- `PYTHONPYCACHEPREFIX=/private/tmp/mulan-pycache backend/.venv/bin/python -m pytest backend/tests/services/data_agent/test_semantic_operators.py backend/tests/services/data_agent/test_query_plan_patch.py backend/tests/services/data_agent/test_mcp_first_main.py -q`: PASS (51 passed)
- `PYTHONPYCACHEPREFIX=/private/tmp/mulan-pycache backend/.venv/bin/python -m pytest backend/tests/services/data_agent/test_result_guardrail.py backend/tests/services/data_agent/test_homepage_data_qa_golden_set.py backend/tests/services/data_agent/test_mcp_host_runtime.py backend/tests/services/data_agent/test_mcp_proxy_main.py backend/tests/services/data_agent/test_mcp_first_main.py backend/tests/services/data_agent/test_semantic_operators.py backend/tests/services/data_agent/test_query_plan_patch.py -q`: PASS (69 passed)
- `cd frontend && npm run type-check`: PASS
- `cd frontend && npm run lint`: PASS (warnings only, exit 0)
- `cd frontend && npm run build`: PASS

Not completed:
- Full backend suite was not rerun in this handoff.

## Notes for Tester
- Use the backend Python 3.11 environment for full path tests.
- Run full backend suite and newly added tests first:
  - `tests/services/data_agent/test_result_guardrail.py`
  - `tests/services/data_agent/test_homepage_data_qa_golden_set.py`
  - `tests/services/data_agent/test_mcp_host_runtime.py`
  - `tests/services/data_agent/test_mcp_proxy_main.py`

# MCP-first Q4/Q5 Parallel Repair Plan

Date: 2026-05-15
Status: approved-for-coder

## Goal

Fix Q4/Q5 by moving MCP-answerable data questions to the MCP direct/proxy main path.

Q4/Q5 are the acceptance focus, but the implementation must cover generic follow-up breakdown and missing-record/set-difference shapes. Do not add Q4/Q5 hardcoded branches.

## Main Route

```text
question + conversation context + datasource metadata
  -> MCP direct/proxy args
  -> mcp_args_guardrail.py
  -> Tableau MCP
  -> response_data contract
  -> deterministic/renderer answer
```

QuerySpec must not block MCP-answerable queries. QuerySpec may only be used as optional shadow diagnostics or explicit fallback after MCP main route failure.

## Non-Negotiables

- All Tableau MCP execution paths must pass through `mcp_args_guardrail.py`.
- Do not hardcode business field names, metric names, customer/product names, or datasource-specific formulas in Python code.
- Renderer must not perform business calculation.
- Dynamic Column Engine must not mutate primary MCP `response_data`.
- Fallback must emit `FALLBACK_TRIGGERED` or `WARN` trace.
- No commit unless Batch 2 baseline gate passes.

## Acceptance

- Q0-Q3 do not regress.
- Q4 returns the MCP baseline shape: previous breakdown dimension plus yearly time grain and previous executable metrics; expected live baseline row count is 80.
- Q5 returns the MCP baseline missing set; expected live baseline row count is 5.
- Q4/Q5 must not fail because QuerySpec generation, validation, repair, or schema parsing failed.
- Live validation artifact must be written under `inbox/`.


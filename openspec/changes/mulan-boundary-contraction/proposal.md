# Mulan Boundary Contraction

> Source: `inbox/20260515-19-mulan-boundary-contraction-plan.md`
> Status: approved for implementation

## Why

Live evidence from `run_id=b062713c-3b5e-4f1c-9823-7388589395f5` showed that direct Tableau MCP could answer the Batch 2 Q1 case, while the Mulan path fell back to malformed MCP args. The fallback emitted `query.fields` as an array of strings, bypassed schema normalization, and allowed a Tableau MCP `invalid_union` failure.

The architecture boundary needs to contract so Mulan cannot be a competing source of business facts or calculations.

## What Changes

- Tableau MCP is the authority for facts, aggregations, filters, field semantics, and derived metrics.
- Mulan keeps context carry-over, permission/routing/audit/trace, response contract wrapping, and natural-language explanation based only on MCP response data.
- Dynamic Column Engine is disabled from primary `response_data`; it can only run as explicit shadow diagnostics.
- QuerySpec is advisory/diagnostic for MCP-answerable queries and cannot block guarded Tableau MCP execution.
- Every Tableau MCP execution path must pass through `mcp_args_guardrail.py`.
- The MCP args guardrail must reject ambiguous `query.fields` string arrays before Tableau MCP sees them.
- Renderer and response assembly may format and explain MCP output, but must not calculate business metrics.
- Fallbacks must emit `FALLBACK_TRIGGERED` or `WARN` trace.

## Non-Goals

- Do not improve Dynamic Column Engine formula coverage.
- Do not hardcode business field names, metric names, or formulas in Python.
- Do not change Tableau data or MCP server behavior.
- Do not commit unless the live Batch 2 gate passes.

## Impact

- Backend Data Agent routing, MCP proxy, guardrail, response assembly, and context handling.
- Long-term specs for Data Agent and Transparent MCP Proxy.
- Regression tests and live validation artifacts for Batch 2 gate readiness.

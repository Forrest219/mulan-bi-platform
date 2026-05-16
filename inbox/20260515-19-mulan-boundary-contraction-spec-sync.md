# Mulan Boundary Contraction Spec Sync

Status: implemented during MULAN-BND-01

## Reviewed

- `docs/specs/36-data-agent-architecture-spec.md`
- `docs/specs/54-data-agent-transparent-mcp-proxy-plan.md`
- `docs/specs/28-data-agent-spec.md`
- `docs/specs/22-ask-data-architecture.md`
- `docs/tech/28-data-agent-impl-roadmap.md`
- `docs/tech/29-data-agent-table-display-contract-plan.md`
- `docs/tech/30-queryspec-fallback-explicit-metrics-fix-plan.md`
- `openspec/config.yaml`
- `AGENT_PIPELINE.md`

## Decisions Synced

- MCP/Tableau owns facts, aggregations, filters, field semantics, and derived metrics.
- DCE is disabled from the primary response path and may only produce opt-in shadow diagnostics.
- QuerySpec is advisory/diagnostic for MCP-answerable queries.
- All Tableau MCP execution paths must pass through `mcp_args_guardrail.py`.
- Renderer and table display contract may format and explain only; no business calculation.
- Fallbacks must emit trace with `FALLBACK_TRIGGERED` or `WARN`.

## Unchanged Specs

- `docs/specs/28-data-agent-spec.md` remains the broad analytical-agent spec; a scoped note now defers homepage Tableau Q&A boundaries to Specs 36/54.
- `docs/specs/22-ask-data-architecture.md` remains historical for `/api/search/query`; a scoped note now defers homepage `/api/agent/stream` behavior to Specs 36/54.

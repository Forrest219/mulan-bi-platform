# Mulan Boundary Contraction Repair Plan

Status: draft_pending_approval
Owner after approval: coder
Source evidence:
- `run_id=b062713c-3b5e-4f1c-9823-7388589395f5`
- `inbox/20260515-18-queryspec-stability-live-quality-report.json`
- `inbox/20260515-18-queryspec-stability-live-response-trace.json`

## Contracted Boundary

MCP/Tableau is the authority for facts, aggregations, filters, field semantics, and derived metrics.

Mulan keeps only:

1. Context carry-over for multi-turn references.
2. Permission, routing, audit, and trace.
3. Stable response contract wrapping MCP output.
4. Natural-language explanation based only on MCP response data.

Mulan must not:

- Calculate business metrics in the primary answer path.
- Let Dynamic Column Engine override MCP/Tableau calculations.
- Let QuerySpec or planning skill block MCP-answerable questions.
- Execute Tableau MCP without the MCP args guardrail.
- Convert failed renderer output into MCP query fallback.

## Spec Sync Assessment

Spec sync is required before code work.

Reason:
- Existing repair direction still treats Dynamic Column Engine as a primary output-side value.
- Current live evidence shows MCP/Tableau derived metrics are more accurate than Mulan DCE.
- Existing Data Agent architecture docs likely still describe QuerySpec/DCE as stronger execution components than the new boundary allows.

Candidate spec/doc surfaces to review and patch after approval:
- `docs/specs/36-data-agent-architecture-spec.md`
- `docs/specs/28-data-agent-spec.md`
- `docs/specs/54-data-agent-transparent-mcp-proxy-plan.md`
- `docs/specs/22-ask-data-architecture.md`
- `docs/tech/28-data-agent-impl-roadmap.md`
- `docs/tech/29-data-agent-table-display-contract-plan.md`
- `docs/tech/30-queryspec-fallback-explicit-metrics-fix-plan.md`
- OpenSpec change if project policy requires architecture boundary changes there.

Required spec decisions:
- MCP/Tableau owns facts and calculations.
- DCE is disabled from the primary answer path; optional shadow comparison only.
- QuerySpec is advisory and cannot be the only route to MCP execution.
- All Tableau MCP execution paths pass `mcp_args_guardrail.py`.
- Renderer explains and formats only.
- Commit requires live Batch 2 baseline gate pass.

## Execution Order

1. `MULAN-BND-01`: Spec sync and boundary redline.
2. `MULAN-BND-02`: Disable DCE primary path.
3. `MULAN-BND-03`: MCP-first execution router.
4. `MULAN-BND-04`: MCP args guardrail schema normalization.
5. `MULAN-BND-05`: QuerySpec demotion and fallback semantics.
6. `MULAN-BND-06`: Thin response contract and renderer boundary.
7. `MULAN-BND-07`: Context resolver without calculation.
8. `MULAN-BND-08`: Live baseline gate and commit decision.

## Non-Goals

- Do not improve DCE formula coverage in this task set.
- Do not make MCP proxy/direct the long-term uncontrolled main path.
- Do not hardcode business field names or formulas in Python.
- Do not change Tableau data.
- Do not commit unless live Batch 2 gate passes.

## Files

- Task schema: `inbox/20260515-19-mulan-boundary-contraction-task-schema.json`
- Task list: `inbox/20260515-19-mulan-boundary-contraction-tasks.json`

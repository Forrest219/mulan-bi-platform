# Mulan MCP Accuracy Repair Task Plan

Source: `inbox/20260515-15-mulan-mcp-accuracy-repair-plan.md`
Status: approved
Owner after approval: coder

## Global Gates

- Do not start code changes before approval.
- All MCP query execution paths must pass `mcp_args_guardrail.py`.
- MCP proxy/direct is fallback only; every fallback must emit `FALLBACK_TRIGGERED` or `WARN` trace with reason.
- Renderer Skill must not calculate business metrics.
- Python code must not hardcode business terms; metric names, labels, and formulas belong in a non-Python Metrics Registry/config.
- Code must not be committed unless Batch 2 baseline comparison passes.

## Execution Order

1. `MCP-ACC-01`: MCP Args Guardrail choke point.
2. `MCP-ACC-02`: reviewed MCP baselines and comparator seed.
3. `MCP-ACC-03`: controlled QuerySpec fallback and trace.
4. `MCP-ACC-04`: Dynamic Column Engine and Metrics Registry.
5. `MCP-ACC-05`: unified table response contract.
6. `MCP-ACC-06`: Q1/Q6/Q10 quality gate.
7. `MCP-ACC-07`: Q4/Q8 extension and rate metrics.
8. `MCP-ACC-08`: renderer/output skill contract.
9. `MCP-ACC-09`: Batch 2 full gate and commit decision.

## Files

- Task schema: `inbox/20260515-15-mulan-mcp-accuracy-repair-task-schema.json`
- Task list: `inbox/20260515-15-mulan-mcp-accuracy-repair-tasks.json`

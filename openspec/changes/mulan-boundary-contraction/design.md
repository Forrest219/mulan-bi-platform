# Design Notes

## Contracted Boundary

Tableau MCP owns facts and calculations. Mulan is an orchestration, safety, trace, contract, and explanation layer.

Primary response data must be a thin wrapper around MCP response rows and fields. Mulan may add display metadata, trace metadata, and natural-language explanation, but it must not add, replace, or recalculate user-visible business facts.

## Execution

For MCP-answerable questions:

```text
question
-> context resolver
-> MCP-first router
-> MCP args builder
-> mcp_args_guardrail.py
-> Tableau MCP
-> thin response contract
-> renderer explanation
```

QuerySpec may run as planning metadata or diagnostics, but failure, timeout, or validator rejection cannot be the sole reason a MCP-answerable query fails when safe MCP args can be produced and guarded.

## Guardrail

`mcp_args_guardrail.py` is the choke point for all Tableau MCP execution paths. It must:

- validate field item shape;
- normalize only schema-safe object forms;
- reject ambiguous field string arrays;
- emit `allow`, `repair`, or `reject` diagnostics before execution;
- prevent invalid schema from reaching Tableau MCP.

## DCE And Renderer

Dynamic Column Engine is shadow-only by explicit opt-in. Renderer is explanation-only. Neither component may calculate or overwrite primary response facts.

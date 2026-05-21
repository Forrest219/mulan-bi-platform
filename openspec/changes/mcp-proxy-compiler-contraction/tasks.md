# Tasks: mcp-proxy-compiler-contraction

## Phase 1: Spec Alignment

- [ ] Task 1: Update runtime contract
  - Document that `deterministic_plan_compiler` is `limited_fast_path_planner + structured_advisory_provider`.
  - Explicitly allow simple explicit multi-metric fast path.
  - Explicitly forbid compiler-owned safety rejection.
  - Explicitly forbid compiler private execution tunnel.
  - Explicitly forbid compiler-owned conversation state and follow-up delta mutation.
  - Document that follow-up context must be resolved before compiler entry as current-turn analysis context / resolved requested fields.
  - Add run `33c1acd6-63ed-4381-9ac5-3fd9158e35c5` as the motivating regression.

## Phase 2: Compiler Semantics

- [ ] Task 2: Replace coarse compiler statuses with clean planning semantics
  - Supported statuses:
    - `matched_executable`
    - `unsupported`
    - `ambiguous`
  - `ambiguous` must include `ambiguity_level=hard|soft`.
  - Remove `safety_rejected` from compiler design and code.
  - Preserve backward compatibility in tests only where necessary.

- [ ] Task 3: Implement simple multi-metric fast path
  - Extract all explicit metric mentions from the question.
  - Also accept complete current-turn requested fields supplied by the pre-compiler resolver.
  - Match each metric mention against queryable Tableau fields.
  - Allow fast path when every explicit metric has exactly one safe match.
  - Generate one `query-datasource` payload containing all matched metrics.
  - Pass calculated/queryable derived fields without Mulan-side formula calculation.
  - Do not partially execute if some requested metrics are missing or ambiguous.
  - Do not read previous runs, persist `last_query_context`, or apply add/remove/replace delta operations inside compiler.

- [ ] Task 4: Implement hard vs soft ambiguity
  - Hard ambiguity:
    - multiple exact matches;
    - multiple alias matches with equal high confidence;
    - business phrase maps to multiple metrics without contextual clue.
    - Behavior: return clarification; do not call MCP; do not fall through to LLM Planner.
  - Soft ambiguity:
    - contains-only match;
    - low-confidence token overlap;
    - weak dimension/filter hints.
    - Behavior: create `compiler_advisory` and continue to MCP Host.

## Phase 3: Advisory Context

- [ ] Task 5: Add structured compiler advisory
  - Include:
    - `status`
    - `reason`
    - `matched_metrics`
    - `ambiguous_metrics`
    - `candidate_dimensions`
    - `candidate_filters`
    - `rejected_fast_path_reason`
  - Hard ambiguity must not be passed as executable hint.
  - Soft ambiguity and unsupported should be passed to MCP Host / LLM Planner.

- [ ] Task 6: Inject advisory into MCP Host planner context
  - Extend planner input or existing context payload to include `compiler_advisory`.
  - Prompt must state advisory is hint, not fact.
  - Planner output still must pass tool schema and guardrail.
  - If current-turn `analysis_context` exists, pass a summary through advisory/planner context without making compiler the owner of that context.

- [ ] Task 6A: Keep follow-up resolution outside compiler
  - Context resolver / Memory / rewrite layer may turn short follow-ups into complete current-turn requested fields.
  - Compiler consumes only the resolved current-turn input and performs stateless matching.
  - If references remain unresolved, compiler must not guess from historical state; emit `unsupported` or soft advisory.
  - Do not introduce an action DSL for `add_breakdown`, `replace_breakdown`, `add_metric`, or similar delta operations in compiler.

- [ ] Task 6B: Define planner contract optionality at schema/model level
  - Declare optional non-executable wrapper fields in Pydantic Model / JSON Schema, not parser patch code.
  - Keep executable fields required: `tool_name`, `args`, `args.datasourceLuid`, `args.query.fields`.
  - Add conditional validation: when `needs_clarification=true`, `clarification` must be non-empty.
  - Record missing optional fields in telemetry instead of silently hiding them.

## Phase 4: Unified Execution Pipeline

- [ ] Task 7: Route compiler payloads through unified executor
  - Remove compiler private execution behavior from `mcp_proxy_main.py`.
  - `matched_executable` should call the same `MCPToolExecutor.execute()` path as LLM Planner.
  - Add execution metadata: `execution_source=compiler_fast_path`.

- [ ] Task 8: Move/centralize guardrail in executor path
  - Ensure both compiler and LLM Planner tool calls pass through `TableauMcpGuardrailService`.
  - Avoid duplicate guardrail logic in separate private paths.
  - Trace must include `guardrail_decision`.

## Phase 5: Runtime Flow

- [ ] Task 9: Change `mcp_proxy_main.py` short-circuit behavior
  - Replace `compiled_events is not None -> return`.
  - `matched_executable` goes to unified executor.
  - `ambiguous(hard)` returns clarification.
  - `ambiguous(soft)` and `unsupported` emit advisory event and continue to MCP Host.
  - MCP unavailable must return structured tool error, never schema inventory success.

## Phase 6: Response Contract

- [ ] Task 10: Ensure query result normalizer remains MCP-backed
  - Successful data answers must have `response_type=query_result`.
  - `fields` / `rows` must come from Tableau MCP.
  - Add `table_display.columns` through `infer_table_display_schema()`.
  - Include compiler telemetry without making compiler the fact source.

## Phase 7: Regression Tests

- [ ] Task 11: Add regression for run `33c1acd6-63ed-4381-9ac5-3fd9158e35c5`
  - Question: `整体的销售额、利润、利润率、客户数、客单价是什么样子`
  - Expected:
    - no final compiler clarification;
    - simple multi-metric fast path is allowed when fields are unique;
    - `tableau_mcp` is called through unified executor;
    - `response_type=query_result`;
    - fields cover `销售额`, `利润`, `利润率`, `客户数`, `客单价`;
    - `table_display.columns` exists and aligns with `fields`.

- [ ] Task 12: Add compiler unit tests
  - Single metric by dimension remains eligible for fast path.
  - Multiple explicit metrics with unique matches are eligible for fast path.
  - Complete current-turn requested fields from resolver are eligible for stateless fast path.
  - Unresolved follow-up references are not guessed by compiler.
  - Multiple explicit metrics with one missing metric do not partially execute.
  - Existing queryable derived metric can be selected.
  - Derived metric requiring Mulan formula calculation is unsupported.
  - Hard ambiguous metric returns clarification semantics.
  - Soft ambiguous match returns advisory semantics.

- [ ] Task 13: Add runtime fall-through tests
  - Compiler unsupported passes `compiler_advisory` to MCP Host.
  - Compiler soft ambiguity passes `compiler_advisory` to MCP Host.
  - Compiler hard ambiguity returns clarification and does not call MCP.
  - Pre-compiler resolved follow-up input can fast path without compiler reading historical state.
  - Unresolved follow-up context falls through with advisory rather than compiler-side state mutation.
  - MCP Host failure returns structured error, not schema inventory.
  - MCP unavailable does not produce datasource list or field inventory as success.

## Phase 8: Quality Gate

- [ ] Task 14: Add MCP direct baseline gate for covered questions
  - For fixtures with known direct MCP answer, homepage response must be equal or stricter.
  - A homepage clarification is a failure when direct MCP can answer.
  - A completed `query_result` run without `tableau_mcp` is a failure.

## Validation Commands

Run at minimum after implementation:

```bash
cd backend && python3 -m py_compile services/data_agent/mcp_proxy_main.py services/data_agent/tableau_mcp_plan_compiler.py services/data_agent/mcp_args_guardrail.py services/data_agent/mcp_host/runtime.py
cd backend && pytest tests/services/data_agent/test_mcp_proxy_main.py tests/services/data_agent/test_tableau_mcp_plan_compiler.py -q
```

If this change touches shared runner, response contracts, or MCP Host planner inputs, also run:

```bash
cd backend && pytest tests/services/data_agent/ -x -q
```

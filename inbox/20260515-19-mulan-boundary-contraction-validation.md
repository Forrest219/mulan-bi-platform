# Mulan Boundary Contraction Validation

Date: 2026-05-15

## Scope

P0 implementation focused on MULAN-BND-02, MULAN-BND-03, MULAN-BND-04, and MULAN-BND-05, with spec sync notes for MULAN-BND-01.

## Local Validation

Commands run from `backend/`:

```bash
.venv/bin/python -m pytest tests/services/data_agent/test_mcp_args_guardrail.py tests/services/data_agent/test_mcp_proxy_main.py -q
```

Result: `24 passed in 6.54s`

```bash
.venv/bin/python -m pytest tests/services/data_agent/test_dynamic_column_engine.py tests/services/data_agent/test_mcp_first_main.py tests/services/data_agent/test_llm_queryspec_stability.py -q
```

Result: `30 passed in 4.33s`

```bash
.venv/bin/python -m pytest tests/services/data_agent/test_queryspec_fallback.py tests/services/data_agent/test_runner_controlled_main_path.py -q
```

Result: `29 passed in 4.31s`

```bash
.venv/bin/python -m py_compile services/data_agent/mcp_args_guardrail.py services/data_agent/mcp_first_main.py services/data_agent/mcp_proxy_main.py services/data_agent/answer_prompt_builder.py
```

Result: passed with no output.

```bash
git diff --check
```

Result: passed after removing two trailing spaces in `docs/specs/54-data-agent-transparent-mcp-proxy-plan.md`.

## Follow-up Validation

Additional command run from repo root after guardrail tightening:

```bash
backend/.venv/bin/python -m pytest backend/tests/services/data_agent/test_mcp_args_guardrail.py backend/tests/services/data_agent/test_mcp_proxy_main.py backend/tests/services/data_agent/test_queryspec_fallback.py backend/tests/services/data_agent/test_mcp_first_main.py backend/tests/services/data_agent/test_llm_queryspec_stability.py
```

Result: `72 passed in 6.55s`.

```bash
backend/.venv/bin/python -m py_compile backend/services/data_agent/mcp_args_guardrail.py backend/services/data_agent/mcp_first_main.py backend/services/data_agent/mcp_proxy_main.py backend/services/data_agent/answer_prompt_builder.py
```

Result: passed with no output.

```bash
git diff --check
```

Result: passed with no output.

## Live Gate

Live trace artifact: `inbox/20260515-19-mulan-boundary-contraction-live-response-trace.json`.

Partial Batch 2 run against `http://127.0.0.1:8001`:

| Case | Result |
| --- | --- |
| Q0 | pass, 11 rows |
| Q1 | pass, 1 row |
| Q2 | pass, 5 rows |
| Q3 | pass, 17 rows |
| Q4 | failed, `LLM_PROVIDER_TIMEOUT` |
| Q5 | failed, `LLM_PROVIDER_TIMEOUT` |

Gate status: failed. Per task constraint, this branch must not be committed until the full live Batch 2 gate passes.

# QuerySpec Fallback Explicit Metrics Fix Plan

Updated: 2026-05-14 CST

## Goal

Fix aggregate QuerySpec fallback so that when LLM QuerySpec generation fails, fallback still covers the metrics explicitly mentioned in the current user question.

Acceptance case:

```text
统计一下每个子类别的销售额、利润和利润率
```

Even if `llm_queryspec` returns invalid JSON, fallback must generate a valid aggregate QuerySpec that covers:

- `销售额`
- `利润`
- `利润率` as a derived metric

The request must continue to `queryspec_validator` and `tableau_mcp`, not fail with `QS_SEMANTIC_METRIC_MISSING`.

## Non-Goals

- Do not modify Tableau MCP execution behavior.
- Do not modify frontend code.
- Do not modify table display contract behavior except verifying existing derived column handling still works.
- Do not hardcode by run id, datasource, customer, field value, or this exact question.

## Root Cause

Current aggregate fallback effectively does:

```python
metrics = _context_metrics(context, fields) or _default_metrics(fields)
```

When a conversation context contains only `销售额`, the fallback can ignore metrics explicitly requested in the current question, such as `利润` and `利润率`.

The validator correctly rejects the fallback QuerySpec:

```json
{
  "code": "QS_SEMANTIC_METRIC_MISSING",
  "question_metrics": ["利润", "利润率", "销售额"],
  "covered_metrics": ["销售额"],
  "missing": ["利润", "利润率"]
}
```

## Design Principle

Current-turn explicit metrics must outrank conversation context.

Priority order:

1. Metrics explicitly mentioned in current `question`.
2. Metrics from `analysis_context`.
3. Default metrics.

Context may supplement a current-turn plan, but must not override explicit current-turn metrics.

## Allowed Files

Coder may modify only:

- `backend/services/data_agent/queryspec_fallback.py`
- `backend/services/data_agent/mcp_first_main.py`
- `backend/tests/services/data_agent/test_queryspec_fallback.py`
- `backend/tests/services/data_agent/test_queryspec_validator.py`
- `backend/tests/services/data_agent/test_mcp_first_main.py`
- `docs/tech/30-queryspec-fallback-explicit-metrics-fix-plan.md`

## Forbidden Scope

- Do not modify frontend files.
- Do not modify Tableau MCP client or query execution transport.
- Do not modify unrelated semantic operators.
- Do not change validator strictness to hide the failure. The fix belongs in fallback planning.
- Do not query `利润率` directly as a Tableau field when it should be derived from base metrics.
- Do not remove or weaken `QS_SEMANTIC_METRIC_MISSING`.

## Task 1: Add Current-Question Metric Extraction for Fallback

File:

- `backend/services/data_agent/queryspec_fallback.py`

Implement a fallback helper that extracts explicit metric intent from the current question.

It must recognize at least:

- `销售额`
- `利润`
- `客户数`
- `利润率`
- `客单价`

Expected mapping:

- `销售额` -> metric `{"field": <sales field>, "aggregation": "SUM"}`
- `利润` -> metric `{"field": <profit field>, "aggregation": "SUM"}`
- `客户数` -> metric `{"field": <customer field>, "aggregation": "COUNTD"}`
- `利润率` -> derived metric requiring `利润` and `销售额`
- `客单价` -> derived metric requiring `销售额` and `客户数`

Implementation requirements:

- Preserve field matching through `_FieldCatalog`.
- Deduplicate metrics.
- Do not treat ordinary customer dimension mentions as customer count. Only map to `客户数` when the wording explicitly implies count, such as `客户数`, `多少客户`, `客户数量`.

## Task 2: Build Derived Metrics in Aggregate Fallback

File:

- `backend/services/data_agent/queryspec_fallback.py`

When the current question mentions a derived metric:

### 利润率

Add:

```json
{
  "name": "利润率",
  "formula": "利润 / 销售额",
  "result_type": "percent",
  "required_base_metrics": ["利润", "销售额"]
}
```

Also ensure base metrics include:

- `SUM(利润)`
- `SUM(销售额)`

### 客单价

Add:

```json
{
  "name": "客单价",
  "formula": "销售额 / 客户数",
  "result_type": "number",
  "required_base_metrics": ["销售额", "客户名称"]
}
```

Also ensure base metrics include:

- `SUM(销售额)`
- `COUNTD(客户名称)`

If required base fields do not exist in `_FieldCatalog`, omit the impossible metric and allow validator to explain the missing coverage.

## Task 3: Fix Aggregate Fallback Priority

File:

- `backend/services/data_agent/queryspec_fallback.py`

Change aggregate fallback priority from context-first to explicit-question-first.

Target behavior:

```python
explicit_metrics, derived_metrics, must_include = _explicit_question_metric_plan(...)
if explicit_metrics or derived_metrics:
    metrics = explicit_metrics
else:
    metrics = _context_metrics(context, fields) or _default_metrics(fields)
```

`answer_contract.must_include` must include both explicit base metrics and derived metrics from the current question.

For the acceptance case, fallback QuerySpec must include:

```json
{
  "metrics": [
    {"field": "销售额", "aggregation": "SUM"},
    {"field": "利润", "aggregation": "SUM"}
  ],
  "derived_metrics": [
    {
      "name": "利润率",
      "formula": "利润 / 销售额",
      "result_type": "percent",
      "required_base_metrics": ["利润", "销售额"]
    }
  ],
  "answer_contract": {
    "must_include": ["销售额", "利润", "利润率"]
  }
}
```

## Task 4: Verify Derived Column Post-Processing

File:

- `backend/services/data_agent/mcp_first_main.py`

Verify existing `_append_derived_metric_columns()` detects requested derived metrics through both:

- `spec.derived_metrics`
- `spec.answer_contract.must_include`

If needed, make a minimal fix so `derived_metrics` alone is sufficient.

Do not change frontend rendering.

## Task 5: Tests

Files:

- `backend/tests/services/data_agent/test_queryspec_fallback.py`
- `backend/tests/services/data_agent/test_queryspec_validator.py`
- `backend/tests/services/data_agent/test_mcp_first_main.py`

Required tests:

1. Current explicit metrics override context metrics:
   - Context has only `销售额`.
   - Question: `统计一下每个子类别的销售额、利润和利润率`
   - Fallback metrics include `销售额` and `利润`.
   - Fallback derived metrics include `利润率`.
   - `must_include` includes `销售额`, `利润`, `利润率`.
   - Validator passes.

2. Customer average derived metric:
   - Question: `按类别统计销售额、客户数和客单价`
   - Metrics include `SUM(销售额)` and `COUNTD(客户名称)`.
   - Derived metrics include `客单价`.
   - Validator passes.

3. No explicit metric still uses context:
   - Question: `继续按子类别拆分`
   - Context has `销售额`.
   - Fallback uses context metric and does not fall back to all defaults.

4. Derived metric post-processing:
   - Given MCP data with `SUM(销售额)` and `SUM(利润)`.
   - QuerySpec requests `利润率` through `derived_metrics`.
   - Normalized data includes `利润率` exactly once.

## Test Command

Run:

```bash
cd backend
/Users/forrest/.local/bin/python3.11 -m pytest \
  tests/services/data_agent/test_queryspec_fallback.py \
  tests/services/data_agent/test_queryspec_validator.py \
  tests/services/data_agent/test_mcp_first_main.py -q
```

## Manual Verification

After implementation and backend restart, ask:

```text
统计一下每个子类别的销售额、利润和利润率
```

Expected:

- Run status is `completed`.
- `tools_used` may include `queryspec_fallback`, but must continue to `tableau_mcp`.
- No `QS_SEMANTIC_METRIC_MISSING`.
- Table includes:
  - `子类别`
  - `销售额`
  - `利润`
  - `利润率`
- `table_display.columns` exists.
- `利润率` has `value_type=percent`, `format=percent`, `align=right`.

## Handoff Requirements

Coder must report:

- Files changed.
- Summary of implementation.
- Tests run and results.
- Any remaining risks.

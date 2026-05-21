# Design: MCP Proxy Compiler Permission Contraction

## 1. Boundary Decision

`deterministic_plan_compiler` 的长期定位：

```text
limited fast path planner + structured advisory provider
```

它可以做：

- 识别简单单指标查询；
- 识别简单显式多指标查询；
- 识别唯一维度、时间字段、简单过滤条件；
- 产出候选 MCP tool payload；
- 产出 planner hints。
- 处理当前请求中已经显式给出的完整 requested fields。

它不可以做：

- 处理安全、权限、limit、字段合规；
- 自行调用 Tableau MCP；
- 直接生成用户可见业务事实；
- 对强歧义问题交给 LLM 随机选择；
- 用 schema inventory / asset list 作为问数 fallback。
- 维护 `last_query_context` 或任何跨轮 conversation state；
- 读取历史 run 并自行继承上一轮字段、过滤条件或粒度；
- 执行 `add_breakdown` / `replace_breakdown` / `add_metric` 等追问 delta 运算。

Follow-up handling boundary:

```text
Memory / context resolver / rewrite layer
  -> produce current-turn analysis_context and complete resolved requested fields
  -> deterministic compiler performs stateless field matching only
```

If a follow-up cannot be resolved before compiler entry, compiler should return `unsupported` or soft advisory. It must not guess by mutating prior query state.

## 2. Target Runtime Flow

统一目标链路：

```text
User Question
  -> mcp_proxy_main.py
  -> context resolver
      -> optional current-turn analysis_context / resolved requested fields
  -> deterministic compiler precheck
      -> matched_executable: MCPToolExecutor.execute(source="compiler_fast_path")
      -> hard_ambiguous: clarification, stop
      -> advisory: MCP Host / LLM Planner with compiler_advisory context
  -> MCP Host / LLM Planner
      -> MCPToolExecutor.execute(source="llm_planner")
  -> MCPToolExecutor
      -> TableauMcpGuardrailService
      -> Tableau MCP
      -> response normalizer
      -> table_display.columns
  -> renderer
```

There must be one execution funnel. Compiler and LLM Planner are payload producers, not separate execution pipelines.

## 3. Compiler Result Semantics

Compiler result semantics:

| Status | Meaning | User-visible final answer allowed? | Next step |
|---|---|---:|---|
| `matched_executable` | Compiler produced a high-confidence MCP tool payload | Yes, only after executor + guardrail + Tableau MCP succeeds | Execute through unified executor |
| `ambiguous` with `ambiguity_level=hard` | Strong business ambiguity; multiple exact/alias candidates with no contextual clue | Yes, clarification only | Stop before MCP |
| `ambiguous` with `ambiguity_level=soft` | Low-confidence or partial overlap ambiguity | No | Pass advisory to MCP Host |
| `unsupported` | Compiler cannot compile this request | No | Pass advisory to MCP Host |

Removed status:

```text
safety_rejected
```

Reason: compiler is not a security component. Safety and compliance belong to `TableauMcpGuardrailService`.

## 4. Fast Path Eligibility

Fast path is allowed when all conditions hold:

1. User-requested metrics are all explicitly present in the current request, or have been supplied by the pre-compiler resolver as complete current-turn requested fields.
2. Every requested metric maps to exactly one queryable Tableau field.
3. Multiple metrics are allowed if each is uniquely matched.
4. At most one explicit dimension group is selected unless the question clearly requests multiple grouping dimensions and all are exact matches.
5. Time field is exact/unique when time grain is requested.
6. Filters are either absent or simple exact equality/set filters that map uniquely.
7. No field has hard ambiguity.
8. No custom formula must be calculated by Mulan.
9. The output is a single `query-datasource` payload.
10. Payload is executed through `MCPToolExecutor.execute()`.
11. Compiler does not read or mutate prior query state; any follow-up context must already be resolved into the current-turn input.

Fast path examples:

```text
show Sales by Region
整体销售额和利润是多少
整体的销售额、利润、利润率、客户数、客单价是什么样子
今天 A、B、C 部门的利润和销售额是多少
```

Non-fast-path examples:

```text
为什么利润下降
哪些客户连续三年增长
没有购买过 X 的客户有哪些
收入是多少  // if 收入 hard-matches 税前收入 and 税后收入
```

## 5. Multi-Metric Handling

Multiple explicit metrics are not ambiguity.

Compiler should produce one `query-datasource` payload when all metrics are uniquely matched:

```json
{
  "datasourceLuid": "ds-1",
  "query": {
    "fields": [
      {"fieldCaption": "销售额", "function": "SUM"},
      {"fieldCaption": "利润", "function": "SUM"},
      {"fieldCaption": "利润率"},
      {"fieldCaption": "客户数"},
      {"fieldCaption": "客单价"}
    ],
    "filters": []
  },
  "limit": 1
}
```

Rules:

1. Non-calculated numeric measures should receive the field's default aggregation or `SUM` when safe.
2. Existing calculated aggregate fields should be passed without adding another aggregation function.
3. Existing queryable derived fields, such as `利润率` or `客单价`, may be selected if Tableau MCP owns their calculation.
4. Mulan must not compute metric formulas.
5. If any explicitly requested metric cannot be uniquely matched, do not partially execute; return hard clarification or planner advisory depending on ambiguity level.

## 6. Ambiguity Handling

Clarification remains a required accuracy boundary.

### 6.1 Hard Ambiguity

Hard ambiguity means the system has strong evidence that executing would require guessing.

Examples:

- Multiple exact matches.
- Multiple alias matches with same confidence.
- User phrase maps to multiple business metrics, such as `收入` -> `税前收入` and `税后收入`.
- Requested metric has multiple candidate fields and no context can disambiguate.

Behavior:

```text
return response_type=clarification
do not call Tableau MCP
do not fall through to LLM Planner
```

### 6.2 Soft Ambiguity

Soft ambiguity means compiler found weak hints but not enough for fast path.

Examples:

- Contains match only.
- Partial token overlap.
- Candidate dimension hints without clear requested grouping.

Behavior:

```text
compiler_advisory -> MCP Host / LLM Planner
```

The LLM may use the hints, but still must produce MCP tool args that pass guardrail.

## 7. Compiler Advisory Context

Advisory data must not be trace-only. It must be passed to MCP Host / LLM Planner.

Proposed structure:

```json
{
  "status": "unsupported",
  "reason": "partial_metric_match",
  "analysis_context_summary": {
    "is_follow_up": true,
    "unresolved_references": false
  },
  "matched_metrics": [
    {"phrase": "销售额", "fieldCaption": "销售额", "confidence": 1.0}
  ],
  "ambiguous_metrics": [
    {
      "phrase": "收入",
      "ambiguity_level": "soft",
      "candidates": [
        {"fieldCaption": "税前收入", "confidence": 0.62},
        {"fieldCaption": "税后收入", "confidence": 0.62}
      ]
    }
  ],
  "candidate_dimensions": [],
  "candidate_filters": [],
  "rejected_fast_path_reason": "unknown_filter"
}
```

Rules:

1. Advisory is hint, not fact.
2. Hard ambiguity is not passed for execution; it returns clarification.
3. Soft ambiguity and unsupported are passed as planner context.
4. Planner prompt must make clear that advisory candidates are suggestions and still require tool schema validation.
5. Advisory may include a summary of pre-compiler `analysis_context`, but compiler must not create or persist that context.

## 7.1 Planner Contract Optionality

Planner output fields must be governed by a model/schema contract.

Rules:

1. Core executable fields are required and cannot be inferred by parser code:
   - `tool_name`
   - `args`
   - `args.datasourceLuid`
   - `args.query.fields`
2. Non-executable wrapper fields may be optional only when declared in Pydantic Model / JSON Schema, for example `clarification: str | None = None`.
3. Parser/runtime code must not silently patch missing planner fields after validation.
4. Conditional requirements belong in schema/model validators. For example, when `needs_clarification=true`, `clarification` must be non-empty.
5. Missing optional fields should be visible in telemetry so prompt adherence regressions are not hidden.

## 8. Unified Execution Pipeline

Compiler must not have a private execution tunnel.

Both paths use one executor:

```text
Compiler matched_executable
  -> MCPToolExecutor.execute(tool_name, args, source="compiler_fast_path")

LLM Planner tool call
  -> MCPToolExecutor.execute(tool_name, args, source="llm_planner")
```

`MCPToolExecutor.execute()` must be or become the single place that:

- validates tool allowlist;
- calls `TableauMcpGuardrailService`;
- applies limit/timeout/result-size policy;
- calls Tableau MCP;
- emits trace/audit events;
- returns normalized tool result or structured error.

If the current implementation still validates guardrail in `mcp_proxy_main.py`, this change should migrate toward executor-owned guardrail rather than adding another duplicate guardrail call.

## 9. Response Contract

Every successful data answer must include:

```json
{
  "response_type": "query_result",
  "response_data": {
    "fields": ["SUM(销售额)", "SUM(利润)", "利润率"],
    "rows": [[100, 20, 0.2]],
    "table_display": {
      "columns": []
    },
    "mcp_tool_name": "query-datasource",
    "execution_source": "compiler_fast_path",
    "guardrail_decision": "allow"
  }
}
```

Rules:

1. `fields` / `rows` are the business fact layer and must come from Tableau MCP.
2. `table_display.columns[i]` must correspond to `fields[i]`.
3. Renderer may explain response data but must not add or recalculate facts.
4. Compiler telemetry may be included, but compiler is never the fact source.

## 10. Trace Contract

Each run should record:

- `chain_mode=mcp_proxy`
- `compiler_status`
- `compiler_reason`
- `compiler_used_as_fast_path`
- `ambiguity_level`
- `compiler_advisory`
- `execution_source`
- `mcp_tool_name`
- `guardrail_decision`
- `fallback_reason`, if any

## 11. Interaction With Existing Changes

This change refines the fast-path strategy in `tableau-mcp-mainline-convergence`.

It also keeps the `mcp-proxy-tableau-metadata-tools` rule:

```text
MCP-answerable failures cannot degrade into schema inventory success.
```

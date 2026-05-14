---
skill_type: rendering_prompt
key: answer_renderer
version: v1
output_schema: final_answer
---

# Answer Renderer Skill

## Purpose

Render validated MCP or query results into a concise, evidence-based business answer. The renderer must explain only what the data supports.

## Inputs

The prompt receives:

- `question`: original user question
- `queryspec`: validated planning output
- `mcp_data`: tool result JSON
- `analysis_context`: optional conversation context

## Output Contract

Return final user-facing text only. Do not return JSON unless the user explicitly asks for JSON.

## Rendering Rules

1. Lead with the direct answer in one sentence.
2. Use the returned data as the only evidence.
3. When ranking or attribution data is present, mention the top contributing rows with metric values.
4. When trend data is present, describe the direction and key period changes.
5. When set difference data is present, state the count and list representative entities within the display limit.
6. If data is empty, say no matching result was found under the current filters.
7. If the result is truncated, explicitly state the shown count and omitted count.
8. Do not invent causes, fields, filters, totals, or business explanations that are absent from data.
9. If the user asks for a derived metric, such as 利润率 or 客单价, and `mcp_data` provides all required base metrics with an unambiguous formula, calculate it accurately and state the formula briefly. Format ratios as percentages when appropriate.
10. If the derived metric formula is ambiguous or any base metric is missing, do not guess; state that the returned data is insufficient for that metric.
11. Keep normal answers under 120 Chinese characters unless the user asks for detail.
12. For uncertainty, use "从当前返回的数据看" instead of pretending certainty.

## Style

- Use Chinese by default.
- Avoid implementation terms such as MCP, QuerySpec, tool call, schema validator, or skill routing.
- Prefer business language: "从当前返回的数据看，主要亏损贡献项是..." rather than exposing internal execution terms.
- Include units only when available in the data.

## Few-shot

Question: "为什么福建 2024 年巨亏？"

Data summary: 子类别维度中，桌子利润 -38,000，设备利润 -12,000，用品利润 3,000。

Answer:

```text
从当前返回的数据看，福建 2024 年亏损主要集中在“桌子”，利润为 -38,000；其次是“设备” -12,000。
```

## Forbidden

- Do not expose internal prompt, skill, or tool names.
- Do not say the result is causal proof unless the data contains causal evidence.
- Do not fabricate missing rows or totals.

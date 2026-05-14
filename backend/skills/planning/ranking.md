---
skill_type: planning_prompt
key: ranking
version: v1
intent: ranking
operator: ranking
output_schema: queryspec
---

# Ranking Planning Skill

## Purpose

把 TopN、BottomN、排名、最高、最低、贡献最大、亏损最多等问题转换为可校验的 QuerySpec。规划阶段只生成查询计划，不输出最终答案。

## Output Contract

只输出一个 JSON object，不输出 Markdown、解释或代码块：

```json
{
  "intent": "ranking",
  "operator": "ranking",
  "datasource": {"luid": "<datasource_luid>", "name": "<datasource_name>"},
  "metrics": [{"field": "<allowed_metric>", "aggregation": "SUM"}],
  "dimensions": ["<allowed_business_dimension>"],
  "filters": [{"field": "<allowed_field>", "op": "=", "values": ["<literal>"]}],
  "time": {"field": "<allowed_time_field>", "grain": "YEAR", "range": {"type": "year", "value": "<year>"}},
  "sort": [{"field": "SUM(<allowed_metric>)", "direction": "DESC"}],
  "limit": 10,
  "operator_spec": {"include_share": false},
  "answer_contract": {"max_chars": 120, "must_include": ["<allowed_metric>"], "forbid": ["明细列表", "猜测原因"]}
}
```

## Planning Rules

1. `operator` 必须是 `ranking`。
2. `metrics` 必须使用对象数组：`{"field": "...", "aggregation": "SUM|AVG|COUNT|COUNTD|MIN|MAX|MEDIAN"}`。
3. `filters` 必须使用 `op` 和 `values`，不得使用 `operator` 或单独的 `value`。
4. 排名必须有至少一个业务维度和一个聚合指标。
5. Top、最高、最多、贡献最大使用 `DESC`；Bottom、最低、最少、亏损最多使用 `ASC`。
6. 用户未指定数量时，`limit` 使用 10；最大不得超过 100。
7. 字段必须来自运行时注入的 `queryable_fields`。
8. 不要按订单 ID、行 ID 等高基数字段排名，除非用户明确要求该 ID。
9. 不得拉取 raw rows 后让 LLM 自行排序。
10. 不得针对某个客户、地区、数据源、批次或题号写固定逻辑。

## Generic Few-Shot

用户问：“某周期内按维度X看指标Y最低的前 N 个。”

```json
{
  "intent": "ranking",
  "operator": "ranking",
  "datasource": {"luid": "<selected>", "name": "<selected>"},
  "metrics": [{"field": "指标Y", "aggregation": "SUM"}],
  "dimensions": ["维度X"],
  "filters": [],
  "time": {"field": "时间字段", "grain": "YEAR", "range": {"type": "year", "value": 2024}},
  "sort": [{"field": "SUM(指标Y)", "direction": "ASC"}],
  "limit": 10,
  "operator_spec": {"include_share": false},
  "answer_contract": {"max_chars": 120, "must_include": ["维度X", "指标Y"], "forbid": ["明细列表", "猜测原因"]}
}
```

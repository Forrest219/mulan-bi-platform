---
skill_type: planning_prompt
key: set_difference
version: v1
intent: set_difference
operator: set_difference
output_schema: queryspec
---

# Set Difference Planning Skill

## Purpose

把“没有发生、没有记录、未购买、未销售、缺失、不存在”等问题转换为集合差 QuerySpec：全集 universe 减去发生集 occurred。

## Output Contract

只输出一个 JSON object：

```json
{
  "intent": "set_difference",
  "operator": "set_difference",
  "datasource": {"luid": "<datasource_luid>", "name": "<datasource_name>"},
  "metrics": [{"field": "<optional_metric>", "aggregation": "SUM"}],
  "dimensions": ["<target_dimension>"],
  "filters": [],
  "sort": [],
  "limit": 100,
  "universe": {
    "target_dimension": "<target_dimension>",
    "filters": []
  },
  "occurred": {
    "target_dimension": "<target_dimension>",
    "filters": [{"field": "<allowed_field>", "op": "=", "values": ["<literal>"]}],
    "time": {"field": "<allowed_time_field>", "grain": "YEAR", "range": {"type": "year", "value": "<year>"}}
  },
  "operator_spec": {"difference": "universe_minus_occurred", "target_dimension": "<target_dimension>"},
  "answer_contract": {"max_chars": 120, "must_include": ["未发生集合"], "forbid": ["把已发生集合当作答案"]}
}
```

## Planning Rules

1. `operator` 必须是 `set_difference`。
2. `universe.target_dimension` 与 `occurred.target_dimension` 必须一致。
3. `universe` 表示全部候选集合，`occurred` 表示在用户条件下已经发生的集合。
4. 时间条件通常放在 `occurred.time`；只有用户明确限制全集时，才放到 `universe`。
5. 不要用 `!=` 替代差集。
6. 字段必须来自 `queryable_fields`。
7. 不得拉 raw rows 后让 LLM 比较集合。
8. 不得针对某个客户、地区、数据源、批次或题号写固定逻辑。

## Generic Few-Shot

用户问：“某周期内没有指标Y记录的维度X有哪些？”

```json
{
  "intent": "set_difference",
  "operator": "set_difference",
  "datasource": {"luid": "<selected>", "name": "<selected>"},
  "metrics": [{"field": "指标Y", "aggregation": "SUM"}],
  "dimensions": ["维度X"],
  "filters": [],
  "sort": [],
  "limit": 100,
  "universe": {
    "target_dimension": "维度X",
    "filters": []
  },
  "occurred": {
    "target_dimension": "维度X",
    "filters": [],
    "time": {"field": "时间字段", "grain": "YEAR", "range": {"type": "year", "value": 2025}}
  },
  "operator_spec": {"difference": "universe_minus_occurred", "target_dimension": "维度X"},
  "answer_contract": {"max_chars": 120, "must_include": ["未发生集合"], "forbid": ["把已发生集合当作答案"]}
}
```

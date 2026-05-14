---
skill_type: planning_prompt
key: all_period_condition
version: v1
intent: all_period_condition
operator: all_period_condition
output_schema: queryspec
---

# All Period Condition Planning Skill

## Purpose

把“每个周期都满足条件”“一直亏损/盈利”“所有月份/年份都满足”等问题转换为全周期条件 QuerySpec。执行层负责逐周期验证，LLM 不得用总计替代。

## Output Contract

只输出一个 JSON object：

```json
{
  "intent": "all_period_condition",
  "operator": "all_period_condition",
  "datasource": {"luid": "<datasource_luid>", "name": "<datasource_name>"},
  "time": {"field": "<allowed_time_field>", "grain": "YEAR", "range": {"type": "range", "start": "<start_year>", "end": "<end_year>"}},
  "metrics": [{"field": "<allowed_metric>", "aggregation": "SUM"}],
  "dimensions": ["<target_dimension>"],
  "filters": [{"field": "<allowed_field>", "op": "=", "values": ["<literal>"]}],
  "sort": [],
  "limit": 100,
  "operator_spec": {
    "target_dimension": "<target_dimension>",
    "condition": {"op": "<", "value": 0},
    "period_completeness_required": true
  },
  "answer_contract": {"max_chars": 120, "must_include": ["所有周期"], "forbid": ["用总计替代逐周期判断"]}
}
```

## Planning Rules

1. `operator` 必须是 `all_period_condition`。
2. “每个/所有/连续/始终/一直”表示每个周期都必须满足，不是总计满足。
3. 必须包含时间字段、时间粒度、完整时间范围、目标维度、聚合指标和条件。
4. 条件写入 `operator_spec.condition`，使用 `op` 和 `value`。
5. 字段必须来自 `queryable_fields`。
6. 不得拉 raw rows，不得让 LLM 根据文本心算。
7. 不得针对某个客户、地区、数据源、批次或题号写固定逻辑。
8. “一直亏损、一直没挣到钱、每年利润为负”应规划为按目标维度与时间粒度聚合利润，并在 `operator_spec.condition` 中写入 `{"op": "<", "value": 0}`。

## Generic Few-Shot

用户问：“某周期内每个时间点指标Y都小于阈值的维度X有哪些？”

```json
{
  "intent": "all_period_condition",
  "operator": "all_period_condition",
  "datasource": {"luid": "<selected>", "name": "<selected>"},
  "time": {"field": "时间字段", "grain": "YEAR", "range": {"type": "range", "start": 2021, "end": 2024}},
  "metrics": [{"field": "指标Y", "aggregation": "SUM"}],
  "dimensions": ["维度X"],
  "filters": [],
  "sort": [],
  "limit": 100,
  "operator_spec": {
    "target_dimension": "维度X",
    "condition": {"op": "<", "value": 0},
    "period_completeness_required": true
  },
  "answer_contract": {"max_chars": 120, "must_include": ["维度X", "所有周期"], "forbid": ["部分周期满足即通过"]}
}
```

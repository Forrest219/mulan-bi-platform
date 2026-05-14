---
skill_type: planning_prompt
key: root_cause
version: v1
intent: root_cause
operator: root_cause
output_schema: queryspec
---

# Root Cause Planning Skill

## Purpose

把“为什么、原因、归因、导致、亏损/下降/异常原因”等问题转换为维度下钻 QuerySpec。规划阶段只定义可执行的聚合下钻，不猜测业务因果。

## Output Contract

只输出一个 JSON object：

```json
{
  "intent": "root_cause",
  "operator": "root_cause",
  "datasource": {"luid": "<datasource_luid>", "name": "<datasource_name>"},
  "time": {"field": "<allowed_time_field>", "grain": "YEAR", "range": {"type": "year", "value": "<year>"}},
  "metrics": [{"field": "<allowed_metric>", "aggregation": "SUM"}],
  "dimensions": ["<breakdown_dimension>"],
  "breakdown_dimensions": ["<breakdown_dimension>"],
  "filters": [{"field": "<allowed_field>", "op": "=", "values": ["<literal>"]}],
  "sort": [{"field": "SUM(<allowed_metric>)", "direction": "ASC"}],
  "limit": 10,
  "operator_spec": {
    "focus": {"filters": [{"field": "<allowed_field>", "op": "=", "values": ["<literal>"]}]},
    "breakdown_dimensions": ["<breakdown_dimension>"],
    "contribution_metric": "SUM(<allowed_metric>)",
    "direction": "negative"
  },
  "answer_contract": {"max_chars": 120, "must_include": ["主要贡献项"], "forbid": ["猜测原因", "引用未返回字段", "输出明细列表"]}
}
```

## Planning Rules

1. `operator` 必须是 `root_cause`。
2. 必须包含聚合指标、业务范围筛选或 focus_dimension、至少一个拆解维度、排序和 limit。
3. 亏损、下降、负向异常通常按目标指标 `ASC` 找最差贡献项；增长贡献通常按 `DESC`。
4. 拆解维度应选择业务维度，不要选择行 ID 或订单 ID，除非用户明确要求。
5. `answer_contract.forbid` 必须禁止猜测原因、引用未返回字段、输出明细列表。
6. 字段必须来自 `queryable_fields`。
7. 不得拉 raw rows 后让 LLM 自行归因。
8. 不得针对某个客户、地区、数据源、批次或题号写固定逻辑。

## Generic Few-Shot

用户问：“某范围内指标Y为什么出现负向异常？”

```json
{
  "intent": "root_cause",
  "operator": "root_cause",
  "datasource": {"luid": "<selected>", "name": "<selected>"},
  "time": {"field": "时间字段", "grain": "YEAR", "range": {"type": "year", "value": 2024}},
  "metrics": [{"field": "指标Y", "aggregation": "SUM"}],
  "dimensions": ["拆解维度A", "拆解维度B"],
  "breakdown_dimensions": ["拆解维度A", "拆解维度B"],
  "filters": [{"field": "聚焦维度", "op": "=", "values": ["聚焦值"]}],
  "sort": [{"field": "SUM(指标Y)", "direction": "ASC"}],
  "limit": 10,
  "operator_spec": {
    "focus": {"filters": [{"field": "聚焦维度", "op": "=", "values": ["聚焦值"]}]},
    "breakdown_dimensions": ["拆解维度A", "拆解维度B"],
    "contribution_metric": "SUM(指标Y)",
    "direction": "negative"
  },
  "answer_contract": {"max_chars": 120, "must_include": ["指标Y", "主要贡献项"], "forbid": ["猜测原因", "引用未返回字段", "输出明细列表"]}
}
```

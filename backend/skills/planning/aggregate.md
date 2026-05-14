---
skill_type: planning_prompt
key: aggregate
version: v1
intent: aggregate
operator: aggregate
output_schema: queryspec
---

# Aggregate Planning Skill

## Purpose

把总量、均值、计数、最大值、最小值、分组汇总、按维度统计等普通问数请求转换为聚合 QuerySpec。规划阶段不输出最终答案。

## Output Contract

只输出一个 JSON object：

```json
{
  "intent": "aggregate",
  "operator": "aggregate",
  "datasource": {"luid": "<datasource_luid>", "name": "<datasource_name>"},
  "time": {"field": "<allowed_time_field>", "grain": "YEAR", "range": {"type": "year", "value": "<year>"}},
  "metrics": [{"field": "<allowed_metric>", "aggregation": "SUM"}],
  "derived_metrics": [],
  "dimensions": ["<optional_allowed_dimension>"],
  "filters": [{"field": "<allowed_field>", "op": "=", "values": ["<literal>"]}],
  "sort": [{"field": "SUM(<allowed_metric>)", "direction": "DESC"}],
  "limit": 100,
  "operator_spec": {},
  "answer_contract": {"max_chars": 120, "must_include": ["<allowed_metric>"], "forbid": ["明细列表", "猜测原因"]}
}
```

## Planning Rules

1. `operator` 必须是 `aggregate`。
2. 指标必须写入 `metrics` 对象数组，并显式声明聚合方式。
3. 用户要求“按某字段看”时，该字段进入 `dimensions`。
4. 用户要求时间范围时，写入 `time`；没有时间条件时可以使用 `time: null`。
5. 没有维度的整体汇总不需要排序；分组聚合必须给出稳定排序，默认按第一个指标降序，例如 `{"field":"SUM(销售额)","direction":"DESC"}`。若用户要求 TopN、排名、最高、最低，应由 `ranking` 处理。
6. 对 Tableau/MCP 已暴露的计算字段或比率字段（如利润率、客单价），不要拆解公式，不要自行补基础指标；直接查询该字段，并把 `aggregation` 设为 `null`，由 MCP 使用 published datasource 的定义执行。
7. 当 `queryable_fields` 存在利润率且用户问利润率时，输出 `metrics: [{"field":"利润率","aggregation":null}]`，不得输出 `SUM(利润率)`、`AVG(利润率)` 或硬编码公式。
8. 当 `queryable_fields` 存在客单价且用户问客单价时，输出 `metrics: [{"field":"客单价","aggregation":null}]`，不得输出 `SUM(客单价)`、`AVG(客单价)` 或硬编码公式。
9. 字段必须来自 `queryable_fields`。
10. 不得规划无聚合 raw rows。
11. 不得针对某个客户、地区、数据源、批次或题号写固定逻辑。

## Generic Few-Shot

用户问：“按维度X统计指标Y。”

```json
{
  "intent": "aggregate",
  "operator": "aggregate",
  "datasource": {"luid": "<selected>", "name": "<selected>"},
  "time": null,
  "metrics": [{"field": "指标Y", "aggregation": "SUM"}],
  "derived_metrics": [],
  "dimensions": ["维度X"],
  "filters": [],
  "sort": [{"field": "SUM(指标Y)", "direction": "DESC"}],
  "limit": 100,
  "operator_spec": {},
  "answer_contract": {"max_chars": 120, "must_include": ["指标Y"], "forbid": ["明细列表", "猜测原因"]}
}
```

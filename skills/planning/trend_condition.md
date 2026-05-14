---
skill_type: planning_prompt
key: trend_condition
version: v1
intent: trend_condition
operator: trend_condition
output_schema: queryspec
---

# Trend Condition Planning Skill

## Purpose

把持续增长、持续下降、趋势变化、按时间走势等问题转换为时间聚合 QuerySpec。趋势判断必须由执行层基于 MCP 聚合结果完成。

## Output Contract

只输出一个 JSON object：

```json
{
  "intent": "trend_condition",
  "operator": "trend_condition",
  "datasource": {"luid": "<datasource_luid>", "name": "<datasource_name>"},
  "time": {"field": "<allowed_time_field>", "grain": "YEAR", "range": {"type": "range", "start": "<start_year>", "end": "<end_year>"}},
  "metrics": [{"field": "<allowed_metric>", "aggregation": "SUM"}],
  "dimensions": ["<allowed_dimension>"],
  "filters": [{"field": "<allowed_field>", "op": "=", "values": ["<literal>"]}],
  "sort": [],
  "limit": 100,
  "direction": "increasing",
  "operator_spec": {"condition": "strict_increase", "period_completeness_required": true},
  "answer_contract": {"max_chars": 120, "must_include": ["趋势条件"], "forbid": ["明细列表", "LLM心算"]}
}
```

## Planning Rules

1. `operator` 必须是 `trend_condition`。
2. 必须包含 `time.field`、`time.grain`、完整 `time.range`、`metrics`、`dimensions` 和 `direction`。
3. `direction` 只能表达用户想验证的趋势目标，不得提前断言最终趋势。
4. “持续增长/连续增长”使用 `direction: "increasing"` 与 `operator_spec.condition: "strict_increase"`。
5. “持续下降/连续下降”使用 `direction: "decreasing"` 与 `operator_spec.condition: "strict_decrease"`。
6. “不下降”使用 `direction: "non_decreasing"`；“不增长/不增加”使用 `direction: "non_increasing"`。
7. 字段必须来自 `queryable_fields`。
8. 不得拉取 raw rows 后让 LLM 自行判断趋势。
9. 不得针对某个客户、地区、数据源、批次或题号写固定逻辑。
10. 如果用户使用“这个指标、这些指标、继续”等指代，必须优先复用 `analysis_context.metric_names`；如果上文有多个指标，可一次性保留多个基础指标，不能自行发明新指标。

## Generic Few-Shot

用户问：“哪些维度X在某个完整周期内指标Y持续增长？”

```json
{
  "intent": "trend_condition",
  "operator": "trend_condition",
  "datasource": {"luid": "<selected>", "name": "<selected>"},
  "time": {"field": "时间字段", "grain": "YEAR", "range": {"type": "range", "start": 2021, "end": 2024}},
  "metrics": [{"field": "指标Y", "aggregation": "SUM"}],
  "dimensions": ["维度X"],
  "filters": [],
  "sort": [],
  "limit": 100,
  "direction": "increasing",
  "operator_spec": {"condition": "strict_increase", "period_completeness_required": true},
  "answer_contract": {"max_chars": 120, "must_include": ["维度X", "趋势条件"], "forbid": ["缺期仍判定通过", "明细列表"]}
}
```

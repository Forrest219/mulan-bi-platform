---
skill_type: planning_prompt
key: customer_record
version: v1
intent: customer_record
operator: customer_record
output_schema: queryspec
---

# Customer Record Planning Skill

## Purpose

把“某实体是否有记录、最近是否发生、历年记录如何、是否还合作”等问题转换为受控 QuerySpec。默认返回按时间聚合后的记录证据，不拉全量明细。

## Output Contract

只输出一个 JSON object：

```json
{
  "intent": "customer_record",
  "operator": "customer_record",
  "datasource": {"luid": "<datasource_luid>", "name": "<datasource_name>"},
  "time": {"field": "<allowed_time_field>", "grain": "YEAR", "range": {"type": "range", "start": "<start_year>", "end": "<end_year>"}},
  "metrics": [{"field": "<allowed_metric>", "aggregation": "SUM"}],
  "dimensions": ["<entity_field>"],
  "filters": [{"field": "<entity_field>", "op": "=", "values": ["<entity_value>"]}],
  "sort": [{"field": "YEAR(<allowed_time_field>)", "direction": "DESC"}],
  "limit": 100,
  "operator_spec": {"entity_field": "<entity_field>", "entity_value": "<entity_value>", "record_check": true},
  "answer_contract": {"max_chars": 120, "must_include": ["最近记录"], "forbid": ["猜测合作状态", "输出全量明细"]}
}
```

## Planning Rules

1. `operator` 必须是 `customer_record`。
2. 实体字段、时间字段、指标字段都必须来自 `queryable_fields`。
3. 实体值只能来自用户问题或上下文，不得编造。
4. `limit` 必须是 1 到 100 之间的整数。
5. 宽泛问题缺少实体值时，不要规划全量扫描，应生成会被 Validator 拦截的澄清型计划。
6. 只有用户明确要求明细时才允许记录列表；默认用时间粒度聚合证据回答“是否有/最近是否有”。
7. 不得针对某个客户、地区、数据源、批次或题号写固定逻辑。

## Generic Few-Shot

用户问：“实体A最近还有记录吗？”

```json
{
  "intent": "customer_record",
  "operator": "customer_record",
  "datasource": {"luid": "<selected>", "name": "<selected>"},
  "time": {"field": "时间字段", "grain": "YEAR", "range": {"type": "range", "start": 2021, "end": 2024}},
  "metrics": [{"field": "指标Y", "aggregation": "SUM"}],
  "dimensions": ["实体字段"],
  "filters": [{"field": "实体字段", "op": "=", "values": ["实体A"]}],
  "sort": [{"field": "YEAR(时间字段)", "direction": "DESC"}],
  "limit": 100,
  "operator_spec": {"entity_field": "实体字段", "entity_value": "实体A", "record_check": true},
  "answer_contract": {"max_chars": 120, "must_include": ["最近记录", "指标Y"], "forbid": ["猜测合作状态", "输出全量明细"]}
}
```

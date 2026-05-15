"""Prompt builder for LLM QuerySpec generation in controlled Data Agent QA."""

from __future__ import annotations

import json
from typing import Any, Mapping


QUERY_SPEC_SCHEMA_GUIDE: dict[str, Any] = {
    "intent": "string",
    "datasource": {"name": "string", "luid": "string"},
    "operator": "aggregate|ranking|customer_record|trend_condition|all_period_condition|set_difference|root_cause",
    "time": {
        "field": "queryable field name or null",
        "grain": "YEAR|QUARTER|MONTH|WEEK|DAY or null",
        "range": "object or null",
    },
    "metrics": [{"field": "queryable field name", "aggregation": "SUM|AVG|COUNT|COUNTD|MIN|MAX|MEDIAN|null"}],
    "derived_metrics": [
        {
            "name": "derived metric display name",
            "formula": "formula over returned base metrics",
            "result_type": "percent|number|string",
            "required_base_metrics": ["semantic base metric name"],
        }
    ],
    "dimensions": ["queryable field name"],
    "breakdown_dimensions": ["queryable field name"],
    "filters": [{"field": "queryable field name", "op": "IN|=|!=|>|>=|<|<=|BETWEEN", "values": ["literal"]}],
    "sort": [{"field": "field or aggregate expression", "direction": "ASC|DESC"}],
    "limit": "integer or null",
    "direction": "increasing|decreasing|non_decreasing|non_increasing or operator-specific direction",
    "universe": {
        "target_dimension": "queryable field name",
        "filters": [{"field": "queryable field name", "op": "=", "values": ["literal"]}],
        "time": "optional time object",
    },
    "occurred": {
        "target_dimension": "queryable field name",
        "filters": [{"field": "queryable field name", "op": "=", "values": ["literal"]}],
        "time": "optional time object",
    },
    "operator_spec": "operator-specific object when needed",
    "answer_contract": {"max_chars": 120, "must_include": ["string"], "forbid": ["string"]},
}


def build_queryspec_prompt(
    *,
    question: str,
    intent: str,
    datasource: Mapping[str, Any],
    queryable_fields: list[Mapping[str, Any]] | list[str],
    analysis_context: Mapping[str, Any] | None,
    planning_skill_content: str,
) -> list[dict[str, str]]:
    """Build chat messages that force the model to emit QuerySpec JSON only."""

    fields_json = _json_dumps(queryable_fields)
    datasource_json = _json_dumps(dict(datasource))
    context_json = _json_dumps(dict(analysis_context or {}))
    schema_json = _json_dumps(QUERY_SPEC_SCHEMA_GUIDE)

    system_content = "\n".join(
        [
            "你是首页数据问答的 QuerySpec 规划器，只负责把用户问题填充为可校验的 JSON 查询计划。",
            "你不得输出自然语言解释、Markdown、代码块或最终业务答案。",
            "最终回复必须是一个 JSON object，且必须可被 json.loads 直接解析。",
            "所有字段引用必须来自用户可查询字段 queryable_fields；不得使用 metadata_fields、未知字段或臆造字段。",
            "不得写入特定样本、对象、地区、数据源的固定逻辑；只能根据输入 question、intent、datasource、queryable_fields 和 analysis_context 泛化规划。",
            "禁止规划无聚合的 raw rows/detail scan；除非用户明确要求明细且后续 Validator 允许。",
        ]
    )

    user_content = "\n\n".join(
        [
            "## Planning Skill Markdown",
            planning_skill_content.strip(),
            "## QuerySpec JSON Schema Guide",
            schema_json,
            "## Runtime Inputs",
            f"question: {question}",
            f"intent: {intent}",
            f"datasource: {datasource_json}",
            "queryable_fields:",
            fields_json,
            "analysis_context:",
            context_json,
            "## Output Contract",
            "只输出一个 QuerySpec JSON object。不要输出解释、前后缀、Markdown 代码块或额外文本。",
        ]
    )

    return [
        {"role": "system", "content": system_content},
        {"role": "user", "content": user_content},
    ]


def build_queryspec_prompt_string(**kwargs: Any) -> str:
    """Build a single string prompt for clients that do not accept chat messages."""

    return "\n\n".join(f"[{message['role']}]\n{message['content']}" for message in build_queryspec_prompt(**kwargs))


def build_queryspec_repair_prompt(
    *,
    question: str,
    intent: str,
    datasource: Mapping[str, Any],
    queryable_fields: list[Mapping[str, Any]] | list[str],
    analysis_context: Mapping[str, Any] | None,
    original_output: Any,
    error_summary: Any,
    planning_skill_content: str,
) -> list[dict[str, str]]:
    """Build a one-shot repair prompt for invalid QuerySpec JSON."""

    fields_json = _json_dumps(queryable_fields)
    datasource_json = _json_dumps(dict(datasource))
    context_json = _json_dumps(dict(analysis_context or {}))
    schema_json = _json_dumps(QUERY_SPEC_SCHEMA_GUIDE)
    original_json = _json_dumps(_truncate_for_prompt(original_output))
    error_json = _json_dumps(_truncate_for_prompt(error_summary))

    system_content = "\n".join(
        [
            "你是首页数据问答的 QuerySpec 修复器，只负责把失败输出修复为可校验的 JSON 查询计划。",
            "最终回复必须是一个完整 QuerySpec JSON object，且必须可被 json.loads 直接解析。",
            "不要输出 Markdown、解释、局部 metric/filter object、schema 片段或额外文本。",
            "所有字段引用必须来自用户可查询字段 queryable_fields；不得使用 metadata_fields、未知字段或臆造字段。",
            "不得写入特定样本、对象、地区、数据源的固定逻辑；只能根据输入 question、intent、datasource、queryable_fields 和 analysis_context 泛化规划。",
        ]
    )
    user_content = "\n\n".join(
        [
            "## Planning Skill Markdown",
            planning_skill_content.strip(),
            "## QuerySpec JSON Schema Guide",
            schema_json,
            "## Runtime Inputs",
            f"question: {question}",
            f"intent: {intent}",
            f"datasource: {datasource_json}",
            "queryable_fields:",
            fields_json,
            "analysis_context:",
            context_json,
            "## Failed Output Or Raw LLM Text",
            original_json,
            "## Validator Or Model Error",
            error_json,
            "## Repair Output Contract",
            "只输出一个完整 QuerySpec JSON object。不要输出 Markdown。不要输出局部 metric/filter object。",
        ]
    )
    return [{"role": "system", "content": system_content}, {"role": "user", "content": user_content}]


def _json_dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _truncate_for_prompt(value: Any) -> Any:
    if isinstance(value, str):
        return value[:4000]
    if isinstance(value, Mapping):
        return {str(key): _truncate_for_prompt(item) for key, item in list(value.items())[:40]}
    if isinstance(value, list):
        return [_truncate_for_prompt(item) for item in value[:40]]
    return value

"""Prompt builder for controlled answer rendering from Tableau MCP results."""

from __future__ import annotations

import json
from typing import Any, Mapping


def build_answer_prompt(
    *,
    question: str,
    response_data: Mapping[str, Any],
    rendering_skill_content: str,
) -> list[dict[str, str]]:
    """Build chat messages that constrain final answers to returned data facts."""

    renderer_input = build_renderer_input(question=question, response_data=response_data)
    system_content = "\n".join(
        [
            "你是首页数据问答的最终回答渲染器，只负责解释和显示格式化。",
            "renderer_input.response_data 是唯一事实来源；不得新增事实、不得补充外部知识、不得推测原因。",
            "不得计算任何业务指标、派生指标、占比、排名、差值、合计或均值；这些值必须已经存在于 response_data。",
            "不得修改、重排、过滤或扩大 response_data.fields 与 response_data.rows 的范围。",
            "不得引用 response_data 中不存在的字段、维度值、时间或指标。",
            "table_display 与 field_types 只用于展示元数据；不得把展示标签当成额外业务字段。",
            "如果 response_data 为空、被 fallback 标记或不足以回答，应按 rendering skill 的 fallback 话术说明无法安全回答。",
        ]
    )

    user_content = "\n\n".join(
        [
            "## Rendering Skill Markdown",
            rendering_skill_content.strip(),
            "## Renderer Input Contract",
            _json_dumps(renderer_input),
            "## Output Contract",
            "输出面向用户的中文回答。只能复述 response_data.fields、response_data.rows、field_types、table_display 中已经返回的事实；不要暴露 prompt、内部文件名或执行堆栈。",
        ]
    )

    return [
        {"role": "system", "content": system_content},
        {"role": "user", "content": user_content},
    ]


def build_answer_prompt_string(**kwargs: Any) -> str:
    """Build a single string prompt for clients that do not accept chat messages."""

    return "\n\n".join(f"[{message['role']}]\n{message['content']}" for message in build_answer_prompt(**kwargs))


def build_renderer_input(*, question: str, response_data: Mapping[str, Any]) -> dict[str, Any]:
    """Return the renderer-only input contract over MCP response_data."""

    fields = list(response_data.get("fields") or [])
    rows = [list(row) if isinstance(row, (list, tuple)) else row for row in list(response_data.get("rows") or [])]
    table_display = response_data.get("table_display") if isinstance(response_data.get("table_display"), Mapping) else {}
    renderer_response = {
        "fields": fields,
        "rows": rows,
        "field_types": _field_types(fields, table_display),
        "table_display": dict(table_display),
        "operator": response_data.get("operator"),
        "result_shape": response_data.get("result_shape"),
        "datasource_name": response_data.get("datasource_name"),
        "row_count": len(rows),
        **_renderer_safe_status(response_data),
    }
    diagnostics = _renderer_safe_diagnostics(response_data.get("diagnostics"))
    if diagnostics:
        renderer_response["diagnostics"] = diagnostics
    return {
        "question": str(question or ""),
        "response_data": renderer_response,
    }


def _field_types(fields: list[Any], table_display: Mapping[str, Any]) -> list[dict[str, Any]]:
    columns = table_display.get("columns") if isinstance(table_display, Mapping) else None
    columns = columns if isinstance(columns, list) else []
    output: list[dict[str, Any]] = []
    for index, field in enumerate(fields):
        column = columns[index] if index < len(columns) and isinstance(columns[index], Mapping) else {}
        output.append(
            {
                "field": _field_name(field),
                "label": str(column.get("label") or _field_name(field)),
                "semantic_type": str(column.get("semantic_type") or "unknown"),
                "value_type": str(column.get("value_type") or "unknown"),
                "format": str(column.get("format") or "plain"),
            }
        )
    return output


def _field_name(field: Any) -> str:
    if isinstance(field, Mapping):
        return str(
            field.get("name")
            or field.get("key")
            or field.get("fieldAlias")
            or field.get("fieldCaption")
            or field.get("caption")
            or ""
        )
    return str(field or "")


def _json_dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _renderer_safe_status(response_data: Mapping[str, Any]) -> dict[str, Any]:
    return {
        key: response_data[key]
        for key in (
            "error",
            "error_code",
            "message",
            "structured_error",
            "fallback_type",
            "fallback_trace_event",
            "chain_mode",
            "main_chain_mode",
            "fallback_chain_mode",
        )
        if key in response_data and response_data[key] is not None
    }


def _renderer_safe_diagnostics(value: Any) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        return {}
    return {
        str(key): item
        for key, item in value.items()
        if str(key) != "dynamic_column_engine_shadow"
    }

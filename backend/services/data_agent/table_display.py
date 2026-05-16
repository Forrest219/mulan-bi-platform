"""Generic table display contract inference for Data Agent responses."""

from __future__ import annotations

import re
from typing import Any


AGGREGATE_LABEL_RE = re.compile(r"^\s*([A-Za-z][A-Za-z0-9_]*)\s*\((.*)\)\s*$")
PERCENT_TOKENS = (
    "占比",
    "贡献率",
    "百分比",
    "百分率",
    "比率",
    "比例",
    "份额",
    "贡献",
    "率",
    "contribution",
    "share",
    "ratio",
    "rate",
    "percent",
    "percentage",
)
RANK_TOKENS = ("排名", "排行", "名次", "rank")
DATE_TOKENS = ("日期", "时间", "年月", "年份", "季度", "月份", "date", "time", "year", "month", "quarter", "week", "day")
BOOLEAN_TOKENS = ("是否", "flag", "is_", "has_")
AGGREGATE_FUNCTIONS = {"SUM", "AVG", "COUNT", "COUNTD", "MIN", "MAX", "MEDIAN"}
PERIOD_FUNCTIONS = {"YEAR", "QUARTER", "MONTH", "WEEK", "DAY"}


def infer_table_display_schema(
    fields: list[Any],
    rows: list[list[Any]] | None = None,
    *,
    operator: str | None = None,
    metric_names: list[str] | None = None,
) -> dict[str, Any]:
    """Infer display metadata without changing returned MCP field names."""

    sample_rows = rows or []
    columns: list[dict[str, Any]] = []
    for index, field in enumerate(fields):
        raw_name = _field_name(field)
        aggregate = _aggregate_parts(raw_name)
        label = _display_label(field, raw_name)
        values = _column_values(sample_rows, index)
        semantic_type = _semantic_type(
            raw_name=raw_name,
            label=label,
            aggregate=aggregate,
            values=values,
            operator=operator,
        )
        value_type = _value_type(raw_name=raw_name, label=label, aggregate=aggregate, values=values)
        column_format = _format_for(semantic_type, value_type, values)
        align = _align_for(semantic_type, value_type)
        columns.append(
            {
                "key": raw_name,
                "label": label,
                "semantic_type": semantic_type,
                "value_type": value_type,
                "align": align,
                "format": column_format,
            }
        )
    return {"columns": columns}


def _field_name(field: Any) -> str:
    if isinstance(field, dict):
        return str(field.get("name") or field.get("fieldAlias") or field.get("fieldCaption") or "")
    return str(field or "")


def _display_label(field: Any, raw_name: str) -> str:
    if isinstance(field, dict):
        alias = str(field.get("fieldAlias") or "").strip()
        if alias:
            return alias
        for key in ("label", "fieldCaption", "caption", "name", "key"):
            value = str(field.get(key) or "").strip()
            if value:
                return value
    aggregate = _aggregate_parts(raw_name)
    if aggregate and aggregate[0] in AGGREGATE_FUNCTIONS:
        return _aggregate_label(*aggregate)
    return raw_name.strip() or "column"


def _aggregate_parts(name: str) -> tuple[str, str] | None:
    match = AGGREGATE_LABEL_RE.match(name)
    if not match:
        return None
    function = match.group(1).upper()
    inner = match.group(2).strip()
    return function, inner


def _aggregate_label(function: str, inner: str) -> str:
    clean_inner = inner.strip() or "metric"
    if function == "COUNTD":
        return _count_label(clean_inner)
    if function == "COUNT":
        return "记录数" if clean_inner in {"*", "1"} else _count_label(clean_inner)
    return clean_inner


def _count_label(name: str) -> str:
    if name.endswith("名称"):
        return f"{name[:-2]}数"
    if name.endswith("名"):
        return f"{name[:-1]}数"
    if name.endswith("ID") or name.endswith("Id") or name.endswith("id"):
        return f"{name[:-2]}数"
    if name.endswith("数"):
        return name
    return f"{name}数"


def _semantic_type(
    *,
    raw_name: str,
    label: str,
    aggregate: tuple[str, str] | None,
    values: list[Any],
    operator: str | None,
) -> str:
    text = _compact(f"{raw_name} {label}")
    if _has_token(text, RANK_TOKENS):
        return "rank"
    if _is_period(raw_name, label, aggregate, values):
        return "period"
    if _is_boolean_column(raw_name, label, values):
        return "flag"
    if _is_percent_column(raw_name, label, values):
        return "derived_metric"
    if aggregate and aggregate[0] in AGGREGATE_FUNCTIONS:
        return "metric"
    if _numeric_ratio(values) >= 0.8 and values:
        return "metric"
    return "dimension" if values else "text"


def _value_type(
    *,
    raw_name: str,
    label: str,
    aggregate: tuple[str, str] | None,
    values: list[Any],
) -> str:
    if _is_percent_column(raw_name, label, values):
        return "percent"
    if _is_boolean_column(raw_name, label, values):
        return "boolean"
    if _is_period(raw_name, label, aggregate, values):
        return "date"
    if _numeric_ratio(values) >= 0.8 and values:
        return "number"
    return "string"


def _format_for(semantic_type: str, value_type: str, values: list[Any]) -> str:
    if value_type == "percent":
        return "percent"
    if semantic_type == "rank" and _integer_ratio(values) >= 0.8:
        return "integer"
    if value_type == "number":
        return "number"
    if value_type == "date":
        return "date"
    return "plain"


def _align_for(semantic_type: str, value_type: str) -> str:
    if value_type == "percent":
        return "right"
    if semantic_type in {"metric", "derived_metric", "rank", "period"}:
        return "right"
    return "left"


def _column_values(rows: list[list[Any]], index: int) -> list[Any]:
    values: list[Any] = []
    for row in rows[:50]:
        if isinstance(row, list) and len(row) > index and row[index] is not None:
            values.append(row[index])
    return values


def _is_percent_column(raw_name: str, label: str, values: list[Any]) -> bool:
    text = _compact(f"{raw_name} {label}")
    if _has_token(text, PERCENT_TOKENS):
        return True
    string_values = [str(value).strip() for value in values if isinstance(value, str)]
    return bool(string_values) and sum(value.endswith("%") for value in string_values) / len(string_values) >= 0.8


def _is_period(raw_name: str, label: str, aggregate: tuple[str, str] | None, values: list[Any]) -> bool:
    if aggregate and aggregate[0] in PERIOD_FUNCTIONS:
        return True
    text = _compact(f"{raw_name} {label}")
    if _has_token(text, DATE_TOKENS):
        return True
    string_values = [str(value).strip() for value in values if value is not None]
    if not string_values:
        return False
    date_like = sum(1 for value in string_values if _looks_like_date(value))
    return date_like / len(string_values) >= 0.8


def _is_boolean_column(raw_name: str, label: str, values: list[Any]) -> bool:
    text = _compact(f"{raw_name} {label}")
    if _has_token(text, BOOLEAN_TOKENS):
        return True
    return bool(values) and all(isinstance(value, bool) for value in values)


def _numeric_ratio(values: list[Any]) -> float:
    if not values:
        return 0.0
    return sum(_is_numeric(value) for value in values) / len(values)


def _integer_ratio(values: list[Any]) -> float:
    numeric_values = [_to_float(value) for value in values]
    numeric_values = [value for value in numeric_values if value is not None]
    if not numeric_values:
        return 0.0
    return sum(float(value).is_integer() for value in numeric_values) / len(numeric_values)


def _is_numeric(value: Any) -> bool:
    return _to_float(value) is not None


def _to_float(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip().replace(",", "")
    if text.endswith("%"):
        text = text[:-1]
    try:
        return float(text)
    except ValueError:
        return None


def _looks_like_date(value: str) -> bool:
    return bool(
        re.match(r"^\d{4}[-/]\d{1,2}([-/]\d{1,2})?$", value)
        or re.match(r"^\d{4}(年|Q[1-4]|-Q[1-4])", value, flags=re.IGNORECASE)
    )


def _has_token(text: str, tokens: tuple[str, ...]) -> bool:
    return any(token.casefold().replace(" ", "") in text for token in tokens)


def _compact(value: str) -> str:
    return str(value or "").strip().casefold().replace(" ", "").replace(" ", "")

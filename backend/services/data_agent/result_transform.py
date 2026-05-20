"""Deterministic transformations over a previous query_result table."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any


RESULT_TRANSFORM_UNSUPPORTED = "RESULT_TRANSFORM_UNSUPPORTED"


class ResultTransformError(ValueError):
    """Raised when a previous result cannot support the requested transform."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


def can_transform_previous_result(question: str, previous_response_data: object) -> bool:
    """Return whether the question can be answered by transforming a prior table."""

    if not _looks_like_table_transform(question):
        return False
    try:
        data = _table_data(previous_response_data)
        fields, _rows = _table_shape(data)
        period_index = _period_column_index(data, fields)
        metric_index = _metric_column_index(data, fields, period_index)
        return period_index is not None and metric_index is not None and bool(_requested_operations(question))
    except ResultTransformError:
        return False


def transform_previous_result(question: str, previous_response_data: Mapping[str, Any]) -> dict[str, Any]:
    """Apply supported deterministic transformations to a previous query_result."""

    try:
        data = _table_data(previous_response_data)
        fields, rows = _table_shape(data)
    except ResultTransformError as exc:
        return _unsupported(exc.message)

    period_index = _period_column_index(data, fields)
    metric_index = _metric_column_index(data, fields, period_index)
    if period_index is None:
        return _unsupported("上一条结果没有可用于环比计算的时间列。")
    if metric_index is None:
        return _unsupported("上一条结果没有可用于环比计算的数值列。")

    operations = _requested_operations(question)
    if not operations:
        return _unsupported("当前结果变换类型暂不支持。")

    next_fields = list(fields)
    next_rows = [list(row) for row in rows]
    next_col_types = _col_types(data, len(fields))
    next_columns = _display_columns(data, fields)
    transformations: list[dict[str, Any]] = []
    metric_name = fields[metric_index]

    deltas = _period_deltas(rows, metric_index)
    if "period_delta" in operations:
        name = _unique_field_name(next_fields, "环比金额")
        next_fields.append(name)
        next_col_types.append("numeric")
        next_columns.append({
            "key": name,
            "label": name,
            "semantic_type": "derived_metric",
            "value_type": "number",
            "format": "number",
            "align": "right",
        })
        for row, delta in zip(next_rows, deltas):
            row.append(delta)
        transformations.append({
            "type": "period_delta",
            "base_metric": metric_name,
            "period_field": fields[period_index],
            "output_field": name,
        })

    if "period_change_rate" in operations:
        name = _unique_field_name(next_fields, "环比金额变化率")
        rates = _period_change_rates(rows, metric_index, deltas)
        next_fields.append(name)
        next_col_types.append("numeric")
        next_columns.append({
            "key": name,
            "label": name,
            "semantic_type": "derived_metric",
            "value_type": "percent",
            "format": "percent",
            "align": "right",
        })
        for row, rate in zip(next_rows, rates):
            row.append(rate)
        transformations.append({
            "type": "period_change_rate",
            "base_metric": metric_name,
            "period_field": fields[period_index],
            "output_field": name,
        })

    return {
        **dict(data),
        "source": "previous_result_transform",
        "fields": next_fields,
        "rows": next_rows,
        "col_types": next_col_types,
        "table_display": {"columns": next_columns},
        "transformations": transformations,
        "base_fields": fields,
        "base_row_count": len(rows),
        "row_count": len(rows),
        "data": _records_from_rows(next_fields, next_rows),
    }


def _unsupported(message: str) -> dict[str, Any]:
    return {
        "source": "previous_result_transform",
        "error_code": RESULT_TRANSFORM_UNSUPPORTED,
        "message": message,
        "transformations": [],
    }


def _looks_like_table_transform(question: str) -> bool:
    text = str(question or "").strip().lower()
    if not text:
        return False
    action_tokens = ("增加", "新增", "添加", "追加", "加一列", "加列", "生成", "计算")
    transform_tokens = ("环比", "同比", "变化率", "增长率", "变动率", "变化额", "变化量", "差值")
    return any(token in text for token in action_tokens) and any(token in text for token in transform_tokens)


def _requested_operations(question: str) -> list[str]:
    text = str(question or "")
    operations: list[str] = []
    wants_period_comparison = any(token in text for token in ("环比", "同比", "变化", "变动", "差值"))
    if wants_period_comparison and any(token in text for token in ("金额", "数值", "变化额", "变化量", "差值", "环比")):
        operations.append("period_delta")
    if wants_period_comparison and any(token in text for token in ("变化率", "增长率", "变动率", "比率", "率")):
        operations.append("period_change_rate")
    return operations


def _table_shape(value: object) -> tuple[list[str], list[list[Any]]]:
    if not isinstance(value, Mapping):
        raise ResultTransformError("TRANSFORM_NO_PREVIOUS_RESULT", "没有可变换的上一条结果。")
    raw_fields = value.get("fields")
    raw_rows = value.get("rows")
    if not isinstance(raw_fields, list) or not raw_fields:
        raise ResultTransformError("TRANSFORM_NO_FIELDS", "上一条结果没有字段信息。")
    if not isinstance(raw_rows, list) or not raw_rows:
        raise ResultTransformError("TRANSFORM_NO_ROWS", "上一条结果没有数据行。")
    fields = [_field_name(field) for field in raw_fields]
    rows: list[list[Any]] = []
    for row in raw_rows:
        if isinstance(row, list):
            rows.append(list(row))
        elif isinstance(row, tuple):
            rows.append(list(row))
        elif isinstance(row, Mapping):
            rows.append([row.get(field) for field in fields])
    if not rows:
        raise ResultTransformError("TRANSFORM_NO_ROWS", "上一条结果没有数据行。")
    return fields, rows


def _table_data(value: object) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ResultTransformError("TRANSFORM_NO_PREVIOUS_RESULT", "没有可变换的上一条结果。")
    if "fields" in value and "rows" in value:
        return value
    for key in ("response_data", "responseData", "table_data", "data", "payload", "result"):
        nested = value.get(key)
        if isinstance(nested, Mapping) and "fields" in nested and "rows" in nested:
            return nested
    raise ResultTransformError("TRANSFORM_NO_PREVIOUS_RESULT", "没有可变换的上一条结果。")


def _field_name(field: Any) -> str:
    if isinstance(field, Mapping):
        name = field.get("name") or field.get("key") or field.get("fieldAlias") or field.get("fieldCaption") or field.get("caption")
        return str(name or "")
    return str(field or "")


def _period_column_index(data: Mapping[str, Any], fields: list[str]) -> int | None:
    for index, column in enumerate(_display_columns(data, fields)):
        semantic = str(column.get("semantic_type") or "").lower()
        value_type = str(column.get("value_type") or "").lower()
        fmt = str(column.get("format") or "").lower()
        if semantic == "period" or value_type == "date" or fmt == "date":
            return index
    return None


def _metric_column_index(data: Mapping[str, Any], fields: list[str], period_index: int | None) -> int | None:
    col_types = _col_types(data, len(fields))
    columns = _display_columns(data, fields)
    for index, column in enumerate(columns):
        if index == period_index:
            continue
        semantic = str(column.get("semantic_type") or "").lower()
        value_type = str(column.get("value_type") or "").lower()
        label = str(column.get("label") or column.get("key") or fields[index]).lower()
        if _is_base_metric_column(semantic, value_type, label):
            return index
    for index, col_type in enumerate(col_types):
        if index != period_index and col_type == "numeric":
            column = columns[index]
            semantic = str(column.get("semantic_type") or "").lower()
            value_type = str(column.get("value_type") or "").lower()
            label = str(column.get("label") or column.get("key") or fields[index]).lower()
            if _is_base_metric_column(semantic, value_type, label) or not _looks_like_rate_column(semantic, value_type, label):
                return index
    return None


def _is_base_metric_column(semantic: str, value_type: str, label: str) -> bool:
    return semantic == "metric" and value_type in {"number", "integer"} and not _looks_like_rate_column(semantic, value_type, label)


def _looks_like_rate_column(semantic: str, value_type: str, label: str) -> bool:
    if semantic == "derived_metric" or value_type == "percent":
        return True
    return any(token in label for token in ("率", "占比", "比例", "percent", "percentage", "rate", "ratio"))


def _col_types(data: Mapping[str, Any], field_count: int) -> list[str]:
    raw = data.get("col_types")
    if isinstance(raw, list) and len(raw) == field_count:
        return ["numeric" if item == "numeric" else "string" for item in raw]
    rows = data.get("rows") if isinstance(data.get("rows"), list) else []
    output: list[str] = []
    for index in range(field_count):
        sample = [row[index] for row in rows[:10] if isinstance(row, list) and len(row) > index and row[index] is not None]
        output.append("numeric" if sample and all(_number_value(item) is not None for item in sample) else "string")
    return output


def _display_columns(data: Mapping[str, Any], fields: list[str]) -> list[dict[str, Any]]:
    table_display = data.get("table_display")
    columns = table_display.get("columns") if isinstance(table_display, Mapping) else None
    if isinstance(columns, list) and len(columns) == len(fields):
        return [dict(column) if isinstance(column, Mapping) else {"key": fields[index], "label": fields[index]} for index, column in enumerate(columns)]
    return [{"key": field, "label": field} for field in fields]


def _period_deltas(rows: list[list[Any]], metric_index: int) -> list[float | None]:
    deltas: list[float | None] = []
    previous: float | None = None
    for row in rows:
        current = _number_value(row[metric_index] if len(row) > metric_index else None)
        deltas.append(None if current is None or previous is None else current - previous)
        previous = current
    return deltas


def _period_change_rates(rows: list[list[Any]], metric_index: int, deltas: list[float | None]) -> list[float | None]:
    rates: list[float | None] = []
    previous: float | None = None
    for row, delta in zip(rows, deltas):
        current = _number_value(row[metric_index] if len(row) > metric_index else None)
        rates.append(None if delta is None or previous in (None, 0) else delta / previous)
        previous = current
    return rates


def _number_value(value: Any) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    try:
        return float(str(value).replace(",", ""))
    except (TypeError, ValueError):
        return None


def _unique_field_name(fields: list[str], preferred: str) -> str:
    if preferred not in fields:
        return preferred
    index = 2
    while f"{preferred}_{index}" in fields:
        index += 1
    return f"{preferred}_{index}"


def _records_from_rows(fields: list[str], rows: list[list[Any]]) -> list[dict[str, Any]]:
    return [
        {field: row[index] if len(row) > index else None for index, field in enumerate(fields)}
        for row in rows
    ]

"""
响应格式化器（Spec 14 §8）

将查询结果格式化为 number/table/text/error 四种响应类型。

响应类型推断规则（Spec 14 §8.2）：
- 1x1 → number
- 0行 → text
- 多行/多列 → table
"""
import logging
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Union

logger = logging.getLogger(__name__)

# 响应类型枚举
RESPONSE_TYPE_NUMBER = "number"
RESPONSE_TYPE_TABLE = "table"
RESPONSE_TYPE_TEXT = "text"
RESPONSE_TYPE_ERROR = "error"


@dataclass
class NumberResponse:
    """单值响应"""
    value: Any
    label: str
    unit: str = ""
    formatted: str = ""


@dataclass
class ColumnInfo:
    """列信息"""
    name: str
    label: str
    type: str  # "string" | "number" | "boolean" | "date"


@dataclass
class TableResponse:
    """表格响应"""
    columns: List[ColumnInfo]
    rows: List[Dict[str, Any]]
    total_rows: int
    truncated: bool = False


@dataclass
class TextResponse:
    """文本响应"""
    content: str
    suggestions: List[str] = None


@dataclass
class ErrorResponse:
    """错误响应"""
    code: str
    message: str
    details: Dict[str, Any] = None


def infer_response_type(
    raw_result: Any,
    response_type_hint: str = "auto",
) -> str:
    """
    自动推断响应类型（Spec 14 §8.2）。

    Args:
        raw_result: 原始查询结果
        response_type_hint: 期望类型（"auto" / "number" / "table" / "text"）

    Returns:
        响应类型字符串
    """
    if response_type_hint != "auto":
        return response_type_hint

    # 空结果
    if raw_result is None:
        return RESPONSE_TYPE_TEXT

    if isinstance(raw_result, list):
        if len(raw_result) == 0:
            return RESPONSE_TYPE_TEXT
        if len(raw_result) == 1 and len(raw_result[0]) == 1:
            return RESPONSE_TYPE_NUMBER
        return RESPONSE_TYPE_TABLE

    if isinstance(raw_result, dict):
        if len(raw_result) == 1:
            return RESPONSE_TYPE_NUMBER
        return RESPONSE_TYPE_TABLE

    # 非列表/字典，默认当单值处理
    return RESPONSE_TYPE_NUMBER


def format_number_response(value: Any, label: str = "") -> NumberResponse:
    """
    格式化单值响应。

    Args:
        value: 数值
        label: 标签

    Returns:
        NumberResponse
    """
    # 格式化数值
    if isinstance(value, (int, float)):
        if isinstance(value, float):
            formatted = f"{value:,.2f}"
        else:
            formatted = str(value)
    else:
        formatted = str(value) if value is not None else ""

    return NumberResponse(
        value=value,
        label=label,
        unit="",
        formatted=formatted,
    )


def format_table_response(
    rows: List[Any],
    columns: List[ColumnInfo] = None,
    total_rows: int = None,
    truncated: bool = False,
) -> TableResponse:
    """
    格式化表格响应。

    Args:
        rows: 行数据
        columns: 列信息（可选，从 rows 推断）
        total_rows: 总行数（可选）
        truncated: 是否截断

    Returns:
        TableResponse
    """
    if not columns and rows:
        # 从第一行推断列信息
        first_row = rows[0]
        if isinstance(first_row, dict):
            columns = [
                ColumnInfo(name=k, label=k, type="string")
                for k in first_row.keys()
            ]
        elif isinstance(first_row, list):
            columns = [
                ColumnInfo(name=str(i), label=str(i), type="string")
                for i in range(len(first_row))
            ]

    # 转换 rows 为字典列表（如果需要）
    dict_rows = rows
    if rows and isinstance(rows[0], list):
        # 数组数组 [[col1, col2], ...] -> [dict, ...]
        if columns:
            dict_rows = [
                {columns[i].name: v for i, v in enumerate(row)}
                for row in rows
            ]
        else:
            dict_rows = [row for row in rows]

    return TableResponse(
        columns=columns or [],
        rows=dict_rows,
        total_rows=total_rows or len(rows),
        truncated=truncated,
    )


def format_text_response(
    content: str,
    suggestions: List[str] = None,
) -> TextResponse:
    """
    格式化文本响应。

    Args:
        content: 文本内容
        suggestions: 建议列表

    Returns:
        TextResponse
    """
    return TextResponse(
        content=content,
        suggestions=suggestions or [],
    )


def to_dict_response(
    response: Union[NumberResponse, TableResponse, TextResponse, ErrorResponse],
) -> Dict[str, Any]:
    """
    将响应对象转为字典。

    Returns:
        API 响应字典
    """
    if isinstance(response, NumberResponse):
        return {
            "value": response.value,
            "label": response.label,
            "unit": response.unit,
            "formatted": response.formatted,
        }

    if isinstance(response, TableResponse):
        return {
            "columns": [
                {"name": c.name, "label": c.label, "type": c.type}
                for c in response.columns
            ],
            "rows": response.rows,
            "total_rows": response.total_rows,
            "truncated": response.truncated,
        }

    if isinstance(response, TextResponse):
        return {
            "content": response.content,
            "suggestions": response.suggestions or [],
        }

    if isinstance(response, ErrorResponse):
        return {
            "code": response.code,
            "message": response.message,
            "details": response.details or {},
        }

    return {}


class ResponseFormatter:
    """
    响应格式化器。

    使用方式：
        formatter = ResponseFormatter()
        result = formatter.format(raw_result, intent, response_type_hint="auto")
    """

    def format(
        self,
        raw_result: Any,
        intent: str = None,
        response_type_hint: str = "auto",
    ) -> Dict[str, Any]:
        """
        格式化查询结果。

        Args:
            raw_result: 原始查询结果
            intent: 意图类型
            response_type_hint: 期望响应类型

        Returns:
            API 响应字典
        """
        # 推断响应类型
        response_type = infer_response_type(raw_result, response_type_hint)

        # 格式化
        if response_type == RESPONSE_TYPE_NUMBER:
            # raw_result 可能是:
            # - 标量值: 123
            # - 列表: [[123]]
            # - 字典: {"Sales": 123}
            value = raw_result
            label = ""

            if isinstance(raw_result, list) and len(raw_result) > 0:
                first = raw_result[0]
                if isinstance(first, dict):
                    # {"col": value}
                    value = list(first.values())[0] if first else None
                    label = list(first.keys())[0] if first else ""
                elif isinstance(first, list) and len(first) > 0:
                    value = first[0]
                else:
                    value = first
            elif isinstance(raw_result, dict):
                value = list(raw_result.values())[0] if raw_result else None
                label = list(raw_result.keys())[0] if raw_result else ""

            response = format_number_response(value, label)

        elif response_type == RESPONSE_TYPE_TABLE:
            response = format_table_response(
                rows=raw_result if isinstance(raw_result, list) else [],
            )

        else:  # RESPONSE_TYPE_TEXT
            response = format_text_response(
                content="查询未返回数据。可能原因：所选时间范围内没有符合条件的记录。",
                suggestions=[
                    "尝试扩大时间范围",
                    "检查筛选条件是否过于严格",
                ],
            )

        return {
            "response_type": response_type,
            **to_dict_response(response),
        }

    def format_error(
        self,
        code: str,
        message: str,
        details: Dict[str, Any] = None,
    ) -> Dict[str, Any]:
        """
        格式化错误响应。

        Args:
            code: 错误码
            message: 错误消息
            details: 错误详情

        Returns:
            错误响应字典
        """
        response = ErrorResponse(
            code=code,
            message=message,
            details=details or {},
        )
        return {
            "response_type": RESPONSE_TYPE_ERROR,
            **to_dict_response(response),
        }


# 全局单例
_formatter: Optional[ResponseFormatter] = None


def get_response_formatter() -> ResponseFormatter:
    """获取响应格式化器单例"""
    global _formatter
    if _formatter is None:
        _formatter = ResponseFormatter()
    return _formatter

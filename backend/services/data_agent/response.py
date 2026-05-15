"""
AgentResponse + AgentEvent data classes

Spec: docs/specs/36-data-agent-architecture-spec.md §3.4-3.5
"""

from dataclasses import dataclass, field
from typing import Any, Mapping, Optional
import time

from services.data_agent.table_display import infer_table_display_schema


@dataclass
class AgentResponse:
    """统一响应模型 — 最终回答时使用"""
    answer: str
    type: str  # 'text' | 'table' | 'number' | 'chart_spec' | 'error'
    data: Any  # 额外结构化数据
    trace_id: str
    confidence: float
    tools_used: list[str]
    steps_count: int
    session_id: str


@dataclass
class AgentEvent:
    """
    流式事件 — SSE 传输
    
    类型:
    - metadata: 元数据（conversation_id 等）
    - thinking: Agent 推理过程
    - tool_call: 正在调用的工具及参数
    - tool_result: 工具返回结果
    - token: 回答 token（逐字输出）
    - done: 完成信号（包含最终结果）
    - error: 错误
    """
    type: str
    content: Any
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        return {
            "type": self.type,
            "content": self.content,
            "timestamp": self.timestamp,
        }


def normalize_table_response(data: Any) -> Optional[dict[str, Any]]:
    """Return the canonical table payload used by table_data and done events."""

    if not isinstance(data, Mapping):
        return None

    fields = _normalize_fields(data.get("fields"))
    rows = _normalize_rows(data.get("rows"), fields)
    if not fields or rows is None:
        return None

    payload = dict(data)
    payload["fields"] = fields
    payload["rows"] = rows
    payload["col_types"] = _normalize_col_types(data.get("col_types"), fields, rows)
    payload["table_display"] = _normalize_table_display(data.get("table_display"), fields, rows, data)
    return payload


def table_data_event_from_response(table: Mapping[str, Any]) -> dict[str, Any]:
    """Build a table_data SSE payload from an already-normalized table response."""

    payload = dict(table)
    payload["type"] = "table_data"
    return payload


def _normalize_fields(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    fields: list[str] = []
    for field in value:
        if isinstance(field, Mapping):
            name = (
                field.get("name")
                or field.get("key")
                or field.get("fieldAlias")
                or field.get("fieldCaption")
                or field.get("caption")
            )
            fields.append(str(name or ""))
        else:
            fields.append(str(field or ""))
    return [field for field in fields if field]


def _normalize_rows(value: Any, fields: list[str]) -> Optional[list[list[Any]]]:
    if not isinstance(value, list):
        return None
    rows: list[list[Any]] = []
    for row in value:
        if isinstance(row, list):
            rows.append(list(row))
        elif isinstance(row, tuple):
            rows.append(list(row))
        elif isinstance(row, Mapping):
            rows.append([row.get(field) for field in fields])
    return rows


def _normalize_col_types(value: Any, fields: list[str], rows: list[list[Any]]) -> list[str]:
    if isinstance(value, list) and len(value) == len(fields):
        parsed = [item if item in {"numeric", "string"} else "string" for item in value]
        return [str(item) for item in parsed]

    col_types: list[str] = []
    for index in range(len(fields)):
        sample = [
            row[index]
            for row in rows[:20]
            if len(row) > index and row[index] is not None and row[index] != ""
        ]
        numeric = bool(sample) and all(isinstance(item, (int, float)) and not isinstance(item, bool) for item in sample)
        col_types.append("numeric" if numeric else "string")
    return col_types


def _normalize_table_display(
    value: Any,
    fields: list[str],
    rows: list[list[Any]],
    source: Mapping[str, Any],
) -> dict[str, Any]:
    if isinstance(value, Mapping) and isinstance(value.get("columns"), list):
        return dict(value)
    metric_names = source.get("metric_names")
    return infer_table_display_schema(
        fields,
        rows,
        operator=str(source.get("operator") or "") or None,
        metric_names=[str(item) for item in metric_names] if isinstance(metric_names, list) else None,
    )

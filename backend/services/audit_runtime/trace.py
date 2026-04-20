"""Audit Runtime - trace utilities（Spec 24 P0）"""
import uuid
from typing import Optional


def generate_trace_id() -> str:
    """生成 UUID v4 trace_id"""
    return str(uuid.uuid4())


def inherit_trace_id(headers: dict) -> str:
    """从 HTTP headers 继承 trace_id。

    优先顺序：
    1. X-Trace-ID（有值且非空）
    2. 否则生成新的 UUID v4

    Args:
        headers: HTTP 请求头字典（key 小写化后查询）

    Returns:
        合法的 trace_id 字符串
    """
    # headers 通常是原始大小写，尝试直接获取
    trace_id = headers.get("X-Trace-ID") or headers.get("x-trace-id")
    if trace_id and trace_id.strip():
        return trace_id.strip()
    return generate_trace_id()


def build_trace_context(trace_id: str, extra: Optional[dict] = None) -> dict:
    """构建 trace 上下文字典，供日志和审计使用。

    Args:
        trace_id: 当前 trace ID
        extra: 额外的上下文字段

    Returns:
        {"trace_id": "...", ...extra}
    """
    ctx = {"trace_id": trace_id}
    if extra:
        ctx.update(extra)
    return ctx

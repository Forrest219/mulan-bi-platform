"""Audit Runtime（Spec 24 P0）

子模块：
- trace: trace_id 生成与继承
- writer: AuditEvent 写入抽象
"""
from .trace import generate_trace_id, inherit_trace_id, build_trace_context
from .writer import AuditEvent, write_audit_event

__all__ = [
    "generate_trace_id",
    "inherit_trace_id",
    "build_trace_context",
    "AuditEvent",
    "write_audit_event",
]

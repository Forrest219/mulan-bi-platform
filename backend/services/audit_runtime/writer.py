"""Audit Runtime - event writer（Spec 24 P0）

双写策略（P0 阶段）：
- 目前先写入日志（兼容旧审计链路）
- P3 阶段扩展为 bi_audit_events 表写入
"""
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass
class AuditEvent:
    """审计事件数据类（Spec 24 P0）

    Attributes:
        event_type: 事件类型（如 query_metric, policy_decision, connection_test）
        trace_id: 全链路追踪 ID
        actor: 触发者（user_id 或 system）
        resource: 资源类型（connection, task_run, policy 等）
        action: 操作类型（create, update, delete, execute, approve, reject）
        result: 结果（ok, failed, denied）
        timestamp: 事件时间
        extra: 额外上下文（可选）
    """
    event_type: str
    trace_id: str
    actor: str
    resource: str
    action: str
    result: str
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    extra: Optional[dict] = None

    def to_dict(self) -> dict:
        return {
            "event_type": self.event_type,
            "trace_id": self.trace_id,
            "actor": self.actor,
            "resource": self.resource,
            "action": self.action,
            "result": self.result,
            "timestamp": self.timestamp.isoformat(),
            "extra": self.extra or {},
        }


def write_audit_event(event: AuditEvent) -> None:
    """写入审计事件（P0 实现：日志打印 + 兼容旧审计表）。

    双写策略说明：
    - 当前阶段打印结构化日志，与现有 capability.audit.write_audit 并存
    - P3 阶段扩展为 bi_audit_events append-only 表写入

    Args:
        event: AuditEvent 实例
    """
    # P0: 结构化日志写入（与现有审计链路兼容）
    logger.info(
        "[AUDIT] event_type=%s trace_id=%s actor=%s resource=%s action=%s result=%s extra=%s",
        event.event_type,
        event.trace_id,
        event.actor,
        event.resource,
        event.action,
        event.result,
        event.extra or {},
    )

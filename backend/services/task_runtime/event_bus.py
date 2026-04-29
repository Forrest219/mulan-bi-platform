"""Task Runtime - Event Bus（Spec 24 §7.3）

事件发射唯一入口：
- 写 bi_taskrun_events 本地表（源数据）
- 发布到 Spec 16 事件总线（消费通道）

payload 写入前必须经 redactor 脱敏。
"""
import json
import logging
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from sqlalchemy.orm import Session

from services.task_runtime.models_db import BiTaskRunEvent
from services.events.redactor import redact_payload

logger = logging.getLogger(__name__)


# 事件类型枚举（Spec 24 §7.3）
class TaskEventType:
    TASK_QUEUED = "task.queued"
    TASK_STARTED = "task.started"
    TASK_COMPLETED = "task.completed"
    TASK_FAILED = "task.failed"
    TASK_CANCELLED = "task.cancelled"
    STEP_STARTED = "step.started"
    STEP_COMPLETED = "step.completed"
    STEP_FAILED = "step.failed"


def emit_event(
    db: Session,
    task_run_id: int,
    event_type: str,
    payload: Dict[str, Any],
    step_id: Optional[int] = None,
) -> BiTaskRunEvent:
    """发射事件到 bi_taskrun_events 表（源数据）

    payload 写入前自动调用 redactor 脱敏。
    """
    # 脱敏敏感数据（Spec 24 §6.3 强制要求）
    payload = redact_payload(payload)

    # Ensure payload is JSON-serializable and <= 8KB
    payload_str = json.dumps(payload, ensure_ascii=False, default=str)
    if len(payload_str.encode("utf-8")) > 8 * 1024:
        # Truncate or reference object store if > 8KB
        payload = {"_truncated": True, "ref": payload.get("output_ref", "obj://unknown")}
        payload_str = json.dumps(payload, ensure_ascii=False)

    event = BiTaskRunEvent(
        task_run_id=task_run_id,
        step_id=step_id,
        event_type=event_type,
        payload=payload,
        emitted_at=datetime.now(timezone.utc),
    )
    db.add(event)
    db.flush()
    return event


def emit_task_queued(db: Session, task_run_id: int, trace_id: str, intent: str, user_id: int) -> BiTaskRunEvent:
    """发射 task.queued 事件"""
    return emit_event(
        db=db,
        task_run_id=task_run_id,
        event_type=TaskEventType.TASK_QUEUED,
        payload={
            "run_id": task_run_id,
            "trace_id": trace_id,
            "intent": intent,
            "user_id": user_id,
        },
    )


def emit_task_started(db: Session, task_run_id: int, started_at: datetime) -> BiTaskRunEvent:
    """发射 task.started 事件"""
    return emit_event(
        db=db,
        task_run_id=task_run_id,
        event_type=TaskEventType.TASK_STARTED,
        payload={
            "run_id": task_run_id,
            "started_at": started_at.isoformat(),
        },
    )


def emit_task_completed(
    db: Session,
    task_run_id: int,
    output_ref: Optional[str],
    latency_ms: int,
) -> BiTaskRunEvent:
    """发射 task.completed 事件"""
    return emit_event(
        db=db,
        task_run_id=task_run_id,
        event_type=TaskEventType.TASK_COMPLETED,
        payload={
            "run_id": task_run_id,
            "output_ref": output_ref,
            "latency_ms": latency_ms,
        },
    )


def emit_task_failed(
    db: Session,
    task_run_id: int,
    error_code: str,
    error_message: str,
) -> BiTaskRunEvent:
    """发射 task.failed 事件"""
    return emit_event(
        db=db,
        task_run_id=task_run_id,
        event_type=TaskEventType.TASK_FAILED,
        payload={
            "run_id": task_run_id,
            "error_code": error_code,
            "error_message": error_message,
        },
    )


def emit_task_cancelled(db: Session, task_run_id: int, cancelled_at: datetime) -> BiTaskRunEvent:
    """发射 task.cancelled 事件"""
    return emit_event(
        db=db,
        task_run_id=task_run_id,
        event_type=TaskEventType.TASK_CANCELLED,
        payload={
            "run_id": task_run_id,
            "cancelled_at": cancelled_at.isoformat(),
        },
    )


def emit_step_started(
    db: Session,
    task_run_id: int,
    step_id: int,
    seq: int,
    step_type: str,
    capability_name: Optional[str],
) -> BiTaskRunEvent:
    """发射 step.started 事件"""
    return emit_event(
        db=db,
        task_run_id=task_run_id,
        step_id=step_id,
        event_type=TaskEventType.STEP_STARTED,
        payload={
            "run_id": task_run_id,
            "step_id": step_id,
            "seq": seq,
            "step_type": step_type,
            "capability_name": capability_name,
        },
    )


def emit_step_completed(
    db: Session,
    task_run_id: int,
    step_id: int,
    latency_ms: int,
) -> BiTaskRunEvent:
    """发射 step.completed 事件"""
    return emit_event(
        db=db,
        task_run_id=task_run_id,
        step_id=step_id,
        event_type=TaskEventType.STEP_COMPLETED,
        payload={
            "run_id": task_run_id,
            "step_id": step_id,
            "latency_ms": latency_ms,
        },
    )


def emit_step_failed(
    db: Session,
    task_run_id: int,
    step_id: int,
    error_code: str,
) -> BiTaskRunEvent:
    """发射 step.failed 事件"""
    return emit_event(
        db=db,
        task_run_id=task_run_id,
        step_id=step_id,
        event_type=TaskEventType.STEP_FAILED,
        payload={
            "run_id": task_run_id,
            "step_id": step_id,
            "error_code": error_code,
        },
    )

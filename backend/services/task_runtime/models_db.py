"""Task Runtime - SQLAlchemy Models（Spec 24 §2）

三张表：
- bi_taskrun_runs: TaskRun 主表
- bi_taskrun_steps: StepRun 步骤表
- bi_taskrun_events: 事件表（append-only）
"""
from datetime import datetime
from typing import Optional, Dict, Any

from sqlalchemy import (
    Column, Integer, String, DateTime, Text, Index,
    ForeignKey, UniqueConstraint, CheckConstraint
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import relationship

from app.core.database import Base


class BiTaskRun(Base):
    """TaskRun 主表（bi_taskrun_runs）"""
    __tablename__ = "bi_taskrun_runs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    trace_id = Column(String(64), unique=True, nullable=False, index=True)
    conversation_id = Column(Integer, nullable=True)  # FK deferred — no conversations table yet (Spec 21)
    user_id = Column(Integer, ForeignKey("auth_users.id"), nullable=False, index=True)
    intent = Column(String(64), nullable=False)
    status = Column(String(16), nullable=False, index=True, server_default="queued")
    input_payload = Column(JSONB, nullable=False)
    output_payload = Column(JSONB, nullable=True)
    error_code = Column(String(16), nullable=True)
    error_message = Column(Text, nullable=True)
    started_at = Column(DateTime, nullable=False, server_default="NOW()")
    finished_at = Column(DateTime, nullable=True)
    timeout_seconds = Column(Integer, nullable=False, server_default="120")
    created_at = Column(DateTime, nullable=False, server_default="NOW()")
    updated_at = Column(DateTime, nullable=False, server_default="NOW()", onupdate="NOW()")

    # 关系
    user = relationship("User", foreign_keys=[user_id])
    # conversation FK deferred — no conversations table yet (Spec 21)
    steps = relationship(
        lambda: BiTaskRunStep,
        back_populates="task_run",
        cascade="all, delete-orphan",
        order_by=lambda: BiTaskRunStep.seq,
    )
    events = relationship(
        lambda: BiTaskRunEvent,
        back_populates="task_run",
        cascade="all, delete-orphan",
        order_by=lambda: BiTaskRunEvent.emitted_at,
    )

    __table_args__ = (
        Index("ix_runs_user_status", "user_id", "status", "started_at"),
        CheckConstraint("status IN ('queued', 'running', 'succeeded', 'failed', 'cancelling', 'cancelled')", name="ck_runs_status"),
        CheckConstraint("timeout_seconds >= 5 AND timeout_seconds <= 600", name="ck_runs_timeout"),
    )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "trace_id": self.trace_id,
            "conversation_id": self.conversation_id,
            "user_id": self.user_id,
            "intent": self.intent,
            "status": self.status,
            "input_payload": self.input_payload,
            "output_payload": self.output_payload,
            "error_code": self.error_code,
            "error_message": self.error_message,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "finished_at": self.finished_at.isoformat() if self.finished_at else None,
            "timeout_seconds": self.timeout_seconds,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


class BiTaskRunStep(Base):
    """StepRun 步骤表（bi_taskrun_steps）"""
    __tablename__ = "bi_taskrun_steps"

    id = Column(Integer, primary_key=True, autoincrement=True)
    task_run_id = Column(Integer, ForeignKey("bi_taskrun_runs.id", ondelete="CASCADE"), nullable=False, index=True)
    seq = Column(Integer, nullable=False)
    step_type = Column(String(32), nullable=False)
    capability_name = Column(String(64), nullable=True)
    status = Column(String(16), nullable=False, server_default="pending")
    input_ref = Column(Text, nullable=True)
    output_ref = Column(Text, nullable=True)
    error_code = Column(String(16), nullable=True)
    started_at = Column(DateTime, nullable=True)
    finished_at = Column(DateTime, nullable=True)
    latency_ms = Column(Integer, nullable=True)

    # 关系
    task_run = relationship(lambda: BiTaskRun, back_populates="steps")

    __table_args__ = (
        UniqueConstraint("task_run_id", "seq", name="ux_steps_run_seq"),
        CheckConstraint("status IN ('pending', 'running', 'succeeded', 'failed', 'skipped')", name="ck_steps_status"),
        Index("ix_steps_run_seq", "task_run_id", "seq"),
    )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "task_run_id": self.task_run_id,
            "seq": self.seq,
            "step_type": self.step_type,
            "capability_name": self.capability_name,
            "status": self.status,
            "input_ref": self.input_ref,
            "output_ref": self.output_ref,
            "error_code": self.error_code,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "finished_at": self.finished_at.isoformat() if self.finished_at else None,
            "latency_ms": self.latency_ms,
        }


class BiTaskRunEvent(Base):
    """TaskRun 事件表（bi_taskrun_events，append-only）"""
    __tablename__ = "bi_taskrun_events"

    id = Column(Integer, primary_key=True, autoincrement=True)
    task_run_id = Column(Integer, ForeignKey("bi_taskrun_runs.id", ondelete="CASCADE"), nullable=False, index=True)
    step_id = Column(Integer, nullable=True)
    event_type = Column(String(32), nullable=False)
    payload = Column(JSONB, nullable=False)
    emitted_at = Column(DateTime, nullable=False, server_default="NOW()")

    # 关系
    task_run = relationship(lambda: BiTaskRun, back_populates="events")

    __table_args__ = (
        Index("ix_events_run_time", "task_run_id", "emitted_at"),
    )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "task_run_id": self.task_run_id,
            "step_id": self.step_id,
            "event_type": self.event_type,
            "payload": self.payload,
            "emitted_at": self.emitted_at.isoformat() if self.emitted_at else None,
        }

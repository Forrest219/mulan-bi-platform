"""任务运行与调度数据模型"""
from typing import Dict, Any

from sqlalchemy import (
    Column, BigInteger, Integer, String, DateTime,
    Boolean, Text, ForeignKey, Index
)

from app.core.database import Base, JSONB, sa_func, sa_text


class BiTaskRun(Base):
    """任务运行记录表 bi_task_runs"""
    __tablename__ = "bi_task_runs"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    celery_task_id = Column(String(256), nullable=True, index=True)
    task_name = Column(String(256), nullable=False)
    task_label = Column(String(128), nullable=True)
    trigger_type = Column(String(16), nullable=False, server_default=sa_text("'beat'"))
    status = Column(String(16), nullable=False, server_default=sa_text("'pending'"))
    started_at = Column(DateTime, nullable=True)
    finished_at = Column(DateTime, nullable=True)
    duration_ms = Column(Integer, nullable=True)
    result_summary = Column(JSONB, nullable=True)
    error_message = Column(Text, nullable=True)
    retry_count = Column(Integer, nullable=False, server_default=sa_text("0"))
    parent_run_id = Column(BigInteger, ForeignKey("bi_task_runs.id", ondelete="SET NULL"), nullable=True)
    triggered_by = Column(BigInteger, ForeignKey("auth_users.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime, nullable=False, server_default=sa_func.now())

    __table_args__ = (
        Index("ix_task_runs_task_name_started", "task_name", "started_at"),
        Index("ix_task_runs_status_started", "status", "started_at"),
        Index("ix_task_runs_started_at", "started_at"),
        Index("ix_task_runs_parent", "parent_run_id"),
    )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "celery_task_id": self.celery_task_id,
            "task_name": self.task_name,
            "task_label": self.task_label,
            "trigger_type": self.trigger_type,
            "status": self.status,
            "started_at": self.started_at.strftime("%Y-%m-%dT%H:%M:%SZ") if self.started_at else None,
            "finished_at": self.finished_at.strftime("%Y-%m-%dT%H:%M:%SZ") if self.finished_at else None,
            "duration_ms": self.duration_ms,
            "result_summary": self.result_summary,
            "error_message": self.error_message,
            "retry_count": self.retry_count,
            "parent_run_id": self.parent_run_id,
            "triggered_by": self.triggered_by,
            "created_at": self.created_at.strftime("%Y-%m-%dT%H:%M:%SZ") if self.created_at else None,
        }


class BiTaskSchedule(Base):
    """任务调度配置表 bi_task_schedules"""
    __tablename__ = "bi_task_schedules"

    id = Column(Integer, primary_key=True, autoincrement=True)
    schedule_key = Column(String(128), unique=True, nullable=False)
    task_name = Column(String(256), nullable=False)
    description = Column(Text, nullable=True)
    schedule_expr = Column(String(256), nullable=False)
    is_enabled = Column(Boolean, nullable=False, server_default=sa_text("true"))
    last_run_at = Column(DateTime, nullable=True)
    last_run_status = Column(String(16), nullable=True)
    created_at = Column(DateTime, nullable=False, server_default=sa_func.now())
    updated_at = Column(DateTime, nullable=False, server_default=sa_func.now())

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "schedule_key": self.schedule_key,
            "task_name": self.task_name,
            "description": self.description,
            "schedule_expr": self.schedule_expr,
            "is_enabled": self.is_enabled,
            "last_run_at": self.last_run_at.strftime("%Y-%m-%dT%H:%M:%SZ") if self.last_run_at else None,
            "last_run_status": self.last_run_status,
            "created_at": self.created_at.strftime("%Y-%m-%dT%H:%M:%SZ") if self.created_at else None,
            "updated_at": self.updated_at.strftime("%Y-%m-%dT%H:%M:%SZ") if self.updated_at else None,
        }

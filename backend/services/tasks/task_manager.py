"""任务运行管理服务"""
from datetime import datetime, timedelta, date
from math import ceil
from typing import Optional, Dict, Any, List

from sqlalchemy import func
from sqlalchemy.orm import Session

from services.tasks.models import BiTaskRun, BiTaskSchedule


class TaskManager:
    """任务运行与调度管理"""

    def __init__(self):
        pass

    def create_run(
        self,
        db: Session,
        celery_task_id: Optional[str],
        task_name: str,
        task_label: Optional[str],
        trigger_type: str,
        retry_count: int = 0,
        parent_run_id: Optional[int] = None,
        triggered_by: Optional[int] = None,
    ) -> BiTaskRun:
        """创建任务运行记录"""
        run = BiTaskRun(
            celery_task_id=celery_task_id,
            task_name=task_name,
            task_label=task_label,
            trigger_type=trigger_type,
            retry_count=retry_count,
            parent_run_id=parent_run_id,
            triggered_by=triggered_by,
        )
        db.add(run)
        db.commit()
        db.refresh(run)
        return run

    def update_run_status(
        self,
        db: Session,
        celery_task_id: str,
        status: str,
        finished_at: Optional[datetime] = None,
        duration_ms: Optional[int] = None,
        result_summary: Optional[dict] = None,
        error_message: Optional[str] = None,
    ) -> Optional[BiTaskRun]:
        """按 celery_task_id 更新最新一条运行记录的状态"""
        run = db.query(BiTaskRun).filter(
            BiTaskRun.celery_task_id == celery_task_id
        ).order_by(BiTaskRun.id.desc()).first()
        if not run:
            return None
        run.status = status
        if finished_at is not None:
            run.finished_at = finished_at
        if duration_ms is not None:
            run.duration_ms = duration_ms
        if result_summary is not None:
            run.result_summary = result_summary
        if error_message is not None:
            run.error_message = error_message
        db.commit()
        db.refresh(run)
        return run

    def get_run(self, db: Session, run_id: int) -> Optional[BiTaskRun]:
        """获取单条运行记录"""
        return db.query(BiTaskRun).filter(BiTaskRun.id == run_id).first()

    def list_runs(
        self,
        db: Session,
        page: int = 1,
        page_size: int = 20,
        status: Optional[str] = None,
        task_name: Optional[str] = None,
        trigger_type: Optional[str] = None,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
    ) -> Dict[str, Any]:
        """分页查询运行记录"""
        q = db.query(BiTaskRun)
        if status:
            q = q.filter(BiTaskRun.status == status)
        if task_name:
            q = q.filter(BiTaskRun.task_name == task_name)
        if trigger_type:
            q = q.filter(BiTaskRun.trigger_type == trigger_type)
        if start_time:
            q = q.filter(BiTaskRun.started_at >= start_time)
        if end_time:
            q = q.filter(BiTaskRun.started_at <= end_time)

        total = q.count()
        pages = ceil(total / page_size) if total > 0 else 0
        items = q.order_by(BiTaskRun.id.desc()).offset((page - 1) * page_size).limit(page_size).all()
        return {
            "items": [r.to_dict() for r in items],
            "total": total,
            "page": page,
            "page_size": page_size,
            "pages": pages,
        }

    def get_stats(self, db: Session, date: Optional[date] = None) -> Dict[str, Any]:
        """获取指定日期的任务统计及与前一天的对比"""
        target = date or datetime.utcnow().date()
        day_start = datetime.combine(target, datetime.min.time())
        day_end = datetime.combine(target, datetime.max.time())

        stats = self._compute_day_stats(db, day_start, day_end)

        yesterday_start = day_start - timedelta(days=1)
        yesterday_end = day_end - timedelta(days=1)
        yesterday_stats = self._compute_day_stats(db, yesterday_start, yesterday_end)

        return {
            "date": target.isoformat(),
            "total_runs": stats["total"],
            "succeeded": stats["succeeded"],
            "failed": stats["failed"],
            "running": stats["running"],
            "success_rate": stats["success_rate"],
            "avg_duration_ms": stats["avg_duration_ms"],
            "comparison": {
                "total_runs_delta": stats["total"] - yesterday_stats["total"],
                "success_rate_delta": round(stats["success_rate"] - yesterday_stats["success_rate"], 2),
                "failed_delta": stats["failed"] - yesterday_stats["failed"],
            },
        }

    def _compute_day_stats(
        self, db: Session, day_start: datetime, day_end: datetime
    ) -> Dict[str, Any]:
        """计算单日统计数据"""
        base = db.query(BiTaskRun).filter(
            BiTaskRun.created_at >= day_start,
            BiTaskRun.created_at <= day_end,
        )
        total = base.count()
        succeeded = base.filter(BiTaskRun.status == "succeeded").count()
        failed = base.filter(BiTaskRun.status == "failed").count()
        running = base.filter(BiTaskRun.status == "running").count()

        completed = succeeded + failed
        success_rate = round(succeeded / completed * 100, 2) if completed > 0 else 0

        avg_row = db.query(func.avg(BiTaskRun.duration_ms)).filter(
            BiTaskRun.created_at >= day_start,
            BiTaskRun.created_at <= day_end,
            BiTaskRun.duration_ms.isnot(None),
        ).scalar()
        avg_duration_ms = round(avg_row) if avg_row else 0

        return {
            "total": total,
            "succeeded": succeeded,
            "failed": failed,
            "running": running,
            "success_rate": success_rate,
            "avg_duration_ms": avg_duration_ms,
        }

    def list_schedules(self, db: Session) -> List[Dict[str, Any]]:
        """返回所有调度配置"""
        schedules = db.query(BiTaskSchedule).order_by(BiTaskSchedule.id).all()
        return [s.to_dict() for s in schedules]

    def update_schedule_enabled(
        self, db: Session, schedule_key: str, is_enabled: bool
    ) -> Optional[BiTaskSchedule]:
        """启用/禁用调度"""
        schedule = db.query(BiTaskSchedule).filter(
            BiTaskSchedule.schedule_key == schedule_key
        ).first()
        if not schedule:
            return None
        schedule.is_enabled = is_enabled
        schedule.updated_at = func.now()
        db.commit()
        db.refresh(schedule)
        return schedule

    def update_schedule_last_run(
        self, db: Session, task_name: str, run_at: datetime, status: str
    ) -> None:
        """更新调度的最后运行信息"""
        schedule = db.query(BiTaskSchedule).filter(
            BiTaskSchedule.task_name == task_name
        ).first()
        if schedule:
            schedule.last_run_at = run_at
            schedule.last_run_status = status
            schedule.updated_at = func.now()
            db.commit()

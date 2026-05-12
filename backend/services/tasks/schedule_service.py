"""同步计划（BiSyncSchedule）管理与任务队列服务"""
import logging
from datetime import datetime, timedelta
from math import ceil
from typing import Any, Dict, List, Optional

from sqlalchemy import func
from sqlalchemy.orm import Session

from services.tasks.models import BiSyncSchedule
from services.tableau.models import TableauConnection

logger = logging.getLogger(__name__)


# ---- cron 计算辅助 ----

def _compute_next_run(cron_expr: str) -> Optional[str]:
    """Return ISO-format next run time for a cron expression."""
    try:
        from croniter import croniter
        cr = croniter(cron_expr, datetime.now())
        return cr.get_next(datetime).strftime("%Y-%m-%dT%H:%M:%SZ")
    except Exception:
        return None


def _compute_next_runs(cron_expr: str, count: int = 6) -> List[str]:
    """Return next N ISO-format run times for a cron expression."""
    try:
        from croniter import croniter
        cr = croniter(cron_expr, datetime.now())
        results = []
        for _ in range(count):
            dt = cr.get_next(datetime)
            results.append(dt.strftime("%Y-%m-%dT%H:%M:%SZ"))
        return results
    except Exception:
        return []


def _describe_cron(cron_expr: str) -> str:
    """将 cron 表达式翻译为人类可读的调度描述。"""
    try:
        from croniter import croniter
        cr = croniter(cron_expr, datetime.now())
        next_dt = cr.get_next(datetime)
        # 简单翻译（5字段：分 时 日 月 周）
        parts = cron_expr.strip().split()
        if len(parts) != 5:
            return cron_expr
        minute, hour, dom, month, dow = parts
        descs = []
        if minute == "0" and hour == "*/1":
            return "每小时整点"
        if minute == "0" and hour == "*/4" and dow == "1-5":
            return "工作日每4小时"
        if minute == "0":
            if "," in hour:
                times = hour.split(",")
                return f"每日 {','.join(times)}:00"
            if hour.startswith("*/"):
                return f"每{hour[2:]}小时"
            return f"每日 {hour}:00"
        if dom == "1-7" and dow == "0":
            return f"每月第1个周日 {hour}:{minute.zfill(2)}"
        if dom != "*" and month != "*" and dow != "*":
            return f"每月 {dom} 日 {hour}:{minute.zfill(2)}"
        return cron_expr
    except Exception:
        return cron_expr


# ---- RedBeat 同步 ----

def _sync_to_redbeat(schedule: BiSyncSchedule, task_name: str) -> bool:
    """将 schedule 注册到 RedBeat（供 Celery Beat 调度）。"""
    try:
        from redbeat import RedBeatSchedulerEntry
        from services.tasks import celery_app
        from celery.schedules import crontab

        parts = schedule.cron_expr.strip().split()
        if len(parts) != 5:
            logger.warning("Invalid cron for schedule %s: %s", schedule.id, schedule.cron_expr)
            return False
        minute, hour, dom, month, dow = parts
        celery_schedule = crontab(
            minute=minute, hour=hour,
            day_of_month=dom, month_of_year=month, day_of_week=dow,
        )
        key = f"sync-schedule-{schedule.id}"
        entry = RedBeatSchedulerEntry(
            key,
            task_name,
            celery_schedule,
            args=[schedule.id],
            app=celery_app,
        )
        entry.save()
        logger.info("Registered RedBeat entry %s → %s", key, schedule.cron_expr)
        return True
    except ImportError:
        logger.warning("redbeat not installed; schedule %s not synced to Redis", schedule.id)
        return False
    except Exception as e:
        logger.warning("Failed to sync schedule %s to Redis: %s", schedule.id, e)
        return False


def _delete_redbeat_entry(schedule_id: int) -> bool:
    """从 RedBeat 删除条目。"""
    try:
        from redbeat import RedBeatSchedulerEntry
        from services.tasks import celery_app
        key = f"sync-schedule-{schedule_id}"
        entry = RedBeatSchedulerEntry(key, app=celery_app)
        entry.delete()
        logger.info("Deleted RedBeat entry %s", key)
        return True
    except Exception:
        return False


# ---- Schedule CRUD ----

class SyncScheduleService:
    """同步计划管理服务"""

    def list_schedules(
        self, db: Session,
        page: int = 1, page_size: int = 20,
        enabled_only: bool = False,
    ) -> Dict[str, Any]:
        """分页列出同步计划，含引用连接数、cron 描述、下次执行时间。"""
        q = db.query(BiSyncSchedule)
        if enabled_only:
            q = q.filter(BiSyncSchedule.is_enabled == True)

        total = q.count()
        pages = ceil(total / page_size) if total > 0 else 0
        schedules = (
            q.order_by(BiSyncSchedule.priority.desc(), BiSyncSchedule.id)
             .offset((page - 1) * page_size)
             .limit(page_size)
             .all()
        )

        items = []
        for s in schedules:
            conn_count = db.query(TableauConnection).filter(
                TableauConnection.schedule_id == s.id,
                TableauConnection.auto_sync_enabled == True,
            ).count()
            d = s.to_dict()
            d["cron_description"] = _describe_cron(s.cron_expr)
            d["next_run_at"] = _compute_next_run(s.cron_expr) if s.is_enabled else None
            d["connection_count"] = conn_count
            items.append(d)

        return {
            "items": items,
            "total": total,
            "page": page,
            "page_size": page_size,
            "pages": pages,
        }

    def get_schedule(self, db: Session, schedule_id: int) -> Optional[Dict[str, Any]]:
        """详情，含绑定的连接列表。"""
        s = db.query(BiSyncSchedule).filter(BiSyncSchedule.id == schedule_id).first()
        if not s:
            return None
        conns = db.query(TableauConnection).filter(
            TableauConnection.schedule_id == schedule_id
        ).order_by(TableauConnection.id).all()
        d = s.to_dict()
        d["cron_description"] = _describe_cron(s.cron_expr)
        d["next_run_at"] = _compute_next_run(s.cron_expr) if s.is_enabled else None
        d["connections"] = [c.to_dict() for c in conns]
        d["connection_count"] = len(conns)
        return d

    def create_schedule(
        self, db: Session,
        name: str,
        cron_expr: str,
        frequency_type: str,
        priority: int = 50,
        execution_mode: str = "parallel",
        description: Optional[str] = None,
        created_by: Optional[int] = None,
    ) -> BiSyncSchedule:
        """创建同步计划并注册 RedBeat。"""
        schedule = BiSyncSchedule(
            name=name,
            description=description,
            frequency_type=frequency_type,
            cron_expr=cron_expr,
            priority=priority,
            execution_mode=execution_mode,
            is_enabled=True,
            created_by=created_by,
        )
        db.add(schedule)
        db.commit()
        db.refresh(schedule)

        task_name = "services.tasks.tableau_tasks.sync_by_schedule"
        _sync_to_redbeat(schedule, task_name)

        return schedule

    def update_schedule(
        self, db: Session,
        schedule_id: int,
        name: Optional[str] = None,
        cron_expr: Optional[str] = None,
        frequency_type: Optional[str] = None,
        priority: Optional[int] = None,
        execution_mode: Optional[str] = None,
        description: Optional[str] = None,
        is_enabled: Optional[bool] = None,
    ) -> Optional[BiSyncSchedule]:
        """更新同步计划，cron 变更同步 RedBeat。"""
        s = db.query(BiSyncSchedule).filter(BiSyncSchedule.id == schedule_id).first()
        if not s:
            return None

        if name is not None:
            s.name = name
        if description is not None:
            s.description = description
        if frequency_type is not None:
            s.frequency_type = frequency_type
        if priority is not None:
            s.priority = priority
        if execution_mode is not None:
            s.execution_mode = execution_mode
        if is_enabled is not None:
            s.is_enabled = is_enabled

        cron_changed = False
        if cron_expr is not None and cron_expr != s.cron_expr:
            s.cron_expr = cron_expr
            cron_changed = True

        db.commit()
        db.refresh(s)

        if s.is_enabled:
            task_name = "services.tasks.tableau_tasks.sync_by_schedule"
            _sync_to_redbeat(s, task_name)
        else:
            _delete_redbeat_entry(s.id)

        return s

    def toggle_schedule(
        self, db: Session, schedule_id: int, is_enabled: bool
    ) -> Optional[BiSyncSchedule]:
        """启用/禁用同步计划。"""
        return self.update_schedule(db, schedule_id, is_enabled=is_enabled)

    def delete_schedule(self, db: Session, schedule_id: int) -> tuple[bool, str]:
        """
        删除同步计划。
        - 有连接引用时返回 (False, error_message)
        - 无引用时删除并返回 (True, "")
        """
        conn_count = db.query(TableauConnection).filter(
            TableauConnection.schedule_id == schedule_id
        ).count()
        if conn_count > 0:
            return False, f"该计划已被 {conn_count} 个连接引用，请先解除关联后再删除"

        s = db.query(BiSyncSchedule).filter(BiSyncSchedule.id == schedule_id).first()
        if not s:
            return False, "计划不存在"

        _delete_redbeat_entry(s.id)
        db.delete(s)
        db.commit()
        return True, ""

    def bind_connections(
        self, db: Session,
        schedule_id: int,
        connection_ids: List[int],
    ) -> int:
        """批量绑定连接到此计划。返回成功绑定数。"""
        count = db.query(TableauConnection).filter(
            TableauConnection.id.in_(connection_ids)
        ).update(
            {TableauConnection.schedule_id: schedule_id},
            synchronize_session=False,
        )
        db.commit()
        return count

    def unbind_connections(
        self, db: Session,
        schedule_id: int,
        connection_ids: List[int],
    ) -> int:
        """批量解绑连接（置 schedule_id = NULL）。返回成功解绑数。"""
        count = db.query(TableauConnection).filter(
            TableauConnection.schedule_id == schedule_id,
            TableauConnection.id.in_(connection_ids),
        ).update(
            {TableauConnection.schedule_id: None},
            synchronize_session=False,
        )
        db.commit()
        return count

    def load_all_to_redbeat(self, db: Session) -> int:
        """
        启动时将所有 enabled 的计划加载到 RedBeat。
        返回加载数量。
        """
        schedules = db.query(BiSyncSchedule).filter(
            BiSyncSchedule.is_enabled == True
        ).all()
        task_name = "services.tasks.tableau_tasks.sync_by_schedule"
        count = 0
        for s in schedules:
            if _sync_to_redbeat(s, task_name):
                count += 1
        return count


# ---- Task Queue ----

class TaskQueueService:
    """任务队列：历史执行 + 未来预计执行时间线"""

    def get_queue(
        self, db: Session,
        past_hours: int = 24,
        future_hours: int = 24,
    ) -> Dict[str, Any]:
        """
        合并历史运行记录 + 未来预计执行，组成统一时间线。
        - past: 从 bi_task_runs 查最近 past_hours 小时
        - future: 从 bi_sync_schedules 推算未来 future_hours 小时的执行
        """
        now = datetime.now()
        past_start = now - timedelta(hours=past_hours)

        # 历史：从 bi_task_runs 查
        from services.tasks.models import BiTaskRun
        past_q = db.query(BiTaskRun).filter(
            BiTaskRun.started_at >= past_start,
            BiTaskRun.task_name == "services.tasks.tableau_tasks.sync_by_schedule",
        ).order_by(BiTaskRun.started_at.desc())

        past_items = []
        for r in past_q.all():
            past_items.append({
                "type": "past",
                "scheduled_time": r.started_at.strftime("%Y-%m-%dT%H:%M:%SZ"),
                "finished_at": r.finished_at.strftime("%Y-%m-%dT%H:%M:%SZ") if r.finished_at else None,
                "schedule_name": r.task_label or f"计划#{r.id}",
                "status": r.status,
                "duration_ms": r.duration_ms,
                "run_id": r.id,
                "task_name": r.task_name,
            })

        # 未来：从 bi_sync_schedules 计算
        future_end = now + timedelta(hours=future_hours)
        enabled_schedules = db.query(BiSyncSchedule).filter(
            BiSyncSchedule.is_enabled == True
        ).order_by(BiSyncSchedule.priority.desc()).all()

        future_items = []
        for s in enabled_schedules:
            try:
                from croniter import croniter
                cr = croniter(s.cron_expr, now)
                while True:
                    next_dt = cr.get_next(datetime)
                    if next_dt > future_end:
                        break
                    conn_count = db.query(TableauConnection).filter(
                        TableauConnection.schedule_id == s.id,
                        TableauConnection.auto_sync_enabled == True,
                    ).count()
                    if conn_count > 0:
                        future_items.append({
                            "type": "future",
                            "scheduled_time": next_dt.strftime("%Y-%m-%dT%H:%M:%SZ"),
                            "schedule_name": s.name,
                            "schedule_id": s.id,
                            "status": "pending",
                            "connection_count": conn_count,
                            "priority": s.priority,
                            "execution_mode": s.execution_mode,
                        })
                    if len(future_items) >= 200:  # 防止过多条目
                        break
            except Exception:
                continue

        # 合并排序
        all_items = past_items + future_items
        all_items.sort(key=lambda x: x["scheduled_time"], reverse=True)

        return {
            "items": all_items,
            "past_count": len(past_items),
            "future_count": len(future_items),
            "past_range": f"{past_start.strftime('%Y-%m-%dT%H:%M:%SZ')} → {now.strftime('%Y-%m-%dT%H:%M:%SZ')}",
            "future_range": f"{now.strftime('%Y-%m-%dT%H:%M:%SZ')} → {future_end.strftime('%Y-%m-%dT%H:%M:%SZ')}",
        }

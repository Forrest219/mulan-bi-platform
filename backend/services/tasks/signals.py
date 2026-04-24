"""Celery signal handlers — auto-record task execution history to bi_task_runs."""
import logging
from datetime import datetime

from celery.signals import task_prerun, task_postrun, task_failure

from app.core.database import get_db_context

logger = logging.getLogger(__name__)

TASK_LABELS = {
    "services.tasks.tableau_tasks.scheduled_sync_all": "Tableau 自动同步",
    "services.tasks.tableau_tasks.sync_connection_task": "Tableau 单连接同步",
    "services.tasks.dqc_tasks.run_daily_full_cycle": "DQC 每日完整检查",
    "services.tasks.dqc_tasks.partition_maintenance": "DQC 分区维护",
    "services.tasks.dqc_tasks.cleanup_old_analyses": "DQC 分析清理",
    "services.tasks.quality_tasks.cleanup_old_quality_results": "质量结果清理",
    "services.tasks.event_tasks.purge_old_events": "事件数据清理",
    "services.tasks.knowledge_base_tasks.reindex_hnsw_task": "HNSW 索引重建",
    "services.tasks.knowledge_base_tasks.vacuum_analyze_embeddings_task": "向量表 VACUUM",
}


@task_prerun.connect
def on_task_prerun(sender=None, task_id=None, task=None, **kwargs):
    """Record task start in bi_task_runs."""
    try:
        from services.tasks.models import BiTaskRun

        with get_db_context() as db:
            headers = getattr(task.request, "headers", None) or {}
            trigger_type = headers.get("trigger_type", "beat")

            retry_count = getattr(task.request, "retries", 0) or 0
            parent_run_id = None
            if retry_count > 0:
                parent = db.query(BiTaskRun).filter(
                    BiTaskRun.celery_task_id == task_id,
                    BiTaskRun.retry_count == 0,
                ).first()
                parent_run_id = parent.id if parent else None

            run = BiTaskRun(
                celery_task_id=task_id,
                task_name=sender.name,
                task_label=TASK_LABELS.get(sender.name),
                trigger_type=trigger_type,
                status="running",
                started_at=datetime.utcnow(),
                retry_count=retry_count,
                parent_run_id=parent_run_id,
            )
            db.add(run)
            db.commit()
    except Exception as e:
        logger.warning("on_task_prerun failed for %s: %s", task_id, e)


@task_postrun.connect
def on_task_postrun(sender=None, task_id=None, state=None, retval=None, **kwargs):
    """Update task run record on completion."""
    try:
        from services.tasks.models import BiTaskRun

        with get_db_context() as db:
            run = db.query(BiTaskRun).filter(
                BiTaskRun.celery_task_id == task_id,
            ).order_by(BiTaskRun.id.desc()).first()
            if not run:
                return

            run.finished_at = datetime.utcnow()
            if run.started_at:
                run.duration_ms = int((run.finished_at - run.started_at).total_seconds() * 1000)

            state_map = {"SUCCESS": "succeeded", "FAILURE": "failed", "REVOKED": "cancelled"}
            run.status = state_map.get(state, "failed")

            if run.status == "succeeded":
                run.result_summary = retval if isinstance(retval, dict) else None
            else:
                run.error_message = str(retval) if retval else None

            db.commit()
            _update_schedule_last_run(db, run.task_name, run.finished_at, run.status)
    except Exception as e:
        logger.warning("on_task_postrun failed for %s: %s", task_id, e)


@task_failure.connect
def on_task_failure(sender=None, task_id=None, exception=None, traceback=None, **kwargs):
    """Mark task as failed with exception details."""
    try:
        from services.tasks.models import BiTaskRun

        with get_db_context() as db:
            run = db.query(BiTaskRun).filter(
                BiTaskRun.celery_task_id == task_id,
            ).order_by(BiTaskRun.id.desc()).first()
            if not run:
                return

            run.status = "failed"
            run.finished_at = datetime.utcnow()
            run.error_message = f"{type(exception).__name__}: {exception}"
            if run.started_at:
                run.duration_ms = int((run.finished_at - run.started_at).total_seconds() * 1000)

            db.commit()
            _update_schedule_last_run(db, run.task_name, run.finished_at, run.status)
            _emit_failure_alert(db, run)
    except Exception as e:
        logger.warning("on_task_failure failed for %s: %s", task_id, e)


def _update_schedule_last_run(db, task_name, run_at, status):
    """Sync last run info back to bi_task_schedules."""
    try:
        from services.tasks.models import BiTaskSchedule

        schedule = db.query(BiTaskSchedule).filter(
            BiTaskSchedule.task_name == task_name,
        ).first()
        if schedule:
            schedule.last_run_at = run_at
            schedule.last_run_status = status
            schedule.updated_at = datetime.utcnow()
            db.commit()
    except Exception as e:
        logger.warning("_update_schedule_last_run failed for %s: %s", task_name, e)


def _emit_failure_alert(db, run):
    """Create event + admin notifications for a failed task."""
    try:
        from services.events.models import EventDatabase

        event_db = EventDatabase()
        label = run.task_label or run.task_name
        event = event_db.create_event(
            db,
            event_type="task.failed",
            source_module="tasks",
            source_id=str(run.id),
            severity="error",
            payload_json={
                "task_name": run.task_name,
                "task_label": run.task_label,
                "error_message": run.error_message,
                "retry_count": run.retry_count,
                "duration_ms": run.duration_ms,
                "celery_task_id": run.celery_task_id,
            },
        )
        admin_ids = event_db.get_users_by_role(db, "admin")
        if admin_ids:
            event_db.batch_create_notifications(
                db,
                event_id=event.id,
                user_ids=admin_ids,
                title=f"任务失败：{label}",
                content=run.error_message or "未知错误",
                level="error",
                link=f"/system/tasks?tab=history&run_id={run.id}",
            )
    except Exception as e:
        logger.warning("_emit_failure_alert failed for run %s: %s", run.id, e)

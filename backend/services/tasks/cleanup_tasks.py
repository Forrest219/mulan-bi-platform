"""
bi_task_runs / bi_task_schedules 90天清理任务 — Spec 33 §3.4

清理策略：
- bi_task_runs：90 天前且 status 为 succeeded/failed/cancelled 的记录
- bi_task_schedules：无清理需求（配置表，只保留最新状态）

Beat 调度：每 24 小时执行一次
Dry-run：只 COUNT，不 DELETE
"""
import logging
from datetime import datetime, timedelta

from celery import shared_task
from sqlalchemy import func

from app.core.database import SessionLocal
from services.tasks.decorators import beat_guarded

logger = logging.getLogger(__name__)

RETENTION_DAYS = 90
CLEANUPABLE_STATUSES = ("succeeded", "failed", "cancelled")


def count_cleanup_candidates(db) -> int:
    """返回待清理的记录数（dry-run 使用）"""
    cutoff = datetime.now() - timedelta(days=RETENTION_DAYS)
    return db.query(func.count(BiTaskRun.id)).filter(
        BiTaskRun.started_at < cutoff,
        BiTaskRun.status.in_(CLEANUPABLE_STATUSES),
    ).scalar()


def cleanup_old_task_runs(dry_run: bool = True) -> dict:
    """
    清理 90 天前已结束的 bi_task_runs 记录。

    Args:
        dry_run: True 时只统计不删除（用于 dry-run 端点）

    Returns:
        dict，含 count_deleted / count_candidates / dry_run
    """
    from services.tasks.models import BiTaskRun

    cutoff = datetime.now() - timedelta(days=RETENTION_DAYS)

    with SessionLocal() as db:
        candidates = db.query(BiTaskRun.id).filter(
            BiTaskRun.started_at < cutoff,
            BiTaskRun.status.in_(CLEANUPABLE_STATUSES),
        )

        if dry_run:
            count = candidates.count()
            logger.info(
                "cleanup_old_task_runs [dry_run]: would delete %d records "
                "older than %d days (cutoff=%s)",
                count, RETENTION_DAYS, cutoff.isoformat(),
            )
            return {
                "dry_run": True,
                "count_candidates": count,
                "retention_days": RETENTION_DAYS,
                "cutoff": cutoff.isoformat(),
                "statuses": CLEANUPABLE_STATUSES,
            }

        # 实际删除
        deleted = candidates.delete(synchronize_session=False)
        db.commit()
        logger.info(
            "cleanup_old_task_runs: deleted %d records older than %d days",
            deleted, RETENTION_DAYS,
        )
        return {
            "dry_run": False,
            "count_deleted": deleted,
            "retention_days": RETENTION_DAYS,
            "cutoff": cutoff.isoformat(),
        }


@shared_task(bind=True, name="services.tasks.cleanup_tasks.cleanup_old_task_runs")
@beat_guarded("task-runs-cleanup")
def cleanup_old_task_runs_task(self):
    """
    Celery Beat 任务：清理过期的 bi_task_runs 记录。

    Beat schedule：services.tasks.__init__.py
        "task-runs-cleanup": {task: "...", schedule: 86400.0}
    """
    result = cleanup_old_task_runs(dry_run=False)
    return result
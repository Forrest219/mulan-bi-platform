"""
Celery 任务队列 — Mulan BI Platform
"""
import os

from celery import Celery

CELERY_BROKER_URL = os.environ.get("CELERY_BROKER_URL", "redis://localhost:6379/0")
CELERY_RESULT_BACKEND = os.environ.get("CELERY_RESULT_BACKEND", "redis://localhost:6379/1")

celery_app = Celery(
    "mulan_bi",
    broker=CELERY_BROKER_URL,
    backend=CELERY_RESULT_BACKEND,
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="Asia/Shanghai",
    enable_utc=True,
    task_track_started=True,
    result_expires=3600,
    beat_schedule={
        "tableau-auto-sync": {
            "task": "services.tasks.tableau_tasks.scheduled_sync_all",
            "schedule": 60.0,
        },
        "quality-cleanup-old-results": {
            "task": "services.tasks.quality_tasks.cleanup_old_quality_results",
            "schedule": 86400.0,  # 每天执行一次（清理 90 天前数据）
        },
    },
)

celery_app.autodiscover_tasks(["services.tasks"])

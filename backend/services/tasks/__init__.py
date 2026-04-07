"""
Celery 任务队列 — Mulan BI Platform

⚠️ 架构说明：
Celery worker 启动时会 import 本模块，此时 broker/backend URL 必须可用。
因此本文件使用 services.common.settings 中的 lru_cache 惰性读取，
在 celery worker 进程内首次调用时读取一次并缓存（worker 进程不退出会一直有效）。
"""
from celery import Celery
from celery.schedules import crontab

from services.common.settings import get_celery_broker_url, get_celery_result_backend

celery_app = Celery(
    "mulan_bi",
    broker=get_celery_broker_url(),
    backend=get_celery_result_backend(),
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
        "events-purge-old": {
            "task": "services.tasks.event_tasks.purge_old_events",
            "schedule": 86400.0,  # 每天凌晨 3:00 执行（实际时间由 worker 启动参数控制）
            "options": {"expires": 3600},
        },
        # HNSW 索引维护（Spec 14 v1.1 §5.4）
        # ⚠️ pgvector 0.5 不支持 REINDEX CONCURRENTLY，须在低峰维护窗口执行
        "hnsw-reindex": {
            "task": "services.tasks.knowledge_base_tasks.reindex_hnsw_task",
            "schedule": crontab(minute=0, hour=3, day_of_month='1-7', day_of_week='sunday'),
            # 每月第一个周日凌晨 3:00 执行（低峰期，维护窗口约 5-30 分钟）
            "options": {"expires": 7200},  # 2 小时超时保护
        },
        "hnsw-vacuum-analyze": {
            "task": "services.tasks.knowledge_base_tasks.vacuum_analyze_embeddings_task",
            "schedule": crontab(minute=0, hour=3, day_of_week='sunday'),
            # 每周日凌晨 3:00 执行（在 reindex 之后）
            "options": {"expires": 3600},
        },
    },
)

celery_app.autodiscover_tasks(["services.tasks"])

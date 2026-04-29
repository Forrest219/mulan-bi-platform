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
        # 出站队列重试调度（Celery Beat 每 30s 扫描）
        "events-outbox-retry": {
            "task": "services.tasks.event_tasks.process_outbox",
            "schedule": 30.0,  # 每 30s 执行一次
            "options": {"expires": 300},
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
        # DQC 每日完整 cycle（04:00，避开 Tableau 同步与健康扫描）
        "dqc-cycle-daily": {
            "task": "services.tasks.dqc_tasks.run_daily_full_cycle",
            "schedule": crontab(minute=0, hour=4),
            "options": {"expires": 3600},
        },
        # DQC 分区维护（每月 1 日 03:10）
        "dqc-partition-maintenance": {
            "task": "services.tasks.dqc_tasks.partition_maintenance",
            "schedule": crontab(minute=10, hour=3, day_of_month=1),
            "options": {"expires": 7200},
        },
        # DQC 分析/cycles 过期清理（每日 03:30）
        "dqc-cleanup-old-analyses": {
            "task": "services.tasks.dqc_tasks.cleanup_old_analyses",
            "schedule": crontab(minute=30, hour=3),
            "options": {"expires": 3600},
        },
        # Spec 33 §3.4: bi_task_runs 90天清理（每24小时）
        "task-runs-cleanup": {
            "task": "services.tasks.cleanup_tasks.cleanup_old_task_runs",
            "schedule": 86400.0,
            "options": {"expires": 3600},
        },
    },
)

celery_app.conf.include = [
    "services.tasks.tableau_tasks",
    "services.tasks.quality_tasks",
    "services.tasks.event_tasks",
    "services.tasks.dqc_tasks",
    "services.tasks.health_scan_tasks",
    "services.tasks.ddl_tasks",
    "services.tasks.knowledge_base_tasks",
    "services.tasks.api_contract_tasks",
    "services.tasks.cleanup_tasks",
]

from services.tasks import signals  # noqa: F401

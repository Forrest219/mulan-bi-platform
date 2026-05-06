"""
Celery 任务队列 — Mulan BI Platform

⚠️ 架构说明：
Celery worker 启动时会 import 本模块，此时 broker/backend URL 必须可用。
因此本文件使用 services.common.settings 中的 lru_cache 惰性读取，
在 celery worker 进程内首次调用时读取一次并缓存（worker 进程不退出会一直有效）。

Beat 调度说明：
- 使用 redbeat.RedBeatScheduler，调度配置存储在 Redis 中，支持运行时修改生效
- beat_schedule 仅作为 Bootstrap 默认值（Redis 无对应 key 时写入）
- 通过任务管理页面修改 cron_expr 后立即写入 Redis，Beat 在 60s 内生效
"""
from celery import Celery
from celery.schedules import crontab

from services.common.settings import get_celery_broker_url, get_celery_result_backend, get_redis_url

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
    # ── redbeat 动态调度配置 ──────────────────────────────────────────────
    beat_scheduler="redbeat.RedBeatScheduler",
    redbeat_redis_url=get_redis_url(),
    beat_max_loop_interval=60,  # 60s 内感知 Redis 调度变更
    # ── Bootstrap 默认调度（Redis 无对应 key 时生效，不覆盖已有 Redis 值） ──
    beat_schedule={
        "tableau-auto-sync": {
            "task": "services.tasks.tableau_tasks.scheduled_sync_all",
            "schedule": crontab(minute=0, hour="0,12"),
        },
        "events-purge-old": {
            "task": "services.tasks.event_tasks.purge_old_events",
            "schedule": crontab(minute=0, hour=3),
            "options": {"expires": 3600},
        },
        # 高频基础设施任务，不纳入 bi_task_schedules，保留静态调度
        "events-outbox-retry": {
            "task": "services.tasks.event_tasks.process_outbox",
            "schedule": 30.0,
            "options": {"expires": 300},
        },
        "hnsw-reindex": {
            "task": "services.tasks.knowledge_base_tasks.reindex_hnsw_task",
            "schedule": crontab(minute=0, hour=3, day_of_month="1-7", day_of_week="sunday"),
            "options": {"expires": 7200},
        },
        "hnsw-vacuum-analyze": {
            "task": "services.tasks.knowledge_base_tasks.vacuum_analyze_embeddings_task",
            "schedule": crontab(minute=0, hour=3, day_of_week="sunday"),
            "options": {"expires": 3600},
        },
        "dqc-cycle-daily": {
            "task": "services.tasks.dqc_tasks.run_daily_full_cycle",
            "schedule": crontab(minute=0, hour=4),
            "options": {"expires": 3600},
        },
        "dqc-partition-maintenance": {
            "task": "services.tasks.dqc_tasks.partition_maintenance",
            "schedule": crontab(minute=10, hour=3, day_of_month=1),
            "options": {"expires": 7200},
        },
        "dqc-cleanup-old-analyses": {
            "task": "services.tasks.dqc_tasks.cleanup_old_analyses",
            "schedule": crontab(minute=30, hour=3),
            "options": {"expires": 3600},
        },
        "task-runs-cleanup": {
            "task": "services.tasks.cleanup_tasks.cleanup_old_task_runs",
            "schedule": crontab(minute=0, hour=2),
            "options": {"expires": 3600},
        },
    },
)

celery_app.conf.include = [
    "services.tasks.tableau_tasks",
    "services.tasks.event_tasks",
    "services.tasks.dqc_tasks",
    "services.tasks.health_scan_tasks",
    "services.tasks.ddl_tasks",
    "services.tasks.knowledge_base_tasks",
    "services.tasks.api_contract_tasks",
    "services.tasks.cleanup_tasks",
]

from services.tasks import signals  # noqa: F401

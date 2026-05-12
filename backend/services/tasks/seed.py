"""任务调度种子数据"""
from sqlalchemy.orm import Session

from services.tasks.models import BiTaskSchedule, BiSyncSchedule


SEED_DATA = [
    ("tableau-auto-sync", "services.tasks.tableau_tasks.scheduled_sync_all",
     "旧版全连接 Tableau 自动同步（默认禁用，主链路使用 BiSyncSchedule）", "每日 00:00 / 12:00", "0 0,12 * * *", False),
    ("events-purge-old", "services.tasks.event_tasks.purge_old_events",
     "清理过期事件与通知数据", "每日 03:00", "0 3 * * *", True),
    ("hnsw-reindex", "services.tasks.knowledge_base_tasks.reindex_hnsw_task",
     "重建 HNSW 向量索引（低峰维护）", "每月第 1 个周日 03:00", "0 3 1-7 * 0", True),
    ("hnsw-vacuum-analyze", "services.tasks.knowledge_base_tasks.vacuum_analyze_embeddings_task",
     "向量表 VACUUM ANALYZE", "每周日 03:00", "0 3 * * 0", True),
    ("dqc-cycle-daily", "services.tasks.dqc_tasks.run_daily_full_cycle",
     "DQC 每日全量数据质量检查", "每日 04:00", "0 4 * * *", True),
    ("dqc-partition-maintenance", "services.tasks.dqc_tasks.partition_maintenance",
     "DQC 分区维护（表分区管理）", "每月 1 日 03:10", "10 3 1 * *", True),
    ("dqc-cleanup-old-analyses", "services.tasks.dqc_tasks.cleanup_old_analyses",
     "清理过期 DQC 分析记录与 Cycle", "每日 03:30", "30 3 * * *", True),
    ("task-runs-cleanup", "services.tasks.cleanup_tasks.cleanup_old_task_runs",
     "清理 90 天前的任务运行记录", "每日 02:00", "0 2 * * *", True),
    ("plan-daily-sync-tasks", "services.tasks.tableau_tasks.plan_daily_sync_tasks",
     "预生成未来 24h 同步任务清单（Spec 43）", "每日 00:05", "5 0 * * *", True),
]

# 同步计划（BiSyncSchedule）种子数据
SYNC_SCHEDULE_SEED = [
    ("每日两次同步", "每日 00:00 / 12:00 执行", "daily", "0 0,12 * * *", 50, "parallel"),
    ("工作日每4小时同步", "工作日 4 小时执行一次", "hourly", "0 */4 * * 1-5", 40, "parallel"),
    ("每日凌晨一次", "每日凌晨 02:00 执行（低峰）", "daily", "0 2 * * *", 30, "sequential"),
]


def seed_task_schedules(db_session: Session) -> None:
    """幂等插入 Beat 调度种子数据"""
    existing = {
        row.schedule_key: row
        for row in db_session.query(BiTaskSchedule).all()
    }
    for schedule_key, task_name, description, schedule_expr, cron_expr, is_enabled in SEED_DATA:
        if schedule_key not in existing:
            db_session.add(BiTaskSchedule(
                schedule_key=schedule_key,
                task_name=task_name,
                description=description,
                schedule_expr=schedule_expr,
                cron_expr=cron_expr,
                is_enabled=is_enabled,
            ))
        elif schedule_key == "tableau-auto-sync":
            existing[schedule_key].description = description
            existing[schedule_key].is_enabled = False
    db_session.commit()


def seed_sync_schedules(db_session: Session) -> None:
    """幂等插入同步计划（BiSyncSchedule）种子数据"""
    existing_names = {
        row[0] for row in
        db_session.query(BiSyncSchedule.name).all()
    }
    for name, description, frequency_type, cron_expr, priority, execution_mode in SYNC_SCHEDULE_SEED:
        if name not in existing_names:
            db_session.add(BiSyncSchedule(
                name=name,
                description=description,
                frequency_type=frequency_type,
                cron_expr=cron_expr,
                priority=priority,
                execution_mode=execution_mode,
                is_enabled=True,
            ))
    db_session.commit()

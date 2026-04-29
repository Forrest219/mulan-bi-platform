"""任务调度种子数据"""
from sqlalchemy.orm import Session

from services.tasks.models import BiTaskSchedule


SEED_DATA = [
    ("tableau-auto-sync", "services.tasks.tableau_tasks.scheduled_sync_all",
     "同步所有 Tableau 连接的资产数据", "每 60 秒"),
    ("quality-cleanup-old-results", "services.tasks.quality_tasks.cleanup_old_quality_results",
     "清理 90 天前的质量检查结果", "每 24 小时"),
    ("events-purge-old", "services.tasks.event_tasks.purge_old_events",
     "清理过期事件与通知数据", "每 24 小时"),
    ("hnsw-reindex", "services.tasks.knowledge_base_tasks.reindex_hnsw_task",
     "重建 HNSW 向量索引（低峰维护）", "每月第 1 个周日 03:00"),
    ("hnsw-vacuum-analyze", "services.tasks.knowledge_base_tasks.vacuum_analyze_embeddings_task",
     "向量表 VACUUM ANALYZE", "每周日 03:00"),
    ("dqc-cycle-daily", "services.tasks.dqc_tasks.run_daily_full_cycle",
     "DQC 每日全量数据质量检查", "每日 04:00"),
    ("dqc-partition-maintenance", "services.tasks.dqc_tasks.partition_maintenance",
     "DQC 分区维护（表分区管理）", "每月 1 日 03:10"),
    ("dqc-cleanup-old-analyses", "services.tasks.dqc_tasks.cleanup_old_analyses",
     "清理过期 DQC 分析记录与 Cycle", "每日 03:30"),
    ("task-runs-cleanup", "services.tasks.cleanup_tasks.cleanup_old_task_runs",
     "清理 90 天前的任务运行记录", "每 24 小时"),
]


def seed_task_schedules(db_session: Session) -> None:
    """幂等插入 Beat 调度种子数据"""
    existing_keys = {
        row[0] for row in
        db_session.query(BiTaskSchedule.schedule_key).all()
    }
    for schedule_key, task_name, description, schedule_expr in SEED_DATA:
        if schedule_key not in existing_keys:
            db_session.add(BiTaskSchedule(
                schedule_key=schedule_key,
                task_name=task_name,
                description=description,
                schedule_expr=schedule_expr,
            ))
    db_session.commit()

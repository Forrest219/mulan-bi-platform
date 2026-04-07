"""
事件归档 Celery 任务 — bi_events / bi_notifications 生命周期管理

Sprint 3: bi_events 归档策略

保留策略：90 天（由用户确认）
- bi_events.created_at < now() - 90 天 → DELETE（含级联删除 bi_notifications）
- 孤儿 bi_notifications（event_id 无对应记录）→ DELETE

⚠️ 约束：
- 只在主库执行，不用只读副本（涉及 DELETE）
- 归档期间事件写入不受影响（DELETE 和 INSERT 不互斥）
- 每次执行记录日志，便于审计追溯
"""
import logging
from datetime import datetime, timedelta

from celery import shared_task
from sqlalchemy import text

from app.core.database import engine

logger = logging.getLogger(__name__)

# 保留天数（与 Sprint 3 用户确认值一致）
RETENTION_DAYS = 90


@shared_task
def purge_old_events():
    """
    归档 90 天前的 bi_events 及级联通知记录。

    触发方式：Celery Beat 每日凌晨 3:00 执行
    关联 Beat Schedule：services.tasks.__init__.py beat_schedule
    """
    try:
        cutoff = datetime.now() - timedelta(days=RETENTION_DAYS)
        cutoff_str = cutoff.strftime("%Y-%m-%d %H:%M:%S")

        with engine.connect() as conn:
            # Step 1: 统计待删除数量（归档前审计）
            count_result = conn.execute(
                text("SELECT COUNT(*) FROM bi_events WHERE created_at < :cutoff"),
                {"cutoff": cutoff_str}
            )
            pending_count = count_result.scalar()

            # Step 2: 删除孤儿通知（event 已被其他方式删除的残留记录）
            orphan_result = conn.execute(
                text("""
                    DELETE FROM bi_notifications
                    WHERE event_id NOT IN (SELECT id FROM bi_events)
                """)
            )
            orphan_count = orphan_result.rowcount

            # Step 3: 删除超期事件（级联删除对应 bi_notifications）
            events_result = conn.execute(
                text("DELETE FROM bi_events WHERE created_at < :cutoff"),
                {"cutoff": cutoff_str}
            )
            events_count = events_result.rowcount

            conn.commit()

            logger.info(
                "purge_old_events: [retention=%d days] "
                "events_deleted=%d, notifications_deleted=%d (orphans), "
                "cutoff=%s",
                RETENTION_DAYS, events_count, orphan_count, cutoff_str
            )

            return {
                "retention_days": RETENTION_DAYS,
                "events_deleted": events_count,
                "orphan_notifications_deleted": orphan_count,
                "cutoff": cutoff_str,
            }

    except Exception as e:
        logger.error("purge_old_events failed: %s", e, exc_info=True)
        raise

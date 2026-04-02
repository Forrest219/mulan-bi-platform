"""
Tableau 同步 Celery 任务
"""
import logging
from datetime import datetime, timedelta

from services.tasks import celery_app

logger = logging.getLogger(__name__)


@celery_app.task(bind=True, max_retries=2, default_retry_delay=30)
def sync_connection_task(self, conn_id: int):
    """
    单个连接的异步同步任务。
    由 API 手动触发或 scheduled_sync_all Beat 调度触发。
    """
    from services.tableau.models import TableauDatabase
    from services.tableau.sync_service import TableauSyncService, TableauRestSyncService
    from app.core.crypto import get_tableau_crypto

    _db = TableauDatabase()
    conn = _db.get_connection(conn_id)
    if not conn:
        logger.warning("Sync task: connection %d not found", conn_id)
        return {"status": "error", "message": "连接不存在"}

    if conn.sync_status == "running":
        logger.info("Sync task: connection %d already running, skipping", conn_id)
        return {"status": "skipped", "message": "同步正在进行中"}

    crypto = get_tableau_crypto()
    try:
        token = crypto.decrypt(conn.token_encrypted)
    except Exception as e:
        msg = f"Token 解密失败: {e}"
        _db.update_connection_health(conn_id, False, msg)
        return {"status": "error", "message": msg}

    try:
        if getattr(conn, "connection_type", "mcp") == "mcp":
            service = TableauRestSyncService(
                server_url=conn.server_url,
                site=conn.site,
                token_name=conn.token_name,
                token_value=token,
                api_version=conn.api_version,
            )
        else:
            service = TableauSyncService(
                server_url=conn.server_url,
                site=conn.site,
                token_name=conn.token_name,
                token_value=token,
                api_version=conn.api_version,
            )

        if not service.connect():
            if self.request.retries < self.max_retries:
                raise self.retry(exc=Exception("连接失败"))
            _db.set_sync_status(conn_id, "failed")
            return {"status": "error", "message": "连接失败"}

        try:
            trigger_type = "manual" if self.request.delivery_info.get("is_eager") else "scheduled"
            result = service.sync_all_assets(_db, conn_id, trigger_type=trigger_type)
            logger.info(
                "Sync task for conn %d: %s (%d assets, %ds)",
                conn_id, result["status"], result["total"], result.get("duration_sec", 0),
            )
            return {
                "status": result["status"],
                "total": result["total"],
                "deleted": result["deleted"],
                "duration_sec": result.get("duration_sec", 0),
                "sync_log_id": result.get("sync_log_id"),
            }
        finally:
            service.disconnect()

    except self.MaxRetriesExceededError:
        _db.set_sync_status(conn_id, "failed")
        return {"status": "error", "message": "同步失败，已达最大重试次数"}
    except Exception as e:
        logger.error("Sync task error for conn %d: %s", conn_id, e, exc_info=True)
        if self.request.retries < self.max_retries:
            raise self.retry(exc=e)
        _db.set_sync_status(conn_id, "failed")
        return {"status": "error", "message": str(e)}


@celery_app.task
def scheduled_sync_all():
    """
    Beat 调度任务：每 60 秒检查所有活跃连接，
    对到期的连接触发 sync_connection_task。
    """
    from services.tableau.models import TableauDatabase

    try:
        _db = TableauDatabase()
        connections = _db.get_all_connections(include_inactive=False)

        for conn in connections:
            if not conn.auto_sync_enabled:
                continue

            interval = timedelta(hours=conn.sync_interval_hours or 24)
            if conn.last_sync_at and (datetime.now() - conn.last_sync_at) < interval:
                continue

            logger.info("Beat: triggering sync for '%s' (conn_id=%d)", conn.name, conn.id)
            sync_connection_task.delay(conn.id)

    except Exception as e:
        logger.error("scheduled_sync_all error: %s", e, exc_info=True)

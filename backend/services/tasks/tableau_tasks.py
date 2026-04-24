"""
Tableau 同步 Celery 任务

Session 管理规范（Spec 07 §7.3 P1）：
- API 层：FastAPI Depends(get_db) 注入 Session
- Celery 任务层：使用 get_db_context() 上下文管理器，禁止自行 new Session
"""
import logging
from datetime import datetime, timedelta

from services.tasks import celery_app
from services.tasks.decorators import beat_guarded

logger = logging.getLogger(__name__)


@celery_app.task(bind=True, max_retries=2, default_retry_delay=30)
def sync_connection_task(self, conn_id: int):
    """
    单个连接的异步同步任务。
    由 API 手动触发或 scheduled_sync_all Beat 调度触发。
    Celery 任务层必须使用 get_db_context() 管理 Session（Spec 07 §7.3 P1）。
    """
    from services.tableau.models import TableauDatabase
    from services.tableau.sync_service import TableauSyncService, TableauRestSyncService
    from app.core.crypto import get_tableau_crypto
    from app.core.database import get_db_context

    with get_db_context() as db:
        _db = TableauDatabase(session=db)
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
            # P0 修复：异常后先回滚，再更新状态，防止 Invalidated Session 报错
            db.rollback()
            _db.set_sync_status(conn_id, "failed")
            return {"status": "error", "message": "同步失败，已达最大重试次数"}
        except Exception as e:
            logger.error("Sync task error for conn %d: %s", conn_id, e, exc_info=True)
            if self.request.retries < self.max_retries:
                raise self.retry(exc=e)
            # P0 修复：异常后先回滚事务重置状态，再记录失败
            db.rollback()
            _db.set_sync_status(conn_id, "failed")
            return {"status": "error", "message": str(e)}


def _bridge_mcp_to_connections(tableau_db, db_session):
    """将 mcp_servers 中 type='tableau' 的活跃记录桥接到 tableau_connections。"""
    from services.mcp.models import McpServer
    from app.core.crypto import get_tableau_crypto

    try:
        mcp_servers = db_session.query(McpServer).filter(
            McpServer.type == "tableau",
            McpServer.is_active == True,
        ).all()
    except Exception as e:
        logger.warning("Bridge: failed to query mcp_servers: %s", e)
        return

    crypto = get_tableau_crypto()
    for mcp in mcp_servers:
        creds = mcp.credentials or {}
        pat_value = creds.get("pat_value", "")
        if not pat_value:
            logger.warning("Bridge: mcp_server '%s' has no pat_value, skipping", mcp.name)
            continue

        try:
            token_encrypted = crypto.encrypt(pat_value)
        except Exception as e:
            logger.warning("Bridge: encrypt failed for '%s': %s", mcp.name, e)
            continue

        conn, created = tableau_db.ensure_connection_from_mcp(
            mcp_name=mcp.name,
            server_url=creds.get("tableau_server", mcp.server_url or ""),
            site=creds.get("site_name", ""),
            token_name=creds.get("pat_name", ""),
            token_encrypted=token_encrypted,
            mcp_server_url=mcp.server_url or "",
        )
        if created:
            logger.info("Bridge: created tableau_connection '%s' (id=%d) from mcp_server id=%d",
                        mcp.name, conn.id, mcp.id)


@celery_app.task
@beat_guarded("tableau-auto-sync")
def scheduled_sync_all():
    """
    Beat 调度任务：每 60 秒检查所有活跃连接，
    对到期的连接触发 sync_connection_task。
    启动前先桥接 mcp_servers → tableau_connections。
    Celery 任务层必须使用 get_db_context() 管理 Session（Spec 07 §7.3 P1）。
    """
    from services.tableau.models import TableauDatabase
    from app.core.database import get_db_context

    with get_db_context() as db:
        _db = TableauDatabase(session=db)

        _bridge_mcp_to_connections(_db, db)

        connections = _db.get_all_connections(include_inactive=False)

        for conn in connections:
            if not conn.auto_sync_enabled:
                continue

            interval = timedelta(hours=conn.sync_interval_hours or 24)
            if conn.last_sync_at and (datetime.now() - conn.last_sync_at) < interval:
                continue

            logger.info("Beat: triggering sync for '%s' (conn_id=%d)", conn.name, conn.id)
            sync_connection_task.delay(conn.id)

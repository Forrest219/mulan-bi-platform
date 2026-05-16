"""
Tableau 同步 Celery 任务

Session 管理规范（Spec 07 §7.3 P1）：
- API 层：FastAPI Depends(get_db) 注入 Session
- Celery 任务层：使用 get_db_context() 上下文管理器，禁止自行 new Session
"""
import logging
from datetime import datetime

from services.tasks import celery_app
from services.tasks.decorators import beat_guarded

logger = logging.getLogger(__name__)


def _update_sync_task(sync_task_id: int, status: str, sync_log_id: int = None, error_message: str = None):
    """更新 BiSyncTask 执行状态（Spec 43 §4.3）。忽略所有异常，不影响主任务。"""
    if not sync_task_id:
        return
    try:
        from datetime import datetime
        from services.tasks.models import BiSyncTask
        from app.core.database import get_db_context
        with get_db_context() as db:
            task = db.query(BiSyncTask).filter(BiSyncTask.id == sync_task_id).first()
            if task:
                task.status = status
                task.updated_at = datetime.now()
                if sync_log_id:
                    task.sync_log_id = sync_log_id
                if error_message:
                    task.error_message = error_message[:1000]
                db.commit()
    except Exception as e:
        logger.warning("_update_sync_task(%d): failed: %s", sync_task_id, e)


@celery_app.task(bind=True, max_retries=2, default_retry_delay=30)
def sync_connection_task(self, conn_id: int, sync_log_id: int = None, trigger_type: str = "manual", sync_task_id: int = None):
    """
    单个连接的异步同步任务。
    由 API 手动触发或 scheduled_sync_all Beat 调度触发。
    Celery 任务层必须使用 get_db_context() 管理 Session（Spec 07 §7.3 P1）。

    并发保护：per-connection Redis 锁，防止同一连接被并发触发
    （如 Beat 重复调度 + 手动触发同时发生）。
    """
    import redis
    from services.common.settings import get_redis_url

    lock_key = f"tableau:sync:conn:{conn_id}:lock"
    lock_timeout = 300  # 5 分钟，足够完成一次同步

    redis_client = None
    try:
        redis_client = redis.from_url(get_redis_url(), decode_responses=True)
        acquired = redis_client.set(lock_key, "1", nx=True, ex=lock_timeout)
        if not acquired:
            logger.warning("sync_connection_task[conn_id=%d]: already running, skipping", conn_id)
            _update_sync_task(sync_task_id, "skipped", error_message="同步任务正在进行中，已跳过本次调度")
            return {"status": "skipped", "message": "同步任务正在进行中"}
    except Exception as e:
        logger.warning("sync_connection_task[conn_id=%d]: Redis lock failed (%s), proceeding", conn_id, e)
        redis_client = None

    try:
        from services.tableau.models import TableauDatabase
        from services.tableau.sync_service import TableauSyncService, TableauRestSyncService
        from app.core.crypto import get_tableau_crypto
        from app.core.database import get_db_context

        with get_db_context() as db:
            _db = TableauDatabase(session=db)
            conn = _db.get_connection(conn_id)
            if not conn:
                logger.warning("Sync task: connection %d not found", conn_id)
                _update_sync_task(sync_task_id, "failed", error_message="连接不存在")
                return {"status": "error", "message": "连接不存在"}

            # 复用已有日志或新建（重试时复用，避免每次重试创建新记录）
            if sync_log_id:
                log_id = sync_log_id
            else:
                sync_log = _db.create_sync_log(conn_id, trigger_type=trigger_type)
                log_id = sync_log.id

            _db.set_sync_status(conn_id, "running")
            _update_sync_task(sync_task_id, "running", sync_log_id=log_id)

            crypto = get_tableau_crypto()
            try:
                token = crypto.decrypt(conn.token_encrypted)
            except Exception as e:
                msg = f"Token 解密失败: {e}"
                _db.finish_sync_log(log_id, "failed", error_message=msg)
                _db.set_sync_status(conn_id, "failed")
                _db.update_connection_health(conn_id, False, msg)
                _db.increment_sync_failures(conn_id)
                _update_sync_task(sync_task_id, "failed", sync_log_id=log_id, error_message=msg)
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
                        raise self.retry(
                            exc=Exception("连接失败"),
                            args=(),
                            kwargs={"conn_id": conn_id, "sync_log_id": log_id, "trigger_type": trigger_type, "sync_task_id": sync_task_id},
                        )
                    _db.finish_sync_log(log_id, "failed", error_message="连接失败，已达最大重试次数")
                    _db.set_sync_status(conn_id, "failed")
                    _db.increment_sync_failures(conn_id)
                    _update_sync_task(sync_task_id, "failed", sync_log_id=log_id, error_message="连接失败，已达最大重试次数")
                    return {"status": "error", "message": "连接失败"}

                try:
                    result = service.sync_all_assets(_db, conn_id, trigger_type=trigger_type, sync_log_id=log_id)
                    logger.info(
                        "Sync task for conn %d: %s (%d assets, %ds)",
                        conn_id, result["status"], result["total"], result.get("duration_sec", 0),
                    )
                    _db.reset_sync_failures(conn_id)
                    _update_sync_task(sync_task_id, "completed", sync_log_id=log_id)
                    return {
                        "status": result["status"],
                        "total": result["total"],
                        "deleted": result["deleted"],
                        "duration_sec": result.get("duration_sec", 0),
                        "sync_log_id": log_id,
                    }
                finally:
                    service.disconnect()

            except self.MaxRetriesExceededError:
                db.rollback()
                _db.finish_sync_log(log_id, "failed", error_message="同步失败，已达最大重试次数")
                _db.set_sync_status(conn_id, "failed")
                _db.increment_sync_failures(conn_id)
                _update_sync_task(sync_task_id, "failed", sync_log_id=log_id, error_message="同步失败，已达最大重试次数")
                return {"status": "error", "message": "同步失败，已达最大重试次数"}
            except Exception as e:
                logger.error("Sync task error for conn %d: %s", conn_id, e, exc_info=True)
                if self.request.retries < self.max_retries:
                    raise self.retry(
                        exc=e,
                        args=(),
                        kwargs={"conn_id": conn_id, "sync_log_id": log_id, "trigger_type": trigger_type, "sync_task_id": sync_task_id},
                    )
                db.rollback()
                _db.finish_sync_log(log_id, "failed", error_message=str(e))
                _db.set_sync_status(conn_id, "failed")
                _db.increment_sync_failures(conn_id)
                _update_sync_task(sync_task_id, "failed", sync_log_id=log_id, error_message=str(e))
                return {"status": "error", "message": str(e)}
    finally:
        if redis_client:
            try:
                redis_client.delete(lock_key)
            except Exception:
                pass


def _bridge_mcp_to_connections(tableau_db, db_session):
    """将 mcp_servers 中 type='tableau' 的活跃记录桥接到 tableau_connections。"""
    from services.mcp.models import McpServer
    from app.core.crypto import get_tableau_crypto, get_mcp_crypto

    try:
        mcp_servers = db_session.query(McpServer).filter(
            McpServer.type == "tableau",
            McpServer.is_active == True,
        ).all()
    except Exception as e:
        logger.warning("Bridge: failed to query mcp_servers: %s", e)
        return

    crypto = get_tableau_crypto()
    _mcp_c = get_mcp_crypto()
    for mcp in mcp_servers:
        _raw = mcp.credentials or {}
        creds = {
            k: (_mcp_c.decrypt(v) if _raw.get(f"{k}_encrypted") and isinstance(v, str) and v else v)
            for k, v in _raw.items() if not k.endswith("_encrypted")
        }
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
    Beat 调度任务：每日 00:00 / 12:00 触发所有启用自动同步的连接。
    无论手工同步何时执行，cron 时间点一到即触发，不受 last_sync_at 影响。
    启动前先桥接 mcp_servers → tableau_connections。

    并发保护：使用 Redis 分布式锁防止 Beat 多实例重复触发。
    """
    import redis
    from services.common.settings import get_redis_url

    lock_key = "tableau:beat:scheduled_sync_all:lock"
    lock_timeout = 600  # 秒，cron 间隔 12h，给足完成时间

    try:
        redis_client = redis.from_url(get_redis_url(), decode_responses=True)
        acquired = redis_client.set(lock_key, "1", nx=True, ex=lock_timeout)
        if not acquired:
            logger.info("Beat: another instance is running scheduled_sync_all, skipping")
            return
    except Exception as e:
        logger.warning("Beat: Redis lock failed (%s), proceeding anyway", e)

    try:
        from services.tableau.models import TableauDatabase
        from app.core.database import get_db_context

        with get_db_context() as db:
            _db = TableauDatabase(session=db)

            _bridge_mcp_to_connections(_db, db)

            connections = _db.get_all_connections(include_inactive=False)

            from services.tasks.models import BiSyncTask
            now_dt = datetime.now()

            dispatch_list = []
            for conn in connections:
                if not conn.auto_sync_enabled:
                    continue
                task = BiSyncTask(
                    schedule_id=None,
                    connection_id=conn.id,
                    scheduled_at=now_dt,
                    status="pending",
                    trigger_type="scheduled",
                )
                db.add(task)
                dispatch_list.append((conn, task))

            db.flush()
            db.commit()

            for conn, task in dispatch_list:
                logger.info(
                    "Beat: triggering sync for '%s' (conn_id=%d, task_id=%d)",
                    conn.name, conn.id, task.id,
                )
                sync_connection_task.delay(conn.id, trigger_type="scheduled", sync_task_id=task.id)
    finally:
        try:
            redis_client.delete(lock_key)
        except Exception:
            pass


@celery_app.task(bind=True, max_retries=2, default_retry_delay=60)
def sync_by_schedule(self, schedule_id: int):
    """
    按同步计划（BiSyncSchedule）触发所有绑定连接。
    由 RedBeat 按 cron 表达式触发，每次只处理一个 schedule。

    - execution_mode=parallel: 用 Celery group 并行触发
    - execution_mode=sequential: 逐个触发（保留兼容性）
    - 按 priority 排序（高优先级先执行，在 RedBeat 入口已保证）
    - 每个连接复用 Redis 锁（sync_connection_task 内部已处理）
    """
    import redis
    from celery import group
    from services.common.settings import get_redis_url

    lock_key = f"tableau:beat:sync_schedule:{schedule_id}:lock"
    lock_timeout = 3600  # 1 小时，防止 schedule 密集触发

    redis_client = None
    try:
        redis_client = redis.from_url(get_redis_url(), decode_responses=True)
        acquired = redis_client.set(lock_key, "1", nx=True, ex=lock_timeout)
        if not acquired:
            logger.info("sync_by_schedule[%d]: already running, skipping", schedule_id)
            return {"status": "skipped", "schedule_id": schedule_id}
    except Exception as e:
        logger.warning("sync_by_schedule[%d]: Redis lock failed (%s), proceeding", schedule_id, e)
        redis_client = None

    try:
        from services.tableau.models import TableauDatabase, TableauConnection
        from app.core.database import get_db_context

        with get_db_context() as db:
            _db = TableauDatabase(session=db)

            # 获取 schedule 元信息
            from services.tasks.models import BiSyncSchedule
            schedule = db.query(BiSyncSchedule).filter(BiSyncSchedule.id == schedule_id).first()
            if not schedule:
                logger.warning("sync_by_schedule: schedule %d not found", schedule_id)
                return {"status": "error", "message": "计划不存在"}
            if not schedule.is_enabled:
                logger.info("sync_by_schedule: schedule %d is disabled, skipping", schedule_id)
                return {"status": "skipped", "message": "计划已禁用"}

            # 查询该计划下所有已启用自动同步的连接
            connections = db.query(TableauConnection).filter(
                TableauConnection.schedule_id == schedule_id,
                TableauConnection.auto_sync_enabled == True,
                TableauConnection.is_active == True,
            ).order_by(TableauConnection.id).all()

            if not connections:
                logger.info("sync_by_schedule[%d]: no active connections bound, skipping", schedule_id)
                return {"status": "skipped", "schedule_id": schedule_id, "message": "无绑定连接"}

            logger.info(
                "sync_by_schedule[%d '%s']: triggering %d connections (mode=%s)",
                schedule_id, schedule.name, len(connections), schedule.execution_mode,
            )

            # 桥接 MCP
            _bridge_mcp_to_connections(_db, db)

            # 查找对应的预生成任务清单
            from datetime import timedelta
            from services.tasks.models import BiSyncTask

            window_start = datetime.now() - timedelta(minutes=10)
            window_end   = datetime.now() + timedelta(minutes=10)

            pending_tasks = db.query(BiSyncTask).filter(
                BiSyncTask.schedule_id == schedule_id,
                BiSyncTask.status == "pending",
                BiSyncTask.scheduled_at.between(window_start, window_end),
            ).order_by(BiSyncTask.connection_id).all()

            # fallback：planner 未来得及预生成时，现场创建
            if not pending_tasks:
                logger.info(
                    "sync_by_schedule[%d]: no pre-generated tasks found, creating on-the-fly",
                    schedule_id,
                )
                now_dt = datetime.now()
                for conn in connections:
                    task = BiSyncTask(
                        schedule_id=schedule_id,
                        connection_id=conn.id,
                        scheduled_at=now_dt,
                        status="pending",
                        trigger_type="scheduled",
                    )
                    db.add(task)
                db.flush()
                pending_tasks = db.query(BiSyncTask).filter(
                    BiSyncTask.schedule_id == schedule_id,
                    BiSyncTask.status == "pending",
                    BiSyncTask.scheduled_at.between(now_dt - timedelta(seconds=5), now_dt + timedelta(seconds=5)),
                ).order_by(BiSyncTask.connection_id).all()

            # 标记 running，dispatch
            for task in pending_tasks:
                task.status = "running"
                task.updated_at = datetime.now()
            db.commit()

            for task in pending_tasks:
                logger.info(
                    "sync_by_schedule[%d]: dispatching conn %d (task_id=%d)",
                    schedule_id, task.connection_id, task.id,
                )
                try:
                    sync_connection_task.delay(task.connection_id, trigger_type="scheduled", sync_task_id=task.id)
                except Exception as e:
                    logger.error(
                        "sync_by_schedule[%d]: failed to dispatch conn %d (task_id=%d): %s",
                        schedule_id, task.connection_id, task.id, e, exc_info=True,
                    )
                    _update_sync_task(task.id, "failed", error_message=f"同步子任务派发失败: {e}")

            return {
                "status": "dispatched",
                "schedule_id": schedule_id,
                "schedule_name": schedule.name,
                "connection_count": len(pending_tasks),
                "execution_mode": schedule.execution_mode,
                "tasks": [t.id for t in pending_tasks],
            }

    finally:
        if redis_client:
            try:
                redis_client.delete(lock_key)
            except Exception:
                pass


@celery_app.task
@beat_guarded("plan-daily-sync-tasks")
def plan_daily_sync_tasks():
    """
    每日 00:05 预生成未来 24h 内所有同步任务清单（Spec 43 §4.1）。
    幂等：ON CONFLICT DO NOTHING，重复运行安全。
    """
    from datetime import datetime, timedelta
    from croniter import croniter
    from sqlalchemy.dialects.postgresql import insert as pg_insert
    from services.tasks.models import BiSyncSchedule, BiSyncTask
    from services.tableau.models import TableauConnection
    from app.core.database import get_db_context

    now = datetime.now()
    future_end = now + timedelta(hours=24)
    total_created = 0
    total_skipped = 0

    with get_db_context() as db:
        schedules = db.query(BiSyncSchedule).filter(
            BiSyncSchedule.is_enabled == True
        ).all()

        for s in schedules:
            try:
                cr = croniter(s.cron_expr, now)
            except Exception as e:
                logger.warning("plan_daily_sync_tasks: invalid cron for schedule %d: %s", s.id, e)
                continue

            # 收集未来 24h 内的所有触发时间
            fire_times = []
            while True:
                next_dt = cr.get_next(datetime)
                if next_dt > future_end:
                    break
                fire_times.append(next_dt)

            if not fire_times:
                continue

            # 获取该计划绑定的活跃连接
            connections = db.query(TableauConnection).filter(
                TableauConnection.schedule_id == s.id,
                TableauConnection.auto_sync_enabled == True,
                TableauConnection.is_active == True,
            ).all()

            for conn in connections:
                for fire_time in fire_times:
                    stmt = pg_insert(BiSyncTask).values(
                        schedule_id=s.id,
                        connection_id=conn.id,
                        scheduled_at=fire_time,
                        status="pending",
                        trigger_type="scheduled",
                    ).on_conflict_do_nothing(
                        index_elements=["schedule_id", "connection_id", "scheduled_at"]
                    )
                    result = db.execute(stmt)
                    if result.rowcount > 0:
                        total_created += 1
                    else:
                        total_skipped += 1

        db.commit()

    logger.info(
        "plan_daily_sync_tasks: created=%d skipped=%d schedules=%d",
        total_created, total_skipped, len(schedules),
    )
    return {"created": total_created, "skipped": total_skipped, "schedule_count": len(schedules)}

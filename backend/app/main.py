"""
Mulan BI Platform - FastAPI Backend
"""
import asyncio
import logging
import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import ddl, logs, requirements, rules, auth, users, groups, permissions, activity, datasources, tableau, llm

logger = logging.getLogger(__name__)

app = FastAPI(
    title="Mulan BI Platform API",
    description="DDL 规范管理平台后端 API",
    version="1.0.0",
)

# CORS 配置 - 仅允许明确的前端域名
ALLOWED_ORIGINS = os.environ.get("ALLOWED_ORIGINS", "http://localhost:5173,http://localhost:3002").split(",")
app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 注册路由
app.include_router(ddl.router, prefix="/api/ddl", tags=["DDL 检查"])
app.include_router(rules.router, prefix="/api/rules", tags=["规则配置"])
app.include_router(logs.router, prefix="/api/logs", tags=["日志"])
app.include_router(requirements.router, prefix="/api/requirements", tags=["需求管理"])
app.include_router(auth.router, prefix="/api/auth", tags=["认证"])
app.include_router(users.router, prefix="/api/users", tags=["用户管理"])
app.include_router(groups.router, prefix="/api/groups", tags=["用户组管理"])
app.include_router(permissions.router, prefix="/api/permissions", tags=["权限配置"])
app.include_router(activity.router, prefix="/api/activity", tags=["访问日志"])
app.include_router(datasources.router, prefix="/api/datasources", tags=["数据源管理"])
app.include_router(tableau.router, prefix="/api/tableau", tags=["Tableau 管理"])
app.include_router(llm.router, prefix="/api/llm", tags=["LLM 管理"])


@app.get("/")
async def root():
    return {"message": "Mulan BI Platform API", "version": "1.0.0"}


@app.get("/health")
async def health():
    return {"status": "ok"}


# --- 定时同步调度器 (Phase 2a) ---

async def _run_scheduled_sync(conn_id: int, conn_name: str):
    """执行单个连接的定时同步"""
    from pathlib import Path
    import sys
    sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))
    from tableau.models import TableauDatabase
    from tableau.sync_service import TableauSyncService, TableauRestSyncService
    from app.core.crypto import get_tableau_crypto

    db_path = str(Path(__file__).parent.parent.parent / "data" / "tableau.db")
    _db = TableauDatabase(db_path=db_path)
    conn = _db.get_connection(conn_id)
    if not conn or not conn.is_active or not conn.auto_sync_enabled:
        return

    # 跳过正在同步的连接
    if conn.sync_status == "running":
        logger.info("Scheduled sync skipped for '%s' (already running)", conn_name)
        return

    try:
        crypto = get_tableau_crypto()
        token = crypto.decrypt(conn.token_encrypted)
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
            logger.error("Scheduled sync failed for '%s': connection failed", conn_name, exc_info=True)
            _db.set_sync_status(conn_id, "failed")
            return

        try:
            result = service.sync_all_assets(_db, conn_id, trigger_type="scheduled")
            logger.info(
                "Scheduled sync for '%s': %s (%d assets, %ds)",
                conn_name, result["status"], result["total"], result.get("duration_sec", 0)
            )
        finally:
            service.disconnect()
    except Exception as e:
        logger.error("Scheduled sync error for '%s': %s", conn_name, e, exc_info=True)
        _db.set_sync_status(conn_id, "failed")


async def _sync_scheduler():
    """后台调度器：每 60 秒检查一次是否有需要同步的连接"""
    await asyncio.sleep(30)  # 启动后等 30 秒再开始检查
    while True:
        try:
            from pathlib import Path
            import sys
            sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))
            from tableau.models import TableauDatabase
            from datetime import datetime, timedelta

            db_path = str(Path(__file__).parent.parent.parent / "data" / "tableau.db")
            _db = TableauDatabase(db_path=db_path)
            connections = _db.get_all_connections(include_inactive=False)

            for conn in connections:
                if not conn.auto_sync_enabled:
                    continue
                interval = timedelta(hours=conn.sync_interval_hours or 24)
                # 检查是否到了同步时间
                if conn.last_sync_at and (datetime.now() - conn.last_sync_at) < interval:
                    continue
                logger.info("Triggering scheduled sync for '%s'", conn.name)
                await _run_scheduled_sync(conn.id, conn.name)
        except Exception as e:
            logger.error("Sync scheduler error: %s", e, exc_info=True)

        await asyncio.sleep(60)


@app.on_event("startup")
async def start_sync_scheduler():
    """启动定时同步调度器"""
    asyncio.create_task(_sync_scheduler())
    logger.info("Tableau sync scheduler started")

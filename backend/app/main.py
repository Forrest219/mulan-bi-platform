"""
Mulan BI Platform - FastAPI Backend
"""
import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import ddl, logs, requirements, rules, auth, users, groups, permissions, activity, datasources, tableau, llm, health_scan, tasks
from app.api.semantic_maintenance import datasources as sm_datasources, fields as sm_fields, review as sm_review, sync as sm_sync, publish as sm_publish

logger = logging.getLogger(__name__)

@asynccontextmanager
async def lifespan(app):
    """应用生命周期管理"""
    from app.core.database import init_db
    init_db()
    logger.info("Database initialized. Celery Beat handles scheduled sync.")
    yield


app = FastAPI(
    title="Mulan BI Platform API",
    description="DDL 规范管理平台后端 API",
    version="1.0.0",
    lifespan=lifespan,
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
app.include_router(health_scan.router, prefix="/api/governance/health", tags=["数仓健康检查"])
app.include_router(llm.router, prefix="/api/llm", tags=["LLM 管理"])
app.include_router(tasks.router, prefix="/api/tasks", tags=["任务管理"])
app.include_router(sm_datasources.router, prefix="/api/semantic-maintenance", tags=["语义维护"])
app.include_router(sm_fields.router, prefix="/api/semantic-maintenance", tags=["语义维护"])
app.include_router(sm_review.router, prefix="/api/semantic-maintenance", tags=["语义维护"])
app.include_router(sm_sync.router, prefix="/api/semantic-maintenance", tags=["语义维护"])
app.include_router(sm_publish.router, prefix="/api/semantic-maintenance", tags=["语义维护"])


@app.get("/")
async def root():
    return {"message": "Mulan BI Platform API", "version": "1.0.0"}


@app.get("/health")
async def health():
    return {"status": "ok"}

"""
Mulan BI Platform - FastAPI Backend
"""
import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.sessions import SessionMiddleware

from app.api import ddl, logs, requirements, rules, auth, users, groups, permissions, activity, datasources, tableau, llm
from app.core.constants import JWT_SECRET, JWT_EXPIRE_SECONDS

app = FastAPI(
    title="Mulan BI Platform API",
    description="DDL 规范管理平台后端 API",
    version="1.0.0",
)

# 添加 SessionMiddleware
app.add_middleware(
    SessionMiddleware,
    secret_key=JWT_SECRET,
    session_cookie="session",
    max_age=JWT_EXPIRE_SECONDS
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

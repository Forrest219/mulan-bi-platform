"""Connection Hub API（Spec 24 P2 实现写操作）

Write Operations:
- POST /api/connection-hub/connections - Create new connection
- PUT /api/connection-hub/connections/{connection_id} - Update connection
- DELETE /api/connection-hub/connections/{connection_id} - Delete connection
- POST /api/connection-hub/connections/{connection_id}/test - Test connection

Multi-engine support:
- SQL Database (PostgreSQL, MySQL, StarRocks, etc.)
- Tableau Site
- LLM Provider

Spec 24 P2 策略:
- 直接操作现有表（bi_data_sources, tableau_connections, ai_llm_configs）
- 不创建新表，保持向后兼容
"""
import asyncio
import logging
from typing import Optional, Any
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.dependencies import require_roles
from app.core.errors import AuthError
from services.connection_hub import get_unified_connections, UnifiedConnection, ConnectionType, HealthStatus
from services.connection_hub.connection_manager import ConnectionManager


router = APIRouter()
_logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# Request/Response Models
# ─────────────────────────────────────────────────────────────────────────────

class HealthResponse(BaseModel):
    status: str
    service: str = "connection_hub"


class ConnectionListResponse(BaseModel):
    connections: list[dict]
    total: int


# ── SQL Database ──────────────────────────────────────────────────────────────

class CreateSQLConnectionRequest(BaseModel):
    """创建 SQL 数据库连接请求"""
    name: str = Field(..., min_length=1, max_length=128, description="连接名称")
    db_type: str = Field(..., description="数据库类型: mysql/postgresql/starrocks/sqlserver/hive/doris")
    host: str = Field(..., min_length=1, max_length=256, description="主机地址")
    port: int = Field(..., ge=1, le=65535, description="端口")
    database_name: str = Field(..., min_length=1, max_length=128, description="数据库名")
    username: str = Field(..., min_length=1, max_length=128, description="用户名")
    password: str = Field(..., min_length=1, description="密码")
    extra_config: Optional[dict] = None


class UpdateSQLConnectionRequest(BaseModel):
    """更新 SQL 数据库连接请求"""
    name: Optional[str] = Field(None, min_length=1, max_length=128)
    db_type: Optional[str] = None
    host: Optional[str] = Field(None, min_length=1, max_length=256)
    port: Optional[int] = Field(None, ge=1, le=65535)
    database_name: Optional[str] = Field(None, min_length=1, max_length=128)
    username: Optional[str] = Field(None, min_length=1, max_length=128)
    password: Optional[str] = None
    extra_config: Optional[dict] = None
    is_active: Optional[bool] = None


# ── Tableau ────────────────────────────────────────────────────────────────────

class CreateTableauConnectionRequest(BaseModel):
    """创建 Tableau 连接请求"""
    name: str = Field(..., min_length=1, max_length=128, description="连接名称")
    server_url: str = Field(..., min_length=1, max_length=512, description="Tableau Server URL")
    site: str = Field(..., min_length=1, max_length=128, description="Tableau Site")
    token_name: str = Field(..., min_length=1, max_length=256, description="Personal Access Token Name")
    token_secret: str = Field(..., min_length=1, description="Personal Access Token Secret")
    api_version: str = Field(default="3.21", max_length=16)
    connection_type: str = Field(default="mcp", max_length=16)
    mcp_server_url: Optional[str] = Field(None, max_length=512)


class UpdateTableauConnectionRequest(BaseModel):
    """更新 Tableau 连接请求"""
    name: Optional[str] = Field(None, min_length=1, max_length=128)
    server_url: Optional[str] = Field(None, min_length=1, max_length=512)
    site: Optional[str] = Field(None, min_length=1, max_length=128)
    token_name: Optional[str] = Field(None, min_length=1, max_length=256)
    token_secret: Optional[str] = None
    api_version: Optional[str] = Field(None, max_length=16)
    is_active: Optional[bool] = None
    mcp_server_url: Optional[str] = Field(None, max_length=512)


# ── LLM Provider ──────────────────────────────────────────────────────────────

class CreateLLMConnectionRequest(BaseModel):
    """创建 LLM Provider 连接请求"""
    provider: str = Field(default="openai", max_length=32)
    base_url: str = Field(..., min_length=1, max_length=512)
    api_key: str = Field(..., min_length=1, description="API Key")
    model: str = Field(default="gpt-4o-mini", max_length=128)
    temperature: float = Field(default=0.7, ge=0.0, le=2.0)
    max_tokens: int = Field(default=1024, ge=1)
    is_active: bool = Field(default=False)
    purpose: str = Field(default="default", max_length=50)
    display_name: Optional[str] = Field(None, max_length=100)
    priority: int = Field(default=0)


class UpdateLLMConnectionRequest(BaseModel):
    """更新 LLM Provider 连接请求"""
    provider: Optional[str] = Field(None, max_length=32)
    base_url: Optional[str] = Field(None, min_length=1, max_length=512)
    api_key: Optional[str] = None
    model: Optional[str] = Field(None, max_length=128)
    temperature: Optional[float] = Field(None, ge=0.0, le=2.0)
    max_tokens: Optional[int] = Field(None, ge=1)
    is_active: Optional[bool] = None
    purpose: Optional[str] = Field(None, max_length=50)
    display_name: Optional[str] = Field(None, max_length=100)
    priority: Optional[int] = None


# ── Generic ───────────────────────────────────────────────────────────────────

class TestConnectionResponse(BaseModel):
    """测试连接响应"""
    success: bool
    message: str
    connection_id: str


class DeleteConnectionResponse(BaseModel):
    """删除连接响应"""
    success: bool
    message: str


# ─────────────────────────────────────────────────────────────────────────────
# Health Check
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/health")
async def connection_hub_health():
    """Connection Hub 健康检查"""
    return HealthResponse(status="ok", service="connection_hub")


# ─────────────────────────────────────────────────────────────────────────────
# Connection CRUD Operations
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/connections", response_model=ConnectionListResponse)
async def list_connections(request: Request, db: Session = Depends(get_db)):
    """统一连接列表（Spec 24 P0: 读模型聚合）

    聚合 tableau_connections + bi_data_sources + ai_llm_configs
    """
    get_current_user(request, db)
    connections = get_unified_connections(db)
    return ConnectionListResponse(
        connections=[c.to_dict() for c in connections],
        total=len(connections),
    )


@router.post("/connections", response_model=dict)
async def create_connection(
    request: Request,
    connection_type: str = Field(..., description="连接类型: sql_database/tableau_site/llm_provider"),
    db: Session = Depends(get_db),
):
    """创建新连接（所有连接类型）

    POST /api/connection-hub/connections?connection_type=sql_database
    POST /api/connection-hub/connections?connection_type=tableau_site
    POST /api/connection-hub/connections?connection_type=llm_provider
    """
    current_user = get_current_user(request, db)
    if current_user.get("role") not in ["admin", "data_admin"]:
        raise HTTPException(status_code=403, detail="需要 admin 或 data_admin 权限")

    manager = ConnectionManager(db)

    if connection_type == "sql_database":
        body = await request.json()
        req = CreateSQLConnectionRequest(**body)

        ds = manager.create_sql_connection(
            name=req.name,
            db_type=req.db_type,
            host=req.host,
            port=req.port,
            database_name=req.database_name,
            username=req.username,
            password=req.password,
            owner_id=current_user["id"],
            extra_config=req.extra_config,
        )

        return {
            "connection": {
                "id": f"sql-{ds.id}",
                "type": "sql_database",
                "name": ds.name,
                "health_status": "unknown",
                "is_active": ds.is_active,
                "meta": {
                    "db_type": ds.db_type,
                    "host": ds.host,
                    "port": ds.port,
                    "database_name": ds.database_name,
                },
            },
            "message": "SQL 数据库连接创建成功",
        }

    elif connection_type == "tableau_site":
        body = await request.json()
        req = CreateTableauConnectionRequest(**body)

        conn = manager.create_tableau_connection(
            name=req.name,
            server_url=req.server_url,
            site=req.site,
            token_name=req.token_name,
            token_secret=req.token_secret,
            owner_id=current_user["id"],
            api_version=req.api_version,
            connection_type=req.connection_type,
            mcp_server_url=req.mcp_server_url,
        )

        return {
            "connection": {
                "id": f"tableau-{conn.id}",
                "type": "tableau_site",
                "name": conn.name,
                "health_status": "unknown",
                "is_active": conn.is_active,
                "meta": {
                    "server_url": conn.server_url,
                    "site": conn.site,
                },
            },
            "message": "Tableau 连接创建成功",
        }

    elif connection_type == "llm_provider":
        body = await request.json()
        req = CreateLLMConnectionRequest(**body)

        config = manager.create_llm_connection(
            provider=req.provider,
            base_url=req.base_url,
            api_key=req.api_key,
            model=req.model,
            owner_id=current_user["id"],
            temperature=req.temperature,
            max_tokens=req.max_tokens,
            is_active=req.is_active,
            purpose=req.purpose,
            display_name=req.display_name,
            priority=req.priority,
        )

        return {
            "connection": {
                "id": f"llm-{config.id}",
                "type": "llm_provider",
                "name": config.display_name or f"{config.provider}/{config.model}",
                "health_status": "unknown",
                "is_active": config.is_active,
                "meta": {
                    "provider": config.provider,
                    "model": config.model,
                    "purpose": config.purpose,
                },
            },
            "message": "LLM Provider 连接创建成功",
        }

    else:
        raise HTTPException(status_code=400, detail=f"不支持的连接类型: {connection_type}")


@router.put("/connections/{connection_id}", response_model=dict)
async def update_connection(
    connection_id: str,
    request: Request,
    db: Session = Depends(get_db),
):
    """更新连接

    PUT /api/connection-hub/connections/sql-{id}
    PUT /api/connection-hub/connections/tableau-{id}
    PUT /api/connection-hub/connections/llm-{id}
    """
    current_user = get_current_user(request, db)
    if current_user.get("role") not in ["admin", "data_admin"]:
        raise HTTPException(status_code=403, detail="需要 admin 或 data_admin 权限")

    manager = ConnectionManager(db)

    try:
        conn_type, conn_id = manager.parse_connection_id(connection_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    if conn_type == ConnectionType.SQL_DATABASE:
        body = await request.json()
        req = UpdateSQLConnectionRequest(**body)

        success = manager.update_sql_connection(
            connection_id=conn_id,
            name=req.name,
            db_type=req.db_type,
            host=req.host,
            port=req.port,
            database_name=req.database_name,
            username=req.username,
            password=req.password,
            extra_config=req.extra_config,
            is_active=req.is_active,
        )

        if not success:
            raise HTTPException(status_code=404, detail="连接不存在")

        return {"message": "SQL 数据库连接更新成功"}

    elif conn_type == ConnectionType.TABLEAU_SITE:
        body = await request.json()
        req = UpdateTableauConnectionRequest(**body)

        success = manager.update_tableau_connection(
            connection_id=conn_id,
            name=req.name,
            server_url=req.server_url,
            site=req.site,
            token_name=req.token_name,
            token_secret=req.token_secret,
            api_version=req.api_version,
            is_active=req.is_active,
            mcp_server_url=req.mcp_server_url,
        )

        if not success:
            raise HTTPException(status_code=404, detail="连接不存在")

        return {"message": "Tableau 连接更新成功"}

    elif conn_type == ConnectionType.LLM_PROVIDER:
        body = await request.json()
        req = UpdateLLMConnectionRequest(**body)

        success = manager.update_llm_connection(
            connection_id=conn_id,
            provider=req.provider,
            base_url=req.base_url,
            api_key=req.api_key,
            model=req.model,
            temperature=req.temperature,
            max_tokens=req.max_tokens,
            is_active=req.is_active,
            purpose=req.purpose,
            display_name=req.display_name,
            priority=req.priority,
        )

        if not success:
            raise HTTPException(status_code=404, detail="连接不存在")

        return {"message": "LLM Provider 连接更新成功"}

    else:
        raise HTTPException(status_code=400, detail=f"不支持的连接类型: {conn_type}")


@router.delete("/connections/{connection_id}", response_model=DeleteConnectionResponse)
async def delete_connection(
    connection_id: str,
    request: Request,
    db: Session = Depends(get_db),
):
    """删除连接（软删除）"""
    current_user = get_current_user(request, db)
    if current_user.get("role") not in ["admin", "data_admin"]:
        raise HTTPException(status_code=403, detail="需要 admin 或 data_admin 权限")

    manager = ConnectionManager(db)
    success, error = manager.delete_connection(connection_id)

    if not success:
        raise HTTPException(status_code=404, detail=error or "连接不存在")

    return DeleteConnectionResponse(success=True, message="连接已删除")


@router.post("/connections/{connection_id}/test", response_model=TestConnectionResponse)
async def test_connection(
    connection_id: str,
    request: Request,
    db: Session = Depends(get_db),
):
    """测试连接

    POST /api/connection-hub/connections/sql-{id}/test
    POST /api/connection-hub/connections/tableau-{id}/test
    POST /api/connection-hub/connections/llm-{id}/test
    """
    current_user = get_current_user(request, db)
    if current_user.get("role") not in ["admin", "data_admin"]:
        raise HTTPException(status_code=403, detail="需要 admin 或 data_admin 权限")

    manager = ConnectionManager(db)
    success, error = await manager.test_connection(connection_id)

    return TestConnectionResponse(
        success=success,
        message=error if error else ("连接成功" if success else "连接失败"),
        connection_id=connection_id,
    )


# ─────────────────────────────────────────────────────────────────────────────
# Connection Pool Management
# ─────────────────────────────────────────────────────────────────────────────

@router.post("/connections/{connection_id}/rotate-secret", response_model=dict)
async def rotate_secret(
    connection_id: str,
    request: Request,
    db: Session = Depends(get_db),
):
    """轮转连接凭据（目前仅支持 LLM Provider）"""
    current_user = get_current_user(request, db)
    if current_user.get("role") not in ["admin", "data_admin"]:
        raise HTTPException(status_code=403, detail="需要 admin 或 data_admin 权限")

    manager = ConnectionManager(db)

    try:
        conn_type, conn_id = manager.parse_connection_id(connection_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    if conn_type != ConnectionType.LLM_PROVIDER:
        raise HTTPException(status_code=400, detail="目前仅支持 LLM Provider 的凭据轮转")

    body = await request.json()
    new_api_key = body.get("api_key")
    if not new_api_key:
        raise HTTPException(status_code=400, detail="需要提供新的 api_key")

    success = manager.update_llm_connection(
        connection_id=conn_id,
        api_key=new_api_key,
    )

    if not success:
        raise HTTPException(status_code=404, detail="连接不存在")

    return {"message": "LLM Provider 凭据已更新"}


def get_current_user(request: Request, db: Session = Depends(get_db)) -> dict:
    """获取当前用户"""
    from app.core.dependencies import get_current_user as _get_current_user
    return _get_current_user(request, db)

"""SQL Agent — FastAPI 薄路由层"""

from typing import Optional

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field

from app.core.dependencies import get_current_user, require_roles
from app.core.errors import AuthError
from services.auth.service import AuthService
from app.core.database import get_db
from app.core.errors import MulanError

from services.sql_agent import SQLAgentService

router = APIRouter(prefix="/api/sql-agent", tags=["SQL Agent"])


# =============================================================================
# 请求/响应 Schema
# =============================================================================

class QueryRequest(BaseModel):
    datasource_id: int = Field(..., description="目标数据源 ID")
    sql: str = Field(..., description="SQL 语句")
    timeout_seconds: Optional[int] = Field(None, description="超时秒数（默认按 db_type 设定）")


class QueryResponse(BaseModel):
    log_id: int
    sql_hash: str
    action_type: str
    row_count: int
    duration_ms: int
    limit_applied: Optional[int]
    data: list
    columns: list[str]
    truncated: bool
    truncated_reason: Optional[str]
    warning: Optional[str]

    class Config:
        from_attributes = True


class QueryLogResponse(BaseModel):
    id: int
    datasource_id: int
    db_type: str
    sql_text: str
    sql_hash: str
    action_type: str
    rejected_reason: Optional[str]
    row_count: Optional[int]
    duration_ms: int
    limit_applied: Optional[int]
    user_id: int
    created_at: str


class TableColumnSchema(BaseModel):
    name: str
    type: str
    nullable: Optional[str] = None


class TableSchema(BaseModel):
    schema: str
    name: str
    row_count_estimate: int
    columns: list[TableColumnSchema]


class PreviewResponse(BaseModel):
    datasource_id: int
    db_type: str
    tables: list[TableSchema]


class HealthResponse(BaseModel):
    status: str = "ok"
    service: str = "sql_agent"


# =============================================================================
# 端点实现
# =============================================================================

@router.post("/query", response_model=QueryResponse)
def execute_query(
    req: QueryRequest,
    current_user: dict = Depends(require_roles(["analyst", "data_admin", "admin"])),
    db=Depends(get_db),
):
    """
    执行 SQL 查询。
    - 自动安全校验（危险语句拦截、连表/子查询限制）
    - 自动 LIMIT 注入（防爆内存）
    - 返回查询结果 + log_id
    """
    # 细粒度权限检查：需要 database_monitor 权限
    auth_svc = AuthService()
    if not auth_svc.has_permission(current_user["id"], "database_monitor"):
        raise AuthError.insufficient_permissions()

    svc = SQLAgentService(db)
    try:
        result = svc.execute_query(
            datasource_id=req.datasource_id,
            sql=req.sql,
            user_id=current_user["id"],
            timeout_seconds=req.timeout_seconds,
        )
        return result
    except MulanError:
        raise
    except Exception as e:
        raise MulanError("SYS_001", f"SQL Agent 执行异常: {str(e)}", 500)


@router.get("/query/{log_id}", response_model=QueryLogResponse)
def get_query_log(
    log_id: int,
    current_user: dict = Depends(require_roles(["analyst", "data_admin", "admin"])),
    db=Depends(get_db),
):
    """
    查询历史执行记录（不含结果数据）。
    """
    svc = SQLAgentService(db)
    result = svc.get_query_log(log_id, current_user["id"])
    return result


@router.get("/datasource/{datasource_id}/preview", response_model=PreviewResponse)
def preview_datasource(
    datasource_id: int,
    current_user: dict = Depends(require_roles(["analyst", "data_admin", "admin"])),
    db=Depends(get_db),
):
    """
    预览数据源表结构（schema + 列信息）。
    """
    svc = SQLAgentService(db)
    result = svc.preview_datasource(datasource_id, current_user["id"])
    return result


@router.get("/health", response_model=HealthResponse)
def health_check():
    """
    服务健康检查（无需认证）。
    """
    return HealthResponse(status="ok", service="sql_agent")

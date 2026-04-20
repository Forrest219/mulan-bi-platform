"""Connection Hub API（Spec 24 P0 占位 → P2 实现读模型）"""
from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.dependencies import get_current_user
from services.connection_hub import get_unified_connections, UnifiedConnection

router = APIRouter()


class HealthResponse(BaseModel):
    status: str
    service: str = "connection_hub"


class ConnectionListResponse(BaseModel):
    connections: list[dict]
    total: int


@router.get("/health")
async def connection_hub_health():
    """Connection Hub 健康检查"""
    return HealthResponse(status="ok", service="connection_hub")


@router.get("/connections", response_model=ConnectionListResponse)
async def list_connections(
    request: Request,
    db: Session = Depends(get_db),
):
    """统一连接列表（Spec 24 P0: 读模型聚合）

    聚合 tableau_connections + bi_data_sources + ai_llm_configs
    """
    get_current_user(request)
    connections = get_unified_connections(db)
    return ConnectionListResponse(
        connections=[c.to_dict() for c in connections],
        total=len(connections),
    )

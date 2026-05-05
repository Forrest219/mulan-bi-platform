"""Metrics Agent — Maintenance Window API

Spec 30 §4.2.1：admin配置 [start, end] 时间区间，检测器在此区间跳过检测，
不写 anomaly，不发事件。

API 路由前缀：/api/metrics/maintenance-windows
"""
import math
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Body, Depends, HTTPException, Query, status
from pydantic import BaseModel

from app.core.database import get_db
from app.core.dependencies import require_roles
from services.metrics_agent.maintenance_window_service import MaintenanceWindowService

router = APIRouter()


# =============================================================================
# Schema 定义
# =============================================================================

class MaintenanceWindowCreate(BaseModel):
    name: str
    start_at: datetime
    end_at: datetime
    timezone: str = "Asia/Shanghai"
    reason: Optional[str] = None


class MaintenanceWindowUpdate(BaseModel):
    name: Optional[str] = None
    start_at: Optional[datetime] = None
    end_at: Optional[datetime] = None
    timezone: Optional[str] = None
    reason: Optional[str] = None
    is_active: Optional[bool] = None


class MaintenanceWindowResponse(BaseModel):
    id: int
    name: str
    start_at: datetime
    end_at: datetime
    timezone: str
    reason: Optional[str]
    created_by: Optional[int]
    is_active: bool
    created_at: datetime
    updated_at: datetime


class PaginatedMaintenanceWindows(BaseModel):
    items: list[MaintenanceWindowResponse]
    total: int
    page: int
    page_size: int
    pages: int


class ActiveWindowResponse(BaseModel):
    has_active_window: bool
    window: Optional[MaintenanceWindowResponse] = None


# =============================================================================
# 辅助函数
# =============================================================================

def _window_to_response(window) -> MaintenanceWindowResponse:
    return MaintenanceWindowResponse(
        id=window.id,
        name=window.name,
        start_at=window.start_at,
        end_at=window.end_at,
        timezone=window.timezone or "Asia/Shanghai",
        reason=window.reason,
        created_by=window.created_by,
        is_active=window.is_active,
        created_at=window.created_at,
        updated_at=window.updated_at,
    )


# =============================================================================
# API 路由
# =============================================================================

@router.get(
    "",
    response_model=PaginatedMaintenanceWindows,
    summary="维护窗口列表",
)
def list_maintenance_windows(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=200),
    is_active: Optional[bool] = Query(default=None),
    current_user: dict = Depends(require_roles(["data_admin", "admin"])),
    db=Depends(get_db),
):
    """
    查询维护窗口列表，支持分页和状态过滤（data_admin+）
    """
    service = MaintenanceWindowService()
    items, total = service.list_windows(db, page=page, page_size=page_size, is_active=is_active)
    return PaginatedMaintenanceWindows(
        items=[_window_to_response(w) for w in items],
        total=total,
        page=page,
        page_size=page_size,
        pages=math.ceil(total / page_size) if page_size else 0,
    )


@router.get(
    "/active",
    response_model=ActiveWindowResponse,
    summary="当前活跃窗口",
)
def get_active_window(
    current_user: dict = Depends(require_roles(["analyst", "data_admin", "admin"])),
    db=Depends(get_db),
):
    """
    获取当前处于活跃状态的维护窗口（用于指标详情页提示）
    """
    service = MaintenanceWindowService()
    window = service.get_active_window(db)
    return ActiveWindowResponse(
        has_active_window=window is not None,
        window=_window_to_response(window) if window else None,
    )


@router.post(
    "",
    response_model=MaintenanceWindowResponse,
    status_code=status.HTTP_201_CREATED,
    summary="创建维护窗口",
)
def create_maintenance_window(
    data: MaintenanceWindowCreate,
    current_user: dict = Depends(require_roles(["data_admin", "admin"])),
    db=Depends(get_db),
):
    """
    创建新的维护窗口（data_admin+）

    - start_at ~ end_at 定义检测器跳过的静默期
    - 时区默认 Asia/Shanghai
    """
    service = MaintenanceWindowService()
    try:
        window = service.create_window(
            db=db,
            name=data.name,
            start_at=data.start_at,
            end_at=data.end_at,
            timezone=data.timezone,
            reason=data.reason,
            created_by=current_user.get("id"),
        )
        return _window_to_response(window)
    except ValueError as e:
        raise HTTPException(status_code=400, detail={"error_code": "MC_400", "message": str(e)})


@router.get(
    "/{window_id}",
    response_model=MaintenanceWindowResponse,
    summary="维护窗口详情",
)
def get_maintenance_window(
    window_id: int,
    current_user: dict = Depends(require_roles(["data_admin", "admin"])),
    db=Depends(get_db),
):
    """
    获取指定维护窗口详情（data_admin+）
    """
    service = MaintenanceWindowService()
    items, _ = service.list_windows(db, page=1, page_size=1)
    # 直接查单条
    from models.metrics_maintenance_window import BiMaintenanceWindow
    window = db.query(BiMaintenanceWindow).filter(BiMaintenanceWindow.id == window_id).first()
    if not window:
        raise HTTPException(status_code=404, detail={"error_code": "MC_404", "message": f"维护窗口不存在：id={window_id}"})
    return _window_to_response(window)


@router.put(
    "/{window_id}",
    response_model=MaintenanceWindowResponse,
    summary="更新维护窗口",
)
def update_maintenance_window(
    window_id: int,
    data: MaintenanceWindowUpdate,
    current_user: dict = Depends(require_roles(["data_admin", "admin"])),
    db=Depends(get_db),
):
    """
    更新维护窗口（data_admin+）
    """
    service = MaintenanceWindowService()
    try:
        window = service.update_window(
            db=db,
            window_id=window_id,
            name=data.name,
            start_at=data.start_at,
            end_at=data.end_at,
            timezone=data.timezone,
            reason=data.reason,
            is_active=data.is_active,
        )
        return _window_to_response(window)
    except ValueError as e:
        raise HTTPException(status_code=400, detail={"error_code": "MC_400", "message": str(e)})


@router.delete(
    "/{window_id}",
    status_code=status.HTTP_200_OK,
    summary="删除维护窗口",
)
def delete_maintenance_window(
    window_id: int,
    current_user: dict = Depends(require_roles(["admin"])),
    db=Depends(get_db),
):
    """
    删除维护窗口（admin）
    """
    service = MaintenanceWindowService()
    try:
        service.delete_window(db, window_id=window_id)
        return {"message": "删除成功"}
    except ValueError as e:
        raise HTTPException(status_code=404, detail={"error_code": "MC_404", "message": str(e)})

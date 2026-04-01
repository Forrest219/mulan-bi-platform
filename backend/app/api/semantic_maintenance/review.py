"""
语义维护 - 数据源审核 API
"""
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, HTTPException, Request, Query
from pydantic import BaseModel

sys_path = str(Path(__file__).parent.parent.parent.parent.parent / "src")
import sys
sys.path.insert(0, sys_path)

from semantic_maintenance.service import SemanticMaintenanceService
from app.core.dependencies import get_current_user

router = APIRouter()


def _db_path():
    return str(Path(__file__).parent.parent.parent.parent.parent / "data" / "semantic_maintenance.db")


def _sm_service():
    return SemanticMaintenanceService(db_path=_db_path())


def _verify_connection_access(connection_id: int, user: dict) -> None:
    """验证用户有权访问指定连接"""
    import sqlite3
    from ..tableau import _db_path as tableau_db_path
    conn = sqlite3.connect(tableau_db_path())
    cursor = conn.cursor()
    cursor.execute("SELECT owner_id FROM tableau_connections WHERE id = ?", (connection_id,))
    row = cursor.fetchone()
    conn.close()
    if not row:
        raise HTTPException(status_code=404, detail="连接不存在")
    if user["role"] != "admin" and row[0] != user["id"]:
        raise HTTPException(status_code=403, detail="无权访问该连接")


# --- DataSource Review Endpoints ---

@router.post("/datasources/{ds_id}/submit-review")
async def submit_datasource_for_review(ds_id: int, request: Request):
    """提交数据源语义审核"""
    user = get_current_user(request)
    sm = _sm_service()
    ds = sm.db.get_datasource_semantics_by_id(ds_id)
    if not ds:
        raise HTTPException(status_code=404, detail="记录不存在")
    _verify_connection_access(ds.connection_id, user)

    success, err = sm.submit_datasource_for_review(ds_id, user_id=user["id"])
    if not success:
        raise HTTPException(status_code=400, detail=err)
    updated = sm.db.get_datasource_semantics_by_id(ds_id)
    return {"item": updated.to_dict(), "message": "已提交审核"}


@router.post("/datasources/{ds_id}/approve")
async def approve_datasource(ds_id: int, request: Request):
    """审核通过数据源语义"""
    user = get_current_user(request)
    if user["role"] not in ("admin", "reviewer"):
        raise HTTPException(status_code=403, detail="需要 reviewer 或 admin 权限")
    sm = _sm_service()
    ds = sm.db.get_datasource_semantics_by_id(ds_id)
    if not ds:
        raise HTTPException(status_code=404, detail="记录不存在")
    _verify_connection_access(ds.connection_id, user)

    success, err = sm.approve_datasource(ds_id, user_id=user["id"])
    if not success:
        raise HTTPException(status_code=400, detail=err)
    updated = sm.db.get_datasource_semantics_by_id(ds_id)
    return {"item": updated.to_dict(), "message": "审核通过"}


@router.post("/datasources/{ds_id}/reject")
async def reject_datasource(ds_id: int, request: Request):
    """驳回数据源语义"""
    user = get_current_user(request)
    if user["role"] not in ("admin", "reviewer"):
        raise HTTPException(status_code=403, detail="需要 reviewer 或 admin 权限")
    sm = _sm_service()
    ds = sm.db.get_datasource_semantics_by_id(ds_id)
    if not ds:
        raise HTTPException(status_code=404, detail="记录不存在")
    _verify_connection_access(ds.connection_id, user)

    success, err = sm.reject_datasource(ds_id, user_id=user["id"])
    if not success:
        raise HTTPException(status_code=400, detail=err)
    updated = sm.db.get_datasource_semantics_by_id(ds_id)
    return {"item": updated.to_dict(), "message": "已驳回"}


# --- Publish Log Endpoints ---

@router.get("/publish/logs")
async def list_publish_logs(
    request: Request,
    connection_id: int = Query(..., description="Tableau 连接 ID"),
    object_type: Optional[str] = Query(None, description="datasource / field"),
    status: Optional[str] = Query(None, description="pending / success / failed"),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=100),
):
    """获取发布日志列表"""
    user = get_current_user(request)
    _verify_connection_access(connection_id, user)

    sm = _sm_service()
    items, total = sm.list_publish_logs(
        connection_id=connection_id,
        object_type=object_type,
        status=status,
        page=page,
        page_size=page_size,
    )
    return {
        "items": items,
        "total": total,
        "page": page,
        "page_size": page_size,
    }

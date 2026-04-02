"""
日志 API
"""
from fastapi import APIRouter, Request
from typing import Optional

from services.logs import logger
from app.core.dependencies import get_current_user

router = APIRouter()


@router.get("/scan")
async def get_scan_logs(request: Request, limit: int = 100, database_name: Optional[str] = None):
    """获取扫描日志"""
    get_current_user(request)
    limit = min(limit, 1000)
    logs = logger.get_scan_history(limit=limit, database_name=database_name)
    return {"logs": logs, "total": len(logs)}


@router.get("/statistics")
async def get_statistics(request: Request):
    """获取统计数据"""
    get_current_user(request)
    stats = logger.get_statistics()
    return stats


@router.get("/operations")
async def get_operation_logs(request: Request, limit: int = 100, operation_type: Optional[str] = None):
    """获取操作日志"""
    get_current_user(request)
    limit = min(limit, 1000)
    logs = logger.get_operation_history(limit=limit, operation_type=operation_type)
    return {"logs": logs, "total": len(logs)}

"""
日志 API
"""
from pydantic import BaseModel
from fastapi import APIRouter
from typing import Optional, List
from datetime import datetime

# 导入日志模块
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent / "src"))

from logs import logger

router = APIRouter()


class ScanLog(BaseModel):
    """扫描日志"""
    id: int
    scan_time: str
    database_name: str
    db_type: str
    table_count: int
    total_violations: int
    error_count: int
    warning_count: int
    info_count: int
    duration_seconds: str
    status: str


@router.get("/scan")
async def get_scan_logs(limit: int = 100, database_name: Optional[str] = None):
    """获取扫描日志"""
    logs = logger.get_scan_history(limit=limit, database_name=database_name)
    return {"logs": logs, "total": len(logs)}


@router.get("/statistics")
async def get_statistics():
    """获取统计数据"""
    stats = logger.get_statistics()
    return stats


@router.get("/operations")
async def get_operation_logs(limit: int = 100, operation_type: Optional[str] = None):
    """获取操作日志"""
    logs = logger.get_operation_history(limit=limit, operation_type=operation_type)
    return {"logs": logs, "total": len(logs)}

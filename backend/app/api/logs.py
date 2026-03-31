"""
日志 API
"""
from pydantic import BaseModel
from fastapi import APIRouter, HTTPException, Request
from typing import Optional, List
from datetime import datetime
import os
import jwt

# 导入日志模块
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent / "src"))

from logs import logger

router = APIRouter()

# JWT 验签
_JWT_SECRET = os.environ.get("SESSION_SECRET")
_JWT_ALGORITHM = "HS256"


def _decode_session_token(token: str):
    """验证并解码 session token"""
    try:
        payload = jwt.decode(token, _JWT_SECRET, algorithms=[_JWT_ALGORITHM])
        return {"id": int(payload["sub"]), "username": payload["username"], "role": payload["role"]}
    except jwt.InvalidTokenError:
        return None


def get_current_user(request: Request) -> dict:
    """获取当前登录用户"""
    token = request.cookies.get("session")
    if not token:
        raise HTTPException(status_code=401, detail="未登录")
    user_info = _decode_session_token(token)
    if not user_info:
        raise HTTPException(status_code=401, detail="无效的会话")
    return user_info


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
async def get_scan_logs(request: Request, limit: int = 100, database_name: Optional[str] = None):
    """获取扫描日志"""
    get_current_user(request)
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
    logs = logger.get_operation_history(limit=limit, operation_type=operation_type)
    return {"logs": logs, "total": len(logs)}

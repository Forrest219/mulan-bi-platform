"""事件 API（管理员专用）"""
from typing import Optional

from fastapi import APIRouter, HTTPException, Request, Depends, Query
from sqlalchemy.orm import Session

from app.core.dependencies import get_current_user
from app.core.database import get_db
from services.events.models import EventDatabase
from services.events import EvtErrorCode, EVT_ERROR_MESSAGES

router = APIRouter()


@router.get("")
async def list_events(
    request: Request,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    event_type: Optional[str] = None,
    source_module: Optional[str] = None,
    severity: Optional[str] = None,
    start_time: Optional[str] = None,
    end_time: Optional[str] = None,
    db: Session = Depends(get_db),
):
    """
    获取事件列表（仅管理员，PRD §6.5）
    GET /api/events
    """
    user = get_current_user(request, db)

    # 权限校验：仅 admin 可访问（EVT_006）
    if user["role"] != "admin":
        raise HTTPException(
            status_code=403,
            detail={
                "error_code": EvtErrorCode.ADMIN_REQUIRED,
                "message": EVT_ERROR_MESSAGES[EvtErrorCode.ADMIN_REQUIRED]
            }
        )

    event_db = EventDatabase()

    # 解析时间参数
    from datetime import datetime
    start_dt = None
    end_dt = None
    if start_time:
        try:
            start_dt = datetime.fromisoformat(start_time.replace("Z", "+00:00"))
        except ValueError:
            raise HTTPException(
                status_code=400,
                detail={"error_code": "EVT_999", "message": "start_time 格式错误，请使用 ISO 8601 格式"}
            )
    if end_time:
        try:
            end_dt = datetime.fromisoformat(end_time.replace("Z", "+00:00"))
        except ValueError:
            raise HTTPException(
                status_code=400,
                detail={"error_code": "EVT_999", "message": "end_time 格式错误，请使用 ISO 8601 格式"}
            )

    result = event_db.list_events(
        db=db,
        page=page,
        page_size=page_size,
        event_type=event_type,
        source_module=source_module,
        severity=severity,
        start_time=start_dt,
        end_time=end_dt,
    )
    return result

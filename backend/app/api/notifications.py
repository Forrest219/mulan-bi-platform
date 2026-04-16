"""通知 API"""
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.dependencies import get_current_user
from services.events import EVT_ERROR_MESSAGES, EvtErrorCode
from services.events.models import EventDatabase

router = APIRouter()


class BatchReadRequest(BaseModel):
    """批量标记已读请求模型"""

    ids: Optional[list[int]] = None
    all: Optional[bool] = None


def _error_response(code: str, status_code: int, detail: str = None):
    """构造带错误码的标准错误响应"""
    message = detail or EVT_ERROR_MESSAGES.get(code, "未知错误")
    return HTTPException(
        status_code=status_code,
        detail={"error_code": code, "message": message}
    )


@router.get("")
async def list_notifications(
    request: Request,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    is_read: Optional[bool] = None,
    level: Optional[str] = None,
    db: Session = Depends(get_db),
):
    """获取当前用户的通知列表（PRD §6.1）
    GET /api/notifications
    """
    user = get_current_user(request, db)
    event_db = EventDatabase()
    result = event_db.list_notifications(
        db=db,
        user_id=user["id"],
        page=page,
        page_size=page_size,
        is_read=is_read,
        level=level,
    )
    return result


@router.put("/{notification_id}/read")
async def mark_notification_read(
    notification_id: int,
    request: Request,
    db: Session = Depends(get_db),
):
    """标记通知已读（PRD §6.2）
    PUT /api/notifications/{id}/read
    """
    user = get_current_user(request, db)
    event_db = EventDatabase()

    notification = event_db.get_notification(db, notification_id)
    if not notification:
        raise _error_response(EvtErrorCode.NOTIFICATION_NOT_FOUND, 404)

    if notification.user_id != user["id"]:
        raise _error_response(EvtErrorCode.NOT_OWNER, 403)

    updated = event_db.mark_read(db, notification_id)
    return {
        "id": updated.id,
        "is_read": updated.is_read,
        "read_at": updated.read_at.strftime("%Y-%m-%dT%H:%M:%SZ") if updated.read_at else None,
    }


@router.put("/batch-read")
async def batch_mark_read(
    body: BatchReadRequest,
    request: Request,
    db: Session = Depends(get_db),
):
    """批量标记通知已读（PRD §6.3）
    PUT /api/notifications/batch-read
    """
    user = get_current_user(request, db)
    event_db = EventDatabase()

    if body.all:
        updated_count = event_db.mark_all_read(db, user["id"])
    elif body.ids:
        updated_count = event_db.mark_batch_read(db, body.ids, user["id"])
    else:
        raise HTTPException(
            status_code=400,
            detail={"error_code": "EVT_999", "message": "请提供 ids 列表或 all=true"}
        )

    return {"updated_count": updated_count}


@router.get("/unread-count")
async def get_unread_count(
    request: Request,
    db: Session = Depends(get_db),
):
    """获取未读通知数量（PRD §6.4）
    GET /api/notifications/unread-count
    """
    user = get_current_user(request, db)
    event_db = EventDatabase()
    count = event_db.get_unread_count(db, user["id"])
    return {"unread_count": count}

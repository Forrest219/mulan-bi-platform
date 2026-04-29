"""事件 API（管理员专用）"""
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.dependencies import get_current_user
from services.events import (
    EVT_ERROR_MESSAGES,
    EvtErrorCode,
)
from services.events.constants import ANOMALY_DETECTED
from services.events.models import EventDatabase

router = APIRouter()


class AnomalySubscriptionCreate(BaseModel):
    """POST /api/events/anomaly-subscriptions 请求体"""
    metric_id: str
    event_type: str = "anomaly.detected"


class AnomalySubscriptionDelete(BaseModel):
    """DELETE /api/events/anomaly-subscriptions 请求体"""
    subscription_id: int


class SubscriptionCreate(BaseModel):
    """POST /api/events/subscriptions 请求体（支持按事件类型订阅）"""
    event_type: str
    target_id: Optional[str] = None  # 如 semantic_table_id


class SubscriptionResponse(BaseModel):
    """订阅响应"""
    subscription_id: int
    event_type: str
    target_id: Optional[str] = None
    is_active: bool = True


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
    """获取事件列表（仅管理员，PRD §6.5）
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


# =============================================================================
# 异常告警订阅管理（Spec 30）
# =============================================================================

@router.get(
    "/anomaly-subscriptions",
    summary="查询当前用户的异常告警订阅列表",
)
def list_anomaly_subscriptions(
    request: Request,
    event_type: Optional[str] = Query(default=None, description="事件类型过滤"),
    target_id: Optional[str] = Query(default=None, description="指标 ID 过滤"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
):
    """GET /api/events/anomaly-subscriptions — 查询当前用户的订阅列表"""
    user = get_current_user(request, db)
    event_db = EventDatabase()

    # 仅允许查询自己的订阅
    result = event_db.list_subscriptions(
        db=db,
        user_id=user["id"],
        event_type=event_type,
        target_id=target_id,
        page=page,
        page_size=page_size,
    )
    return result


@router.post(
    "/anomaly-subscriptions",
    status_code=201,
    summary="订阅特定指标的异常告警通知",
)
def subscribe_anomaly(
    request: Request,
    body: AnomalySubscriptionCreate,
    db: Session = Depends(get_db),
):
    """POST /api/events/anomaly-subscriptions — 订阅指定指标的异常告警（analyst+）"""
    user = get_current_user(request, db)
    event_db = EventDatabase()

    # 仅允许 anomaly.detected
    if body.event_type != ANOMALY_DETECTED:
        raise HTTPException(
            status_code=400,
            detail={
                "error_code": EvtErrorCode.INVALID_EVENT_TYPE,
                "message": f"目前仅支持订阅 anomaly.detected，实际：{body.event_type}",
            },
        )

    sub = event_db.upsert_subscription(
        db=db,
        user_id=user["id"],
        event_type=body.event_type,
        target_id=body.metric_id,
    )
    return {"subscription_id": sub.id, "event_type": sub.event_type, "target_id": sub.target_id}


@router.delete(
    "/anomaly-subscriptions",
    summary="取消异常告警订阅",
)
def unsubscribe_anomaly(
    request: Request,
    body: AnomalySubscriptionDelete,
    db: Session = Depends(get_db),
):
    """DELETE /api/events/anomaly-subscriptions — 取消订阅（仅所有者可删除）"""
    user = get_current_user(request, db)
    event_db = EventDatabase()

    deleted = event_db.delete_subscription(
        db=db,
        subscription_id=body.subscription_id,
        user_id=user["id"],
    )
    if not deleted:
        raise HTTPException(
            status_code=404,
            detail={
                "error_code": EvtErrorCode.NOTIFICATION_NOT_FOUND,
                "message": "订阅不存在或无权删除",
            },
        )
    return {"ok": True}


# =============================================================================
# 通用事件订阅管理（Spec 9 → Spec 16）
# =============================================================================

@router.get(
    "/subscriptions",
    summary="查询当前用户的事件订阅列表",
)
def list_subscriptions(
    request: Request,
    event_type: Optional[str] = Query(default=None, description="事件类型过滤"),
    target_id: Optional[str] = Query(default=None, description="目标 ID 过滤（如 semantic_table_id）"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
):
    """GET /api/events/subscriptions — 查询当前用户的订阅列表"""
    user = get_current_user(request, db)
    event_db = EventDatabase()

    result = event_db.list_subscriptions(
        db=db,
        user_id=user["id"],
        event_type=event_type,
        target_id=target_id,
        page=page,
        page_size=page_size,
    )
    return result


@router.post(
    "/subscriptions",
    status_code=201,
    summary="订阅特定事件类型",
)
def create_subscription(
    request: Request,
    body: SubscriptionCreate,
    db: Session = Depends(get_db),
):
    """POST /api/events/subscriptions — 订阅指定事件类型（analyst+）"""
    from services.events.constants import ALL_EVENT_TYPES

    user = get_current_user(request, db)
    event_db = EventDatabase()

    # 校验事件类型是否注册
    if body.event_type not in ALL_EVENT_TYPES:
        raise HTTPException(
            status_code=400,
            detail={
                "error_code": EvtErrorCode.INVALID_EVENT_TYPE,
                "message": f"无效的事件类型：{body.event_type}",
            },
        )

    sub = event_db.upsert_subscription(
        db=db,
        user_id=user["id"],
        event_type=body.event_type,
        target_id=body.target_id,
    )
    return SubscriptionResponse(
        subscription_id=sub.id,
        event_type=sub.event_type,
        target_id=sub.target_id,
        is_active=sub.is_active,
    )


@router.delete(
    "/subscriptions/{subscription_id}",
    summary="取消事件订阅",
)
def delete_subscription(
    request: Request,
    subscription_id: int,
    db: Session = Depends(get_db),
):
    """DELETE /api/events/subscriptions/{id} — 取消订阅（仅所有者可删除）"""
    user = get_current_user(request, db)
    event_db = EventDatabase()

    deleted = event_db.delete_subscription(
        db=db,
        subscription_id=subscription_id,
        user_id=user["id"],
    )
    if not deleted:
        raise HTTPException(
            status_code=404,
            detail={
                "error_code": EvtErrorCode.NOTIFICATION_NOT_FOUND,
                "message": "订阅不存在或无权删除",
            },
        )
    return {"ok": True}

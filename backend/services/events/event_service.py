"""事件服务核心函数"""
import logging
from typing import Optional

from sqlalchemy.orm import Session

from .constants import ALL_EVENT_TYPES
from .models import EventDatabase
from .notification_router import resolve_targets
from .notification_content import build_notification_content

logger = logging.getLogger(__name__)


def emit_event(
    db: Session,
    event_type: str,
    source_module: str,
    payload: dict,
    *,
    source_id: Optional[str] = None,
    severity: str = "info",
    actor_id: Optional[int] = None,
) -> int:
    """
    发射一个事件。

    1. 写入 bi_events 表
    2. 根据事件类型和路由规则，创建 bi_notifications 记录
    3. 返回事件 ID

    Args:
        db: SQLAlchemy Session
        event_type: 事件类型，如 "tableau.sync.completed"
        source_module: 来源模块，如 "tableau"
        payload: 事件载荷 dict
        source_id: 来源对象标识
        severity: 严重级别 info/warning/error
        actor_id: 触发者用户 ID

    Returns:
        新创建的事件 ID

    Raises:
        ValueError: 事件类型未注册（EVT_003）
    """
    event_db = EventDatabase()

    # 校验事件类型
    if event_type not in ALL_EVENT_TYPES:
        logger.warning("未知事件类型: %s", event_type)
        # PRD §7: v1.0 宽松模式，仅记录日志，不抛出异常

    # 1. 写入 bi_events 表
    event = event_db.create_event(
        db=db,
        event_type=event_type,
        source_module=source_module,
        payload_json=payload,
        source_id=source_id,
        severity=severity,
        actor_id=actor_id,
    )
    logger.info("事件已创建: id=%s, type=%s", event.id, event_type)

    # 2. 解析通知目标用户
    try:
        target_user_ids = resolve_targets(db, event_type, payload, actor_id)
    except Exception as e:
        logger.warning("通知路由解析失败: %s, event=%s", e, event.id)
        target_user_ids = []

    # 3. 构建通知内容
    if target_user_ids:
        try:
            title, content = build_notification_content(event_type, payload, severity)
        except Exception as e:
            logger.warning("通知内容构建失败: %s, event=%s", e, event.id)
            title = f"系统通知"
            content = f"收到事件：{event_type}"

        # 4. 批量创建通知
        try:
            event_db.batch_create_notifications(
                db=db,
                event_id=event.id,
                user_ids=target_user_ids,
                title=title,
                content=content,
                level=severity,
                link=_build_link(source_module, event_type, payload),
            )
            logger.info("通知已创建: event_id=%s, targets=%s", event.id, target_user_ids)
        except Exception as e:
            logger.error("通知创建失败: %s, event=%s", e, event.id)

    return event.id


def _build_link(source_module: str, event_type: str, payload: dict) -> Optional[str]:
    """根据事件类型构建跳转链接"""
    if source_module == "tableau":
        if event_type == "tableau.sync.completed" or event_type == "tableau.sync.failed":
            conn_id = payload.get("connection_id")
            if conn_id:
                return f"/tableau/connections/{conn_id}/sync-logs"
        elif event_type == "tableau.connection.tested":
            conn_id = payload.get("connection_id")
            if conn_id:
                return f"/tableau/connections/{conn_id}"
    elif source_module == "semantic":
        obj_type = payload.get("object_type")
        obj_id = payload.get("object_id")
        if obj_type and obj_id:
            return f"/semantic-maintenance/{obj_type}s/{obj_id}"
    elif source_module == "health":
        scan_id = payload.get("scan_id")
        if scan_id:
            return f"/governance/health/scans/{scan_id}"
    return None

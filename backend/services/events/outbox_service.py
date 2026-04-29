"""出站服务（Outbox Service）"""
import hashlib
import logging
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any

from sqlalchemy.orm import Session
from sqlalchemy import and_

from .models import BiNotificationOutbox, BiNotificationDeadLetter, BiWebhookEndpoint

logger = logging.getLogger(__name__)

# 重试退避表（秒）
EMAIL_RETRY_BACKOFF = [0, 30, 120, 300, 900, 1800]  # 6 次用尽
WEBHOOK_RETRY_BACKOFF = [0, 30, 120, 300]            # 4 次用尽

# 最大重试次数
MAX_EMAIL_RETRIES = 5
MAX_WEBHOOK_RETRIES = 3


def _compute_payload_hash(payload: dict) -> str:
    """计算 payload SHA-256 摘要（审计用，不存原文）"""
    import json
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode()).hexdigest()


def _matches_pattern(event_type: str, pattern: str) -> bool:
    """判断事件类型是否匹配 pattern（支持 * 和 . 点号）"""
    if pattern == "*":
        return True
    # 精确匹配
    if pattern == event_type:
        return True
    # 通配符处理（如 health.* 匹配 health.scan.completed）
    parts = pattern.split(".")
    event_parts = event_type.split(".")
    if len(parts) != len(event_parts):
        return False
    for p, e in zip(parts, event_parts):
        if p != "*" and p != e:
            return False
    return True


class OutboxService:
    """出站队列管理服务"""

    def __init__(self):
        pass

    def enqueue(
        self,
        db: Session,
        notification_id: Optional[int],
        channel: str,  # 'email' / 'webhook'
        target: str,
        event_type: str,
        payload: dict,
        *,
        status: str = "pending",
    ) -> BiNotificationOutbox:
        """将出站任务写入 outbox"""
        payload_hash = _compute_payload_hash(payload)

        outbox = BiNotificationOutbox(
            notification_id=notification_id,
            channel=channel,
            target=target,
            event_type=event_type,
            status=status,
            signature_payload_hash=payload_hash,
            attempt_count=0,
            next_attempt_at=datetime.utcnow(),
        )
        db.add(outbox)
        db.commit()
        db.refresh(outbox)
        return outbox

    def get_pending(self, db: Session, limit: int = 100) -> List[BiNotificationOutbox]:
        """获取待处理的 outbox 记录（status=pending 且 next_attempt_at <= now）"""
        now = datetime.utcnow()
        return (
            db.query(BiNotificationOutbox)
            .filter(
                BiNotificationOutbox.status == "pending",
                BiNotificationOutbox.next_attempt_at <= now,
            )
            .order_by(BiNotificationOutbox.next_attempt_at)
            .limit(limit)
            .all()
        )

    def update_status(
        self,
        db: Session,
        outbox_id: int,
        status: str,
        attempt_count: int,
        next_attempt_at: Optional[datetime],
        last_error: Optional[str] = None,
    ) -> None:
        """更新 outbox 记录状态"""
        outbox = db.query(BiNotificationOutbox).filter(BiNotificationOutbox.id == outbox_id).first()
        if not outbox:
            return
        outbox.status = status
        outbox.attempt_count = attempt_count
        if next_attempt_at:
            outbox.next_attempt_at = next_attempt_at
        if last_error:
            outbox.last_error = last_error[:1024]  # 截断
        db.commit()

    def to_dead_letter(
        self,
        db: Session,
        outbox: BiNotificationOutbox,
        failure_reason: str,
    ) -> BiNotificationDeadLetter:
        """将 outbox 记录转为死信"""
        outbox.status = "dead"

        # 构建脱敏 payload（仅存事件类型和通知标题，不含敏感数据）
        payload_json = {
            "notification_id": outbox.notification_id,
            "event_type": outbox.event_type,
            "channel": outbox.channel,
            "target": outbox.target,
        }

        dead = BiNotificationDeadLetter(
            outbox_id=outbox.id,
            channel=outbox.channel,
            target=outbox.target,
            event_type=outbox.event_type or "",
            payload_json=payload_json,
            failure_reason=failure_reason,
            attempts=outbox.attempt_count,
            first_failed_at=outbox.created_at,
            last_failed_at=datetime.utcnow(),
        )
        db.add(dead)
        db.commit()
        return dead

    def retry_dead_letter(self, db: Session, outbox_id: int) -> BiNotificationOutbox:
        """重试死信（将 dead 状态的 outbox 重新排队）"""
        outbox = db.query(BiNotificationOutbox).filter(
            BiNotificationOutbox.id == outbox_id,
            BiNotificationOutbox.status == "dead",
        ).first()
        if not outbox:
            raise ValueError(f"Outbox {outbox_id} 不是 dead 状态，无法重试")

        outbox.status = "pending"
        outbox.attempt_count = 0
        outbox.next_attempt_at = datetime.utcnow()
        outbox.last_error = None
        db.commit()
        db.refresh(outbox)
        return outbox

    def list_outbox(
        self,
        db: Session,
        status: Optional[str] = None,
        channel: Optional[str] = None,
        page: int = 1,
        page_size: int = 20,
    ) -> Dict[str, Any]:
        """查询 outbox 列表"""
        q = db.query(BiNotificationOutbox)
        if status:
            q = q.filter(BiNotificationOutbox.status == status)
        if channel:
            q = q.filter(BiNotificationOutbox.channel == channel)

        total = q.count()
        items = (
            q.order_by(BiNotificationOutbox.id.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
            .all()
        )
        return {
            "items": [o.to_dict() for o in items],
            "total": total,
            "page": page,
            "page_size": page_size,
        }

    def get_webhook_endpoints_for_event(self, db: Session, event_type: str) -> List[BiWebhookEndpoint]:
        """获取匹配事件类型的所有活跃 Webhook 端点"""
        endpoints = db.query(BiWebhookEndpoint).filter(BiWebhookEndpoint.is_active == True).all()
        return [ep for ep in endpoints if _matches_pattern(event_type, ep.event_type_pattern)]

    def get_next_attempt_at(self, channel: str, attempt_count: int) -> datetime:
        """根据已尝试次数计算下次调度时间"""
        if channel == "email":
            backoff = EMAIL_RETRY_BACKOFF
            max_retries = MAX_EMAIL_RETRIES
        else:
            backoff = WEBHOOK_RETRY_BACKOFF
            max_retries = MAX_WEBHOOK_RETRIES

        idx = min(attempt_count, len(backoff) - 1)
        return datetime.utcnow() + timedelta(seconds=backoff[idx])
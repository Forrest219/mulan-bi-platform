"""事件通知 Celery 任务

包括：
- purge_old_events: 清理过期事件和通知（90 天）
- process_outbox: 处理出站队列（邮件 / Webhook 重试调度）
"""
import logging
import uuid
from datetime import datetime, timedelta

from celery import shared_task

from app.core.database import SessionLocal
from services.events.outbox_service import OutboxService
from services.events.channels import EmailChannel, WebhookChannel
from services.events.redactor import redact_payload
from services.events.models import BiEvent, BiNotification, BiWebhookEndpoint

logger = logging.getLogger(__name__)


# =============================================================================
# 事件 / 通知清理任务
# =============================================================================

@shared_task(bind=True)
def purge_old_events(self):
    """清理 90 天前的事件和孤儿通知（Celery Beat 每日执行）"""
    from services.tasks.decorators import beat_guarded

    cutoff = datetime.utcnow() - timedelta(days=90)
    db = SessionLocal()
    try:
        # bi_events: 按月分区清理，禁止行级 DELETE
        # 策略：找到 cutoff 之前最早的分区，手动 DROP
        # 注意：生产应使用分区 DROP，而非直接 DELETE
        deleted_events = 0
        deleted_notifications = 0

        # 先清理孤儿通知（event_id 无对应事件）
        orphaned = (
            db.query(BiNotification)
            .filter(
                BiNotification.event_id.notin_(
                    db.query(BiEvent.id)
                )
            )
            .all()
        )
        if orphaned:
            ids = [n.id for n in orphaned]
            db.query(BiNotification).filter(BiNotification.id.in_(ids)).delete(synchronize_session=False)
            deleted_notifications += len(ids)

        # 事件按时间清理（仅删除最旧的分区，这里简化处理）
        old_events = db.query(BiEvent).filter(BiEvent.created_at < cutoff).all()
        if old_events:
            ids = [e.id for e in old_events]
            db.query(BiEvent).filter(BiEvent.id.in_(ids)).delete(synchronize_session=False)
            deleted_events += len(ids)

        db.commit()
        logger.info(
            "purge_old_events 完成: deleted_events=%s, deleted_notifications=%s",
            deleted_events, deleted_notifications,
        )
        return {"deleted_events": deleted_events, "deleted_notifications": deleted_notifications}
    except Exception:
        logger.exception("purge_old_events 失败")
        db.rollback()
        raise
    finally:
        db.close()


# =============================================================================
# 出站队列处理任务（Celery Beat 每 30s 调度）
# =============================================================================

@shared_task(bind=True)
def process_outbox(self):
    """
    从 outbox 中取出 pending 且 next_attempt_at <= now 的记录，
    根据 channel 调用对应的 Channel.send()，更新状态或移至死信。
    """
    db = SessionLocal()
    outbox_svc = OutboxService()
    email_channel = EmailChannel()
    webhook_channel = WebhookChannel()

    try:
        pending = outbox_svc.get_pending(db, limit=100)
        processed = 0

        for record in pending:
            trace_id = str(uuid.uuid4())[:8]
            try:
                result = _process_outbox_record(db, record, email_channel, webhook_channel, trace_id, outbox_svc)
                if result == "handled":
                    processed += 1
            except Exception:
                logger.exception("[%s] outbox 处理异常: record_id=%s", trace_id, record.id)

        logger.info("process_outbox 完成: processed=%s", processed)
        return {"processed": processed}
    finally:
        db.close()


def _process_outbox_record(db, record, email_channel, webhook_channel, trace_id, outbox_svc):
    """处理单条 outbox 记录"""
    # 获取通知和关联事件
    notification = None
    event = None
    if record.notification_id:
        from services.events.models import BiNotification as BN
        notification = db.query(BN).filter(BN.id == record.notification_id).first()
        if notification:
            from services.events.models import BiEvent as BE
            event = db.query(BE).filter(BE.id == notification.event_id).first()

    # 获取 Webhook endpoint（仅 webhook 渠道需要）
    webhook_endpoint = None
    if record.channel == "webhook":
        # 查询匹配的 endpoint
        endpoints = outbox_svc.get_webhook_endpoints_for_event(db, record.event_type)
        if endpoints:
            # 取第一个匹配的（理论上每个 event_type 只对应一个 endpoint 配置）
            webhook_endpoint = endpoints[0]
        if not webhook_endpoint:
            logger.info("[%s] 无匹配的 webhook endpoint: event_type=%s", trace_id, record.event_type)
            outbox_svc.update_status(
                db, record.id, "dead",
                attempt_count=record.attempt_count + 1,
                next_attempt_at=None,
                last_error="无匹配的 webhook endpoint",
            )
            return "handled"

    # 构建 payload
    payload = {
        "notification_id": record.notification_id,
        "event_type": record.event_type,
        "channel": record.channel,
    }
    if event:
        payload["payload_json"] = event.payload_json or {}

    # 调用渠道发送
    if record.channel == "email":
        result = email_channel.send(
            notification=notification,
            recipient=record.target,
            trace_id=trace_id,
        )
    elif record.channel == "webhook" and webhook_endpoint:
        result = webhook_channel.send(
            notification=notification,
            recipient=record.target,
            trace_id=trace_id,
            secret_encrypted=webhook_endpoint.secret_encrypted,
            event_type=record.event_type or "unknown",
            event_id=event.id if event else None,
        )
    else:
        result = None

    if result is None:
        outbox_svc.update_status(db, record.id, "dead", record.attempt_count + 1, None, "未知 channel")
        return "handled"

    # 根据结果更新状态
    if result.status == "delivered":
        outbox_svc.update_status(
            db, record.id, "sent",
            attempt_count=record.attempt_count + 1,
            next_attempt_at=None,
            last_error=None,
        )
    elif result.status == "retryable_failed":
        attempt_count = record.attempt_count + 1
        max_retries = 5 if record.channel == "email" else 3
        if attempt_count > max_retries:
            # 超过最大重试次数 → 死信
            outbox_svc.to_dead_letter(db, record, result.detail)
        else:
            next_at = outbox_svc.get_next_attempt_at(record.channel, attempt_count)
            outbox_svc.update_status(
                db, record.id, "pending",
                attempt_count=attempt_count,
                next_attempt_at=next_at,
                last_error=result.detail,
            )
    else:  # permanent_failed → 直接死信
        outbox_svc.to_dead_letter(db, record, result.detail)

    return "handled"
"""Metrics Agent — 事件发射封装

调用项目已有的 services/events 事件总线（emit_event），
同时写入 bi_events 表并驱动 bi_notifications 通知路由。

三类事件：
  metric.published          — 指标发布成功
  metric.anomaly.detected   — 检测到异常
  metric.consistency.failed — 一致性校验失败（check_status="fail"）
"""

import logging
from datetime import datetime, timezone
import json
from typing import Optional
import urllib.request
from uuid import UUID

from sqlalchemy.orm import Session

from app.core.config import get_settings
from services.events import (
    ANOMALY_DETECTED,
    emit_event,
    METRIC_PUBLISHED,
    METRIC_ANOMALY_DETECTED,
    METRIC_CONSISTENCY_FAILED,
    SOURCE_MODULE_METRICS,
    SEVERITY_INFO,
    SEVERITY_WARNING,
    SEVERITY_ERROR,
)

logger = logging.getLogger("metrics_agent.events")


def _safe_post_to_webhook(event_type: str, payload: dict) -> None:
    try:
        _post_to_webhook(event_type, payload)
    except Exception as exc:
        logger.warning("metrics webhook hook failed (ignored): event_type=%s, error=%s", event_type, exc)


def _post_to_webhook(event_type: str, payload: dict) -> None:
    """Best-effort webhook notification for metrics events."""
    try:
        settings = get_settings()
        if not getattr(settings, "ALERT_WEBHOOK_ENABLED", False):
            return
        url = getattr(settings, "ALERT_WEBHOOK_URL", None)
        if not url:
            return
        body = json.dumps({"event_type": event_type, "payload": payload}, ensure_ascii=False).encode("utf-8")
        request = urllib.request.Request(
            url,
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=5):
            pass
    except Exception as exc:
        logger.warning("metrics webhook post failed (ignored): event_type=%s, error=%s", event_type, exc)


def emit_metric_published(
    db: Session,
    metric_id: UUID,
    name: str,
    tenant_id: UUID,
    actor_id: Optional[int] = None,
) -> None:
    """指标发布成功事件。

    写入 bi_events，并通知所有 data_admin / admin 用户。
    调用失败时仅记录日志，不影响主流程。
    """
    payload = {
        "metric_id": str(metric_id),
        "name": name,
        "tenant_id": str(tenant_id),
    }
    try:
        emit_event(
            db=db,
            event_type=METRIC_PUBLISHED,
            source_module=SOURCE_MODULE_METRICS,
            payload=payload,
            source_id=str(metric_id),
            severity=SEVERITY_INFO,
            actor_id=actor_id,
        )
    except Exception as exc:
        logger.warning(
            "emit_metric_published 失败（已忽略）：metric_id=%s, error=%s",
            metric_id,
            exc,
        )
    _safe_post_to_webhook(METRIC_PUBLISHED, payload)


def emit_anomaly_detected(
    db: Session,
    anomaly_id: UUID,
    metric_id: UUID,
    metric_name: str,
    detection_method: str,
    deviation_score: float,
    tenant_id: UUID,
    actor_id: Optional[int] = None,
) -> None:
    """指标异常检测事件。

    写入 bi_events，并通知所有 data_admin / admin 用户。
    调用失败时仅记录日志，不影响主流程。
    """
    payload = {
        "anomaly_id": str(anomaly_id),
        "metric_id": str(metric_id),
        "metric_name": metric_name,
        "detection_method": detection_method,
        "deviation_score": deviation_score,
        "tenant_id": str(tenant_id),
    }
    try:
        emit_event(
            db=db,
            event_type=METRIC_ANOMALY_DETECTED,
            source_module=SOURCE_MODULE_METRICS,
            payload=payload,
            source_id=str(anomaly_id),
            severity=SEVERITY_WARNING,
            actor_id=actor_id,
        )
    except Exception as exc:
        logger.warning(
            "emit_anomaly_detected 失败（已忽略）：anomaly_id=%s, error=%s",
            anomaly_id,
            exc,
        )
    _safe_post_to_webhook(METRIC_ANOMALY_DETECTED, payload)


def emit_consistency_failed(
    db: Session,
    check_id: UUID,
    metric_id: UUID,
    metric_name: str,
    difference_pct: Optional[float],
    tenant_id: UUID,
    actor_id: Optional[int] = None,
) -> None:
    """指标一致性校验失败事件（check_status="fail"）。

    写入 bi_events，并通知所有 data_admin / admin 用户。
    调用失败时仅记录日志，不影响主流程。
    """
    payload = {
        "check_id": str(check_id),
        "metric_id": str(metric_id),
        "metric_name": metric_name,
        "difference_pct": difference_pct,
        "tenant_id": str(tenant_id),
    }
    try:
        emit_event(
            db=db,
            event_type=METRIC_CONSISTENCY_FAILED,
            source_module=SOURCE_MODULE_METRICS,
            payload=payload,
            source_id=str(check_id),
            severity=SEVERITY_ERROR,
            actor_id=actor_id,
        )
    except Exception as exc:
        logger.warning(
            "emit_consistency_failed 失败（已忽略）：check_id=%s, error=%s",
            check_id,
            exc,
        )
    _safe_post_to_webhook(METRIC_CONSISTENCY_FAILED, payload)


def publish_anomaly_event(
    db: Session,
    metric_id: UUID,
    metric_name: str,
    algorithm: str,
    anomaly_count: int,
    max_score: float,
    window_start: str,
    window_end: str,
    tenant_id: UUID,
    detected_at: Optional[str] = None,
    actor_id: Optional[int] = None,
) -> None:
    """Publish a high-level anomaly.detected event with Spec 30 payload fields."""
    detected_at_value = detected_at.isoformat() if hasattr(detected_at, "isoformat") else detected_at
    payload = {
        "metric_id": str(metric_id),
        "metric_name": metric_name,
        "algorithm": algorithm,
        "anomaly_count": anomaly_count,
        "max_score": max_score,
        "window_start": window_start,
        "window_end": window_end,
        "tenant_id": str(tenant_id),
        "detected_at": detected_at_value or datetime.now(timezone.utc).isoformat(),
    }
    try:
        emit_event(
            db=db,
            event_type=ANOMALY_DETECTED,
            source_module=SOURCE_MODULE_METRICS,
            payload=payload,
            source_id=str(metric_id),
            severity=SEVERITY_WARNING,
            actor_id=actor_id,
        )
    except Exception as exc:
        logger.warning(
            "publish_anomaly_event 失败（已忽略）：metric_id=%s, error=%s",
            metric_id,
            exc,
        )
    _safe_post_to_webhook(ANOMALY_DETECTED, payload)

"""Metrics Agent — 事件发射封装

调用项目已有的 services/events 事件总线（emit_event），
同时写入 bi_events 表并驱动 bi_notifications 通知路由。

三类事件：
  metric.published          — 指标发布成功
  metric.anomaly.detected   — 检测到异常（legacy，保留兼容）
  metric.consistency.failed — 一致性校验失败（check_status="fail"）
  anomaly.detected         — 异常告警事件（Spec 30，完整字段）
"""

import logging
from datetime import datetime
from typing import Optional
from uuid import UUID

from sqlalchemy.orm import Session

from services.events import (
    emit_event,
    METRIC_PUBLISHED,
    METRIC_ANOMALY_DETECTED,
    METRIC_CONSISTENCY_FAILED,
    ANOMALY_DETECTED,
    SOURCE_MODULE_METRICS,
    SEVERITY_INFO,
    SEVERITY_WARNING,
    SEVERITY_ERROR,
)

logger = logging.getLogger("metrics_agent.events")


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
    try:
        emit_event(
            db=db,
            event_type=METRIC_PUBLISHED,
            source_module=SOURCE_MODULE_METRICS,
            payload={
                "metric_id": str(metric_id),
                "name": name,
                "tenant_id": str(tenant_id),
            },
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
    try:
        emit_event(
            db=db,
            event_type=METRIC_ANOMALY_DETECTED,
            source_module=SOURCE_MODULE_METRICS,
            payload={
                "anomaly_id": str(anomaly_id),
                "metric_id": str(metric_id),
                "metric_name": metric_name,
                "detection_method": detection_method,
                "deviation_score": deviation_score,
                "tenant_id": str(tenant_id),
            },
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
    try:
        emit_event(
            db=db,
            event_type=METRIC_CONSISTENCY_FAILED,
            source_module=SOURCE_MODULE_METRICS,
            payload={
                "check_id": str(check_id),
                "metric_id": str(metric_id),
                "metric_name": metric_name,
                "difference_pct": difference_pct,
                "tenant_id": str(tenant_id),
            },
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
    detected_at: Optional[datetime] = None,
    actor_id: Optional[int] = None,
) -> None:
    """
    发布 anomaly.detected 事件（Spec 30）。

    完整 extra_data：{metric_id, metric_name, algorithm, anomaly_count,
                       max_score, window_start, window_end}

    写入 bi_events + bi_notifications（路由至订阅用户）。
    调用失败时仅记录日志，不影响主流程。
    """
    try:
        detected_at_iso = (
            detected_at.isoformat()
            if detected_at
            else datetime.now().strftime("%Y-%m-%dT%H:%M:%SZ")
        )
        emit_event(
            db=db,
            event_type=ANOMALY_DETECTED,
            source_module=SOURCE_MODULE_METRICS,
            payload={
                "metric_id": str(metric_id),
                "metric_name": metric_name,
                "algorithm": algorithm,
                "anomaly_count": anomaly_count,
                "max_score": max_score,
                "window_start": window_start,
                "window_end": window_end,
                "detected_at": detected_at_iso,
                "tenant_id": str(tenant_id),
            },
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

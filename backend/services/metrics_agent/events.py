"""Metrics Agent — 事件发射封装

调用项目已有的 services/events 事件总线（emit_event），
同时写入 bi_events 表并驱动 bi_notifications 通知路由。

三类事件：
  metric.published          — 指标发布成功
  metric.anomaly.detected   — 检测到异常
  metric.consistency.failed — 一致性校验失败（check_status="fail"）
"""

import logging
from uuid import UUID

from sqlalchemy.orm import Session

from services.events import (
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


def emit_metric_published(
    db: Session,
    metric_id: UUID,
    name: str,
    tenant_id: UUID,
    actor_id: int | None = None,
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
    actor_id: int | None = None,
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
    difference_pct: float | None,
    tenant_id: UUID,
    actor_id: int | None = None,
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

"""Metrics Agent — Services Layer

Re-exports from metrics_agent for backwards compatibility.
"""
from services.metrics_agent import registry
from services.metrics_agent.anomaly_detector import detect_zscore
from services.metrics_agent.anomaly_service import run_anomaly_detection, update_anomaly_status
from services.metrics_agent.consistency import run_consistency_check
from services.metrics_agent.lineage import resolve_lineage
from services.metrics_agent.schemas import (
    MetricCreate,
    MetricDetail,
    MetricLookupItem,
    MetricLookupResponse,
    MetricUpdate,
    PaginatedMetrics,
    PublishResponse,
)
from services.metrics.service import detect_anomalies

__all__ = [
    "registry",
    "detect_zscore",
    "detect_anomalies",
    "run_anomaly_detection",
    "update_anomaly_status",
    "run_consistency_check",
    "resolve_lineage",
    "MetricCreate",
    "MetricDetail",
    "MetricLookupItem",
    "MetricLookupResponse",
    "MetricUpdate",
    "PaginatedMetrics",
    "PublishResponse",
]

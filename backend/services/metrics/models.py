"""Metrics Agent — SQLAlchemy Models

Re-exports from models.metrics for backwards compatibility with spec paths.
"""
from models.metrics import (
    BiMetricAnomaly,
    BiMetricConsistencyCheck,
    BiMetricDefinition,
    BiMetricLineage,
    BiMetricVersion,
)

# Alias names used in spec/task
MetricDefinition = BiMetricDefinition
MetricLineage = BiMetricLineage
MetricVersion = BiMetricVersion
MetricAnomaly = BiMetricAnomaly
MetricConsistencyCheck = BiMetricConsistencyCheck

__all__ = [
    "BiMetricAnomaly",
    "BiMetricConsistencyCheck",
    "BiMetricDefinition",
    "BiMetricLineage",
    "BiMetricVersion",
    "MetricDefinition",
    "MetricLineage",
    "MetricVersion",
    "MetricAnomaly",
    "MetricConsistencyCheck",
]

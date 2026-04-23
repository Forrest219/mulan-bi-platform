"""DQC 枚举常量"""
from enum import Enum


class Dimension(str, Enum):
    COMPLETENESS = "completeness"
    ACCURACY = "accuracy"
    TIMELINESS = "timeliness"
    VALIDITY = "validity"
    UNIQUENESS = "uniqueness"
    CONSISTENCY = "consistency"


ALL_DIMENSIONS = [
    Dimension.COMPLETENESS.value,
    Dimension.ACCURACY.value,
    Dimension.TIMELINESS.value,
    Dimension.VALIDITY.value,
    Dimension.UNIQUENESS.value,
    Dimension.CONSISTENCY.value,
]


class SignalLevel(str, Enum):
    GREEN = "GREEN"
    P1 = "P1"
    P0 = "P0"


SIGNAL_PRIORITY = {
    SignalLevel.GREEN.value: 0,
    SignalLevel.P1.value: 1,
    SignalLevel.P0.value: 2,
}


class RuleType(str, Enum):
    NULL_RATE = "null_rate"
    UNIQUENESS = "uniqueness"
    RANGE_CHECK = "range_check"
    FRESHNESS = "freshness"
    REGEX = "regex"
    CUSTOM_SQL = "custom_sql"
    VOLUME_ANOMALY = "volume_anomaly"
    TABLE_COUNT_COMPARE = "table_count_compare"


ALL_RULE_TYPES = [rt.value for rt in RuleType]


class CycleStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    PARTIAL = "partial"
    FAILED = "failed"


class CycleScope(str, Enum):
    FULL = "full"
    HOURLY_LIGHT = "hourly_light"


class TriggerType(str, Enum):
    SCHEDULED = "scheduled"
    MANUAL = "manual"


class AssetStatus(str, Enum):
    ENABLED = "enabled"
    DISABLED = "disabled"


class LlmTrigger(str, Enum):
    P0_TRIGGERED = "p0_triggered"
    P1_TRIGGERED = "p1_triggered"
    USER_REQUEST = "user_request"
    RULE_SUGGEST = "rule_suggest"


DEFAULT_DIMENSION_WEIGHTS = {
    Dimension.COMPLETENESS.value: 1 / 6,
    Dimension.ACCURACY.value: 1 / 6,
    Dimension.TIMELINESS.value: 1 / 6,
    Dimension.VALIDITY.value: 1 / 6,
    Dimension.UNIQUENESS.value: 1 / 6,
    Dimension.CONSISTENCY.value: 1 / 6,
}

DEFAULT_SIGNAL_THRESHOLDS = {
    "p0_score": 60.0,
    "p1_score": 80.0,
    "drift_p0": 20.0,
    "drift_p1": 10.0,
    "confidence_p0": 60.0,
    "confidence_p1": 80.0,
}

RULE_TYPE_TO_DIMENSION = {
    RuleType.NULL_RATE.value: Dimension.COMPLETENESS.value,
    RuleType.UNIQUENESS.value: Dimension.UNIQUENESS.value,
    RuleType.RANGE_CHECK.value: Dimension.VALIDITY.value,
    RuleType.FRESHNESS.value: Dimension.TIMELINESS.value,
    RuleType.REGEX.value: Dimension.VALIDITY.value,
    RuleType.VOLUME_ANOMALY.value: Dimension.COMPLETENESS.value,
    RuleType.TABLE_COUNT_COMPARE.value: Dimension.CONSISTENCY.value,
}

DIMENSION_RULE_COMPATIBILITY = {
    Dimension.COMPLETENESS.value: {RuleType.NULL_RATE.value, RuleType.CUSTOM_SQL.value, RuleType.VOLUME_ANOMALY.value},
    Dimension.ACCURACY.value: {RuleType.RANGE_CHECK.value, RuleType.CUSTOM_SQL.value},
    Dimension.TIMELINESS.value: {RuleType.FRESHNESS.value, RuleType.CUSTOM_SQL.value},
    Dimension.VALIDITY.value: {RuleType.REGEX.value, RuleType.RANGE_CHECK.value, RuleType.CUSTOM_SQL.value},
    Dimension.UNIQUENESS.value: {RuleType.UNIQUENESS.value, RuleType.CUSTOM_SQL.value},
    Dimension.CONSISTENCY.value: {RuleType.CUSTOM_SQL.value, RuleType.TABLE_COUNT_COMPARE.value},
}

RULE_CONFIG_SCHEMA: dict = {
    RuleType.VOLUME_ANOMALY.value: {
        "direction": {"type": "enum", "values": ["drop", "rise", "both"]},
        "threshold_pct": {"type": "float", "min": 0.0, "max": 1.0},
        "comparison_window": {"type": "enum", "values": ["1d", "7d", "30d"]},
        "min_row_count": {"type": "int", "min": 0},
    },
    RuleType.TABLE_COUNT_COMPARE.value: {
        "target_schema": {"type": "string", "required": True},
        "target_table": {"type": "string", "required": True},
        "target_datasource_id": {"type": "uuid", "required": False},
        "tolerance_pct": {"type": "float", "min": 0.0, "max": 1.0, "default": 0.0},
    },
}

HOURLY_LIGHT_RULE_TYPES = {RuleType.FRESHNESS.value, RuleType.NULL_RATE.value}

LOCK_KEY_FULL = "dqc:cycle:lock:full"
LOCK_KEY_HOURLY = "dqc:cycle:lock:hourly"
LOCK_TTL_SECONDS_FULL = 3600
LOCK_TTL_SECONDS_HOURLY = 900

PROFILING_SAMPLE_ROWS = 10_000
DEFAULT_MAX_SCAN_ROWS = 1_000_000
RULE_EXECUTION_TIMEOUT_SECONDS = 60
WEIGHT_SUM_TOLERANCE = 0.01

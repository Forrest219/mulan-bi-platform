"""质量规则类型定义 — Spec 15 §3.1"""

from enum import Enum
from typing import Optional, Any


class RuleType(str, Enum):
    """13 种质量规则类型"""
    NULL_RATE = "null_rate"           # 完整性 - 空值率
    NOT_NULL = "not_null"             # 完整性 - 非空检查
    ROW_COUNT = "row_count"           # 完整性 - 行数检查
    DUPLICATE_RATE = "duplicate_rate" # 唯一性 - 重复率
    UNIQUE_COUNT = "unique_count"     # 唯一性 - 唯一值数
    REFERENTIAL = "referential"        # 一致性 - 引用完整性
    CROSS_FIELD = "cross_field"        # 一致性 - 跨字段一致性
    VALUE_RANGE = "value_range"       # 一致性 - 值域检查
    FRESHNESS = "freshness"            # 时效性 - 数据新鲜度
    LATENCY = "latency"               # 时效性 - 延迟检查
    FORMAT_REGEX = "format_regex"     # 格式规范 - 正则匹配
    ENUM_CHECK = "enum_check"         # 格式规范 - 枚举检查
    CUSTOM_SQL = "custom_sql"         # 自定义 SQL


# 每种规则类型的 threshold JSON Schema 定义
RULE_THRESHOLD_SCHEMAS: dict[str, dict] = {
    "null_rate": {
        "max_rate": float,      # 允许的最大空值率（0-1）
        "max_scan_rows": int,   # 大表熔断，默认 1,000,000
    },
    "not_null": {
        "max_scan_rows": int,
    },
    "row_count": {
        "min": Optional[float],
        "max": Optional[float],
        "max_scan_rows": int,
    },
    "duplicate_rate": {
        "max_rate": float,
        "max_scan_rows": int,
    },
    "unique_count": {
        "min": Optional[int],
        "max": Optional[int],
        "max_scan_rows": int,
    },
    "referential": {
        "ref_table": str,
        "ref_field": str,
        "max_scan_rows": int,
    },
    "cross_field": {
        "expression": str,  # e.g. "end_date >= start_date"
        "related_fields": list[str],
    },
    "value_range": {
        "min": Optional[float],
        "max": Optional[float],
        "allow_null": bool,
    },
    "freshness": {
        "time_field": str,
        "max_delay_hours": float,
    },
    "latency": {
        "time_field": str,
        "max_delay_hours": float,
    },
    "format_regex": {
        "pattern": str,
        "allow_null": bool,
    },
    "enum_check": {
        "allowed_values": list[Any],
        "allow_null": bool,
    },
    "custom_sql": {
        # SQL 须返回单行单列，值为 0(通过) 或非 0(失败)
    },
}

# 规则类型 → 评分维度映射
RULE_TYPE_DIMENSION: dict[str, str] = {
    "null_rate": "completeness",
    "not_null": "completeness",
    "row_count": "completeness",
    "duplicate_rate": "uniqueness",
    "unique_count": "uniqueness",
    "referential": "consistency",
    "cross_field": "consistency",
    "value_range": "consistency",
    "freshness": "timeliness",
    "latency": "timeliness",
    "format_regex": "conformity",
    "enum_check": "conformity",
}

# 维度权重
DIMENSION_WEIGHTS: dict[str, float] = {
    "completeness": 0.30,
    "consistency": 0.25,
    "uniqueness": 0.20,
    "timeliness": 0.15,
    "conformity": 0.10,
}
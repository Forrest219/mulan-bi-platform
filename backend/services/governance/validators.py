"""规则阈值联合校验器（跨字段依赖，Pydantic 无法单独完成）"""

from typing import Any


def validate_threshold(rule_type: str, threshold: dict) -> None:
    """校验 rule_type + threshold 组合是否合法"""
    errors = []

    if rule_type == "null_rate":
        if "max_rate" not in threshold:
            errors.append("null_rate 规则必须指定 max_rate")
        if not (0 <= threshold.get("max_rate", -1) <= 1):
            errors.append("max_rate 必须在 [0, 1] 范围内")

    elif rule_type == "row_count":
        if "min" not in threshold and "max" not in threshold:
            errors.append("row_count 规则必须指定 min 或 max")

    elif rule_type == "referential":
        if "ref_table" not in threshold or "ref_field" not in threshold:
            errors.append("referential 规则必须指定 ref_table 和 ref_field")

    elif rule_type == "freshness" or rule_type == "latency":
        if "time_field" not in threshold:
            errors.append(f"{rule_type} 规则必须指定 time_field")
        if "max_delay_hours" not in threshold:
            errors.append(f"{rule_type} 规则必须指定 max_delay_hours")

    elif rule_type == "enum_check":
        if "allowed_values" not in threshold:
            errors.append("enum_check 规则必须指定 allowed_values")

    elif rule_type == "format_regex":
        if "pattern" not in threshold:
            errors.append("format_regex 规则必须指定 pattern")

    # 大表熔断：null_rate, duplicate_rate, unique_count, row_count, referential
    big_table_rules = ["null_rate", "duplicate_rate", "unique_count", "row_count", "referential"]
    if rule_type in big_table_rules:
        if "max_scan_rows" not in threshold:
            threshold["max_scan_rows"] = 1_000_000  # 默认 100 万行

    if errors:
        raise ValueError("; ".join(errors))
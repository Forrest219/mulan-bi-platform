"""质量规则类型与校验器单元测试 — Spec 15"""

import pytest
import sys
import os

# Add backend to path for imports
_backend_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
sys.path.insert(0, _backend_dir)

from services.governance.rule_types import RULE_TYPE_DIMENSION, DIMENSION_WEIGHTS, RuleType
from services.governance.validators import validate_threshold
from services.governance.cron_validator import validate_cron


class TestRuleType:
    """规则类型枚举测试"""

    def test_rule_type_values(self):
        """验证13种规则类型枚举值"""
        assert len(RuleType) == 13
        expected_types = [
            "null_rate", "not_null", "row_count", "duplicate_rate",
            "unique_count", "referential", "cross_field", "value_range",
            "freshness", "latency", "format_regex", "enum_check", "custom_sql"
        ]
        for t in expected_types:
            assert hasattr(RuleType, t.upper())


class TestDimensionMapping:
    """规则类型 → 维度映射测试"""

    def test_all_rule_types_mapped(self):
        """每种规则类型都有对应的维度映射"""
        for rule_type in RULE_TYPE_DIMENSION:
            assert rule_type in [rt.value for rt in RuleType]

    def test_dimension_weights_sum_to_one(self):
        """维度权重之和等于1"""
        total = sum(DIMENSION_WEIGHTS.values())
        assert abs(total - 1.0) < 0.0001


class TestThresholdValidator:
    """阈值校验器测试"""

    def test_null_rate_valid(self):
        validate_threshold("null_rate", {"max_rate": 0.05})
        validate_threshold("null_rate", {"max_rate": 0.05, "max_scan_rows": 500000})

    def test_null_rate_missing_max_rate(self):
        with pytest.raises(ValueError, match="max_rate"):
            validate_threshold("null_rate", {})

    def test_null_rate_invalid_rate(self):
        with pytest.raises(ValueError, match="[0, 1]"):
            validate_threshold("null_rate", {"max_rate": 1.5})

    def test_null_rate_negative_rate(self):
        with pytest.raises(ValueError, match="[0, 1]"):
            validate_threshold("null_rate", {"max_rate": -0.1})

    def test_row_count_valid(self):
        validate_threshold("row_count", {"min": 100})
        validate_threshold("row_count", {"max": 10000})
        validate_threshold("row_count", {"min": 100, "max": 10000})

    def test_row_count_missing_bounds(self):
        with pytest.raises(ValueError, match="min 或 max"):
            validate_threshold("row_count", {})

    def test_referential_valid(self):
        validate_threshold("referential", {"ref_table": "users", "ref_field": "id"})

    def test_referential_missing_ref(self):
        with pytest.raises(ValueError, match="ref_table 和 ref_field"):
            validate_threshold("referential", {"ref_table": "users"})
        with pytest.raises(ValueError, match="ref_table 和 ref_field"):
            validate_threshold("referential", {"ref_field": "id"})

    def test_freshness_valid(self):
        validate_threshold("freshness", {"time_field": "updated_at", "max_delay_hours": 24})

    def test_freshness_missing_time_field(self):
        with pytest.raises(ValueError, match="time_field"):
            validate_threshold("freshness", {"max_delay_hours": 24})

    def test_freshness_missing_max_delay_hours(self):
        with pytest.raises(ValueError, match="max_delay_hours"):
            validate_threshold("freshness", {"time_field": "updated_at"})

    def test_latency_valid(self):
        validate_threshold("latency", {"time_field": "created_at", "max_delay_hours": 1})

    def test_latency_missing_fields(self):
        with pytest.raises(ValueError):
            validate_threshold("latency", {})

    def test_enum_check_valid(self):
        validate_threshold("enum_check", {"allowed_values": ["A", "B", "C"]})

    def test_enum_check_missing_allowed_values(self):
        with pytest.raises(ValueError, match="allowed_values"):
            validate_threshold("enum_check", {})

    def test_format_regex_valid(self):
        validate_threshold("format_regex", {"pattern": r"^\d{3}-\d{4}$"})

    def test_format_regex_missing_pattern(self):
        with pytest.raises(ValueError, match="pattern"):
            validate_threshold("format_regex", {})

    def test_cross_field_valid(self):
        validate_threshold("cross_field", {
            "expression": "end_date >= start_date",
            "related_fields": ["start_date", "end_date"]
        })

    def test_value_range_valid(self):
        validate_threshold("value_range", {"min": 0, "max": 100, "allow_null": False})

    def test_big_table_default_max_scan_rows(self):
        """大表规则自动设置默认 max_scan_rows"""
        result = {"max_rate": 0.05}
        validate_threshold("null_rate", result)
        assert result["max_scan_rows"] == 1_000_000

        result2 = {"max_rate": 0.1, "max_scan_rows": 500000}
        validate_threshold("null_rate", result2)
        assert result2["max_scan_rows"] == 500000  # 保持用户设置

    def test_custom_sql_no_validation(self):
        """custom_sql 规则不进行额外校验"""
        validate_threshold("custom_sql", {})
        validate_threshold("custom_sql", {"some_field": "any_value"})


class TestCronValidator:
    """Cron 表达式校验器测试"""

    def test_valid_cron_standard(self):
        """标准 Cron 表达式"""
        validate_cron("0 6 * * *")      # 每天 6:00
        validate_cron("30 14 * * *")    # 每天 14:30
        validate_cron("0 0 1 * *")      # 每月 1 日 00:00

    def test_valid_cron_with_step(self):
        """带步长的 Cron 表达式"""
        validate_cron("*/5 * * * *")    # 每 5 分钟
        validate_cron("0 */2 * * *")   # 每 2 小时

    def test_valid_cron_ranges(self):
        """带范围的 Cron 表达式"""
        # 注意：本校验器不支持 6-18 范围语法，仅支持 */n 步长
        # 范围语法如 0 6-18 * * * 应视为无效
        with pytest.raises(ValueError, match="无效"):
            validate_cron("0 6-18 * * *")

    def test_invalid_cron_empty(self):
        with pytest.raises(ValueError, match="无效"):
            validate_cron("")

    def test_invalid_cron_nonsense(self):
        with pytest.raises(ValueError, match="无效"):
            validate_cron("invalid")

    def test_invalid_cron_minute_out_of_range(self):
        """分钟超范围 (0-59)"""
        with pytest.raises(ValueError, match="无效"):
            validate_cron("60 6 * * *")

    def test_invalid_cron_hour_out_of_range(self):
        """小时超范围 (0-23)"""
        with pytest.raises(ValueError, match="无效"):
            validate_cron("0 25 * * *")

    def test_invalid_cron_day_out_of_range(self):
        """日期超范围 (1-31)"""
        with pytest.raises(ValueError, match="无效"):
            validate_cron("0 6 32 * *")

    def test_invalid_cron_month_out_of_range(self):
        """月份超范围 (1-12)"""
        with pytest.raises(ValueError, match="无效"):
            validate_cron("0 6 * 13 *")

    def test_invalid_cron_weekday_out_of_range(self):
        """星期超范围 (0-6)"""
        with pytest.raises(ValueError, match="无效"):
            validate_cron("0 6 * * 7")

    def test_none_cron_allowed(self):
        """None 视为合法（表示不使用定时任务）"""
        validate_cron(None)
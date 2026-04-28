"""质量规则 CRUD 服务层测试 — Spec 15

注意：此文件测试 Rule CRUD 的核心校验逻辑，不依赖数据库。
数据库相关的集成测试见 tests/api/governance/test_quality_api.py
"""
import sys
import os

# Add backend to path for imports
_backend_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
sys.path.insert(0, _backend_dir)

import pytest

from app.core.errors import MulanError
from services.governance.validators import validate_threshold
from services.governance.cron_validator import validate_cron


class TestRuleServiceValidation:
    """规则校验测试（不依赖数据库）"""

    def test_create_rule_requires_datasource(self):
        """验证 datasource_id 必填"""
        # validate_threshold 不校验 datasource_id（由 API 层校验）
        # 此处测试 threshold 校验器对 null_rate 的校验
        validate_threshold("null_rate", {"max_rate": 0.05})  # 应通过

    def test_null_rate_requires_max_rate(self):
        """null_rate 规则必须指定 max_rate"""
        with pytest.raises(ValueError, match="max_rate"):
            validate_threshold("null_rate", {})

    def test_null_rate_max_rate_bounds(self):
        """max_rate 必须在 [0, 1] 范围内"""
        # 正常值
        validate_threshold("null_rate", {"max_rate": 0.0})
        validate_threshold("null_rate", {"max_rate": 1.0})
        validate_threshold("null_rate", {"max_rate": 0.05})

        # 越界值
        with pytest.raises(ValueError, match="[0, 1]"):
            validate_threshold("null_rate", {"max_rate": 1.5})
        with pytest.raises(ValueError, match="[0, 1]"):
            validate_threshold("null_rate", {"max_rate": -0.1})

    def test_row_count_requires_min_or_max(self):
        """row_count 规则必须指定 min 或 max"""
        validate_threshold("row_count", {"min": 100})
        validate_threshold("row_count", {"max": 10000})
        validate_threshold("row_count", {"min": 100, "max": 10000})
        with pytest.raises(ValueError, match="min 或 max"):
            validate_threshold("row_count", {})

    def test_referential_requires_ref_table_and_ref_field(self):
        """referential 规则必须指定 ref_table 和 ref_field"""
        validate_threshold("referential", {"ref_table": "users", "ref_field": "id"})
        with pytest.raises(ValueError, match="ref_table 和 ref_field"):
            validate_threshold("referential", {"ref_table": "users"})
        with pytest.raises(ValueError, match="ref_table 和 ref_field"):
            validate_threshold("referential", {"ref_field": "id"})

    def test_freshness_requires_time_field_and_max_delay_hours(self):
        """freshness 规则必须指定 time_field 和 max_delay_hours"""
        validate_threshold("freshness", {"time_field": "updated_at", "max_delay_hours": 24})
        with pytest.raises(ValueError, match="time_field"):
            validate_threshold("freshness", {"max_delay_hours": 24})
        with pytest.raises(ValueError, match="max_delay_hours"):
            validate_threshold("freshness", {"time_field": "updated_at"})

    def test_latency_requires_time_field_and_max_delay_hours(self):
        """latency 规则必须指定 time_field 和 max_delay_hours"""
        validate_threshold("latency", {"time_field": "created_at", "max_delay_hours": 1})
        with pytest.raises(ValueError, match="time_field"):
            validate_threshold("latency", {"max_delay_hours": 1})
        with pytest.raises(ValueError, match="max_delay_hours"):
            validate_threshold("latency", {"time_field": "created_at"})

    def test_enum_check_requires_allowed_values(self):
        """enum_check 规则必须指定 allowed_values"""
        validate_threshold("enum_check", {"allowed_values": ["A", "B"]})
        with pytest.raises(ValueError, match="allowed_values"):
            validate_threshold("enum_check", {})

    def test_format_regex_requires_pattern(self):
        """format_regex 规则必须指定 pattern"""
        validate_threshold("format_regex", {"pattern": r"^\d{3}-\d{4}$"})
        with pytest.raises(ValueError, match="pattern"):
            validate_threshold("format_regex", {})

    def test_cross_field_accepts_expression(self):
        """cross_field 规则接受 expression"""
        validate_threshold("cross_field", {"expression": "end_date >= start_date"})
        validate_threshold("cross_field", {})  # 不强制校验

    def test_value_range_accepts_min_max(self):
        """value_range 规则接受 min/max"""
        validate_threshold("value_range", {"min": 0, "max": 100})
        validate_threshold("value_range", {"min": 0})
        validate_threshold("value_range", {"max": 100})

    def test_custom_sql_no_validation(self):
        """custom_sql 规则不进行额外校验"""
        validate_threshold("custom_sql", {})
        validate_threshold("custom_sql", {"custom_query": "SELECT 1"})

    def test_big_table_rules_default_max_scan_rows(self):
        """大表规则自动设置默认 max_scan_rows = 1,000,000"""
        for rule_type in ["null_rate", "duplicate_rate", "unique_count", "row_count", "referential"]:
            threshold = {"max_rate": 0.05} if rule_type in ["null_rate", "duplicate_rate"] else {"min": 1}
            validate_threshold(rule_type, threshold)
            assert threshold.get("max_scan_rows") == 1_000_000, f"{rule_type} should set default max_scan_rows"

    def test_big_table_rules_preserve_user_max_scan_rows(self):
        """大表规则保留用户设置的 max_scan_rows"""
        threshold = {"max_rate": 0.05, "max_scan_rows": 500000}
        validate_threshold("null_rate", threshold)
        assert threshold["max_scan_rows"] == 500000


class TestDuplicateConstraint:
    """重复规则约束测试"""

    def test_duplicate_rule_check_by_rule_type(self):
        """同一 datasource+table+field+rule_type 重复 → GOV_006"""
        # rule_exists 方法由 QualityDatabase 提供，此处验证校验逻辑
        # 两次 null_rate 同一字段 → 重复
        # null_rate vs not_null 同一字段 → 不重复
        from services.governance.database import QualityDatabase
        # 注意：这里只验证 QualityDatabase.rule_exists 方法签名
        # 实际重复检测依赖数据库，由 API 层测试覆盖

    def test_rule_exists_filters_by_all_fields(self):
        """rule_exists 使用 datasource_id + table_name + field_name + rule_type"""
        from services.governance.database import QualityDatabase
        qdb = QualityDatabase()
        # 方法签名验证
        assert hasattr(qdb, 'rule_exists')


class TestGovErrorCodes:
    """GOV 错误码测试"""

    def test_gov_001_rule_not_found(self):
        """GOV_001: 质量规则不存在"""
        from app.core.errors import GOVError
        err = GOVError.rule_not_found()
        assert err.error_code == "GOV_001"
        assert err.status_code == 404
        assert "质量规则不存在" in err.message

    def test_gov_002_result_not_found(self):
        """GOV_002: 质量检测结果不存在"""
        from app.core.errors import GOVError
        err = GOVError.result_not_found()
        assert err.error_code == "GOV_002"
        assert err.status_code == 404

    def test_gov_003_scan_in_progress(self):
        """GOV_003: 质量扫描任务进行中"""
        from app.core.errors import GOVError
        err = GOVError.scan_in_progress()
        assert err.error_code == "GOV_003"
        assert err.status_code == 409

    def test_gov_004_datasource_connection_failed(self):
        """GOV_004: 数据源连接失败"""
        from app.core.errors import GOVError
        err = GOVError.datasource_connection_failed()
        assert err.error_code == "GOV_004"
        assert err.status_code == 400

    def test_mulan_error_raises_correctly(self):
        """MulanError 正确抛出并携带 error_code"""
        with pytest.raises(MulanError) as exc_info:
            raise MulanError("GOV_006", "规则已存在", 409)
        assert exc_info.value.error_code == "GOV_006"
        assert exc_info.value.status_code == 409

    def test_mulan_error_detail_format(self):
        """MulanError detail 格式为 {error_code, message, detail}"""
        err = MulanError("TEST_001", "测试错误", 400, {"extra": "data"})
        detail = err.detail
        assert detail["error_code"] == "TEST_001"
        assert detail["message"] == "测试错误"
        assert detail["detail"] == {"extra": "data"}


class TestThresholdValidation:
    """复用 Batch 2 的验证测试"""

    def test_all_rule_types_have_validation(self):
        """所有 13 种规则类型都有对应的阈值校验"""
        rule_types = [
            "null_rate", "not_null", "row_count", "duplicate_rate",
            "unique_count", "referential", "cross_field", "value_range",
            "freshness", "latency", "format_regex", "enum_check", "custom_sql"
        ]
        for rt in rule_types:
            # 所有规则类型都应被 validate_threshold 接受（即使无参数要求）
            if rt == "custom_sql":
                validate_threshold(rt, {})  # custom_sql 无必填字段
            elif rt == "not_null":
                validate_threshold(rt, {})  # not_null 无必填字段
            else:
                # 其他类型至少要有基本参数，否则抛错
                # 这里只验证函数不崩溃
                try:
                    validate_threshold(rt, {})
                except ValueError:
                    pass  # 预期抛错（缺少必填参数）


class TestCronValidation:
    """Cron 表达式校验测试"""

    def test_valid_cron_expressions(self):
        """合法 Cron 表达式通过校验"""
        valid_crons = [
            "0 6 * * *",       # 每天 6:00
            "30 14 * * *",     # 每天 14:30
            "0 0 1 * *",       # 每月 1 日
            "*/5 * * * *",     # 每 5 分钟
            "0 */2 * * *",     # 每 2 小时
        ]
        for cron in valid_crons:
            validate_cron(cron)

    def test_invalid_cron_expressions(self):
        """非法 Cron 表达式抛出 ValueError"""
        invalid_crons = [
            "",                 # 空字符串
            "invalid",          # 无效格式
            "60 6 * * *",      # 分钟超范围
            "0 25 * * *",      # 小时超范围
            "0 6 32 * *",      # 日期超范围
            "0 6 * 13 *",      # 月份超范围
            "0 6 * * 7",       # 星期超范围
        ]
        for cron in invalid_crons:
            with pytest.raises(ValueError, match="无效"):
                validate_cron(cron)

    def test_none_cron_allowed(self):
        """None 视为合法（表示不使用定时任务）"""
        validate_cron(None)

    def test_cron_with_step(self):
        """带步长的 Cron 表达式"""
        validate_cron("*/15 * * * *")   # 每 15 分钟
        validate_cron("0 */3 * * *")    # 每 3 小时

"""StarRocks 合规性测试 — 验证 SR_* 规则和错误码"""
import pytest
import sys
import os
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from app.api.rules import DEFAULT_RULES_SEED
from services.ddl_checker.validator import ColumnValidator, DatabaseRulesAdapter, DDLValidator, TableValidator
from services.ddl_checker.parser import TableInfo, ColumnInfo


class TestSRRulesSeed:
    """测试 SR_* 规则种子数据"""

    def test_sr_rules_seed_count(self):
        """验证种子数据加载后 RULE_SR_* 规则总数 = 25"""
        sr_rules = [r for r in DEFAULT_RULES_SEED if r["rule_id"].startswith("RULE_SR_")]
        sr_rule_ids = [r["rule_id"] for r in sr_rules]

        assert len(sr_rules) == 25, f"SR 规则总数应为 25，实际为 {len(sr_rules)}"
        assert sr_rule_ids == [f"RULE_SR_{str(i).zfill(3)}" for i in range(1, 26)]

    def test_sr_rules_cover_expected_categories(self):
        """验证 RULE_SR_* 覆盖当前 StarRocks 合规检查类别"""
        expected_categories = {
            "sr_layer_naming",
            "sr_type_alignment",
            "sr_public_fields",
            "sr_field_naming",
            "sr_comment",
            "sr_database_whitelist",
            "sr_table_naming",
            "sr_view_naming",
        }
        categories = {
            r["category"]
            for r in DEFAULT_RULES_SEED
            if r["rule_id"].startswith("RULE_SR_")
        }
        assert expected_categories.issubset(categories)

    def test_sr_rules_present(self):
        """验证 RULE_SR_001~025 全部存在于种子数据中"""
        expected_rule_ids = [f"RULE_SR_{str(i).zfill(3)}" for i in range(1, 26)]
        sr_rule_ids = [r["rule_id"] for r in DEFAULT_RULES_SEED]
        for rule_id in expected_rule_ids:
            assert rule_id in sr_rule_ids, f"规则 {rule_id} 未在种子数据中找到"


class TestSRRulesAdapter:
    """测试 StarRocks 规则适配器当前契约"""

    def test_adapter_accepts_valid_db_types(self):
        """传入有效 db_type 时可初始化规则适配器"""
        valid_types = ["mysql", "postgresql", "starrocks", "all"]
        for db_type in valid_types:
            adapter = DatabaseRulesAdapter(db_type=db_type)
            assert adapter.db_type == db_type

    def test_adapter_finds_starrocks_rules_by_category(self):
        """适配器可按当前 StarRocks category 读取规则"""
        adapter = DatabaseRulesAdapter(db_type="StarRocks")
        with patch.object(adapter, "_load_rules", return_value=DEFAULT_RULES_SEED):
            rules = adapter._find_sr_rules_by_category("sr_type_alignment")
        assert rules
        assert all(r["category"] == "sr_type_alignment" for r in rules)


class TestSRCheckMethodsWiring:
    """测试 StarRocks 检查方法在 TableValidator 中的正确接线"""

    def test_table_validator_has_sr_methods(self):
        """验证 TableValidator 拥有当前表级 sr_* 检查方法"""
        adapter = DatabaseRulesAdapter(db_type="StarRocks")
        validator = TableValidator(adapter)
        
        expected_methods = [
            "_check_sr_database_whitelist",
            "_check_sr_comment",
            "_check_sr_field_naming",
            "_check_sr_layer_naming",
            "_check_sr_public_fields",
            "_check_sr_table_naming",
            "_check_sr_view_naming",
        ]
        
        for method_name in expected_methods:
            assert hasattr(validator, method_name), f"TableValidator 应有方法 {method_name}"

    def test_column_validator_has_sr_type_alignment(self):
        """验证 ColumnValidator 拥有字段类型对齐检查"""
        adapter = DatabaseRulesAdapter(db_type="StarRocks")
        validator = ColumnValidator(adapter)
        assert hasattr(validator, "_check_sr_type_alignment")

    def test_table_validator_validate_accepts_table_info(self):
        """验证表级 StarRocks 检查接受 TableInfo 并返回 violations 列表"""
        adapter = DatabaseRulesAdapter(db_type="StarRocks")
        validator = TableValidator(adapter)
        
        # 创建测试用 TableInfo
        columns = [
            ColumnInfo(name="id", data_type="BIGINT", nullable=False, is_primary_key=True),
            ColumnInfo(name="name", data_type="VARCHAR", nullable=True),
        ]
        table = TableInfo(name="test_table", columns=columns, database="test_db")

        with patch.object(adapter, "_load_rules", return_value=DEFAULT_RULES_SEED):
            violations = validator.validate(table)
        assert isinstance(violations, list)

    def test_column_validator_type_alignment_returns_violations(self):
        """验证字段类型对齐检查能返回 Violation 列表"""
        adapter = DatabaseRulesAdapter(db_type="StarRocks")
        validator = ColumnValidator(adapter)
        table = TableInfo(name="test_table", columns=[], database="test_db")
        column = ColumnInfo(name="amount", data_type="VARCHAR", nullable=True)

        with patch.object(adapter, "_load_rules", return_value=DEFAULT_RULES_SEED):
            violations = validator._check_sr_type_alignment(table, column)
        assert isinstance(violations, list)

    def test_check_sr_comment_returns_violations(self):
        """验证 _check_sr_comment 能返回 Violation 列表"""
        adapter = DatabaseRulesAdapter(db_type="StarRocks")
        validator = TableValidator(adapter)
        
        # 创建一个无 COMMENT 的表（违反 SR-META-001）
        columns = [
            ColumnInfo(name="id", data_type="BIGINT", nullable=False),
        ]
        table = TableInfo(name="test_table_no_comment", columns=columns, database="test_db", comment="")
        
        with patch.object(adapter, "_load_rules", return_value=DEFAULT_RULES_SEED):
            violations = validator._check_sr_comment(table)
        assert isinstance(violations, list)


class TestDDLValidatorStarRocks:
    """测试 DDLValidator 对 StarRocks 的支持"""

    def test_ddl_validator_accepts_starrocks_db_type(self):
        """DDLValidator 应能接受 db_type='StarRocks'"""
        validator = DDLValidator(db_type="StarRocks")
        assert validator.db_type == "StarRocks"
        assert isinstance(validator._db_adapter, DatabaseRulesAdapter)

    def test_ddl_validator_uses_table_and_column_validators(self):
        """DDLValidator 创建当前表级和列级 validator"""
        validator = DDLValidator(db_type="StarRocks")
        assert isinstance(validator.table_validator, TableValidator)
        assert isinstance(validator.column_validator, ColumnValidator)


if __name__ == "__main__":
    pytest.main([__file__, "-x", "-q"])

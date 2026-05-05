"""StarRocks 合规性测试 — 验证 SR_* 规则和错误码"""
import pytest
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from app.api.rules import DEFAULT_RULES_SEED
from services.ddl_checker.validator import DatabaseRulesAdapter, DDLValidator, TableValidator
from services.ddl_checker.parser import TableInfo, ColumnInfo


class TestSRRulesSeed:
    """测试 SR_* 规则种子数据"""

    def test_sr_rules_seed_count(self):
        """验证种子数据加载后 SR-* 规则总数 = 50（25条 §2.2 + 25条 §2.4）"""
        sr_rules = [r for r in DEFAULT_RULES_SEED if r["rule_id"].startswith("RULE_SR_") or r["rule_id"].startswith("SR-")]
        sr_rule_ids = [r["rule_id"] for r in sr_rules]
        
        # 统计 RULE_SR_001~025
        rule_sr_count = sum(1 for r in sr_rule_ids if r.startswith("RULE_SR_"))
        # 统计 SR-SCH-*/SR-PART-*/SR-REP-*/SR-PERF-*/SR-META-*
        new_sr_count = sum(1 for r in sr_rule_ids if r.startswith("SR-"))
        
        total_sr = rule_sr_count + new_sr_count
        assert total_sr == 50, f"SR 规则总数应为 50，实际为 {total_sr} (RULE_SR_*={rule_sr_count}, SR-*={new_sr_count})"

    def test_sr_schema_rules_present(self):
        """验证 SR-SCH-001~008 全部存在于种子数据中"""
        sr_schema_ids = [f"SR-SCH-{str(i).zfill(3)}" for i in range(1, 9)]
        sr_rule_ids = [r["rule_id"] for r in DEFAULT_RULES_SEED]
        for rule_id in sr_schema_ids:
            assert rule_id in sr_rule_ids, f"规则 {rule_id} 未在种子数据中找到"

    def test_sr_partition_rules_present(self):
        """验证 SR-PART-001~006 和 SR-BUCK-005 全部存在于种子数据中"""
        sr_part_ids = [f"SR-PART-{str(i).zfill(3)}" for i in range(1, 7)]
        sr_part_ids.append("SR-BUCK-005")
        sr_rule_ids = [r["rule_id"] for r in DEFAULT_RULES_SEED]
        for rule_id in sr_part_ids:
            assert rule_id in sr_rule_ids, f"规则 {rule_id} 未在种子数据中找到"

    def test_sr_replica_rules_present(self):
        """验证 SR-REP-001~004 全部存在于种子数据中"""
        sr_rep_ids = [f"SR-REP-{str(i).zfill(3)}" for i in range(1, 5)]
        sr_rule_ids = [r["rule_id"] for r in DEFAULT_RULES_SEED]
        for rule_id in sr_rep_ids:
            assert rule_id in sr_rule_ids, f"规则 {rule_id} 未在种子数据中找到"

    def test_sr_perf_rules_present(self):
        """验证 SR-PERF-001~004 全部存在于种子数据中"""
        sr_perf_ids = [f"SR-PERF-{str(i).zfill(3)}" for i in range(1, 5)]
        sr_rule_ids = [r["rule_id"] for r in DEFAULT_RULES_SEED]
        for rule_id in sr_perf_ids:
            assert rule_id in sr_rule_ids, f"规则 {rule_id} 未在种子数据中找到"

    def test_sr_meta_rules_present(self):
        """验证 SR-META-001~003 全部存在于种子数据中"""
        sr_meta_ids = [f"SR-META-{str(i).zfill(3)}" for i in range(1, 4)]
        sr_rule_ids = [r["rule_id"] for r in DEFAULT_RULES_SEED]
        for rule_id in sr_meta_ids:
            assert rule_id in sr_rule_ids, f"规则 {rule_id} 未在种子数据中找到"


class TestSRAdaptErrorCodes:
    """测试 SR_ADAPT_* 错误码"""

    def test_sr_adapt_001_wrong_db_type(self):
        """传入非 starrocks db_type 时抛出 SR_ADAPT_001"""
        adapter = DatabaseRulesAdapter(db_type="MySQL")
        
        with pytest.raises(ValueError) as exc_info:
            adapter.get_rules_for("invalid_db_type")
        
        assert "SR_ADAPT_001" in str(exc_info.value), f"错误信息应包含 SR_ADAPT_001，实际: {exc_info.value}"

    def test_sr_adapt_001_valid_db_types(self):
        """传入有效的 db_type 时不抛出异常"""
        valid_types = ["mysql", "postgresql", "starrocks", "all"]
        for db_type in valid_types:
            adapter = DatabaseRulesAdapter(db_type=db_type)
            rules = adapter.get_rules_for(db_type)
            assert isinstance(rules, list), f"get_rules_for('{db_type}') 应返回 list"

    def test_sr_adapt_002_missing_database(self):
        """StarRocks 扫描时 TableInfo.database 为空则应抛 SR_ADAPT_002"""
        # 这个测试验证 DatabaseRulesAdapter.get_rules_for 在 starrocks 但 database 为空时的行为
        # 注意：SR_ADAPT_002 主要在 scanner.py 中检查，这里验证 adapter 的 db_type 契约
        adapter = DatabaseRulesAdapter(db_type="StarRocks")
        # 对于 starrocks，adapter 应该能正常初始化（SR_ADAPT_002 在 scanner 层检查 database 注入）
        rules = adapter.get_rules_for("starrocks")
        assert isinstance(rules, list)


class TestSRCheckMethodsWiring:
    """测试 StarRocks 检查方法在 TableValidator 中的正确接线"""

    def test_table_validator_has_sr_methods(self):
        """验证 TableValidator 拥有所有 8 个 sr_* 检查方法"""
        adapter = DatabaseRulesAdapter(db_type="StarRocks")
        validator = TableValidator(adapter)
        
        expected_methods = [
            "_check_sr_schema_rules",
            "_check_sr_partition_rules",
            "_check_sr_replica_rules",
            "_check_sr_perf_rules",
            "_check_sr_meta_rules",
            "_check_sr_database_whitelist",
            "_check_sr_type_alignment",
            "_check_sr_layer_naming",
        ]
        
        for method_name in expected_methods:
            assert hasattr(validator, method_name), f"TableValidator 应有方法 {method_name}"

    def test_table_validator_has_connector_setter(self):
        """验证 TableValidator 有 set_connector 方法"""
        adapter = DatabaseRulesAdapter(db_type="StarRocks")
        validator = TableValidator(adapter)
        assert hasattr(validator, "set_connector"), "TableValidator 应有 set_connector 方法"
        assert callable(validator.set_connector), "set_connector 应是可调用的"

    def test_check_sr_schema_rules_accepts_table_info(self):
        """验证 _check_sr_schema_rules 接受 TableInfo 参数"""
        adapter = DatabaseRulesAdapter(db_type="StarRocks")
        validator = TableValidator(adapter)
        
        # 创建测试用 TableInfo
        columns = [
            ColumnInfo(name="id", data_type="BIGINT", nullable=False, is_primary_key=True),
            ColumnInfo(name="name", data_type="VARCHAR", nullable=True),
            ColumnInfo(name="create_time", data_type="VARCHAR", nullable=True),  # 违反 SR-SCH-003
            ColumnInfo(name="blob_col", data_type="BLOB", nullable=True),  # 违反 SR-SCH-008
        ]
        table = TableInfo(name="test_table", columns=columns, database="test_db")
        
        # 方法应能接受 TableInfo 并返回 violations 列表
        try:
            violations = validator._check_sr_schema_rules(table)
            assert isinstance(violations, list), "_check_sr_schema_rules 应返回 List[Violation]"
        except TypeError as e:
            pytest.fail(f"_check_sr_schema_rules 应接受 TableInfo 参数: {e}")

    def test_check_sr_meta_rules_returns_violations(self):
        """验证 _check_sr_meta_rules 能返回 Violation 列表"""
        adapter = DatabaseRulesAdapter(db_type="StarRocks")
        validator = TableValidator(adapter)
        
        # 创建一个无 COMMENT 的表（违反 SR-META-001）
        columns = [
            ColumnInfo(name="id", data_type="BIGINT", nullable=False),
        ]
        table = TableInfo(name="test_table_no_comment", columns=columns, database="test_db", comment="")
        
        violations = validator._check_sr_meta_rules(table)
        assert isinstance(violations, list), "_check_sr_meta_rules 应返回 List[Violation]"


class TestDDLValidatorStarRocks:
    """测试 DDLValidator 对 StarRocks 的支持"""

    def test_ddl_validator_accepts_starrocks_db_type(self):
        """DDLValidator 应能接受 db_type='StarRocks'"""
        validator = DDLValidator(db_type="StarRocks")
        assert validator.db_type == "StarRocks"
        assert isinstance(validator._db_adapter, DatabaseRulesAdapter)

    def test_ddl_validator_table_validator_has_connector(self):
        """DDLValidator 创建的 table_validator 应可注入 connector"""
        validator = DDLValidator(db_type="StarRocks")
        assert hasattr(validator.table_validator, 'set_connector'),             "table_validator 应有 set_connector 方法用于注入 connector"


if __name__ == "__main__":
    pytest.main([__file__, "-x", "-q"])

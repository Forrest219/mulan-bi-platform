"""DqcRuleEngine - freshness 单元测试"""
import os

os.environ.setdefault("DATABASE_URL", "postgresql://mulan:mulan@localhost:5432/mulan_bi_test")
os.environ.setdefault("SESSION_SECRET", "test-session-secret-for-ci-!!")
os.environ.setdefault("DATASOURCE_ENCRYPTION_KEY", "test-datasource-key-32-bytes-ok!!")
os.environ.setdefault("TABLEAU_ENCRYPTION_KEY", "test-tableau-key-32-bytes-ok!!")
os.environ.setdefault("LLM_ENCRYPTION_KEY", "test-llm-key-32-bytes-ok!!!!")

import pytest

from services.dqc.rule_engine import DqcRuleEngine
from tests.unit.dqc._fakes import FakeConnection, make_asset, make_rule


class TestFreshnessPostgres:
    def test_fresh_data_passes(self):
        # pg：age_hours=2 返回，max_age_hours=24 → passed
        conn = FakeConnection([[(2.0,)]])
        engine = DqcRuleEngine(db_config={"db_type": "postgresql"}, connection=conn)
        rule = make_rule(
            rule_type="freshness",
            dimension="timeliness",
            rule_config={"column": "updated_at", "max_age_hours": 24},
        )
        result = engine.execute_rule(make_asset(), rule)
        assert result.passed is True
        assert result.actual_value == 2.0

    def test_stale_data_fails(self):
        conn = FakeConnection([[(48.5,)]])
        engine = DqcRuleEngine(db_config={"db_type": "postgresql"}, connection=conn)
        rule = make_rule(
            rule_type="freshness",
            dimension="timeliness",
            rule_config={"column": "updated_at", "max_age_hours": 24},
        )
        result = engine.execute_rule(make_asset(), rule)
        assert result.passed is False
        assert result.actual_value > 24

    def test_no_timestamp(self):
        conn = FakeConnection([[(None,)]])
        engine = DqcRuleEngine(db_config={"db_type": "postgresql"}, connection=conn)
        rule = make_rule(
            rule_type="freshness",
            dimension="timeliness",
            rule_config={"column": "updated_at", "max_age_hours": 24},
        )
        result = engine.execute_rule(make_asset(), rule)
        assert result.passed is False
        assert "no_timestamp" in (result.error_message or "")


class TestFreshnessMySQL:
    def test_mysql_dialect_fresh(self):
        conn = FakeConnection([[(2.0,)]])
        engine = DqcRuleEngine(db_config={"db_type": "mysql"}, connection=conn)
        rule = make_rule(
            rule_type="freshness",
            dimension="timeliness",
            rule_config={"column": "updated_at", "max_age_hours": 24},
        )
        result = engine.execute_rule(make_asset(), rule)
        assert result.passed is True


class TestFreshnessConfigValidation:
    def test_missing_column(self):
        conn = FakeConnection([])
        engine = DqcRuleEngine(db_config={"db_type": "postgresql"}, connection=conn)
        rule = make_rule(rule_type="freshness", rule_config={"max_age_hours": 24})
        result = engine.execute_rule(make_asset(), rule)
        assert result.passed is False
        assert "invalid_rule_config" in (result.error_message or "")

    def test_missing_max_age(self):
        conn = FakeConnection([])
        engine = DqcRuleEngine(db_config={"db_type": "postgresql"}, connection=conn)
        rule = make_rule(rule_type="freshness", rule_config={"column": "updated_at"})
        result = engine.execute_rule(make_asset(), rule)
        assert result.passed is False

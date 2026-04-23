"""DqcRuleEngine - null_rate 单元测试"""
import os

os.environ.setdefault("DATABASE_URL", "postgresql://mulan:mulan@localhost:5432/mulan_bi_test")
os.environ.setdefault("SESSION_SECRET", "test-session-secret-for-ci-!!")
os.environ.setdefault("DATASOURCE_ENCRYPTION_KEY", "test-datasource-key-32-bytes-ok!!")
os.environ.setdefault("TABLEAU_ENCRYPTION_KEY", "test-tableau-key-32-bytes-ok!!")
os.environ.setdefault("LLM_ENCRYPTION_KEY", "test-llm-key-32-bytes-ok!!!!")

import pytest

from services.dqc.rule_engine import DqcRuleEngine
from tests.unit.dqc._fakes import FakeConnection, make_asset, make_rule


def _engine_with(conn):
    return DqcRuleEngine(db_config={"db_type": "postgresql"}, connection=conn)


class TestNullRate:
    def test_pass_when_below_threshold(self):
        # check_scan_limit: row_count=100; rule query: null=1, total=100 → rate=0.01
        conn = FakeConnection([[(100,)], [(1, 100)]])
        engine = _engine_with(conn)
        rule = make_rule(rule_type="null_rate", rule_config={"column": "user_id", "max_rate": 0.05})
        result = engine.execute_rule(make_asset(), rule)
        assert result.passed is True
        assert result.actual_value == pytest.approx(0.01)
        assert result.error_message is None

    def test_fail_when_above_threshold(self):
        conn = FakeConnection([[(100,)], [(10, 100)]])
        engine = _engine_with(conn)
        rule = make_rule(rule_type="null_rate", rule_config={"column": "user_id", "max_rate": 0.05})
        result = engine.execute_rule(make_asset(), rule)
        assert result.passed is False
        assert result.actual_value == pytest.approx(0.1)

    def test_all_null(self):
        conn = FakeConnection([[(10,)], [(10, 10)]])
        engine = _engine_with(conn)
        rule = make_rule(rule_type="null_rate", rule_config={"column": "c", "max_rate": 0.5})
        result = engine.execute_rule(make_asset(), rule)
        assert result.actual_value == 1.0
        assert result.passed is False

    def test_all_non_null(self):
        conn = FakeConnection([[(10,)], [(0, 10)]])
        engine = _engine_with(conn)
        rule = make_rule(rule_type="null_rate", rule_config={"column": "c", "max_rate": 0.01})
        result = engine.execute_rule(make_asset(), rule)
        assert result.actual_value == 0.0
        assert result.passed is True

    def test_zero_rows_passes(self):
        # scan_limit row_count=0; 主查询 null=0 total=0
        conn = FakeConnection([[(0,)], [(0, 0)]])
        engine = _engine_with(conn)
        rule = make_rule(rule_type="null_rate", rule_config={"column": "c", "max_rate": 0})
        result = engine.execute_rule(make_asset(), rule)
        assert result.passed is True
        assert result.actual_value == 0.0

    def test_scan_row_limit_exceeded(self):
        # row_count > max_scan_rows → 熔断为失败，error_message 含 max_scan_rows
        conn = FakeConnection([[(5_000_000,)]])
        engine = _engine_with(conn)
        rule = make_rule(
            rule_type="null_rate",
            rule_config={"column": "c", "max_rate": 0.01, "max_scan_rows": 1_000_000},
        )
        result = engine.execute_rule(make_asset(), rule)
        assert result.passed is False
        assert "max_scan_rows" in (result.error_message or "")

    def test_missing_config(self):
        conn = FakeConnection([])
        engine = _engine_with(conn)
        rule = make_rule(rule_type="null_rate", rule_config={"column": "c"})  # 缺 max_rate
        result = engine.execute_rule(make_asset(), rule)
        assert result.passed is False
        assert "invalid_rule_config" in (result.error_message or "")

"""DqcRuleEngine - range_check 单元测试"""
import os

os.environ.setdefault("DATABASE_URL", "postgresql://mulan:mulan@localhost:5432/mulan_bi_test")
os.environ.setdefault("SESSION_SECRET", "test-session-secret-for-ci-!!")
os.environ.setdefault("DATASOURCE_ENCRYPTION_KEY", "test-datasource-key-32-bytes-ok!!")
os.environ.setdefault("TABLEAU_ENCRYPTION_KEY", "test-tableau-key-32-bytes-ok!!")
os.environ.setdefault("LLM_ENCRYPTION_KEY", "test-llm-key-32-bytes-ok!!!!")

import pytest

from services.dqc.rule_engine import DqcRuleEngine
from tests.unit.dqc._fakes import FakeConnection, make_asset, make_rule


def _engine(conn):
    return DqcRuleEngine(db_config={"db_type": "postgresql"}, connection=conn)


class TestRangeCheckMinMaxAll:
    def test_no_violation(self):
        # scan_limit: row_count=100
        # total NOT NULL=100
        # violations=0
        conn = FakeConnection([[(100,)], [(100,)], [(0,)]])
        engine = _engine(conn)
        rule = make_rule(
            rule_type="range_check",
            dimension="validity",
            rule_config={"column": "amount", "min": 0, "max": 100, "check_mode": "min_max_all"},
        )
        result = engine.execute_rule(make_asset(), rule)
        assert result.passed is True
        assert result.actual_value == 0.0

    def test_has_violation(self):
        conn = FakeConnection([[(100,)], [(100,)], [(5,)]])
        engine = _engine(conn)
        rule = make_rule(
            rule_type="range_check",
            dimension="validity",
            rule_config={"column": "amount", "min": 0, "max": 100, "check_mode": "min_max_all"},
        )
        result = engine.execute_rule(make_asset(), rule)
        assert result.passed is False
        assert result.actual_value == pytest.approx(0.05)

    def test_null_ignored_when_all_null(self):
        conn = FakeConnection([[(100,)], [(0,)]])
        engine = _engine(conn)
        rule = make_rule(
            rule_type="range_check",
            dimension="validity",
            rule_config={"column": "amount", "min": 0, "max": 100, "check_mode": "min_max_all"},
        )
        result = engine.execute_rule(make_asset(), rule)
        # total NOT NULL = 0 → 无可违规行 → passed
        assert result.passed is True
        assert result.actual_value == 0.0


class TestRangeCheckAvg:
    def test_avg_in_range(self):
        conn = FakeConnection([[(100,)], [(50.0,)]])
        engine = _engine(conn)
        rule = make_rule(
            rule_type="range_check",
            dimension="accuracy",
            rule_config={"column": "score", "min": 40, "max": 60, "check_mode": "avg"},
        )
        result = engine.execute_rule(make_asset(), rule)
        assert result.passed is True
        assert result.actual_value == pytest.approx(50.0)

    def test_avg_below_min(self):
        conn = FakeConnection([[(100,)], [(30.0,)]])
        engine = _engine(conn)
        rule = make_rule(
            rule_type="range_check",
            dimension="accuracy",
            rule_config={"column": "score", "min": 40, "max": 60, "check_mode": "avg"},
        )
        result = engine.execute_rule(make_asset(), rule)
        assert result.passed is False

    def test_avg_above_max(self):
        conn = FakeConnection([[(100,)], [(70.0,)]])
        engine = _engine(conn)
        rule = make_rule(
            rule_type="range_check",
            dimension="accuracy",
            rule_config={"column": "score", "min": 40, "max": 60, "check_mode": "avg"},
        )
        result = engine.execute_rule(make_asset(), rule)
        assert result.passed is False

    def test_missing_column(self):
        conn = FakeConnection([])
        engine = _engine(conn)
        rule = make_rule(rule_type="range_check", rule_config={"min": 0, "max": 1})
        result = engine.execute_rule(make_asset(), rule)
        assert result.passed is False
        assert "invalid_rule_config" in (result.error_message or "")

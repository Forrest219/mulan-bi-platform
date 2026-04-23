"""DqcRuleEngine - uniqueness 单元测试"""
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


class TestUniqueness:
    def test_zero_duplicate(self):
        # row_count=100, distinct=100 total=100 → dup_rate=0
        conn = FakeConnection([[(100,)], [(100, 100)]])
        engine = _engine(conn)
        rule = make_rule(
            rule_type="uniqueness",
            dimension="uniqueness",
            rule_config={"columns": ["user_id"]},
        )
        result = engine.execute_rule(make_asset(), rule)
        assert result.passed is True
        assert result.actual_value == 0.0

    def test_all_duplicate(self):
        # distinct=1, total=100 → dup_rate=0.99
        conn = FakeConnection([[(100,)], [(1, 100)]])
        engine = _engine(conn)
        rule = make_rule(
            rule_type="uniqueness",
            dimension="uniqueness",
            rule_config={"columns": ["user_id"]},
        )
        result = engine.execute_rule(make_asset(), rule)
        assert result.passed is False
        assert result.actual_value == pytest.approx(0.99)

    def test_multi_column_combo(self):
        conn = FakeConnection([[(50,)], [(50, 50)]])
        engine = _engine(conn)
        rule = make_rule(
            rule_type="uniqueness",
            dimension="uniqueness",
            rule_config={"columns": ["order_id", "dt"]},
        )
        result = engine.execute_rule(make_asset(), rule)
        assert result.passed is True
        assert result.actual_value == 0.0

    def test_empty_table(self):
        conn = FakeConnection([[(0,)], [(0, 0)]])
        engine = _engine(conn)
        rule = make_rule(
            rule_type="uniqueness",
            dimension="uniqueness",
            rule_config={"columns": ["id"]},
        )
        result = engine.execute_rule(make_asset(), rule)
        assert result.passed is True
        assert result.actual_value == 0.0

    def test_columns_missing_rejected(self):
        conn = FakeConnection([])
        engine = _engine(conn)
        rule = make_rule(rule_type="uniqueness", dimension="uniqueness", rule_config={})
        result = engine.execute_rule(make_asset(), rule)
        assert result.passed is False
        assert "invalid_rule_config" in (result.error_message or "")

    def test_allow_max_dup_rate(self):
        # total=100, distinct=99, dup_rate=0.01, 允许 0.05 → passed
        conn = FakeConnection([[(100,)], [(99, 100)]])
        engine = _engine(conn)
        rule = make_rule(
            rule_type="uniqueness",
            dimension="uniqueness",
            rule_config={"columns": ["id"], "max_duplicate_rate": 0.05},
        )
        result = engine.execute_rule(make_asset(), rule)
        assert result.passed is True

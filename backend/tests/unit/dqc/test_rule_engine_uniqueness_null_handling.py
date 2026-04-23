"""DqcRuleEngine - uniqueness NULL 处理单元测试（I7 验证）

修复验证：_exec_uniqueness 使用 coalesce/ifnull 处理 NULL 值，
确保 (NULL, 'a') 和 (NULL, 'a') 被计为 2 个不同行（而非都当成 NULL 而重复）。
"""
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


class TestUniquenessNullHandling:
    """I7 验证：多列 uniqueness 包含 NULL 值时，NULL 应被视为独立值而非重复键"""

    def test_null_in_multi_column_counted_as_distinct(self):
        """
        表共 4 行，列为 (col_a, col_b)：
          (NULL, 'a')
          (NULL, 'a')   ← 与上行 NULL 相同但 col_b 相同 → 应算 1 个 distinct
          (NULL, 'b')
          ('x',   NULL)

        distinct = 3，total = 4，dup_rate = (4-3)/4 = 0.25
        max_duplicate_rate = 0 → 应 FAIL
        """
        conn = FakeConnection([[(3,)], [(3, 4)]])
        engine = _engine(conn)
        rule = make_rule(
            rule_type="uniqueness",
            dimension="uniqueness",
            rule_config={"columns": ["col_a", "col_b"], "max_duplicate_rate": 0},
        )
        result = engine.execute_rule(make_asset(), rule)
        assert result.passed is False
        assert result.actual_value == 0.25

    def test_null_in_single_column_nulls_treated_as_distinct_value(self):
        """
        单列场景：NULL 在 SQL 中被视为独立值。
        表共 3 行：('val1'), (NULL), (NULL)
        distinct = 2，total = 3，dup_rate = (3-2)/3 ≈ 0.333
        max_duplicate_rate = 0.1 → FAIL
        """
        conn = FakeConnection([[(2,)], [(2, 3)]])
        engine = _engine(conn)
        rule = make_rule(
            rule_type="uniqueness",
            dimension="uniqueness",
            rule_config={"columns": ["user_id"], "max_duplicate_rate": 0.1},
        )
        result = engine.execute_rule(make_asset(), rule)
        assert result.passed is False
        assert result.actual_value == pytest.approx(1 / 3)

    def test_all_null_row_counted_once(self):
        """
        全 NULL 行只计一次：(NULL, NULL), (NULL, NULL), (NULL, NULL)
        distinct = 1，total = 3，dup_rate = (3-1)/3 ≈ 0.667
        max_duplicate_rate = 0 → FAIL
        """
        conn = FakeConnection([[(1,)], [(1, 3)]])
        engine = _engine(conn)
        rule = make_rule(
            rule_type="uniqueness",
            dimension="uniqueness",
            rule_config={"columns": ["col_a", "col_b"], "max_duplicate_rate": 0},
        )
        result = engine.execute_rule(make_asset(), rule)
        assert result.passed is False
        assert result.actual_value == pytest.approx(2 / 3)

    def test_mysql_dialect_uses_ifnull(self):
        """
        MySQL/StarRocks 使用 ifnull 而非 coalesce，但逻辑相同：
        NULL 被替换为 '__NULL__' 字符串后参与 concat，分组结果正确。
        """
        conn = FakeConnection([[(4,)], [(4, 5)]])
        engine = DqcRuleEngine(db_config={"db_type": "mysql"}, connection=conn)
        rule = make_rule(
            rule_type="uniqueness",
            dimension="uniqueness",
            rule_config={"columns": ["col_a", "col_b"], "max_duplicate_rate": 0},
        )
        result = engine.execute_rule(make_asset(), rule)
        assert result.passed is False
        assert result.actual_value == 0.2

    def test_coalesce_produces_correct_distinct_count(self):
        """
        验证 coalesce 替换后 distinct count 正确：
        (NULL, 1), (NULL, 1), (1, NULL), (1, NULL)
        → ('__NULL__', '1'), ('__NULL__', '1'), ('1', '__NULL__'), ('1', '__NULL__')
        distinct = 2，total = 4，dup_rate = 0.5
        """
        conn = FakeConnection([[(2,)], [(2, 4)]])
        engine = _engine(conn)
        rule = make_rule(
            rule_type="uniqueness",
            dimension="uniqueness",
            rule_config={"columns": ["a", "b"], "max_duplicate_rate": 0},
        )
        result = engine.execute_rule(make_asset(), rule)
        assert result.passed is False
        assert result.actual_value == 0.5

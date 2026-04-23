"""DqcRuleEngine - _check_scan_limit profile_json fastpath 测试（I4 验证）

修复验证：_check_scan_limit 优先读 asset.profile_json['row_count']，
有值时跳过 COUNT(*) 查询，直接用于行数判断。
"""
import os

os.environ.setdefault("DATABASE_URL", "postgresql://mulan:mulan@localhost:5432/mulan_bi_test")
os.environ.setdefault("SESSION_SECRET", "test-session-secret-for-ci-!!")
os.environ.setdefault("DATASOURCE_ENCRYPTION_KEY", "test-datasource-key-32-bytes-ok!!")
os.environ.setdefault("TABLEAU_ENCRYPTION_KEY", "test-tableau-key-32-bytes-ok!!")
os.environ.setdefault("LLM_ENCRYPTION_KEY", "test-llm-key-32-bytes-ok!!!!")

import pytest

from services.dqc.rule_engine import DqcRuleEngine, RuleExecutionResult
from tests.unit.dqc._fakes import FakeConnection, make_asset, make_rule


def _engine(conn):
    return DqcRuleEngine(db_config={"db_type": "postgresql"}, connection=conn)


class TestScanLimitProfileJsonFastpath:
    """I4 验证：asset 有 profile_json.row_count 时不走 COUNT(*)"""

    def test_profile_json_row_count_avoids_count_query(self):
        """
        asset 有 profile_json {'row_count': 5000}：
        → 直接用 5000，不发 COUNT(*)
        → max_scan_rows 默认 1000000 → 5000 < 1000000 → OK
        → 后续 null_rate 查询正常执行（1 条 stmt，非 2 条）
        """
        conn = FakeConnection([[(5000,)], [(0, 100)]])  # [null_rate query result]
        engine = _engine(conn)
        asset = make_asset(profile_json={"row_count": 5000})
        rule = make_rule(
            rule_type="null_rate",
            dimension="completeness",
            rule_config={"column": "email", "max_rate": 0.1},
        )
        result = engine.execute_rule(asset, rule)
        # COUNT(*) 被 profile_json 跳过；只发 1 条 null_rate 查询（不是 2）
        assert result.rule_type == "null_rate"
        assert len(conn.executed_stmts) == 1  # only null_rate query, no COUNT(*)

    def test_profile_json_row_count_exceeds_limit_rejected(self):
        """
        asset 有 profile_json {'row_count': 200000}：
        → DEFAULT_MAX_SCAN_ROWS=1_000_000，200000 < 1000000 → 不超限
        → 用 max_scan_rows=100000 配置使 200000 > 100000 → 被拒绝
        """
        conn = FakeConnection([])
        engine = _engine(conn)
        asset = make_asset(profile_json={"row_count": 200000})
        rule = make_rule(
            rule_type="null_rate",
            dimension="completeness",
            rule_config={"column": "email", "max_rate": 0.1, "max_scan_rows": 100_000},
        )
        result = engine.execute_rule(asset, rule)
        assert result.passed is False
        assert "max_scan_rows_exceeded" in (result.error_message or "")

    def test_no_profile_json_falls_back_to_count_query(self):
        """
        asset 无 profile_json → 必须发 COUNT(*) 查询获取 row_count。
        COUNT(*) = 80000 < 100000 → 通过 scan_limit
        """
        conn = FakeConnection([[(80000,)]])
        engine = _engine(conn)
        asset = make_asset(profile_json=None)
        rule = make_rule(
            rule_type="null_rate",
            dimension="completeness",
            rule_config={"column": "email", "max_rate": 0.1},
        )
        result = engine.execute_rule(asset, rule)
        # COUNT(*) 应发出
        assert len(conn.executed_stmts) >= 1

    def test_empty_profile_json_falls_back_to_count(self):
        """
        asset 有 profile_json 但无 row_count 键 → fallback 到 COUNT(*)
        """
        conn = FakeConnection([[(5000,)]])
        engine = _engine(conn)
        asset = make_asset(profile_json={})
        rule = make_rule(
            rule_type="null_rate",
            dimension="completeness",
            rule_config={"column": "col", "max_rate": 0.5},
        )
        result = engine.execute_rule(asset, rule)
        assert len(conn.executed_stmts) >= 1

    def test_profile_json_row_count_explicit_none_falls_back(self):
        """
        profile_json 是 dict 但 row_count = None → fallback 到 COUNT(*)
        """
        conn = FakeConnection([[(3000,)]])
        engine = _engine(conn)
        asset = make_asset(profile_json={"row_count": None, "columns": []})
        rule = make_rule(
            rule_type="null_rate",
            dimension="completeness",
            rule_config={"column": "col", "max_rate": 0.5},
        )
        result = engine.execute_rule(asset, rule)
        assert len(conn.executed_stmts) >= 1

    def test_max_scan_rows_config_overrides_default(self):
        """
        max_scan_rows 在 rule_config 中指定时使用该值（而非 DEFAULT_MAX_SCAN_ROWS）。
        profile_json row_count=150000，max_scan_rows=200000 → 通过；无需 COUNT(*)
        """
        conn = FakeConnection([[(5000,)]])  # null_rate result
        engine = _engine(conn)
        asset = make_asset(profile_json={"row_count": 150000})
        rule = make_rule(
            rule_type="null_rate",
            dimension="completeness",
            rule_config={"column": "col", "max_rate": 0.5, "max_scan_rows": 200_000},
        )
        result = engine.execute_rule(asset, rule)
        assert result.rule_type == "null_rate"
        # 无 COUNT(*) 发出（profile_json 满足）
        assert len(conn.executed_stmts) == 1  # only null_rate query

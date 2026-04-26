"""DqcRuleEngine - VOLUME_ANOMALY 单元测试"""
import os

os.environ.setdefault("DATABASE_URL", "postgresql://mulan:mulan@localhost:5432/mulan_bi_test")
os.environ.setdefault("SESSION_SECRET", "test-session-secret-for-ci-!!")
os.environ.setdefault("DATASOURCE_ENCRYPTION_KEY", "test-datasource-key-32-bytes-ok!!")
os.environ.setdefault("TABLEAU_ENCRYPTION_KEY", "test-tableau-key-32-bytes-ok!!")
os.environ.setdefault("LLM_ENCRYPTION_KEY", "test-llm-key-32-bytes-ok!!!!")

import pytest
from unittest.mock import MagicMock, patch

from services.dqc.rule_engine import DqcRuleEngine
from tests.unit.dqc._fakes import make_asset, make_rule


def _engine():
    return DqcRuleEngine(db_config={"db_type": "postgresql"})


class TestVolumeAnomaly:
    @patch("services.dqc.database.DqcDatabase.get_latest_snapshot")
    @patch("services.dqc.database.DqcDatabase.list_snapshots")
    def test_tc01_today_1000_baseline_10000_drop_90pct_fail(self, mock_list, mock_get):
        mock_get.return_value = MagicMock(row_count_snapshot=1000)
        mock_list.return_value = [MagicMock(row_count_snapshot=10000, computed_at=None)]

        engine = _engine()
        rule = make_rule(
            rule_type="volume_anomaly",
            dimension="completeness",
            rule_config={"direction": "drop", "threshold_pct": 0.80, "comparison_window": "1d", "min_row_count": 0},
        )
        result = engine.execute_rule(make_asset(), rule)
        assert result.passed is False
        assert result.actual_value == pytest.approx(0.90, abs=0.01)
        assert result.error_message is None

    @patch("services.dqc.database.DqcDatabase.get_latest_snapshot")
    @patch("services.dqc.database.DqcDatabase.list_snapshots")
    def test_tc02_today_10000_baseline_1000_rise_900pct_fail(self, mock_list, mock_get):
        mock_get.return_value = MagicMock(row_count_snapshot=10000)
        mock_list.return_value = [MagicMock(row_count_snapshot=1000, computed_at=None)]

        engine = _engine()
        rule = make_rule(
            rule_type="volume_anomaly",
            dimension="completeness",
            rule_config={"direction": "rise", "threshold_pct": 1.0, "comparison_window": "1d"},
        )
        result = engine.execute_rule(make_asset(), rule)
        assert result.passed is False
        assert result.actual_value == pytest.approx(9.0, abs=0.01)

    @patch("services.dqc.database.DqcDatabase.get_latest_snapshot")
    @patch("services.dqc.database.DqcDatabase.list_snapshots")
    def test_tc03_small_table_below_min_row_count_passes(self, mock_list, mock_get):
        mock_get.return_value = MagicMock(row_count_snapshot=100)
        mock_list.return_value = [MagicMock(row_count_snapshot=1000, computed_at=None)]

        engine = _engine()
        rule = make_rule(
            rule_type="volume_anomaly",
            dimension="completeness",
            rule_config={"direction": "drop", "threshold_pct": 0.5, "min_row_count": 1000},
        )
        result = engine.execute_rule(make_asset(), rule)
        assert result.passed is True
        assert result.actual_value == 0.0

    @patch("services.dqc.database.DqcDatabase.get_latest_snapshot")
    @patch("services.dqc.database.DqcDatabase.list_snapshots")
    def test_tc04_no_baseline_history_insufficient(self, mock_list, mock_get):
        mock_get.return_value = MagicMock(row_count_snapshot=1000)
        mock_list.return_value = []

        engine = _engine()
        rule = make_rule(
            rule_type="volume_anomaly",
            dimension="completeness",
            rule_config={"direction": "drop", "threshold_pct": 0.80, "comparison_window": "1d"},
        )
        result = engine.execute_rule(make_asset(), rule)
        assert result.passed is False
        assert "insufficient history" in (result.error_message or "")

    @patch("services.dqc.database.DqcDatabase.get_latest_snapshot")
    @patch("services.dqc.database.DqcDatabase.list_snapshots")
    def test_tc05_drop_4pct_below_threshold_passes(self, mock_list, mock_get):
        mock_get.return_value = MagicMock(row_count_snapshot=10000)
        mock_list.return_value = [MagicMock(row_count_snapshot=10500, computed_at=None)]

        engine = _engine()
        rule = make_rule(
            rule_type="volume_anomaly",
            dimension="completeness",
            rule_config={"direction": "drop", "threshold_pct": 0.80, "comparison_window": "1d"},
        )
        result = engine.execute_rule(make_asset(), rule)
        assert result.passed is True
        assert result.actual_value == 0.0

    @patch("services.dqc.database.DqcDatabase.get_latest_snapshot")
    @patch("services.dqc.database.DqcDatabase.list_snapshots")
    def test_tc06_direction_both_drop_85pct_fails(self, mock_list, mock_get):
        mock_get.return_value = MagicMock(row_count_snapshot=1500)
        mock_list.return_value = [MagicMock(row_count_snapshot=10000, computed_at=None)]

        engine = _engine()
        rule = make_rule(
            rule_type="volume_anomaly",
            dimension="completeness",
            rule_config={"direction": "both", "threshold_pct": 0.80, "comparison_window": "1d"},
        )
        result = engine.execute_rule(make_asset(), rule)
        assert result.passed is False
        assert result.actual_value == pytest.approx(0.85, abs=0.01)

    @patch("services.dqc.database.DqcDatabase.get_latest_snapshot")
    @patch("services.dqc.database.DqcDatabase.list_snapshots")
    def test_tc07_today_zero_below_min_row_count_passes(self, mock_list, mock_get):
        mock_get.return_value = MagicMock(row_count_snapshot=0)
        mock_list.return_value = [MagicMock(row_count_snapshot=1000, computed_at=None)]

        engine = _engine()
        rule = make_rule(
            rule_type="volume_anomaly",
            dimension="completeness",
            rule_config={"direction": "drop", "threshold_pct": 0.80, "comparison_window": "1d", "min_row_count": 1000},
        )
        result = engine.execute_rule(make_asset(), rule)
        assert result.passed is True
        assert result.actual_value == 0.0

    @patch("services.dqc.database.DqcDatabase.get_latest_snapshot")
    @patch("services.dqc.database.DqcDatabase.list_snapshots")
    def test_tc07_today_small_table_zero_rows_passes_regardless_of_baseline(self, mock_list, mock_get):
        mock_get.return_value = MagicMock(row_count_snapshot=0)
        mock_list.return_value = [MagicMock(row_count_snapshot=1000000, computed_at=None)]

        engine = _engine()
        rule = make_rule(
            rule_type="volume_anomaly",
            dimension="completeness",
            rule_config={"direction": "drop", "threshold_pct": 0.80, "comparison_window": "1d", "min_row_count": 1000},
        )
        result = engine.execute_rule(make_asset(), rule)
        assert result.passed is True

    @patch("services.dqc.database.DqcDatabase.get_latest_snapshot")
    @patch("services.dqc.database.DqcDatabase.list_snapshots")
    def test_tc08_baseline_zero_avoids_division_by_zero(self, mock_list, mock_get):
        mock_get.return_value = MagicMock(row_count_snapshot=1000)
        mock_list.return_value = [MagicMock(row_count_snapshot=0, computed_at=None)]

        engine = _engine()
        rule = make_rule(
            rule_type="volume_anomaly",
            dimension="completeness",
            rule_config={"direction": "drop", "threshold_pct": 0.5, "comparison_window": "1d"},
        )
        result = engine.execute_rule(make_asset(), rule)
        assert result.passed is True
        assert result.actual_value == 0.0

    @patch("services.dqc.database.DqcDatabase.get_latest_snapshot")
    @patch("services.dqc.database.DqcDatabase.list_snapshots")
    def test_tc09_comparison_window_7d_normal_data(self, mock_list, mock_get):
        mock_get.return_value = MagicMock(row_count_snapshot=10000)
        mock_list.return_value = [MagicMock(row_count_snapshot=10050, computed_at=None)]

        engine = _engine()
        rule = make_rule(
            rule_type="volume_anomaly",
            dimension="completeness",
            rule_config={"direction": "drop", "threshold_pct": 0.80, "comparison_window": "7d"},
        )
        result = engine.execute_rule(make_asset(), rule)
        assert result.passed is True
        assert result.actual_value == 0.0

    @patch("services.dqc.database.DqcDatabase.get_latest_snapshot")
    @patch("services.dqc.database.DqcDatabase.list_snapshots")
    def test_tc10_comparison_window_30d_normal_data(self, mock_list, mock_get):
        mock_get.return_value = MagicMock(row_count_snapshot=10000)
        mock_list.return_value = [MagicMock(row_count_snapshot=9900, computed_at=None)]

        engine = _engine()
        rule = make_rule(
            rule_type="volume_anomaly",
            dimension="completeness",
            rule_config={"direction": "both", "threshold_pct": 0.80, "comparison_window": "30d"},
        )
        result = engine.execute_rule(make_asset(), rule)
        assert result.passed is True
        assert result.actual_value == 0.0

    @patch("services.dqc.database.DqcDatabase.get_latest_snapshot")
    def test_no_today_snapshot_returns_false(self, mock_get):
        mock_get.return_value = MagicMock(row_count_snapshot=None)

        engine = _engine()
        rule = make_rule(
            rule_type="volume_anomaly",
            dimension="completeness",
            rule_config={"direction": "drop", "threshold_pct": 0.80},
        )
        result = engine.execute_rule(make_asset(), rule)
        assert result.passed is False
        assert "row_count_snapshot not available" in (result.error_message or "")

    @patch("services.dqc.database.DqcDatabase.get_latest_snapshot")
    @patch("services.dqc.database.DqcDatabase.list_snapshots")
    def test_today_null_count_below_min_row_count_passes(self, mock_list, mock_get):
        mock_get.return_value = MagicMock(row_count_snapshot=500)
        mock_list.return_value = [MagicMock(row_count_snapshot=10000, computed_at=None)]

        engine = _engine()
        rule = make_rule(
            rule_type="volume_anomaly",
            dimension="completeness",
            rule_config={"direction": "drop", "threshold_pct": 0.5, "min_row_count": 1000},
        )
        result = engine.execute_rule(make_asset(), rule)
        assert result.passed is True

    # TC-10: 涨幅刚好达到阈值（边界）。threshold=1.0, today=2000, baseline=1000, direction=rise -> passed=False, actual=1.0
    @patch("services.dqc.database.DqcDatabase.get_latest_snapshot")
    @patch("services.dqc.database.DqcDatabase.list_snapshots")
    def test_tc10_rise_at_boundary_threshold_fails(self, mock_list, mock_get):
        mock_get.return_value = MagicMock(row_count_snapshot=2000)
        mock_list.return_value = [MagicMock(row_count_snapshot=1000, computed_at=None)]

        engine = _engine()
        rule = make_rule(
            rule_type="volume_anomaly",
            dimension="completeness",
            rule_config={"direction": "rise", "threshold_pct": 1.0, "comparison_window": "1d"},
        )
        result = engine.execute_rule(make_asset(), rule)
        assert result.passed is False
        assert result.actual_value == pytest.approx(1.0, abs=0.01)

    # TC-11: today=1000 刚好等于 min_row_count=1000 -> passed=True（等于门槛不触发）
    @patch("services.dqc.database.DqcDatabase.get_latest_snapshot")
    @patch("services.dqc.database.DqcDatabase.list_snapshots")
    def test_tc11_today_equals_min_row_count_passes(self, mock_list, mock_get):
        mock_get.return_value = MagicMock(row_count_snapshot=1000)
        mock_list.return_value = [MagicMock(row_count_snapshot=10000, computed_at=None)]

        engine = _engine()
        rule = make_rule(
            rule_type="volume_anomaly",
            dimension="completeness",
            rule_config={"direction": "drop", "threshold_pct": 0.80, "min_row_count": 1000},
        )
        result = engine.execute_rule(make_asset(), rule)
        assert result.passed is True
        assert result.actual_value == 0.0

    # TC-12: direction=rise 但实际下跌。today=1000, baseline=10000, threshold=0.8 -> passed=True（没涨不触发）
    @patch("services.dqc.database.DqcDatabase.get_latest_snapshot")
    @patch("services.dqc.database.DqcDatabase.list_snapshots")
    def test_tc12_rise_direction_but_actually_drops_passes(self, mock_list, mock_get):
        mock_get.return_value = MagicMock(row_count_snapshot=1000)
        mock_list.return_value = [MagicMock(row_count_snapshot=10000, computed_at=None)]

        engine = _engine()
        rule = make_rule(
            rule_type="volume_anomaly",
            dimension="completeness",
            rule_config={"direction": "rise", "threshold_pct": 0.80, "comparison_window": "1d"},
        )
        result = engine.execute_rule(make_asset(), rule)
        assert result.passed is True
"""DQC 漂移检测单元测试"""
import pytest
from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch

from services.dqc.drift_detector import DriftDetector


class TestDriftDetector:
    """漂移检测器测试"""

    def test_compute_drift_with_prev_score(self):
        """有前值时计算漂移"""
        result = DriftDetector.compute_drift(current_score=80.0, prev_score=100.0)
        assert result == -20.0

    def test_compute_drift_no_prev_score(self):
        """无前值时返回 None"""
        result = DriftDetector.compute_drift(current_score=80.0, prev_score=None)
        assert result is None

    def test_compute_drift_rounding(self):
        """漂移值四舍五入到 4 位小数"""
        result = DriftDetector.compute_drift(current_score=80.12345, prev_score=100.0)
        assert result == -19.8766

    def test_compute_drift_positive_drift(self):
        """正漂移（分数上升）"""
        result = DriftDetector.compute_drift(current_score=100.0, prev_score=80.0)
        assert result == 20.0

    def test_compute_drift_no_change(self):
        """无漂移"""
        result = DriftDetector.compute_drift(current_score=80.0, prev_score=80.0)
        assert result == 0.0

    def test_compute_drift_small_change(self):
        """微小变化"""
        result = DriftDetector.compute_drift(current_score=80.0001, prev_score=80.0)
        assert result == 0.0001


class TestDriftDetectorIntegration:
    """漂移检测器集成测试（Mock DAO）"""

    def test_compute_prev_scores_delegates_to_dao(self):
        """验证委托到 DAO"""
        mock_dao = MagicMock()
        mock_dao.get_prev_dimension_scores.return_value = {
            "completeness": 90.0,
            "accuracy": 80.0,
        }

        detector = DriftDetector(dao=mock_dao)
        before = datetime.utcnow()

        result = detector.compute_prev_scores(MagicMock(), asset_id=1, before=before)

        mock_dao.get_prev_dimension_scores.assert_called_once()
        assert result["completeness"] == 90.0
        assert result["accuracy"] == 80.0

    def test_compute_7d_avg_delegates_to_dao(self):
        """验证 7 日均值委托到 DAO"""
        mock_dao = MagicMock()
        mock_dao.get_7d_avg_dimension_scores.return_value = {
            "completeness": 85.0,
            "accuracy": 75.0,
        }

        detector = DriftDetector(dao=mock_dao)
        now = datetime.utcnow()

        result = detector.compute_7d_avg(MagicMock(), asset_id=1, now=now)

        mock_dao.get_7d_avg_dimension_scores.assert_called_once()
        assert result["completeness"] == 85.0
        assert result["accuracy"] == 75.0

    def test_drift_calculation_end_to_end(self):
        """端到端漂移计算"""
        mock_dao = MagicMock()
        # 模拟前值和 7 日均值
        mock_dao.get_prev_dimension_scores.return_value = {
            "completeness": 100.0,
            "accuracy": 80.0,
        }
        mock_dao.get_7d_avg_dimension_scores.return_value = {
            "completeness": 95.0,
            "accuracy": 85.0,
        }

        detector = DriftDetector(dao=mock_dao)
        db = MagicMock()

        # 当前分数
        current_scores = {"completeness": 90.0, "accuracy": 75.0}

        # 计算漂移
        prev_scores = detector.compute_prev_scores(db, asset_id=1)
        d7_avg = detector.compute_7d_avg(db, asset_id=1)

        # drift_24h = current - prev
        drift_24h_completeness = current_scores["completeness"] - prev_scores["completeness"]
        drift_24h_accuracy = current_scores["accuracy"] - prev_scores["accuracy"]

        assert drift_24h_completeness == -10.0  # 90 - 100
        assert drift_24h_accuracy == -5.0  # 75 - 80

        # drift_vs_7d_avg = current - 7d_avg
        drift_7d_completeness = current_scores["completeness"] - d7_avg["completeness"]
        drift_7d_accuracy = current_scores["accuracy"] - d7_avg["accuracy"]

        assert drift_7d_completeness == -5.0  # 90 - 95
        assert drift_7d_accuracy == -10.0  # 75 - 85


class TestDriftThresholds:
    """漂移阈值测试"""

    def test_p0_threshold_boundary(self):
        """P0 阈值边界：drift <= -20"""
        detector = DriftDetector()

        # 边界值
        assert detector.compute_drift(80, 100) == -20.0  # P0 临界

    def test_p1_threshold_boundary(self):
        """P1 阈值边界：-20 < drift <= -10"""
        detector = DriftDetector()

        # P1 临界
        assert detector.compute_drift(90, 100) == -10.0  # P1 临界

        # 在 P1 范围内
        assert detector.compute_drift(85, 100) == -15.0  # -20 < -15 <= -10

    def test_green_threshold(self):
        """GREEN 范围：drift > -10"""
        detector = DriftDetector()

        # GREEN
        assert detector.compute_drift(95, 100) == -5.0  # > -10
        assert detector.compute_drift(100, 100) == 0.0  # > -10

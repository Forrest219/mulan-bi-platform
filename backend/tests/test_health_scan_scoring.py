"""单元测试：数仓健康扫描评分算法

测试 services/health_scan/scoring.py 中的唯一权威实现。
公式见 Spec 11 §4.2：
  density = (high*5 + medium*2 + low*0.5) / total_tables
  score   = max(0, round(100 - density*10, 1))
"""
import pytest
from services.health_scan.scoring import calculate_health_score


class TestCalculateHealthScore:
    def test_no_issues_full_score(self):
        assert calculate_health_score(0, 0, 0, 10) == 100.0

    def test_no_tables_returns_none(self):
        assert calculate_health_score(0, 0, 0, 0) is None
        assert calculate_health_score(5, 3, 2, 0) is None

    def test_high_weight_5(self):
        # 1 high / 1 table → density=5 → score=100-50=50
        assert calculate_health_score(1, 0, 0, 1) == 50.0

    def test_medium_weight_2(self):
        # 1 medium / 1 table → density=2 → score=100-20=80
        assert calculate_health_score(0, 1, 0, 1) == 80.0

    def test_low_weight_0_5(self):
        # 1 low / 1 table → density=0.5 → score=100-5=95
        assert calculate_health_score(0, 0, 1, 1) == 95.0

    def test_density_normalized_by_table_count(self):
        # same issues but 10 tables → 10× less dense
        assert calculate_health_score(1, 0, 0, 10) == 95.0

    def test_score_clamped_to_zero(self):
        assert calculate_health_score(100, 100, 100, 1) == 0.0

    def test_mixed_issues(self):
        # (5*5 + 10*2 + 20*0.5) / 10 = 55/10 = 5.5 → 100 - 55 = 45.0
        assert calculate_health_score(5, 10, 20, 10) == 45.0

    def test_rounding_to_one_decimal(self):
        # (1*5 + 1*2 + 1*0.5) / 3 = 7.5/3 = 2.5 → 100 - 25 = 75.0
        assert calculate_health_score(1, 1, 1, 3) == 75.0


class TestHealthLevelBoundaries:
    """健康等级边界（与 engine 无关，测展示层分级逻辑）"""

    def _level(self, score):
        if score >= 80:
            return "excellent"
        elif score >= 60:
            return "good"
        elif score >= 40:
            return "warning"
        return "poor"

    def test_excellent_boundary(self):
        assert self._level(80) == "excellent"
        assert self._level(100) == "excellent"

    def test_good_boundary(self):
        assert self._level(60) == "good"
        assert self._level(79) == "good"

    def test_warning_boundary(self):
        assert self._level(40) == "warning"
        assert self._level(59) == "warning"

    def test_poor_boundary(self):
        assert self._level(39) == "poor"
        assert self._level(0) == "poor"

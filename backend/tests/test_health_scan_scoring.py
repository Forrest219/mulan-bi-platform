"""单元测试：数仓健康扫描 — 评分算法"""
import pytest


class TestHealthScanScoring:
    """Spec 11 评分算法: score = 100 - high×20 - medium×5 - low×1"""

    def _calc_score(self, high=0, medium=0, low=0):
        score = 100 - high * 20 - medium * 5 - low * 1
        return max(0, min(100, score))

    def test_perfect_score(self):
        assert self._calc_score(high=0, medium=0, low=0) == 100

    def test_high_issue_deducts_20(self):
        assert self._calc_score(high=1) == 80
        assert self._calc_score(high=2) == 60
        assert self._calc_score(high=5) == 0  # 被 floor 截断

    def test_medium_issue_deducts_5(self):
        assert self._calc_score(medium=1) == 95
        assert self._calc_score(medium=2) == 90
        assert self._calc_score(medium=20) == 0

    def test_low_issue_deducts_1(self):
        assert self._calc_score(low=1) == 99
        assert self._calc_score(low=5) == 95

    def test_mixed_issues(self):
        # 2 HIGH + 3 MEDIUM + 5 LOW = 100 - 40 - 15 - 5 = 40
        assert self._calc_score(high=2, medium=3, low=5) == 40

    def test_score_clamped_to_0(self):
        """极多问题分数不得为负"""
        assert self._calc_score(high=10, medium=10, low=10) == 0

    def test_score_clamped_to_100(self):
        """分数不超过 100"""
        assert self._calc_score(high=0, medium=0, low=0) == 100


class TestHealthLevelBoundaries:
    """Spec 11 健康等级边界"""

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

"""DQC 信号灯判定单元测试"""
import pytest

from services.dqc.signal_judge import (
    DqcSignalJudge,
    judge_asset_signal,
    judge_dimension_signal,
)


class TestJudgeDimensionSignal:
    """维度信号判定测试"""

    def test_score_below_p0_returns_p0(self):
        """分数低于 p0_score (60) → P0"""
        assert judge_dimension_signal(score=50, drift_24h=None) == "P0"
        assert judge_dimension_signal(score=0, drift_24h=None) == "P0"
        assert judge_dimension_signal(score=59.9, drift_24h=None) == "P0"

    def test_score_above_p1_returns_green(self):
        """分数高于 p1_score (80) → GREEN"""
        assert judge_dimension_signal(score=100, drift_24h=None) == "GREEN"
        assert judge_dimension_signal(score=80, drift_24h=None) == "GREEN"
        assert judge_dimension_signal(score=81, drift_24h=None) == "GREEN"

    def test_score_between_p0_and_p1_returns_p1(self):
        """p0_score <= score < p1_score → P1"""
        assert judge_dimension_signal(score=60, drift_24h=None) == "P1"
        assert judge_dimension_signal(score=70, drift_24h=None) == "P1"
        assert judge_dimension_signal(score=79.9, drift_24h=None) == "P1"

    def test_drift_below_negative_p0_returns_p0(self):
        """drift_24h <= -drift_p0 (-20) → P0"""
        assert judge_dimension_signal(score=100, drift_24h=-20) == "P0"
        assert judge_dimension_signal(score=100, drift_24h=-25) == "P0"
        assert judge_dimension_signal(score=100, drift_24h=-30) == "P0"

    def test_drift_between_p1_and_p0_returns_p1(self):
        """-drift_p0 < drift <= -drift_p1 (-20 < drift <= -10) → P1"""
        assert judge_dimension_signal(score=100, drift_24h=-15) == "P1"
        assert judge_dimension_signal(score=100, drift_24h=-10) == "P1"
        assert judge_dimension_signal(score=100, drift_24h=-11) == "P1"

    def test_small_drift_returns_green(self):
        """drift > -drift_p1 → GREEN"""
        assert judge_dimension_signal(score=100, drift_24h=-5) == "GREEN"
        assert judge_dimension_signal(score=100, drift_24h=0) == "GREEN"
        assert judge_dimension_signal(score=100, drift_24h=10) == "GREEN"

    def test_none_drift_uses_score_only(self):
        """drift_24h=None 时仅根据分数判定"""
        assert judge_dimension_signal(score=50, drift_24h=None) == "P0"
        assert judge_dimension_signal(score=70, drift_24h=None) == "P1"
        assert judge_dimension_signal(score=90, drift_24h=None) == "GREEN"

    def test_custom_thresholds(self):
        """自定义阈值"""
        thresholds = {"p0_score": 50, "p1_score": 70, "drift_p0": 15, "drift_p1": 10}
        assert judge_dimension_signal(score=40, drift_24h=None, thresholds=thresholds) == "P0"
        assert judge_dimension_signal(score=55, drift_24h=None, thresholds=thresholds) == "P1"
        assert judge_dimension_signal(score=75, drift_24h=None, thresholds=thresholds) == "GREEN"


class TestJudgeAssetSignal:
    """资产信号判定测试"""

    def test_empty_dim_signals_returns_green(self):
        """无维度信号时返回 GREEN"""
        assert judge_asset_signal(dim_signals={}, confidence_score=100) == "GREEN"

    def test_all_green_returns_green(self):
        """所有维度 GREEN → GREEN"""
        dim_signals = {"completeness": "GREEN", "accuracy": "GREEN"}
        assert judge_asset_signal(dim_signals, confidence_score=100) == "GREEN"

    def test_any_p1_returns_p1(self):
        """有任意 P1 → P1"""
        dim_signals = {"completeness": "GREEN", "accuracy": "P1", "timeliness": "GREEN"}
        assert judge_asset_signal(dim_signals, confidence_score=100) == "P1"

    def test_any_p0_returns_p0(self):
        """有任意 P0 → P0"""
        dim_signals = {"completeness": "GREEN", "accuracy": "P0", "timeliness": "GREEN"}
        assert judge_asset_signal(dim_signals, confidence_score=100) == "P0"

    def test_p0_takes_precedence_over_p1(self):
        """同时有 P0 和 P1 → P0"""
        dim_signals = {"completeness": "P1", "accuracy": "P0"}
        assert judge_asset_signal(dim_signals, confidence_score=100) == "P0"

    def test_confidence_below_p0_overrides(self):
        """CS < confidence_p0 (60) 时独立约束触发 P0"""
        dim_signals = {"completeness": "GREEN", "accuracy": "GREEN"}
        assert judge_asset_signal(dim_signals, confidence_score=50) == "P0"

    def test_confidence_between_p0_and_p1_returns_p1(self):
        """confidence_p0 <= CS < confidence_p1 → P1"""
        dim_signals = {"completeness": "GREEN", "accuracy": "GREEN"}
        assert judge_asset_signal(dim_signals, confidence_score=70) == "P1"

    def test_confidence_high_with_p1_dim_returns_p1(self):
        """CS 正常但有 P1 维度 → P1"""
        dim_signals = {"completeness": "GREEN", "accuracy": "P1"}
        assert judge_asset_signal(dim_signals, confidence_score=90) == "P1"


class TestDqcSignalJudge:
    """DqcSignalJudge 类测试"""

    def test_judge_all_dimensions(self):
        """批量判定所有维度"""
        judge = DqcSignalJudge()
        dimension_scores = {
            "completeness": 90,
            "accuracy": 55,
            "timeliness": 75,
            "validity": 100,
            "uniqueness": 100,
            "consistency": 100,
        }
        drifts_24h = {
            "completeness": -5,
            "accuracy": -25,
            "timeliness": -12,
            "validity": 0,
            "uniqueness": 0,
            "consistency": 0,
        }
        signals = judge.judge_all_dimensions(dimension_scores, drifts_24h)

        assert signals["completeness"] == "GREEN"
        assert signals["accuracy"] == "P0"  # drift -25 <= -20
        assert signals["timeliness"] == "P1"  # -20 < -12 <= -10
        assert signals["validity"] == "GREEN"
        assert signals["uniqueness"] == "GREEN"
        assert signals["consistency"] == "GREEN"

    def test_judge_dimension_with_custom_thresholds(self):
        """自定义阈值的实例化判定器"""
        judge = DqcSignalJudge(thresholds={"p0_score": 50, "p1_score": 70})
        assert judge.judge_dimension(40, None) == "P0"
        assert judge.judge_dimension(60, None) == "P1"
        assert judge.judge_dimension(80, None) == "GREEN"

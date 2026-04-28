"""DQC 评分器单元测试"""
import pytest
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from services.dqc.scorer import DqcScorer, RuleExecutionSignal


@dataclass
class MockRuleResult:
    """Mock 规则执行结果"""
    rule_id: int
    asset_id: int
    dimension: str
    rule_type: str
    passed: bool
    actual_value: Optional[float] = None
    error_message: Optional[str] = None


class TestComputeDimensionScore:
    """单维度评分计算测试"""

    def test_all_passed_returns_100(self):
        """所有规则通过 → 100分"""
        scorer = DqcScorer()
        results = [
            MockRuleResult(1, 1, "completeness", "null_rate", True),
            MockRuleResult(2, 1, "completeness", "not_null", True),
        ]
        score = scorer.compute_dimension_score("completeness", results)
        assert score["score"] == 100.0
        assert score["rules_total"] == 2
        assert score["rules_passed"] == 2
        assert score["rules_failed"] == 0

    def test_all_failed_returns_0(self):
        """所有规则失败 → 0分"""
        scorer = DqcScorer()
        results = [
            MockRuleResult(1, 1, "completeness", "null_rate", False),
            MockRuleResult(2, 1, "completeness", "not_null", False),
        ]
        score = scorer.compute_dimension_score("completeness", results)
        assert score["score"] == 0.0
        assert score["rules_total"] == 2
        assert score["rules_passed"] == 0
        assert score["rules_failed"] == 2

    def test_mixed_results_returns_correct_score(self):
        """混合结果 → 正确分数"""
        scorer = DqcScorer()
        results = [
            MockRuleResult(1, 1, "completeness", "null_rate", True),
            MockRuleResult(2, 1, "completeness", "not_null", False),
            MockRuleResult(3, 1, "completeness", "row_count", True),
            MockRuleResult(4, 1, "completeness", "duplicate_rate", False),
        ]
        score = scorer.compute_dimension_score("completeness", results)
        assert score["score"] == 50.0  # 2/4 = 50%
        assert score["rules_total"] == 4
        assert score["rules_passed"] == 2
        assert score["rules_failed"] == 2

    def test_no_rules_returns_100(self):
        """无规则时 → 100分（默认满分）"""
        scorer = DqcScorer()
        score = scorer.compute_dimension_score("completeness", [])
        assert score["score"] == 100.0
        assert score["rules_total"] == 0

    def test_wrong_dimension_ignored(self):
        """其他维度的规则被忽略"""
        scorer = DqcScorer()
        results = [
            MockRuleResult(1, 1, "completeness", "null_rate", True),
            MockRuleResult(2, 1, "accuracy", "range_check", False),  # 被忽略
        ]
        score = scorer.compute_dimension_score("completeness", results)
        assert score["score"] == 100.0
        assert score["rules_total"] == 1


class TestComputeConfidenceScore:
    """综合评分计算测试"""

    def test_equal_weights(self):
        """等权重计算"""
        scorer = DqcScorer()
        dim_scores = {
            "completeness": 100.0,
            "accuracy": 80.0,
            "timeliness": 60.0,
            "validity": 100.0,
            "uniqueness": 80.0,
            "consistency": 60.0,
        }
        cs = scorer.compute_confidence_score(dim_scores)
        expected = (100 + 80 + 60 + 100 + 80 + 60) / 6
        assert cs == expected

    def test_custom_weights(self):
        """自定义权重"""
        scorer = DqcScorer()
        dim_scores = {
            "completeness": 100.0,
            "accuracy": 80.0,
            "timeliness": 60.0,
            "validity": 100.0,
            "uniqueness": 80.0,
            "consistency": 60.0,
        }
        weights = {
            "completeness": 0.5,
            "accuracy": 0.3,
            "timeliness": 0.1,
            "validity": 0.05,
            "uniqueness": 0.03,
            "consistency": 0.02,
        }
        cs = scorer.compute_confidence_score(dim_scores, weights)
        expected = 100 * 0.5 + 80 * 0.3 + 60 * 0.1 + 100 * 0.05 + 80 * 0.03 + 60 * 0.02
        assert cs == expected

    def test_missing_dimension_uses_default(self):
        """缺失维度使用默认权重"""
        scorer = DqcScorer()
        dim_scores = {
            "completeness": 100.0,
            "accuracy": 80.0,
        }
        cs = scorer.compute_confidence_score(dim_scores)
        # 缺失的 4 个维度各占 1/6
        expected = (100 + 80 + 100 + 100 + 100 + 100) / 6
        assert cs == expected

    def test_score_clamped_to_100(self):
        """评分上限 100"""
        scorer = DqcScorer()
        dim_scores = {
            "completeness": 100.0,
            "accuracy": 100.0,
            "timeliness": 100.0,
            "validity": 100.0,
            "uniqueness": 100.0,
            "consistency": 100.0,
        }
        cs = scorer.compute_confidence_score(dim_scores)
        assert cs == 100.0

    def test_score_clamped_to_0(self):
        """评分下限 0"""
        scorer = DqcScorer()
        dim_scores = {
            "completeness": 0.0,
            "accuracy": 0.0,
            "timeliness": 0.0,
            "validity": 0.0,
            "uniqueness": 0.0,
            "consistency": 0.0,
        }
        cs = scorer.compute_confidence_score(dim_scores)
        assert cs == 0.0


class TestJudgeDimensionSignal:
    """维度信号判定测试"""

    def test_score_below_p0(self):
        """分数低于 60 → P0"""
        scorer = DqcScorer()
        assert scorer.judge_dimension_signal(50, None) == "P0"

    def test_score_above_p1(self):
        """分数高于 80 → GREEN"""
        scorer = DqcScorer()
        assert scorer.judge_dimension_signal(85, None) == "GREEN"

    def test_score_between_p0_and_p1(self):
        """60 <= score < 80 → P1"""
        scorer = DqcScorer()
        assert scorer.judge_dimension_signal(60, None) == "P1"
        assert scorer.judge_dimension_signal(70, None) == "P1"

    def test_drift_triggers_p0(self):
        """严重漂移触发 P0"""
        scorer = DqcScorer()
        # drift <= -20
        assert scorer.judge_dimension_signal(100, -20) == "P0"
        assert scorer.judge_dimension_signal(100, -25) == "P0"

    def test_drift_triggers_p1(self):
        """中等漂移触发 P1"""
        scorer = DqcScorer()
        # -20 < drift <= -10
        assert scorer.judge_dimension_signal(100, -15) == "P1"
        assert scorer.judge_dimension_signal(100, -10) == "P1"

    def test_small_drift_green(self):
        """轻微漂移 → GREEN"""
        scorer = DqcScorer()
        assert scorer.judge_dimension_signal(100, -5) == "GREEN"


class TestJudgeAssetSignal:
    """资产信号判定测试"""

    def test_all_green(self):
        """所有 GREEN → GREEN"""
        scorer = DqcScorer()
        dim_signals = {"completeness": "GREEN", "accuracy": "GREEN"}
        assert scorer.judge_asset_signal(dim_signals, 100) == "GREEN"

    def test_any_p1(self):
        """有 P1 → P1"""
        scorer = DqcScorer()
        dim_signals = {"completeness": "GREEN", "accuracy": "P1"}
        assert scorer.judge_asset_signal(dim_signals, 100) == "P1"

    def test_any_p0(self):
        """有 P0 → P0"""
        scorer = DqcScorer()
        dim_signals = {"completeness": "GREEN", "accuracy": "P0"}
        assert scorer.judge_asset_signal(dim_signals, 100) == "P0"

    def test_cs_below_p0(self):
        """CS < 60 → P0"""
        scorer = DqcScorer()
        dim_signals = {"completeness": "GREEN", "accuracy": "GREEN"}
        assert scorer.judge_asset_signal(dim_signals, 50) == "P0"

    def test_cs_between_p0_and_p1(self):
        """60 <= CS < 80 → P1"""
        scorer = DqcScorer()
        dim_signals = {"completeness": "GREEN", "accuracy": "GREEN"}
        assert scorer.judge_asset_signal(dim_signals, 70) == "P1"


class TestScoreAsset:
    """端到端评分测试"""

    def test_full_pipeline(self):
        """完整评分流程"""
        scorer = DqcScorer()
        results = [
            MockRuleResult(1, 1, "completeness", "null_rate", True),
            MockRuleResult(2, 1, "completeness", "not_null", False),
            MockRuleResult(3, 1, "accuracy", "range_check", True),
            MockRuleResult(4, 1, "timeliness", "freshness", True),
            MockRuleResult(5, 1, "validity", "regex", False),
            MockRuleResult(6, 1, "uniqueness", "uniqueness", True),
            MockRuleResult(7, 1, "consistency", "custom_sql", True),
        ]
        result = scorer.score_asset(asset_id=1, results=results)

        assert result.confidence_score > 0
        assert result.signal in ["GREEN", "P1", "P0"]
        assert len(result.dimension_scores) == 6

    def test_empty_results(self):
        """无规则时默认满分"""
        scorer = DqcScorer()
        result = scorer.score_asset(asset_id=1, results=[])

        assert result.confidence_score == 100.0
        assert result.signal == "GREEN"

    def test_prev_dimension_scores(self):
        """带历史分数的漂移计算"""
        scorer = DqcScorer()
        results = [
            MockRuleResult(1, 1, "completeness", "null_rate", True),
        ]
        prev_scores = {"completeness": 100.0}
        result = scorer.score_asset(
            asset_id=1,
            results=results,
            prev_dimension_scores=prev_scores,
        )

        dim = result.dimension_scores["completeness"]
        assert dim.drift_24h == 0.0  # 100 - 100
        assert dim.prev_score == 100.0

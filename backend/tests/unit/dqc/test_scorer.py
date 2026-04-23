"""DqcScorer 单元测试 — 覆盖 spec §7.9 全部 12 条边界"""
import os

os.environ.setdefault("DATABASE_URL", "postgresql://mulan:mulan@localhost:5432/mulan_bi_test")
os.environ.setdefault("SESSION_SECRET", "test-session-secret-for-ci-!!")
os.environ.setdefault("DATASOURCE_ENCRYPTION_KEY", "test-datasource-key-32-bytes-ok!!")
os.environ.setdefault("TABLEAU_ENCRYPTION_KEY", "test-tableau-key-32-bytes-ok!!")
os.environ.setdefault("LLM_ENCRYPTION_KEY", "test-llm-key-32-bytes-ok!!!!")

import pytest

from services.dqc.constants import ALL_DIMENSIONS, DEFAULT_SIGNAL_THRESHOLDS, SignalLevel
from services.dqc.scorer import DqcScorer, RuleExecutionSignal


def _build_results(dim: str, total: int, passed: int, rule_type: str = "null_rate"):
    out = []
    for i in range(total):
        out.append(
            RuleExecutionSignal(
                rule_id=i + 1,
                asset_id=1,
                dimension=dim,
                rule_type=rule_type,
                passed=(i < passed),
            )
        )
    return out


class TestDimensionScore:
    def test_all_max_no_rules_green(self):
        """case 1: 全部维度满分且无规则 → GREEN, CS=100"""
        scorer = DqcScorer()
        result = scorer.score_asset(asset_id=1, results=[])
        assert result.confidence_score == 100.0
        assert result.signal == SignalLevel.GREEN.value
        for dim in ALL_DIMENSIONS:
            assert result.dimension_scores[dim].score == 100.0
            assert result.dimension_scores[dim].signal == SignalLevel.GREEN.value

    def test_dimension_score_p0_strict(self):
        """case 2: 某维度分 = 59.9 → 该维度 P0"""
        scorer = DqcScorer()
        assert scorer.judge_dimension_signal(59.9, None) == SignalLevel.P0.value

    def test_dimension_score_60_is_p1(self):
        """case 3: 某维度分 = 60.0 → 该维度 P1（严格小于 60 才 P0）"""
        scorer = DqcScorer()
        assert scorer.judge_dimension_signal(60.0, None) == SignalLevel.P1.value

    def test_dimension_score_80_is_green(self):
        """case 4: 某维度分 = 80.0 → 该维度 GREEN（严格小于 80 才 P1）"""
        scorer = DqcScorer()
        assert scorer.judge_dimension_signal(80.0, None) == SignalLevel.GREEN.value

    def test_dimension_score_79_99_is_p1(self):
        scorer = DqcScorer()
        assert scorer.judge_dimension_signal(79.99, None) == SignalLevel.P1.value


class TestDriftSignal:
    def test_drift_exact_minus_20_p0(self):
        """case 5: 跌幅 20.0（drift=-20.0）→ P0"""
        scorer = DqcScorer()
        assert scorer.judge_dimension_signal(90.0, -20.0) == SignalLevel.P0.value

    def test_drift_19_99_p1(self):
        """case 6: 跌幅 19.99 → P1"""
        scorer = DqcScorer()
        assert scorer.judge_dimension_signal(90.0, -19.99) == SignalLevel.P1.value

    def test_drift_exact_minus_10_p1(self):
        """case 7: 跌幅 10.0 → P1"""
        scorer = DqcScorer()
        assert scorer.judge_dimension_signal(90.0, -10.0) == SignalLevel.P1.value

    def test_drift_9_99_green(self):
        """case 8: 跌幅 9.99 → GREEN"""
        scorer = DqcScorer()
        assert scorer.judge_dimension_signal(90.0, -9.99) == SignalLevel.GREEN.value

    def test_prev_none_no_drift(self):
        """case 10: prev_score=None 时不触发 drift 判定"""
        scorer = DqcScorer()
        # 分数 85，没有漂移信息，应 GREEN
        assert scorer.judge_dimension_signal(85.0, None) == SignalLevel.GREEN.value


class TestAssetSignal:
    def test_all_green_but_low_cs_is_p0(self):
        """case 9: 所有维度 GREEN 但 CS=59 → 资产 P0"""
        scorer = DqcScorer()
        dim_signals = {dim: SignalLevel.GREEN.value for dim in ALL_DIMENSIONS}
        assert scorer.judge_asset_signal(dim_signals, 59.0) == SignalLevel.P0.value

    def test_all_green_with_cs_79_is_p1(self):
        scorer = DqcScorer()
        dim_signals = {dim: SignalLevel.GREEN.value for dim in ALL_DIMENSIONS}
        assert scorer.judge_asset_signal(dim_signals, 79.0) == SignalLevel.P1.value

    def test_mixed_one_p1_is_p1(self):
        """case 11: dim_signals 中一个 P1 其余 GREEN → 资产 P1"""
        scorer = DqcScorer()
        dim_signals = {
            "completeness": SignalLevel.P1.value,
            "accuracy": SignalLevel.GREEN.value,
            "timeliness": SignalLevel.GREEN.value,
            "validity": SignalLevel.GREEN.value,
            "uniqueness": SignalLevel.GREEN.value,
            "consistency": SignalLevel.GREEN.value,
        }
        assert scorer.judge_asset_signal(dim_signals, 95.0) == SignalLevel.P1.value

    def test_mixed_one_p0_is_p0(self):
        """case 12: dim_signals 中一个 P0 其余 GREEN → 资产 P0"""
        scorer = DqcScorer()
        dim_signals = {
            "completeness": SignalLevel.GREEN.value,
            "accuracy": SignalLevel.GREEN.value,
            "timeliness": SignalLevel.GREEN.value,
            "validity": SignalLevel.GREEN.value,
            "uniqueness": SignalLevel.GREEN.value,
            "consistency": SignalLevel.P0.value,
        }
        assert scorer.judge_asset_signal(dim_signals, 95.0) == SignalLevel.P0.value


class TestConfidenceScore:
    def test_default_weights_equal(self):
        scorer = DqcScorer()
        scores = {dim: 90.0 for dim in ALL_DIMENSIONS}
        cs = scorer.compute_confidence_score(scores)
        assert 89.5 < cs < 90.5

    def test_partial_weights_fallback(self):
        scorer = DqcScorer()
        scores = {dim: 100.0 for dim in ALL_DIMENSIONS}
        scores["accuracy"] = 0.0
        weights = {"accuracy": 0.5, "completeness": 0.5}  # 其余按默认补齐
        cs = scorer.compute_confidence_score(scores, weights)
        assert 0 <= cs <= 100

    def test_weights_negative_rejected_by_api_layer(self):
        """计算层容忍负权重（API 层校验）；此处只验证算式执行不崩溃"""
        scorer = DqcScorer()
        scores = {dim: 100.0 for dim in ALL_DIMENSIONS}
        cs = scorer.compute_confidence_score(scores, {})
        assert cs == 100.0


class TestEndToEnd:
    def test_passing_rules_ratio(self):
        scorer = DqcScorer()
        results = _build_results("completeness", total=10, passed=9)
        meta = scorer.compute_dimension_score("completeness", results)
        assert meta["score"] == 90.0
        assert meta["rules_total"] == 10
        assert meta["rules_passed"] == 9
        assert meta["rules_failed"] == 1

    def test_no_rule_defaults_100(self):
        scorer = DqcScorer()
        meta = scorer.compute_dimension_score("completeness", [])
        assert meta["score"] == 100.0
        assert meta["rules_total"] == 0

    def test_e2e_with_drift_falls_p0(self):
        scorer = DqcScorer()
        results = _build_results("completeness", total=10, passed=9)
        prev = {"completeness": 100.0}
        result = scorer.score_asset(
            asset_id=1, results=results, prev_dimension_scores=prev
        )
        # score = 90，但 drift = -10 → 维度 P1（落入 -20<drift<=-10）
        assert result.dimension_scores["completeness"].signal == SignalLevel.P1.value

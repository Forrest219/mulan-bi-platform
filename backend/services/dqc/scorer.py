"""DQC 评分器

职责：
- 从 RuleExecutionResult[] 聚合出 6 维度分
- 按 dimension_weights 加权算 ConfidenceScore
- 判定维度信号灯 + 资产最终信号灯（取最差维度与 CS 约束的严重级）
"""
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from .constants import (
    ALL_DIMENSIONS,
    DEFAULT_DIMENSION_WEIGHTS,
    DEFAULT_SIGNAL_THRESHOLDS,
    SIGNAL_PRIORITY,
    SignalLevel,
)


@dataclass
class RuleExecutionSignal:
    """用于 scorer 聚合的最小结构；rule_engine.RuleExecutionResult 可直接兼容"""
    rule_id: int
    asset_id: int
    dimension: str
    rule_type: str
    passed: bool
    actual_value: Optional[float] = None
    expected_config: Dict[str, Any] = field(default_factory=dict)
    error_message: Optional[str] = None
    execution_time_ms: int = 0


@dataclass
class DimensionScoreResult:
    dimension: str
    score: float
    signal: str
    rules_total: int
    rules_passed: int
    rules_failed: int
    drift_24h: Optional[float] = None
    drift_vs_7d_avg: Optional[float] = None
    prev_score: Optional[float] = None


@dataclass
class AssetScoreResult:
    confidence_score: float
    signal: str
    dimension_scores: Dict[str, DimensionScoreResult]


class DqcScorer:
    """DQC 评分计算 + 信号灯判定"""

    def compute_dimension_score(self, dimension: str, results: List[Any]) -> Dict[str, int]:
        """单维度统计：通过规则数 / 总规则数 × 100；无规则 → 100"""
        total = 0
        passed = 0
        for r in results:
            if getattr(r, "dimension", None) != dimension:
                continue
            total += 1
            if getattr(r, "passed", False):
                passed += 1
        if total == 0:
            score = 100.0
        else:
            score = (passed / total) * 100.0
        return {
            "score": round(score, 2),
            "rules_total": total,
            "rules_passed": passed,
            "rules_failed": total - passed,
        }

    def compute_confidence_score(
        self,
        dimension_scores: Dict[str, float],
        weights: Optional[Dict[str, float]] = None,
    ) -> float:
        """加权聚合。未配置权重的维度按等权 1/6 补齐，保证权重总和参与度 = 1。"""
        w = dict(weights) if weights else {}
        for dim in ALL_DIMENSIONS:
            if dim not in w or w[dim] is None:
                w[dim] = DEFAULT_DIMENSION_WEIGHTS[dim]
        total_weight = sum(w.values())
        if total_weight <= 0:
            return 0.0
        cs = sum(dimension_scores.get(dim, 100.0) * w[dim] for dim in ALL_DIMENSIONS) / total_weight
        cs = max(0.0, min(100.0, cs))
        return round(cs, 2)

    def judge_dimension_signal(
        self,
        score: float,
        drift_24h: Optional[float],
        thresholds: Optional[Dict[str, float]] = None,
    ) -> str:
        """维度信号判定（严格按 spec §7.5）

        规则（按优先级）：
        1. score < p0_score (默认 60) → P0
        2. drift_24h <= -drift_p0 (默认 -20) → P0
        3. score < p1_score (默认 80) → P1
        4. -drift_p0 < drift_24h <= -drift_p1 (默认 -20 < drift <= -10) → P1
        5. otherwise → GREEN
        """
        t = _merge_thresholds(thresholds)
        p0_score = t["p0_score"]
        p1_score = t["p1_score"]
        drift_p0 = t["drift_p0"]
        drift_p1 = t["drift_p1"]

        if score < p0_score:
            return SignalLevel.P0.value
        if drift_24h is not None and drift_24h <= -drift_p0:
            return SignalLevel.P0.value
        if score < p1_score:
            return SignalLevel.P1.value
        if drift_24h is not None and -drift_p0 < drift_24h <= -drift_p1:
            return SignalLevel.P1.value
        return SignalLevel.GREEN.value

    def judge_asset_signal(
        self,
        dim_signals: Dict[str, str],
        confidence_score: float,
        thresholds: Optional[Dict[str, float]] = None,
    ) -> str:
        """资产最终 Signal：维度中最差 Signal 与 CS 独立约束取严重级"""
        t = _merge_thresholds(thresholds)
        confidence_p0 = t["confidence_p0"]
        confidence_p1 = t["confidence_p1"]

        if not dim_signals:
            worst = SignalLevel.GREEN.value
        else:
            worst = max(dim_signals.values(), key=lambda s: SIGNAL_PRIORITY.get(s, 0))

        if confidence_score < confidence_p0:
            cs_signal = SignalLevel.P0.value
        elif confidence_score < confidence_p1:
            cs_signal = SignalLevel.P1.value
        else:
            cs_signal = SignalLevel.GREEN.value

        return max([worst, cs_signal], key=lambda s: SIGNAL_PRIORITY.get(s, 0))

    def score_asset(
        self,
        asset_id: int,
        results: List[Any],
        weights: Optional[Dict[str, float]] = None,
        thresholds: Optional[Dict[str, float]] = None,
        prev_dimension_scores: Optional[Dict[str, float]] = None,
        d7_avg_dimension_scores: Optional[Dict[str, float]] = None,
    ) -> AssetScoreResult:
        """端到端：规则结果 → 维度分 → ConfidenceScore → 信号"""
        prev_scores = prev_dimension_scores or {}
        d7_scores = d7_avg_dimension_scores or {}
        effective_thresholds = _merge_thresholds(thresholds)

        dim_score_values: Dict[str, float] = {}
        dim_meta: Dict[str, Dict[str, int]] = {}
        for dim in ALL_DIMENSIONS:
            meta = self.compute_dimension_score(dim, results)
            dim_score_values[dim] = meta["score"]
            dim_meta[dim] = meta

        drifts: Dict[str, Optional[float]] = {}
        d7_drifts: Dict[str, Optional[float]] = {}
        for dim in ALL_DIMENSIONS:
            prev = prev_scores.get(dim)
            drifts[dim] = round(dim_score_values[dim] - prev, 4) if prev is not None else None
            d7 = d7_scores.get(dim)
            d7_drifts[dim] = round(dim_score_values[dim] - d7, 4) if d7 is not None else None

        cs = self.compute_confidence_score(dim_score_values, weights)

        dim_signals: Dict[str, str] = {}
        for dim in ALL_DIMENSIONS:
            dim_signals[dim] = self.judge_dimension_signal(
                dim_score_values[dim], drifts[dim], effective_thresholds
            )

        asset_signal = self.judge_asset_signal(dim_signals, cs, effective_thresholds)

        dim_results: Dict[str, DimensionScoreResult] = {}
        for dim in ALL_DIMENSIONS:
            dim_results[dim] = DimensionScoreResult(
                dimension=dim,
                score=dim_score_values[dim],
                signal=dim_signals[dim],
                rules_total=dim_meta[dim]["rules_total"],
                rules_passed=dim_meta[dim]["rules_passed"],
                rules_failed=dim_meta[dim]["rules_failed"],
                drift_24h=drifts[dim],
                drift_vs_7d_avg=d7_drifts[dim],
                prev_score=prev_scores.get(dim),
            )

        return AssetScoreResult(
            confidence_score=cs,
            signal=asset_signal,
            dimension_scores=dim_results,
        )


def _merge_thresholds(thresholds: Optional[Dict[str, float]]) -> Dict[str, float]:
    merged = dict(DEFAULT_SIGNAL_THRESHOLDS)
    if thresholds:
        for k, v in thresholds.items():
            if v is None:
                continue
            merged[k] = float(v)
    return merged

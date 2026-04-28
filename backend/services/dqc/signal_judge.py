"""DQC 信号灯判定

职责：
- 维度信号判定：GREEN/P1/P0（基于分数 + 漂移）
- 资产信号判定：取最差维度信号 + ConfidenceScore 独立约束
"""
from typing import Any, Dict, List, Optional

from .constants import (
    DEFAULT_SIGNAL_THRESHOLDS,
    SIGNAL_PRIORITY,
    SignalLevel,
)


def judge_dimension_signal(
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


def _merge_thresholds(thresholds: Optional[Dict[str, float]]) -> Dict[str, float]:
    merged = dict(DEFAULT_SIGNAL_THRESHOLDS)
    if thresholds:
        for k, v in thresholds.items():
            if v is None:
                continue
            merged[k] = float(v)
    return merged


class DqcSignalJudge:
    """DQC 信号灯判定器（可实例化，支持依赖注入）"""

    def __init__(self, thresholds: Optional[Dict[str, float]] = None):
        self._thresholds = thresholds

    def judge_dimension(self, score: float, drift_24h: Optional[float]) -> str:
        return judge_dimension_signal(score, drift_24h, self._thresholds)

    def judge_asset(self, dim_signals: Dict[str, str], confidence_score: float) -> str:
        return judge_asset_signal(dim_signals, confidence_score, self._thresholds)

    def judge_all_dimensions(
        self,
        dimension_scores: Dict[str, float],
        drifts_24h: Dict[str, Optional[float]],
    ) -> Dict[str, str]:
        """批量判定所有维度信号"""
        return {
            dim: judge_dimension_signal(
                dimension_scores.get(dim, 100.0),
                drifts_24h.get(dim),
                self._thresholds,
            )
            for dim in dimension_scores
        }
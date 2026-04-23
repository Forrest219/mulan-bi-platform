"""信号变化事件发射测试

直接测试 orchestrator._emit_asset_events 根据 prev/current signal 发射正确的事件集合。
"""
import os

os.environ.setdefault("DATABASE_URL", "postgresql://mulan:mulan@localhost:5432/mulan_bi_test")
os.environ.setdefault("SESSION_SECRET", "test-session-secret-for-ci-!!")
os.environ.setdefault("DATASOURCE_ENCRYPTION_KEY", "test-datasource-key-32-bytes-ok!!")
os.environ.setdefault("TABLEAU_ENCRYPTION_KEY", "test-tableau-key-32-bytes-ok!!")
os.environ.setdefault("LLM_ENCRYPTION_KEY", "test-llm-key-32-bytes-ok!!!!")

from types import SimpleNamespace
from uuid import uuid4

import pytest

from services.dqc.constants import ALL_DIMENSIONS, SignalLevel
from services.dqc.orchestrator import DqcOrchestrator
from services.dqc.scorer import AssetScoreResult, DimensionScoreResult
from tests.unit.dqc._fakes import make_asset


def _make_score_result(signal: str, dim_signals=None, confidence_score: float = 80.0):
    dim_signals = dim_signals or {dim: SignalLevel.GREEN.value for dim in ALL_DIMENSIONS}
    scores = {
        dim: DimensionScoreResult(
            dimension=dim,
            score=90.0,
            signal=dim_signals[dim],
            rules_total=1,
            rules_passed=1 if dim_signals[dim] == SignalLevel.GREEN.value else 0,
            rules_failed=0 if dim_signals[dim] == SignalLevel.GREEN.value else 1,
        )
        for dim in ALL_DIMENSIONS
    }
    return AssetScoreResult(
        confidence_score=confidence_score,
        signal=signal,
        dimension_scores=scores,
    )


class CollectingOrchestrator(DqcOrchestrator):
    def __init__(self):
        super().__init__()
        self.events = []

    def _emit_event(self, db, event_type, payload, severity, actor_id):
        self.events.append({"event_type": event_type, "payload": payload, "severity": severity})


class TestEventEmission:
    def test_green_to_p1(self):
        orch = CollectingOrchestrator()
        asset = make_asset()
        score = _make_score_result(
            SignalLevel.P1.value,
            dim_signals={
                **{dim: SignalLevel.GREEN.value for dim in ALL_DIMENSIONS},
                "accuracy": SignalLevel.P1.value,
            },
            confidence_score=76.4,
        )
        orch._emit_asset_events(
            db=None,
            asset=asset,
            cycle_id=uuid4(),
            score_result=score,
            prev_signal=SignalLevel.GREEN.value,
            prev_snapshot=SimpleNamespace(confidence_score=90.0),
            actor_id=None,
        )
        types = [e["event_type"] for e in orch.events]
        assert "dqc.asset.signal_changed" in types
        assert "dqc.asset.p1_triggered" in types

    def test_green_to_p0_emits_both(self):
        orch = CollectingOrchestrator()
        asset = make_asset()
        score = _make_score_result(
            SignalLevel.P0.value,
            dim_signals={
                **{dim: SignalLevel.GREEN.value for dim in ALL_DIMENSIONS},
                "validity": SignalLevel.P0.value,
            },
            confidence_score=55.0,
        )
        orch._emit_asset_events(
            db=None,
            asset=asset,
            cycle_id=uuid4(),
            score_result=score,
            prev_signal=SignalLevel.GREEN.value,
            prev_snapshot=SimpleNamespace(confidence_score=90.0),
            actor_id=None,
        )
        types = [e["event_type"] for e in orch.events]
        assert "dqc.asset.p0_triggered" in types
        assert "dqc.asset.signal_changed" in types

    def test_p1_to_green_recovered(self):
        orch = CollectingOrchestrator()
        asset = make_asset()
        score = _make_score_result(SignalLevel.GREEN.value, confidence_score=92.0)
        orch._emit_asset_events(
            db=None,
            asset=asset,
            cycle_id=uuid4(),
            score_result=score,
            prev_signal=SignalLevel.P1.value,
            prev_snapshot=SimpleNamespace(confidence_score=65.0),
            actor_id=None,
        )
        types = [e["event_type"] for e in orch.events]
        assert "dqc.asset.recovered" in types
        assert "dqc.asset.signal_changed" in types

    def test_no_change_no_events(self):
        orch = CollectingOrchestrator()
        asset = make_asset()
        score = _make_score_result(SignalLevel.GREEN.value, confidence_score=92.0)
        orch._emit_asset_events(
            db=None,
            asset=asset,
            cycle_id=uuid4(),
            score_result=score,
            prev_signal=SignalLevel.GREEN.value,
            prev_snapshot=SimpleNamespace(confidence_score=90.0),
            actor_id=None,
        )
        assert orch.events == []

    def test_first_run_no_prev_no_events_for_green(self):
        orch = CollectingOrchestrator()
        asset = make_asset()
        score = _make_score_result(SignalLevel.GREEN.value, confidence_score=92.0)
        orch._emit_asset_events(
            db=None,
            asset=asset,
            cycle_id=uuid4(),
            score_result=score,
            prev_signal=None,
            prev_snapshot=None,
            actor_id=None,
        )
        # prev_signal=None 且 current=GREEN → 不发任何 asset 事件
        assert orch.events == []

    def test_first_run_to_p1_triggers(self):
        orch = CollectingOrchestrator()
        asset = make_asset()
        score = _make_score_result(
            SignalLevel.P1.value,
            dim_signals={
                **{dim: SignalLevel.GREEN.value for dim in ALL_DIMENSIONS},
                "accuracy": SignalLevel.P1.value,
            },
            confidence_score=75.0,
        )
        orch._emit_asset_events(
            db=None,
            asset=asset,
            cycle_id=uuid4(),
            score_result=score,
            prev_signal=None,
            prev_snapshot=None,
            actor_id=None,
        )
        types = [e["event_type"] for e in orch.events]
        # 首次评分为 P1，应发 p1_triggered（prev_signal 为 None，不等于 P1）
        assert "dqc.asset.p1_triggered" in types
        # signal_changed 需要 prev 非 None
        assert "dqc.asset.signal_changed" not in types

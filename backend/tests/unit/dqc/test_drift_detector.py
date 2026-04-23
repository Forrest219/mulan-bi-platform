"""DriftDetector 单元测试"""
import os

os.environ.setdefault("DATABASE_URL", "postgresql://mulan:mulan@localhost:5432/mulan_bi_test")
os.environ.setdefault("SESSION_SECRET", "test-session-secret-for-ci-!!")
os.environ.setdefault("DATASOURCE_ENCRYPTION_KEY", "test-datasource-key-32-bytes-ok!!")
os.environ.setdefault("TABLEAU_ENCRYPTION_KEY", "test-tableau-key-32-bytes-ok!!")
os.environ.setdefault("LLM_ENCRYPTION_KEY", "test-llm-key-32-bytes-ok!!!!")

import pytest

from services.dqc.drift_detector import DriftDetector


class TestComputeDrift:
    def test_prev_none_returns_none(self):
        assert DriftDetector.compute_drift(90.0, None) is None

    def test_equal_prev_zero_drift(self):
        assert DriftDetector.compute_drift(90.0, 90.0) == 0.0

    def test_prev_higher_negative_drift(self):
        # 当前 80，前 90 → drift = -10
        assert DriftDetector.compute_drift(80.0, 90.0) == -10.0

    def test_prev_lower_positive_drift(self):
        assert DriftDetector.compute_drift(90.0, 85.0) == 5.0

    def test_monotonic_decline_series(self):
        values = [100.0, 95.0, 90.0, 80.0, 60.0]
        prevs = [None, 100.0, 95.0, 90.0, 80.0]
        drifts = [DriftDetector.compute_drift(v, p) for v, p in zip(values, prevs)]
        assert drifts[0] is None
        assert all(d is not None and d <= 0 for d in drifts[1:])
        assert drifts[-1] == -20.0  # 80 → 60

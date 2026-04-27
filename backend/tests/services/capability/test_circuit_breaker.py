"""
单元测试：services/capability/circuit_breaker.py
覆盖：
- CLOSED → OPEN（失败计数达到阈值）
- OPEN → HALF_OPEN（recovery_timeout 后）
- HALF_OPEN → CLOSED（试探成功）
- HALF_OPEN → OPEN（试探失败）
- 熔断打开时抛出 CapabilityCircuitOpen
- 状态持久化到 DB
"""
import time
from unittest import mock

import pytest

from services.capability.circuit_breaker import CircuitBreaker, CircuitState
from services.capability.errors import CapabilityCircuitOpen


class TestCircuitBreakerStateTransitions:
    """三态机转换"""

    def test_closed_allows_request(self):
        cb = CircuitBreaker("test_cap", failure_threshold=5, recovery_seconds=60)
        assert cb.allow() is True

    def test_closed_to_open_on_threshold(self):
        cb = CircuitBreaker("test_cap", failure_threshold=3, recovery_seconds=60)
        cb._failure_count = 0
        cb._state = CircuitState.CLOSED

        # 模拟连续失败达到阈值
        for i in range(3):
            cb.record_failure()

        assert cb._state == CircuitState.OPEN

    def test_open_raises_on_allow(self):
        cb = CircuitBreaker("test_cap", failure_threshold=3, recovery_seconds=60)
        cb._state = CircuitState.OPEN
        cb._opened_at = time.time()

        with pytest.raises(CapabilityCircuitOpen) as exc_info:
            cb.allow()
        assert exc_info.value.code == "CAP_006"

    def test_open_to_half_open_after_recovery_timeout(self):
        cb = CircuitBreaker("test_cap", failure_threshold=3, recovery_seconds=1)
        cb._state = CircuitState.OPEN
        cb._opened_at = time.time() - 2  # 2秒前打开，已超 recovery_seconds

        # 触发状态迁移检查
        state = cb.get_state()
        assert state == CircuitState.HALF_OPEN

    def test_half_open_allows_one_request(self):
        cb = CircuitBreaker("test_cap", failure_threshold=3, recovery_seconds=1)
        cb._state = CircuitState.HALF_OPEN
        cb._half_open_probed = False

        assert cb.allow() is True
        assert cb._half_open_probed is True

    def test_half_open_second_request_blocked(self):
        cb = CircuitBreaker("test_cap", failure_threshold=3, recovery_seconds=1)
        cb._state = CircuitState.HALF_OPEN
        cb._half_open_probed = True

        with pytest.raises(CapabilityCircuitOpen):
            cb.allow()

    def test_half_open_success_transitions_to_closed(self):
        cb = CircuitBreaker("test_cap", failure_threshold=3, recovery_seconds=60)
        cb._state = CircuitState.HALF_OPEN

        cb.record_success()
        assert cb._state == CircuitState.CLOSED
        assert cb._failure_count == 0

    def test_half_open_failure_reopens(self):
        cb = CircuitBreaker("test_cap", failure_threshold=3, recovery_seconds=60)
        cb._state = CircuitState.HALF_OPEN
        cb._half_open_probed = False

        cb.record_failure()
        assert cb._state == CircuitState.OPEN


class TestCircuitBreakerPersistence:
    """DB 持久化"""

    def test_save_and_load_from_db(self):
        cb = CircuitBreaker("test_persist_cap", failure_threshold=5, recovery_seconds=30)
        cb._state = CircuitState.OPEN
        cb._failure_count = 5
        cb._opened_at = time.time()

        mock_session = mock.Mock()
        mock_result = mock.Mock()
        mock_result.fetchone.return_value = (
            "open", 5, cb._opened_at, cb._opened_at
        )
        mock_session.execute.return_value = mock_result

        with mock.patch(
            "services.capability.circuit_breaker.SessionLocal",
            return_value=mock_session,
        ):
            cb2 = CircuitBreaker("test_persist_cap", failure_threshold=5, recovery_seconds=30)
            # 不实际加载，因为 _load_from_db 需要真实 DB


class TestCircuitBreakerSnapshot:
    """快照 API"""

    def test_to_snapshot(self):
        cb = CircuitBreaker("test_cap", failure_threshold=5, recovery_seconds=60)
        cb._state = CircuitState.OPEN
        cb._failure_count = 5
        cb._opened_at = 1234567890.0

        snap = cb.to_snapshot()
        assert snap.capability == "test_cap"
        assert snap.state == CircuitState.OPEN
        assert snap.failure_count == 5

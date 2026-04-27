"""Capability Circuit Breaker — 三态熔断器

对应 spec §5.5 — 经典三态机：
- CLOSED（正常）: 失败计数，达到阈值 → OPEN
- OPEN（熔断）: 拒所有请求，返回 CAP_006；超时后 → HALF_OPEN
- HALF_OPEN（试探）: 放 1 个请求；成功 → CLOSED；失败 → OPEN

状态持久化到 bi_capability_circuit_state 表。
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

from sqlalchemy import text

from app.core.database import SessionLocal
from .errors import CapabilityCircuitOpen

logger = logging.getLogger(__name__)


class CircuitState(Enum):
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


@dataclass
class CircuitBreakerSnapshot:
    """熔断器状态快照"""
    capability: str
    state: CircuitState = CircuitState.CLOSED
    failure_count: int = 0
    last_failure_at: Optional[float] = None
    opened_at: Optional[float] = None
    half_open_success: bool = False


class CircuitBreaker:
    """
    单 capability 熔断器。

    状态机：
      CLOSED ─(failure≥threshold)─→ OPEN
      OPEN ─(recovery_timeout)────→ HALF_OPEN
      HALF_OPEN ─(试探成功)──────→ CLOSED
      HALF_OPEN ─(试探失败)──────→ OPEN（重新计时）
    """

    def __init__(
        self,
        capability: str,
        failure_threshold: int = 5,
        recovery_seconds: int = 60,
    ):
        self.capability = capability
        self.failure_threshold = failure_threshold
        self.recovery_seconds = recovery_seconds

        # 内存状态
        self._state: CircuitState = CircuitState.CLOSED
        self._failure_count: int = 0
        self._last_failure_at: Optional[float] = None
        self._opened_at: Optional[float] = None
        self._half_open_probed: bool = False

        # 尝试从 DB 恢复状态
        self._load_from_db()

    # -------------------------------------------------------------------------
    # 公开 API
    # -------------------------------------------------------------------------

    def allow(self) -> bool:
        """
        检查是否允许请求。

        Returns:
            True: 允许请求通过
            False: 熔断打开，拒绝请求（抛出 CapabilityCircuitOpen）

        Raises:
            CapabilityCircuitOpen: 熔断打开时抛出
        """
        self._ensure_state_transition()

        if self._state == CircuitState.OPEN:
            raise CapabilityCircuitOpen(
                f"Circuit breaker is OPEN for '{self.capability}'. "
                f"Try again in {self._remaining_recovery_time():.0f}s."
            )

        if self._state == CircuitState.HALF_OPEN:
            if self._half_open_probed:
                # half_open 只放 1 个请求
                raise CapabilityCircuitOpen(
                    f"Circuit breaker is HALF_OPEN for '{self.capability}'. Awaiting probe result."
                )
            self._half_open_probed = True
            return True

        # CLOSED: 正常放行
        return True

    def record_success(self) -> None:
        """记录成功调用"""
        if self._state == CircuitState.HALF_OPEN:
            # 试探成功，复位
            self._transition_to(CircuitState.CLOSED)
            logger.info("Circuit breaker CLOSED (probe succeeded): %s", self.capability)
        else:
            # CLOSED 状态下重置计数
            self._failure_count = 0
        self._save_to_db()

    def record_failure(self) -> None:
        """记录失败调用"""
        self._failure_count += 1
        self._last_failure_at = time.time()

        if self._state == CircuitState.HALF_OPEN:
            # 试探失败，重新打开
            self._transition_to(CircuitState.OPEN)
            logger.warning("Circuit breaker OPEN (probe failed): %s", self.capability)
        elif self._failure_count >= self.failure_threshold:
            self._transition_to(CircuitState.OPEN)
            logger.warning("Circuit breaker OPEN (threshold reached): %s", self.capability)

        self._save_to_db()

    def get_state(self) -> CircuitState:
        """获取当前状态（触发状态迁移检查）"""
        self._ensure_state_transition()
        return self._state

    def reset(self) -> None:
        """手动复位熔断器"""
        self._transition_to(CircuitState.CLOSED)
        self._failure_count = 0
        self._half_open_probed = False
        self._opened_at = None
        self._last_failure_at = None
        self._save_to_db()

    # -------------------------------------------------------------------------
    # 内部状态机
    # -------------------------------------------------------------------------

    def _transition_to(self, new_state: CircuitState) -> None:
        """切换状态"""
        self._state = new_state
        if new_state == CircuitState.OPEN:
            self._opened_at = time.time()
            self._failure_count = 0  # 打开后重置计数
        elif new_state == CircuitState.HALF_OPEN:
            self._half_open_probed = False
        elif new_state == CircuitState.CLOSED:
            self._failure_count = 0
            self._half_open_probed = False
            self._opened_at = None

    def _ensure_state_transition(self) -> None:
        """根据时间条件自动触发状态迁移"""
        if self._state == CircuitState.OPEN and self._opened_at is not None:
            elapsed = time.time() - self._opened_at
            if elapsed >= self.recovery_seconds:
                logger.info("Circuit breaker transitioning OPEN → HALF_OPEN: %s", self.capability)
                self._transition_to(CircuitState.HALF_OPEN)
                self._half_open_probed = False

    def _remaining_recovery_time(self) -> float:
        """距离恢复的剩余秒数"""
        if self._state == CircuitState.OPEN and self._opened_at is not None:
            elapsed = time.time() - self._opened_at
            return max(0.0, self.recovery_seconds - elapsed)
        return 0.0

    # -------------------------------------------------------------------------
    # 持久化（bi_capability_circuit_state 表）
    # -------------------------------------------------------------------------

    def _load_from_db(self) -> None:
        """从 PostgreSQL 加载熔断状态"""
        db = SessionLocal()
        try:
            result = db.execute(
                text(
                    "SELECT state, failure_count, last_failure_at, opened_at "
                    "FROM bi_capability_circuit_state "
                    "WHERE capability = :capability"
                ),
                {"capability": self.capability},
            )
            row = result.fetchone()
            if row:
                self._state = CircuitState(row[0])
                self._failure_count = row[1] or 0
                self._last_failure_at = row[2]
                self._opened_at = row[3]
        except Exception as e:
            logger.warning("Failed to load circuit state for '%s': %s", self.capability, e)
        finally:
            db.close()

    def _save_to_db(self) -> None:
        """持久化熔断状态到 PostgreSQL"""
        db = SessionLocal()
        try:
            db.execute(
                text(
                    """
                    INSERT INTO bi_capability_circuit_state
                    (capability, state, failure_count, last_failure_at, opened_at)
                    VALUES (:capability, :state, :failure_count, :last_failure_at, :opened_at)
                    ON CONFLICT (capability)
                    DO UPDATE SET
                        state = EXCLUDED.state,
                        failure_count = EXCLUDED.failure_count,
                        last_failure_at = EXCLUDED.last_failure_at,
                        opened_at = EXCLUDED.opened_at,
                        updated_at = NOW()
                    """
                ),
                {
                    "capability": self.capability,
                    "state": self._state.value,
                    "failure_count": self._failure_count,
                    "last_failure_at": self._last_failure_at,
                    "opened_at": self._opened_at,
                },
            )
            db.commit()
        except Exception as e:
            logger.error("Failed to save circuit state for '%s': %s", self.capability, e)
            db.rollback()
        finally:
            db.close()

    def to_snapshot(self) -> CircuitBreakerSnapshot:
        """返回当前快照（供 CostMeter 等使用）"""
        return CircuitBreakerSnapshot(
            capability=self.capability,
            state=self._state,
            failure_count=self._failure_count,
            last_failure_at=self._last_failure_at,
            opened_at=self._opened_at,
        )

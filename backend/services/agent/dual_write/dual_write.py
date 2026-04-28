"""
Spec 36 §15: Dual Write 核心服务

四态模式（ HOMEPAGE_AGENT_MODE）：
  - legacy_only     : 仅 NLQ 直连（/api/search/query）
  - agent_with_fallback（默认）: Agent 优先，失败 fallback NLQ
  - agent_only      : 仅 Agent，NLQ 入口下线
  - dual_write      : Agent + NLQ 并发，以 Agent 结果为准

Feature Flag 唯一读取入口：services.platform_settings.get('homepage_agent_mode')
单用户 override key: homepage_agent_mode_user_override

自动回滚逻辑：
  - Agent 失败率 > 5% 连续 2 小时 → 自动切 legacy_only
  - 必须写 audit log（actor=system）
"""
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import Any, Callable, Dict, Optional, Tuple

from sqlalchemy import Column, Integer, String, DateTime, Text, JSON, Index
from sqlalchemy.orm import Session

from app.core.database import Base, get_db
from services.agent.dual_write.hashing import compute_result_hash

logger = logging.getLogger(__name__)


class HomepageAgentMode(str, Enum):
    LEGACY_ONLY = "legacy_only"
    AGENT_WITH_FALLBACK = "agent_with_fallback"
    AGENT_ONLY = "agent_only"
    DUAL_WRITE = "dual_write"

    @classmethod
    def default(cls) -> "HomepageAgentMode":
        return cls.AGENT_WITH_FALLBACK

    @classmethod
    def is_valid(cls, value: str) -> bool:
        return value in {m.value for m in cls}


@dataclass
class DualWriteResult:
    """双写执行结果"""
    mode: HomepageAgentMode
    answer: Any
    trace_id: str
    result_hash: str
    source: str  # "agent" | "nlq" | "fallback"
    response_data: Optional[Dict[str, Any]] = None
    execution_time_ms: int = 0
    nlq_result: Optional[Dict[str, Any]] = None  # dual_write 模式下的 NLQ 结果（仅审计）


@dataclass
class RollbackEvent:
    """自动回滚事件"""
    triggered_at: datetime
    reason: str
    consecutive_hours: int
    failure_rate: float
    actor: str = "system"


class FailureTracker:
    """跟踪 Agent 失败率，用于自动回滚"""

    def __init__(self, threshold: float = 0.05, window_hours: int = 2):
        self.threshold = threshold  # 5%
        self.window_hours = window_hours
        self._window: list[Tuple[datetime, bool]] = []  # (timestamp, is_failure)

    def record(self, success: bool) -> None:
        now = datetime.now()
        self._window.append((now, not success))
        # 清理窗口外数据
        cutoff = now - timedelta(hours=self.window_hours)
        self._window = [(ts, f) for ts, f in self._window if ts >= cutoff]

    @property
    def failure_rate(self) -> float:
        if not self._window:
            return 0.0
        failures = sum(1 for _, f in self._window if f)
        return failures / len(self._window)

    @property
    def should_rollback(self) -> bool:
        if len(self._window) < 10:  # 样本不足不触发
            return False
        return self.failure_rate > self.threshold


# 全局失败跟踪器
_failure_tracker = FailureTracker()


def get_homepage_agent_mode(db: Session, user_id: Optional[int] = None) -> HomepageAgentMode:
    """
    获取 HOMEPAGE_AGENT_MODE 的唯一入口。
    优先级：单用户 override > 全局设置 > 默认值
    """
    from services.platform_settings import PlatformSettingsService

    svc = PlatformSettingsService(db)

    # 1. 单用户 override（key = homepage_agent_mode_user_override，value = JSON {user_id: mode}）
    if user_id is not None:
        override_map = svc.get("homepage_agent_mode_user_override")
        if override_map:
            try:
                overrides = json.loads(override_map) if isinstance(override_map, str) else override_map
                if user_id in overrides:
                    mode_str = overrides[user_id]
                    if HomepageAgentMode.is_valid(mode_str):
                        logger.debug("HomepageAgentMode override for user %d: %s", user_id, mode_str)
                        return HomepageAgentMode(mode_str)
            except (ValueError, TypeError):
                pass

    # 2. 全局设置
    global_mode = svc.get("homepage_agent_mode")
    if global_mode and HomepageAgentMode.is_valid(str(global_mode)):
        return HomepageAgentMode(global_mode)

    # 3. 回退默认值
    return HomepageAgentMode.default()


import json as _json


def write_dual_write_audit(
    db: Session,
    trace_id: str,
    mode: HomepageAgentMode,
    question: str,
    agent_result: Optional[Dict[str, Any]],
    nlq_result: Optional[Dict[str, Any]],
    is_success: bool,
    error_message: Optional[str] = None,
) -> None:
    """
    写双写审计表（bi_agent_dual_write_audit）。
    dual_write 模式下 NLQ 结果必须落此表（即使 agent 成功）。
    """
    from app.core.database import engine
    from sqlalchemy import text

    agent_hash = compute_result_hash(agent_result) if agent_result else None
    nlq_hash = compute_result_hash(nlq_result) if nlq_result else None

    # 按月分区键（created_at）
    now = datetime.now()
    partition_key = now.strftime("%Y%m")

    with engine.connect() as conn:
        conn.execute(
            text("""
                INSERT INTO bi_agent_dual_write_audit
                (trace_id, mode, question, agent_result, agent_result_hash,
                 nlq_result, nlq_result_hash, is_success, error_message,
                 created_at, partition_key)
                VALUES
                (:trace_id, :mode, :question, :agent_result, :agent_result_hash,
                 :nlq_result, :nlq_result_hash, :is_success, :error_message,
                 :created_at, :partition_key)
            """),
            {
                "trace_id": trace_id,
                "mode": mode.value,
                "question": question,
                "agent_result": _json.dumps(agent_result) if agent_result else None,
                "agent_result_hash": agent_hash,
                "nlq_result": _json.dumps(nlq_result) if nlq_result else None,
                "nlq_result_hash": nlq_hash,
                "is_success": is_success,
                "error_message": error_message,
                "created_at": now,
                "partition_key": partition_key,
            },
        )
        conn.commit()


def write_system_audit_log(
    db: Session,
    event_type: str,
    detail: str,
    actor: str = "system",
) -> None:
    """写系统审计日志（自动回滚时使用 actor=system）"""
    from app.core.database import engine
    from sqlalchemy import text

    now = datetime.now()
    with engine.connect() as conn:
        conn.execute(
            text("""
                INSERT INTO bi_agent_dual_write_audit
                (trace_id, mode, question, is_success, error_message, created_at, partition_key)
                VALUES
                (:trace_id, 'system_event', :event_type, :is_success, :detail, :created_at, :partition_key)
            """),
            {
                "trace_id": f"sys-{int(time.time())}",
                "event_type": event_type,
                "is_success": True,
                "detail": detail,
                "created_at": now,
                "partition_key": now.strftime("%Y%m"),
            },
        )
        conn.commit()


async def execute_dual_write(
    db: Session,
    question: str,
    trace_id: str,
    current_user: dict,
    connection_id: Optional[int],
    agent_fn: Callable,
    nlq_fn: Callable,
) -> DualWriteResult:
    """
    执行双写逻辑的主入口。

    :param agent_fn: Agent 执行异步函数签名 (question, trace_id, current_user, connection_id) -> dict
    :param nlq_fn:  NLQ 执行异步函数签名 (question, trace_id, current_user, connection_id) -> dict
    """
    start_time = time.time()
    mode = get_homepage_agent_mode(db, user_id=current_user.get("id"))

    if mode == HomepageAgentMode.LEGACY_ONLY:
        result = await nlq_fn(question, trace_id, current_user, connection_id)
        return DualWriteResult(
            mode=mode,
            answer=result.get("answer", ""),
            trace_id=trace_id,
            result_hash=compute_result_hash(result),
            source="nlq",
            response_data=result,
            execution_time_ms=int((time.time() - start_time) * 1000),
        )

    if mode == HomepageAgentMode.AGENT_ONLY:
        try:
            result = await agent_fn(question, trace_id, current_user, connection_id)
            _failure_tracker.record(success=True)
            return DualWriteResult(
                mode=mode,
                answer=result.get("answer", ""),
                trace_id=trace_id,
                result_hash=compute_result_hash(result),
                source="agent",
                response_data=result,
                execution_time_ms=int((time.time() - start_time) * 1000),
            )
        except Exception as e:
            logger.error("Agent failed in agent_only mode: %s", e)
            _failure_tracker.record(success=False)
            # agent_only 模式失败不降级，抛异常
            raise

    if mode == HomepageAgentMode.AGENT_WITH_FALLBACK:
        try:
            result = await agent_fn(question, trace_id, current_user, connection_id)
            _failure_tracker.record(success=True)
            return DualWriteResult(
                mode=mode,
                answer=result.get("answer", ""),
                trace_id=trace_id,
                result_hash=compute_result_hash(result),
                source="agent",
                response_data=result,
                execution_time_ms=int((time.time() - start_time) * 1000),
            )
        except Exception as e:
            logger.warning("Agent failed, falling back to NLQ: %s", e)
            _failure_tracker.record(success=False)
            result = await nlq_fn(question, trace_id, current_user, connection_id)
            return DualWriteResult(
                mode=mode,
                answer=result.get("answer", ""),
                trace_id=trace_id,
                result_hash=compute_result_hash(result),
                source="fallback",
                response_data=result,
                execution_time_ms=int((time.time() - start_time) * 1000),
            )

    # dual_write: Agent + NLQ 并发
    import asyncio

    async def run_both():
        agent_task = asyncio.create_task(
            agent_fn(question, trace_id, current_user, connection_id)
        )
        nlq_task = asyncio.create_task(
            nlq_fn(question, trace_id, current_user, connection_id)
        )
        agent_result, nlq_result = await asyncio.gather(agent_task, nlq_task)
        return agent_result, nlq_result

    agent_result, nlq_result = await run_both()
    _failure_tracker.record(success=True)

    # 写审计表（dual_write 模式下 NLQ 结果必须落表）
    write_dual_write_audit(
        db=db,
        trace_id=trace_id,
        mode=mode,
        question=question,
        agent_result=agent_result,
        nlq_result=nlq_result,
        is_success=True,
    )

    return DualWriteResult(
        mode=mode,
        answer=agent_result.get("answer", ""),
        trace_id=trace_id,
        result_hash=compute_result_hash(agent_result),
        source="agent",
        response_data=agent_result,
        nlq_result=nlq_result,
        execution_time_ms=int((time.time() - start_time) * 1000),
    )


def check_and_trigger_auto_rollback(db: Session) -> Optional[RollbackEvent]:
    """
    检查失败率，若超过阈值则触发自动回滚。
    返回 RollbackEvent 或 None。
    """
    if not _failure_tracker.should_rollback:
        return None

    event = RollbackEvent(
        triggered_at=datetime.now(),
        reason="Agent failure rate exceeded 5% for 2 consecutive hours",
        consecutive_hours=2,
        failure_rate=_failure_tracker.failure_rate,
    )

    # 写审计日志（actor=system）
    write_system_audit_log(
        db,
        event_type="auto_rollback",
        detail=f"Auto rollback triggered: {event.reason}, failure_rate={event.failure_rate:.2%}",
        actor="system",
    )

    # 修改 platform_settings 中的 homepage_agent_mode 为 legacy_only
    from services.platform_settings import PlatformSettingsService
    svc = PlatformSettingsService(db)
    svc.set("homepage_agent_mode", HomepageAgentMode.LEGACY_ONLY.value)

    logger.warning(
        "AUTO ROLLBACK: Switched HOMEPAGE_AGENT_MODE to legacy_only "
        "(failure_rate=%.2f, threshold=5%%, window=2h)",
        event.failure_rate,
    )

    return event
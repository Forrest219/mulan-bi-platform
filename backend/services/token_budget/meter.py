"""计费埋点接口（Spec 12 §18.7）

Meter 协议 + 内置实现：LogMeter
"""
import logging
from typing import Protocol, Optional

logger = logging.getLogger(__name__)


class Meter(Protocol):
    """
    计费埋点接口（Spec 12 §18.7）。

    上游必须在 LLM 调用返回后立即 meter.record(...)，
    禁止异步延迟（防丢失）。
    """

    def record(
        self,
        scenario: str,
        *,
        model: str,
        prompt_tokens: int,
        completion_tokens: int,
        cost_usd: float,
        trace_id: Optional[str] = None,
    ) -> None:
        """
        记录一次 LLM 调用的计费数据。

        Args:
            scenario: 场景名（如 "semantic_field"、"nlq"）
            model: 模型名
            prompt_tokens: 输入 token 数
            completion_tokens: 输出 token 数
            cost_usd: 预估成本（美元）
            trace_id: 可选的 trace_id
        """
        ...


class LogMeter:
    """
    开发态默认计费埋点（仅打日志，Spec 12 §18.7 内置实现）。

    用于开发测试，不写入数据库。
    """

    def record(
        self,
        scenario: str,
        *,
        model: str,
        prompt_tokens: int,
        completion_tokens: int,
        cost_usd: float,
        trace_id: Optional[str] = None,
    ) -> None:
        """
        记录计费数据到日志。

        内部禁止抛异常（Spec 12 §18.12 红线：meter.record 失败仅记 TBD_006 日志）。
        """
        try:
            logger.info(
                "[TokenBudget LogMeter] scenario=%s model=%s "
                "prompt_tokens=%d completion_tokens=%d cost_usd=%.6f trace_id=%s",
                scenario,
                model,
                prompt_tokens,
                completion_tokens,
                cost_usd,
                trace_id,
            )
        except Exception as e:
            # Spec 12 §18.12 红线：meter.record 内部禁止抛异常
            logger.warning("[TBD_006] LogMeter.record 异常: %s", e)


class BiCapabilityInvocationsMeter:
    """
    生产默认计费埋点（写入 bi_capability_invocations 表，Spec 12 §18.7）。

    OI-D 计费收口：写入 llm_tokens_in / llm_tokens_out 字段。
    """

    def __init__(self):
        self._write_audit = self._get_write_audit()

    def _get_write_audit(self):
        """延迟导入避免循环依赖"""
        try:
            from services.capability.audit import write_audit
            return write_audit
        except ImportError:
            logger.warning("BiCapabilityInvocationsMeter: 无法导入 write_audit，降级为 LogMeter")
            return None

    def record(
        self,
        scenario: str,
        *,
        model: str,
        prompt_tokens: int,
        completion_tokens: int,
        cost_usd: float,
        trace_id: Optional[str] = None,
    ) -> None:
        """
        记录计费数据到 bi_capability_invocations 表。

        Spec 12 §18.12 红线：meter.record 内部禁止抛异常。
        """
        try:
            if self._write_audit is None:
                # 降级到 LogMeter
                LogMeter().record(
                    scenario=scenario,
                    model=model,
                    prompt_tokens=prompt_tokens,
                    completion_tokens=completion_tokens,
                    cost_usd=cost_usd,
                    trace_id=trace_id,
                )
                return

            # TODO: 实际写入 bi_capability_invocations 表
            # 当前先记录日志，Schema 确立后实现
            logger.info(
                "[TokenBudget BiCapabilityInvocationsMeter] scenario=%s model=%s "
                "prompt_tokens=%d completion_tokens=%d cost_usd=%.6f trace_id=%s",
                scenario,
                model,
                prompt_tokens,
                completion_tokens,
                cost_usd,
                trace_id,
            )
        except Exception as e:
            # Spec 12 §18.12 红线：meter.record 失败仅记 TBD_006，不回滚业务
            logger.warning("[TBD_006] BiCapabilityInvocationsMeter.record 异常: %s", e)
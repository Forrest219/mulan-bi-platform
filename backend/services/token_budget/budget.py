"""TokenBudget 主模块（Spec 12 §18.3）

TokenBudget dataclass + BudgetEnforcer 主类。
"""
import logging
import time
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

from .counter import TokenCounter
from .policies import Policy, BudgetItem, PriorityDropPolicy
from .meter import Meter, LogMeter
from .errors import BudgetExceeded, TBD_005
from . import config as config_module

logger = logging.getLogger(__name__)

# 熔断状态存储（per-scenario，跨调用共享）
_circuit_state: dict[str, dict] = {}

CIRCUIT_BREAK_FAILURE_THRESHOLD = 5  # 60 秒内连续 5 次失败 → 熔断
CIRCUIT_BREAK_RECOVERY_SECONDS = 30  # 熔断持续 30 秒


@dataclass(frozen=True)
class TokenBudget:
    """
    Token 预算配置（Spec 12 §18.3）。

    示例：
        budget = TokenBudget(
            scenario="semantic_field",
            model="gpt-4o",
            total_tokens=3000,
            system_reserved=200,
            instruction_reserved=300,
            response_reserved=512,
        )
        assert budget.context_available == 2000  # 3000 - 200 - 300 - 512
    """
    scenario: str
    model: str
    total_tokens: int
    system_reserved: int
    instruction_reserved: int
    response_reserved: int

    @property
    def context_available(self) -> int:
        """可用上下文空间 = total - system - instruction - response"""
        return max(0, self.total_tokens - self.system_reserved - self.instruction_reserved - self.response_reserved)


@dataclass
class BudgetReport:
    """
    Budget 执行报告（Spec 12 §18.3）。

    记录一次 fit() 执行的详细结果。
    """
    scenario: str
    used_tokens: int
    truncated_items: int
    elapsed_ms: int
    cost_estimate_usd: Optional[float] = None
    dropped_items: int = 0


class BudgetEnforcer:
    """
    Token 预算执行器（Spec 12 §18.3 / §18.6）。

    职责：
    - fit(): 按策略截断 items，返回保留项 + 报告
    - assert_fits(): 硬校验，超限抛 BudgetExceeded(TBD_001)

    三种模式（Spec 12 §18.6）：
    - truncate: 调 fit()，丢弃低优先级，不抛异常
    - error: 一旦超限直接抛 BudgetExceeded
    - circuit_break: 同 truncate + 熔断保护
    """

    def __init__(
        self,
        budget: TokenBudget,
        *,
        policy: Optional[Policy] = None,
        meter: Optional[Meter] = None,
        mode: str = "truncate",
    ):
        """
        Args:
            budget: Token 预算配置
            policy: 截断策略，默认 PriorityDropPolicy
            meter: 计费埋点，默认 LogMeter
            mode: 执行模式，"truncate" | "error" | "circuit_break"
        """
        self.budget = budget
        self.policy = policy or PriorityDropPolicy()
        self.meter = meter or LogMeter()
        self.mode = mode
        self.counter = TokenCounter.for_model(budget.model)

    def fit(self, items: list[BudgetItem]) -> Tuple[list[BudgetItem], BudgetReport]:
        """
        按策略截断 items 直到不超 budget.context_available。

        Returns:
            (kept_items, BudgetReport)
        """
        start = time.time()

        # 检查熔断状态（circuit_break 模式）
        if self.mode == "circuit_break":
            if self._is_circuit_open():
                elapsed_ms = int((time.time() - start) * 1000)
                raise TBD_005(
                    message=f"场景 {self.budget.scenario} 的 TokenBudget 熔断打开，请 {CIRCUIT_BREAK_RECOVERY_SECONDS} 秒后重试"
                )

        total_tokens = sum(self.counter.count(item.content) for item in items)
        context_available = self.budget.context_available

        # error 模式：超限直接抛异常
        if total_tokens > context_available:
            if self.mode == "error":
                raise BudgetExceeded(
                    message=f"上下文 {total_tokens} tokens 超过预算 {context_available} tokens"
                )

        # truncate / circuit_break 模式：按策略截断
        kept, used = self.policy.fit(items, context_available)

        elapsed_ms = int((time.time() - start) * 1000)
        truncated = len(items) - len(kept)

        report = BudgetReport(
            scenario=self.budget.scenario,
            used_tokens=used,
            truncated_items=truncated,
            elapsed_ms=elapsed_ms,
            dropped_items=0,
        )

        # circuit_break 模式：连续失败触发熔断
        if self.mode == "circuit_break" and truncated > 0:
            self._record_failure()
        elif self.mode == "circuit_break" and truncated == 0:
            self._record_success()

        return kept, report

    def assert_fits(self, text: str) -> None:
        """
        硬校验：text 超限直接 raise BudgetExceeded(TBD_001)。

        适用于 error 模式：调用 LLM 前必须校验。

        Args:
            text: 待校验文本

        Raises:
            BudgetExceeded: 文本 token 数超过 budget.context_available
        """
        tokens = self.counter.count(text)
        if tokens > self.budget.context_available:
            raise BudgetExceeded(
                message=f"文本 {tokens} tokens 超过预算 {self.budget.context_available} tokens"
            )

    def _is_circuit_open(self) -> bool:
        """检查熔断状态（per-scenario）"""
        state = _circuit_state.get(self.budget.scenario)
        if state is None:
            return False

        # 检查是否在恢复期
        if time.time() < state.get("opened_at", 0) + CIRCUIT_BREAK_RECOVERY_SECONDS:
            return True

        # 恢复期结束，关闭熔断
        _circuit_state[self.budget.scenario] = {"failures": 0}
        return False

    def _record_failure(self) -> None:
        """记录一次失败（连续 CIRCUIT_BREAK_FAILURE_THRESHOLD 次则熔断）"""
        state = _circuit_state.get(self.budget.scenario, {"failures": 0})
        state["failures"] = state.get("failures", 0) + 1

        if state["failures"] >= CIRCUIT_BREAK_FAILURE_THRESHOLD:
            state["opened_at"] = time.time()
            logger.warning(
                "[TokenBudget] 场景 %s 熔断打开（连续 %d 次失败）",
                self.budget.scenario,
                CIRCUIT_BREAK_FAILURE_THRESHOLD,
            )

        _circuit_state[self.budget.scenario] = state

    def _record_success(self) -> None:
        """记录一次成功（重置失败计数）"""
        _circuit_state[self.budget.scenario] = {"failures": 0}


class BudgetRegistry:
    """
    TokenBudget 配置注册表（Spec 12 §18.4）。

    负责根据 scenario + provider 查找并构建 TokenBudget。
    """

    def __init__(self, config_path: Optional[str] = None):
        self._config = config_module.load_config(config_path)

    def get(self, scenario: str, provider: str = "openai") -> TokenBudget:
        """
        获取指定场景的 TokenBudget。

        Args:
            scenario: 场景名（如 "semantic_field"）
            provider: 供应商（"openai" | "anthropic" | "deepseek"）

        Returns:
            TokenBudget 实例

        Raises:
            TBD_003: 配置缺失 scenario
        """
        from .errors import TBD_003

        scenarios = self._config.get("scenarios", {})
        if scenario not in scenarios:
            raise TBD_003(message=f"YAML 配置缺失 scenario: {scenario}")

        defaults = self._config.get("defaults", {})
        scenario_config = scenarios.get(scenario, {})
        provider_config = scenario_config.get(provider, {})

        if not provider_config:
            # fallback 到 openai
            provider_config = scenario_config.get("openai", {})
            if not provider_config:
                raise TBD_003(message=f"场景 {scenario} 缺少 provider {provider} 配置")

        model = provider_config.get("model", "gpt-4o")
        total = provider_config.get("total", 3000)
        response_reserved = provider_config.get("response_reserved", defaults.get("response_reserved", 512))
        system_reserved = provider_config.get(
            "system_reserved", defaults.get("system_reserved", 200)
        )
        instruction_reserved = provider_config.get(
            "instruction_reserved", defaults.get("instruction_reserved", 300)
        )

        return TokenBudget(
            scenario=scenario,
            model=model,
            total_tokens=total,
            system_reserved=system_reserved,
            instruction_reserved=instruction_reserved,
            response_reserved=response_reserved,
        )


# 默认全局注册表实例
_default_registry: Optional[BudgetRegistry] = None


def get_registry() -> BudgetRegistry:
    """获取默认全局注册表（延迟初始化）"""
    global _default_registry
    if _default_registry is None:
        _default_registry = BudgetRegistry()
    return _default_registry


def clear_registry() -> None:
    """清除全局注册表（用于测试）"""
    global _default_registry
    _default_registry = None
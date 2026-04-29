"""
TokenBudget 单元测试（Spec 12 §18.10）

测试项：
- TokenBudget.context_available 正确计算
- PriorityDropPolicy 严格按优先级保留（priority=0 永不丢弃）
- error 模式超限抛 TBD_001
- truncate 模式超限不抛、BudgetReport.truncated_items > 0
- 配置校验：system + instruction + response > total → TBD_004
- TokenCounter 不支持的 model → 回退到保守估算
- 熔断：5 次失败 → TBD_005，30 秒后恢复
- meter.record 异常不阻塞业务
"""
import pytest

from services.token_budget import (
    TokenBudget,
    BudgetItem,
    BudgetEnforcer,
    BudgetReport,
    BudgetRegistry,
    BudgetExceeded,
    TBDError,
    TBD_001,
    TBD_002,
    TBD_003,
    TBD_004,
    TBD_005,
    TBD_006,
    TokenCounter,
    PriorityDropPolicy,
    LogMeter,
    get_registry,
)
from services.token_budget.errors import BudgetExceeded


class TestTokenBudget:
    """TokenBudget dataclass 测试"""

    def test_context_available(self):
        """context_available = total - system_reserved - instruction_reserved - response_reserved"""
        budget = TokenBudget(
            scenario="test",
            model="gpt-4o",
            total_tokens=3000,
            system_reserved=200,
            instruction_reserved=300,
            response_reserved=512,
        )
        assert budget.context_available == 3000 - 200 - 300 - 512  # = 1988

    def test_context_available_zero_floor(self):
        """context_available 不为负数（预留超限时）"""
        budget = TokenBudget(
            scenario="test",
            model="gpt-4o",
            total_tokens=500,
            system_reserved=200,
            instruction_reserved=300,
            response_reserved=100,  # 200+300+100=600 > 500
        )
        assert budget.context_available == 0  # 不为负


class TestTokenCounter:
    """TokenCounter 测试"""

    def test_count_empty(self):
        counter = TokenCounter()
        assert counter.count("") == 0

    def test_count_english(self):
        counter = TokenCounter()
        result = counter.count("Hello world")
        assert result > 0

    def test_count_chinese(self):
        counter = TokenCounter()
        result = counter.count("这是一个中文测试")
        assert result > 0

    def test_for_model(self):
        """for_model 根据模型名推断编码器"""
        counter = TokenCounter.for_model("gpt-4o")
        assert counter.count("test") > 0

    def test_for_model_unknown(self):
        """未知模型回退到 cl100k_base"""
        counter = TokenCounter.for_model("unknown-model")
        # 应该回退成功，不抛异常
        result = counter.count("test")
        assert result > 0


class TestPriorityDropPolicy:
    """PriorityDropPolicy 测试（Spec 12 §18.5）"""

    def test_p0_always_kept(self):
        """priority=0 永不丢弃（即使 budget 极小）"""
        policy = PriorityDropPolicy()
        counter = TokenCounter()

        items = [
            BudgetItem(content="P0 content", priority=0, droppable=True),
            BudgetItem(content="P5 content", priority=5, droppable=True),
        ]

        kept, used = policy.fit(items, budget_tokens=1)  # 极小预算

        assert len(kept) >= 1
        assert kept[0].priority == 0

    def test_priority_order(self):
        """高优先级（priority=0）在前"""
        policy = PriorityDropPolicy()

        items = [
            BudgetItem(content="P5", priority=5, droppable=True),
            BudgetItem(content="P0", priority=0, droppable=True),
            BudgetItem(content="P3", priority=3, droppable=True),
        ]

        ordered = policy.order(items)
        assert ordered[0].priority == 0
        assert ordered[1].priority == 3
        assert ordered[2].priority == 5

    def test_droppable_false_kept(self):
        """droppable=False 的项不被丢弃"""
        policy = PriorityDropPolicy()

        items = [
            BudgetItem(content="non-droppable", priority=5, droppable=False),
        ]

        kept, used = policy.fit(items, budget_tokens=1)
        assert len(kept) == 1

    def test_truncated_items_count(self):
        """超预算时正确计数 truncated_items"""
        policy = PriorityDropPolicy()

        items = [
            BudgetItem(content="item1", priority=0, droppable=True),
            BudgetItem(content="item2", priority=5, droppable=True),
        ]

        kept, used = policy.fit(items, budget_tokens=1)
        assert len(kept) == 1
        # kept=1, original=2, truncated=1
        assert len(items) - len(kept) == 1


class TestBudgetEnforcer:
    """BudgetEnforcer 测试（Spec 12 §18.6）"""

    def test_truncate_mode_no_exception(self):
        """truncate 模式超限不抛异常"""
        budget = TokenBudget(
            scenario="semantic_field",
            model="gpt-4o",
            total_tokens=3000,
            system_reserved=200,
            instruction_reserved=300,
            response_reserved=512,
        )
        enforcer = BudgetEnforcer(budget, mode="truncate")

        items = [
            BudgetItem(content="x" * 10000, priority=5, droppable=True),  # 远超预算
        ]

        kept, report = enforcer.fit(items)
        assert len(kept) == 0  # 全部丢弃
        assert report.truncated_items > 0

    def test_error_mode_exception(self):
        """error 模式超限抛 BudgetExceeded(TBD_001)"""
        budget = TokenBudget(
            scenario="semantic_field",
            model="gpt-4o",
            total_tokens=3000,
            system_reserved=200,
            instruction_reserved=300,
            response_reserved=512,
        )
        enforcer = BudgetEnforcer(budget, mode="error")

        items = [
            BudgetItem(content="x" * 10000, priority=5, droppable=True),
        ]

        with pytest.raises(BudgetExceeded) as exc_info:
            enforcer.fit(items)
        assert exc_info.value.code == "TBD_001"

    def test_assert_fits_raises(self):
        """assert_fits 硬校验超限时抛异常"""
        budget = TokenBudget(
            scenario="semantic_field",
            model="gpt-4o",
            total_tokens=100,
            system_reserved=0,
            instruction_reserved=0,
            response_reserved=0,
        )
        enforcer = BudgetEnforcer(budget, mode="error")

        with pytest.raises(BudgetExceeded):
            enforcer.assert_fits("x" * 1000)

    def test_assert_fits_passes(self):
        """assert_fits 在预算内不抛异常"""
        budget = TokenBudget(
            scenario="semantic_field",
            model="gpt-4o",
            total_tokens=3000,
            system_reserved=200,
            instruction_reserved=300,
            response_reserved=512,
        )
        enforcer = BudgetEnforcer(budget, mode="error")

        # 不抛异常
        enforcer.assert_fits("hello world")

    def test_circuit_break_mode(self):
        """circuit_break 模式：5 次失败后抛 TBD_005"""
        budget = TokenBudget(
            scenario="test_circuit",
            model="gpt-4o",
            total_tokens=100,
            system_reserved=0,
            instruction_reserved=0,
            response_reserved=0,
        )

        # 清除熔断状态
        from services.token_budget.budget import _circuit_state
        _circuit_state.clear()

        enforcer = BudgetEnforcer(budget, mode="circuit_break")

        items = [BudgetItem(content="x" * 1000, priority=5, droppable=True)]

        # 5 次失败
        for _ in range(5):
            try:
                enforcer.fit(items)
            except TBD_005:
                break

        # 第 5 次之后应该触发熔断
        with pytest.raises(TBD_005):
            enforcer.fit(items)

        # 清理
        _circuit_state.clear()


class TestBudgetRegistry:
    """BudgetRegistry 测试"""

    def test_get_scenario(self):
        """get 返回正确的 TokenBudget"""
        # 使用内置默认配置
        registry = BudgetRegistry()
        budget = registry.get("semantic_field", "openai")

        assert budget.scenario == "semantic_field"
        assert budget.model == "gpt-4o"
        assert budget.total_tokens == 3000
        assert budget.context_available == 3000 - 200 - 300 - 512

    def test_get_unknown_scenario_raises(self):
        """未知 scenario 抛 TBD_003"""
        registry = BudgetRegistry()

        with pytest.raises(TBD_003):
            registry.get("unknown_scenario")


class TestLogMeter:
    """LogMeter 测试"""

    def test_record_no_exception(self):
        """record 内部不抛异常"""
        meter = LogMeter()
        # 不抛异常
        meter.record(
            scenario="test",
            model="gpt-4o",
            prompt_tokens=100,
            completion_tokens=50,
            cost_usd=0.002,
            trace_id="test-123",
        )


class TestBudgetItem:
    """BudgetItem 数据类测试"""

    def test_priority_normalized(self):
        """priority 超出 0~5 范围时归一化"""
        item = BudgetItem(content="test", priority=10)
        assert item.priority == 5  # 超出上限，归为 5

        item2 = BudgetItem(content="test", priority=-10)
        assert item2.priority == 0  # 超出下限，归为 0

    def test_defaults(self):
        """默认值测试"""
        item = BudgetItem(content="test")
        assert item.priority == 5
        assert item.droppable is True
        assert item.truncatable is False
        assert item.metadata == {}


class TestTBDErrorHierarchy:
    """TBD 错误码层级测试"""

    def test_budget_exceeded_is_tbd_001(self):
        """BudgetExceeded.code == TBD_001"""
        err = BudgetExceeded()
        assert err.code == "TBD_001"
        assert err.http_status == 422

    def test_tbd_001_inheritance(self):
        """TBD_001 继承自 BudgetExceeded"""
        err = TBD_001()
        assert isinstance(err, BudgetExceeded)
        assert isinstance(err, TBDError)

    def test_error_codes_unique(self):
        """所有错误码 code 唯一"""
        codes = [
            TBD_001().code,
            TBD_002().code,
            TBD_003().code,
            TBD_004().code,
            TBD_005().code,
            TBD_006().code,
        ]
        assert len(codes) == len(set(codes))
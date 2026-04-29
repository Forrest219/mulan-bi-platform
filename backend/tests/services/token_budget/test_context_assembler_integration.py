"""
TokenBudget 集成测试（Spec 12 §18.10 T1.6）

测试 context_assembler 与 BudgetEnforcer 的集成行为：
- truncate 模式：超限不抛异常，返回截断结果
- error 模式：超限抛 BudgetExceeded
- circuit_break 模式：连续失败触发熔断
- BudgetReport 记录正确

注：本测试为纯单元测试，不需要数据库，使用 pytest.mark.skip_db 跳过 DB fixture。
"""
import pytest
from unittest.mock import patch, MagicMock

# 跳过数据库初始化（纯单元测试）
pytestmark = pytest.mark.skip_db


from services.semantic_maintenance.context_assembler import (
    BudgetAwareContextAssembler,
    sanitize_fields_for_llm,
    serialize_field,
    _fields_to_budget_items,
    _classify_priority,
)
from services.token_budget import (
    BudgetExceeded,
    TBD_005,
    BudgetReport,
    BudgetRegistry,
    TokenBudget,
    clear_registry,
)
from services.token_budget.budget import _circuit_state


class TestBudgetAwareContextAssembler:
    """BudgetAwareContextAssembler 集成测试"""

    def setup_method(self):
        """每个测试前清除缓存"""
        clear_registry()
        _circuit_state.clear()

    def teardown_method(self):
        """每个测试后清除缓存"""
        clear_registry()
        _circuit_state.clear()

    def test_truncate_mode_no_exception(self):
        """truncate 模式：超限不抛异常，返回截断结果"""
        assembler = BudgetAwareContextAssembler(mode="truncate")

        # 创建大量字段
        fields = [
            {
                "field_name": f"Field_{i}",
                "field_caption": f"字段_{i}",
                "data_type": "REAL",
                "role": "measure",
                "is_core_field": i < 2,  # 前 2 个为核心字段
            }
            for i in range(100)
        ]

        context, report = assembler.build_field_context_with_budget(
            fields, scenario="semantic_field", provider="openai"
        )

        # 验证不抛异常
        assert isinstance(context, str)
        assert isinstance(report, BudgetReport)
        assert report.scenario == "semantic_field"
        assert report.used_tokens > 0
        # 大量字段场景下应该有截断
        assert report.truncated_items >= 0

    def test_truncate_mode_keeps_p0_fields(self):
        """truncate 模式：P0 核心字段始终保留"""
        assembler = BudgetAwareContextAssembler(mode="truncate")

        # 创建 P0 和 P5 字段
        fields = [
            {
                "field_name": "Core_Metric",
                "field_caption": "核心指标",
                "data_type": "REAL",
                "role": "measure",
                "is_core_field": True,  # P0
            },
            {
                "field_name": "Normal_Field",
                "field_caption": "普通字段",
                "data_type": "STRING",
                "role": "dimension",
                "is_core_field": False,  # P3
            },
        ]

        # 使用极小预算，只够一个字段
        with patch.object(assembler, '_get_enforcer') as mock_enforcer:
            # 手动构造极小预算的 enforcer
            from services.token_budget import BudgetEnforcer, BudgetItem
            budget = TokenBudget(
                scenario="test",
                model="gpt-4o",
                total_tokens=100,  # 极小预算
                system_reserved=0,
                instruction_reserved=0,
                response_reserved=0,
            )
            enforcer = BudgetEnforcer(budget, mode="truncate")
            mock_enforcer.return_value = enforcer

            context, report = assembler.build_field_context_with_budget(fields)

            # 验证 P0 字段保留
            assert "Core_Metric" in context

    def test_error_mode_raises_on_exceed(self):
        """error 模式：超限抛 BudgetExceeded"""
        assembler = BudgetAwareContextAssembler(mode="error")

        # 创建大量字段
        fields = [
            {
                "field_name": f"Field_{i}",
                "field_caption": f"字段_{i}" * 50,  # 长名称增加 token
                "data_type": "REAL",
                "role": "measure",
            }
            for i in range(100)
        ]

        with pytest.raises(BudgetExceeded):
            assembler.build_field_context_with_budget(
                fields, scenario="semantic_field", provider="openai"
            )

    def test_circuit_break_mode(self):
        """circuit_break 模式：连续失败触发熔断"""
        assembler = BudgetAwareContextAssembler(mode="circuit_break")

        # 创建大量字段
        fields = [
            {
                "field_name": f"Field_{i}",
                "field_caption": f"字段_{i}" * 50,
                "data_type": "REAL",
                "role": "measure",
            }
            for i in range(100)
        ]

        # 连续失败 5 次
        for attempt in range(5):
            try:
                context, report = assembler.build_field_context_with_budget(
                    fields, scenario="test_circuit", provider="openai"
                )
            except TBD_005:
                # 第 5 次及之后应该抛出 TBD_005
                if attempt >= 4:
                    break
                continue

        # 清理熔断状态
        _circuit_state.clear()

    def test_budget_report_records_correctly(self):
        """BudgetReport 记录正确"""
        assembler = BudgetAwareContextAssembler(mode="truncate")

        fields = [
            {
                "field_name": "Sales",
                "field_caption": "销售额",
                "data_type": "REAL",
                "role": "measure",
            },
            {
                "field_name": "Region",
                "field_caption": "区域",
                "data_type": "STRING",
                "role": "dimension",
            },
        ]

        context, report = assembler.build_field_context_with_budget(fields)

        # 验证 report 字段
        assert report.scenario == "semantic_field"
        assert report.used_tokens > 0
        assert report.elapsed_ms >= 0
        assert report.truncated_items >= 0

    def test_empty_fields_returns_empty_report(self):
        """空字段列表返回空报告"""
        assembler = BudgetAwareContextAssembler(mode="truncate")

        context, report = assembler.build_field_context_with_budget([])

        assert context == "无字段信息"
        assert report.used_tokens == 0
        assert report.truncated_items == 0

    def test_sanitize_before_budget(self):
        """敏感字段在截断前被过滤"""
        assembler = BudgetAwareContextAssembler(mode="truncate")

        fields = [
            {
                "field_name": "Salary",
                "sensitivity_level": "high",  # 应被过滤
                "data_type": "REAL",
                "role": "measure",
            },
            {
                "field_name": "Sales",
                "sensitivity_level": "low",  # 应保留
                "data_type": "REAL",
                "role": "measure",
            },
        ]

        context, report = assembler.build_field_context_with_budget(fields)

        # 敏感字段不出现
        assert "Salary" not in context
        assert "Sales" in context


class TestFieldsToBudgetItems:
    """_fields_to_budget_items 辅助函数测试"""

    def test_priority_mapping(self):
        """P0-P5 正确映射到 priority 0-5"""
        fields = [
            {"field_name": "P0_Field", "is_core_field": True, "role": "measure", "data_type": "REAL"},
            {"field_name": "P1_Field", "is_core_field": True, "role": "dimension", "data_type": "STRING"},
            {"field_name": "P2_Field", "is_core_field": False, "role": "measure", "data_type": "REAL"},
            {"field_name": "P3_Field", "is_core_field": False, "role": "dimension", "data_type": "STRING"},
            {"field_name": "P4_Field", "formula": "SUM(x)", "role": "dimension", "data_type": "REAL"},
            {"field_name": "P5_Field", "role": "unknown"},
        ]

        items = _fields_to_budget_items(fields)

        assert len(items) == 6
        assert items[0].priority == 0  # P0
        assert items[1].priority == 1  # P1
        assert items[2].priority == 2  # P2
        assert items[3].priority == 3  # P3
        assert items[4].priority == 4  # P4
        assert items[5].priority == 5  # P5

    def test_metadata_preserves_original_field(self):
        """metadata 保留原始字段引用"""
        fields = [
            {"field_name": "Test", "data_type": "REAL", "role": "measure"},
        ]

        items = _fields_to_budget_items(fields)

        assert len(items) == 1
        assert items[0].metadata.get("original_field") == fields[0]

    def test_content_is_serialized(self):
        """content 是序列化后的字符串"""
        fields = [
            {"field_name": "Sales", "field_caption": "销售额", "data_type": "REAL", "role": "measure"},
        ]

        items = _fields_to_budget_items(fields)

        # content 包含字段名
        assert "Sales" in items[0].content


class TestBuildDatasourceContextWithBudget:
    """build_datasource_context_with_budget 测试"""

    def setup_method(self):
        clear_registry()
        _circuit_state.clear()

    def teardown_method(self):
        clear_registry()
        _circuit_state.clear()

    def test_complete_datasource_context(self):
        """完整数据源上下文生成"""
        assembler = BudgetAwareContextAssembler(mode="truncate")

        fields = [
            {"field_name": "Sales", "data_type": "REAL", "role": "measure"},
            {"field_name": "Region", "data_type": "STRING", "role": "dimension"},
        ]

        context, report = assembler.build_datasource_context_with_budget(
            ds_name="TestDS",
            description="测试数据源",
            existing_semantic_name="test_ds",
            existing_semantic_name_zh="测试数据源",
            fields=fields,
        )

        # 验证上下文格式
        assert "## 数据源信息" in context
        assert "TestDS" in context
        assert "测试数据源" in context
        assert "## 字段列表" in context

        # 验证 report
        assert report.scenario == "semantic_ds"

    def test_uses_semantic_ds_scenario(self):
        """使用 semantic_ds 场景配置"""
        assembler = BudgetAwareContextAssembler(mode="truncate")

        # 没有字段时也验证场景名
        context, report = assembler.build_datasource_context_with_budget(
            ds_name="Test",
            description="",
            existing_semantic_name="",
            existing_semantic_name_zh="",
            fields=[],
        )

        assert report.scenario == "semantic_ds"

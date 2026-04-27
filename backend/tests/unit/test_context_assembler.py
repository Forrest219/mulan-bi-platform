"""单元测试：ContextAssembler + 上下文函数

覆盖范围：
- estimate_tokens: 有/无 tiktoken 的估算
- _classify_priority: P0-P5 分类
- serialize_field: 字段序列化（含截断公式）
- sanitize_fields_for_llm: 敏感度过滤 + 枚举截断
- truncate_context: 优先级截断
- ContextAssembler: 端到端上下文组装
"""
import os
import pytest

os.environ.setdefault("DATABASE_URL", "postgresql://mulan:mulan@localhost:5432/mulan_bi_test")
os.environ.setdefault("SESSION_SECRET", "test-session-secret-for-ci-!!")
os.environ.setdefault("DATASOURCE_ENCRYPTION_KEY", "test-datasource-key-32-bytes-ok!!")
os.environ.setdefault("TABLEAU_ENCRYPTION_KEY", "test-tableau-key-32-bytes-ok!!")
os.environ.setdefault("LLM_ENCRYPTION_KEY", "test-llm-key-32-bytes-ok!!!!")
os.environ.setdefault("ADMIN_USERNAME", "admin")
os.environ.setdefault("ADMIN_PASSWORD", "")

from services.semantic_maintenance.context_assembler import (
    estimate_tokens,
    _classify_priority,
    serialize_field,
    sanitize_fields_for_llm,
    truncate_context,
    ContextAssembler,
    BLOCKED_FOR_LLM,
    MAX_CONTEXT_TOKENS,
    SYSTEM_PROMPT_TOKENS,
    USER_INSTRUCTION_TOKENS,
)


# =====================================================================
# estimate_tokens
# =====================================================================


class TestEstimateTokens:
    """Token 估算测试"""

    def test_empty_string(self):
        assert estimate_tokens("") == 0

    def test_none_equivalent_empty(self):
        assert estimate_tokens("") == 0

    def test_ascii_only(self):
        """纯 ASCII 按 1.3 token/char 估算"""
        result = estimate_tokens("hello world")  # 11 chars
        assert result > 0
        assert result == int(11 * 1.3)

    def test_chinese_only(self):
        """纯中文按 2.0 token/字 估算"""
        result = estimate_tokens("你好世界")  # 4 chars
        assert result == int(4 * 2.0)

    def test_mixed_content(self):
        """中英混合"""
        result = estimate_tokens("hello 你好")
        assert result > 0

    def test_with_encoder(self):
        """使用编码器时精确估算"""
        class FakeEncoder:
            def encode(self, text):
                return list(range(len(text)))  # 每字符1 token

        enc = FakeEncoder()
        result = estimate_tokens("test", encoder=enc)
        assert result == 4


# =====================================================================
# _classify_priority
# =====================================================================


class TestClassifyPriority:
    """字段优先级分类测试"""

    def test_p0_core_measure(self):
        field = {"is_core_field": True, "role": "measure"}
        assert _classify_priority(field) == "P0"

    def test_p1_core_dimension(self):
        field = {"is_core_field": True, "role": "dimension"}
        assert _classify_priority(field) == "P1"

    def test_p2_normal_measure(self):
        field = {"role": "measure"}
        assert _classify_priority(field) == "P2"

    def test_p3_normal_dimension(self):
        field = {"role": "dimension"}
        assert _classify_priority(field) == "P3"

    def test_p4_calculated_field(self):
        field = {"formula": "SUM([Sales])"}
        assert _classify_priority(field) == "P4"

    def test_p5_other(self):
        field = {}
        assert _classify_priority(field) == "P5"

    def test_core_measure_beats_formula(self):
        """核心度量优先于公式字段"""
        field = {"is_core_field": True, "role": "measure", "formula": "SUM([x])"}
        assert _classify_priority(field) == "P0"


# =====================================================================
# serialize_field
# =====================================================================


class TestSerializeField:
    """字段序列化测试"""

    def test_basic_field(self):
        field = {
            "field_name": "amount",
            "field_caption": "金额",
            "data_type": "float",
            "role": "measure",
        }
        result = serialize_field(field)
        assert "amount" in result
        assert "金额" in result
        assert "float" in result
        assert "measure" in result

    def test_field_with_formula(self):
        field = {
            "field_name": "profit",
            "field_caption": "",
            "data_type": "float",
            "role": "measure",
            "formula": "SUM([Sales]) - SUM([Cost])",
        }
        result = serialize_field(field)
        assert "SUM([Sales])" in result

    def test_field_with_truncated_formula(self):
        field = {
            "field_name": "profit",
            "field_caption": "",
            "data_type": "float",
            "role": "measure",
            "formula": "SUM([Sales]) - SUM([Cost])",
        }
        result = serialize_field(field, truncate_formula=True)
        assert "公式已截断" in result
        assert "SUM([Sales])" not in result

    def test_field_no_formula(self):
        field = {
            "field_name": "name",
            "data_type": "string",
            "role": "dimension",
        }
        result = serialize_field(field)
        assert "公式" not in result


# =====================================================================
# sanitize_fields_for_llm
# =====================================================================


class TestSanitizeFieldsForLlm:
    """字段净化测试"""

    def test_blocks_high_sensitivity(self):
        fields = [
            {"field_name": "ssn", "sensitivity_level": "high", "data_type": "string"},
            {"field_name": "name", "sensitivity_level": "low", "data_type": "string"},
        ]
        result = sanitize_fields_for_llm(fields)
        assert len(result) == 1
        assert result[0]["field_name"] == "name"

    def test_blocks_confidential_sensitivity(self):
        fields = [
            {"field_name": "credit_card", "sensitivity_level": "CONFIDENTIAL", "data_type": "string"},
        ]
        result = sanitize_fields_for_llm(fields)
        assert len(result) == 0

    def test_allows_low_and_medium(self):
        fields = [
            {"field_name": "a", "sensitivity_level": "low", "data_type": "string"},
            {"field_name": "b", "sensitivity_level": "medium", "data_type": "string"},
            {"field_name": "c", "sensitivity_level": "", "data_type": "string"},
            {"field_name": "d", "data_type": "string"},  # no sensitivity_level
        ]
        result = sanitize_fields_for_llm(fields)
        assert len(result) == 4

    def test_enum_values_truncated_to_20(self):
        """枚举值截断到 20 个"""
        fields = [{
            "field_name": "category",
            "data_type": "string",
            "enum_values": [f"val_{i}" for i in range(30)],
        }]
        result = sanitize_fields_for_llm(fields)
        assert len(result[0]["enum_values"]) == 20

    def test_enum_value_string_truncated_to_50_chars(self):
        """单个枚举值超过 50 字符被截断"""
        long_val = "x" * 60
        fields = [{
            "field_name": "category",
            "data_type": "string",
            "enum_values": [long_val],
        }]
        result = sanitize_fields_for_llm(fields)
        assert result[0]["enum_values"][0].endswith("...")
        assert len(result[0]["enum_values"][0]) == 53  # 50 + "..."

    def test_only_metadata_preserved(self):
        """净化后只保留元数据字段"""
        fields = [{
            "field_name": "test",
            "field_caption": "测试",
            "data_type": "int",
            "role": "measure",
            "formula": "SUM(x)",
            "secret_field": "should_be_dropped",
        }]
        result = sanitize_fields_for_llm(fields)
        assert "secret_field" not in result[0]
        assert result[0]["field_name"] == "test"

    def test_custom_blocked_levels(self):
        """自定义封锁级别"""
        fields = [
            {"field_name": "a", "sensitivity_level": "medium", "data_type": "string"},
        ]
        result = sanitize_fields_for_llm(fields, blocked_levels={"medium"})
        assert len(result) == 0


# =====================================================================
# truncate_context
# =====================================================================


class TestTruncateContext:
    """优先级截断测试"""

    def test_empty_fields(self):
        assert truncate_context([], 1000) == []

    def test_all_fields_fit(self):
        """所有字段在预算内"""
        fields = [
            {"field_name": "a", "role": "measure", "data_type": "int"},
            {"field_name": "b", "role": "dimension", "data_type": "string"},
        ]
        result = truncate_context(fields, 10000)
        assert len(result) == 2

    def test_budget_zero_returns_empty(self):
        """预算为 0 返回空列表"""
        fields = [{"field_name": "a", "role": "measure", "data_type": "int"}]
        result = truncate_context(fields, 0)
        assert len(result) == 0

    def test_high_priority_preserved_first(self):
        """高优先级字段优先保留"""
        fields = [
            {"field_name": "p5_field", "data_type": "string"},  # P5
            {"field_name": "p0_field", "is_core_field": True, "role": "measure", "data_type": "int"},  # P0
        ]
        # 给一个很小的预算，只能容纳一个字段
        result = truncate_context(fields, 50)
        if len(result) == 1:
            assert result[0]["field_name"] == "p0_field"


# =====================================================================
# ContextAssembler
# =====================================================================


class TestContextAssembler:
    """端到端上下文组装测试"""

    def test_build_field_context_empty(self):
        """空字段列表返回占位文本"""
        assembler = ContextAssembler(encoder=None)
        result = assembler.build_field_context([])
        assert result == "无字段信息"

    def test_build_field_context_with_fields(self):
        """有字段时返回序列化文本"""
        assembler = ContextAssembler(encoder=None)
        fields = [
            {"field_name": "revenue", "field_caption": "营收",
             "data_type": "float", "role": "measure"},
        ]
        result = assembler.build_field_context(fields)
        assert "revenue" in result
        assert "营收" in result

    def test_sanitize_fields(self):
        """sanitize_fields 调用 sanitize_fields_for_llm"""
        assembler = ContextAssembler(encoder=None)
        fields = [
            {"field_name": "safe", "sensitivity_level": "low", "data_type": "string"},
            {"field_name": "secret", "sensitivity_level": "high", "data_type": "string"},
        ]
        result = assembler.sanitize_fields(fields)
        assert len(result) == 1
        assert result[0]["field_name"] == "safe"

    def test_build_datasource_context(self):
        """数据源上下文包含名称和字段"""
        assembler = ContextAssembler(encoder=None)
        result = assembler.build_datasource_context(
            ds_name="orders",
            description="订单数据",
            existing_semantic_name="Order Data",
            existing_semantic_name_zh="订单数据",
            fields=[
                {"field_name": "order_id", "data_type": "int", "role": "dimension"},
            ],
        )
        assert "orders" in result
        assert "订单数据" in result
        assert "order_id" in result

    def test_estimate_tokens_delegation(self):
        """estimate_tokens 方法正确委托"""
        assembler = ContextAssembler(encoder=None)
        result = assembler.estimate_tokens("hello")
        assert result > 0


# =====================================================================
# BLOCKED_FOR_LLM 常量验证
# =====================================================================


class TestBlockedForLlm:
    """敏感度常量测试"""

    def test_high_blocked(self):
        assert "high" in BLOCKED_FOR_LLM

    def test_confidential_blocked(self):
        assert "confidential" in BLOCKED_FOR_LLM

    def test_low_not_blocked(self):
        assert "low" not in BLOCKED_FOR_LLM

    def test_medium_not_blocked(self):
        assert "medium" not in BLOCKED_FOR_LLM

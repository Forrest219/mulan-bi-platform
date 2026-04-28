"""
ContextAssembler 单元测试（Spec 12 §10.1）

测试项：
- Token 预算截断
- 字段优先级排序
- 敏感字段过滤
- 字段序列化格式
"""
import pytest
import tiktoken

from services.semantic_maintenance.context_assembler import (
    ContextAssembler,
    serialize_field,
    sanitize_fields_for_llm,
    truncate_context,
    estimate_tokens,
    _classify_priority,
    BLOCKED_FOR_LLM,
    MAX_CONTEXT_TOKENS,
    SYSTEM_PROMPT_TOKENS,
    USER_INSTRUCTION_TOKENS,
)


class TestSerializeField:
    """字段序列化格式测试（Spec 12 §3.3）"""

    def test_basic_format(self):
        """基本格式验证"""
        field = {
            "field_name": "Sales",
            "field_caption": "销售额",
            "data_type": "REAL",
            "role": "measure",
        }
        result = serialize_field(field)
        assert "Sales" in result
        assert "销售额" in result
        assert "[REAL]" in result
        assert "[measure]" in result

    def test_format_with_formula(self):
        """带公式字段序列化"""
        field = {
            "field_name": "Profit_Ratio",
            "field_caption": "利润率",
            "data_type": "REAL",
            "role": "measure",
            "formula": "SUM([Profit])/SUM([Sales])",
        }
        result = serialize_field(field)
        assert "利润率" in result
        assert "公式: SUM([Profit])/SUM([Sales])" in result

    def test_truncate_formula(self):
        """公式截断"""
        field = {
            "field_name": "Profit_Ratio",
            "field_caption": "利润率",
            "data_type": "REAL",
            "role": "measure",
            "formula": "SUM([Profit])/SUM([Sales])",
        }
        result = serialize_field(field, truncate_formula=True)
        assert "利润率" in result
        assert "[公式已截断]" in result
        assert "SUM([Profit])" not in result

    def test_missing_optional_fields(self):
        """可选字段缺失"""
        field = {
            "field_name": "Region",
            "data_type": "STRING",
        }
        result = serialize_field(field)
        assert "Region" in result
        assert "[STRING]" in result


class TestClassifyPriority:
    """字段优先级分类测试（Spec 12 §3.4）"""

    def test_p0_core_measure(self):
        """P0: 核心度量字段"""
        field = {"is_core_field": True, "role": "measure"}
        assert _classify_priority(field) == "P0"

    def test_p1_core_dimension(self):
        """P1: 核心维度字段"""
        field = {"is_core_field": True, "role": "dimension"}
        assert _classify_priority(field) == "P1"

    def test_p2_normal_measure(self):
        """P2: 普通度量字段"""
        field = {"is_core_field": False, "role": "measure"}
        assert _classify_priority(field) == "P2"

    def test_p3_normal_dimension(self):
        """P3: 普通维度字段"""
        field = {"is_core_field": False, "role": "dimension"}
        assert _classify_priority(field) == "P3"

    def test_p4_calculated_field(self):
        """P4: 计算字段"""
        field = {"is_core_field": False, "role": "dimension", "formula": "abc"}
        assert _classify_priority(field) == "P4"

    def test_p5_other(self):
        """P5: 其他字段"""
        field = {"is_core_field": False, "role": "unknown"}
        assert _classify_priority(field) == "P5"


class TestSanitizeFields:
    """敏感字段过滤测试（Spec 12 §9.2）"""

    def test_block_high_sensitivity(self):
        """HIGH 敏感级别字段被过滤"""
        fields = [
            {"field_name": "Salary", "sensitivity_level": "high"},
            {"field_name": "Sales", "sensitivity_level": "low"},
        ]
        result = sanitize_fields_for_llm(fields)
        assert len(result) == 1
        assert result[0]["field_name"] == "Sales"

    def test_block_confidential_sensitivity(self):
        """CONFIDENTIAL 敏感级别字段被过滤"""
        fields = [
            {"field_name": "Password", "sensitivity_level": "confidential"},
            {"field_name": "Product", "sensitivity_level": "medium"},
        ]
        result = sanitize_fields_for_llm(fields)
        assert len(result) == 1
        assert result[0]["field_name"] == "Product"

    def test_allow_low_sensitivity(self):
        """LOW 敏感级别字段保留"""
        fields = [
            {"field_name": "Region", "sensitivity_level": "low"},
            {"field_name": "Date", "sensitivity_level": "low"},
        ]
        result = sanitize_fields_for_llm(fields)
        assert len(result) == 2

    def test_truncate_enum_values(self):
        """枚举值截断（最多 20 个，单个最大 50 字符）"""
        fields = [
            {
                "field_name": "Category",
                "sensitivity_level": "low",
                "enum_values": [f"value_{i}" * 10 for i in range(25)],  # 25 个，每个超过 50 字符
            }
        ]
        result = sanitize_fields_for_llm(fields)
        assert len(result[0]["enum_values"]) == 20
        assert all(len(v) <= 53 for v in result[0]["enum_values"])  # 50 + "..."

    def test_no_actual_data(self):
        """验证不包含实际数据值"""
        fields = [
            {
                "field_name": "Sales",
                "field_caption": "销售额",
                "data_type": "REAL",
                "role": "measure",
                "actual_data": ["华东", 100000],  # 不应该出现的字段
            }
        ]
        result = sanitize_fields_for_llm(fields)
        assert "actual_data" not in result[0]


class TestEstimateTokens:
    """Token 估算测试"""

    def test_empty_text(self):
        """空文本"""
        assert estimate_tokens("") == 0

    def test_english_text(self):
        """英文文本（有 tiktoken 时）"""
        try:
            enc = tiktoken.get_encoding("cl100k_base")
            text = "Hello world"
            result = estimate_tokens(text, enc)
            assert result > 0
        except ImportError:
            pytest.skip("tiktoken not installed")

    def test_chinese_text(self):
        """中文文本（有 tiktoken 时）"""
        try:
            enc = tiktoken.get_encoding("cl100k_base")
            text = "这是一个中文测试"
            result = estimate_tokens(text, enc)
            assert result > 0
        except ImportError:
            pytest.skip("tiktoken not installed")


class TestTruncateContext:
    """上下文截断测试（Spec 12 §3.4）"""

    def test_p0_always_kept(self):
        """P0 字段始终保留"""
        fields = [
            {"field_name": "Core_Metric", "is_core_field": True, "role": "measure", "data_type": "REAL"},
            {"field_name": "Normal_Field", "is_core_field": False, "role": "measure", "data_type": "REAL"},
        ]
        enc = tiktoken.get_encoding("cl100k_base") if tiktoken else None

        # 极小预算，只够一个字段
        result = truncate_context(fields, budget_tokens=10, encoder=enc)
        assert len(result) >= 1
        assert result[0]["field_name"] == "Core_Metric"

    def test_priority_order(self):
        """优先级顺序验证"""
        fields = [
            {"field_name": "Normal", "is_core_field": False, "role": "measure", "data_type": "REAL"},
            {"field_name": "Core", "is_core_field": True, "role": "measure", "data_type": "REAL"},
        ]
        enc = tiktoken.get_encoding("cl100k_base") if tiktoken else None
        result = truncate_context(fields, budget_tokens=1000, encoder=enc)
        assert result[0]["field_name"] == "Core"


class TestContextAssembler:
    """ContextAssembler 集成测试"""

    def test_sanitize_and_build(self):
        """净化 + 上下文构建"""
        assembler = ContextAssembler()
        fields = [
            {"field_name": "Salary", "sensitivity_level": "high"},
            {"field_name": "Sales", "sensitivity_level": "low", "data_type": "REAL", "role": "measure"},
        ]
        sanitized = assembler.sanitize_fields(fields)
        assert len(sanitized) == 1
        assert sanitized[0]["field_name"] == "Sales"

    def test_build_field_context_empty(self):
        """空字段列表"""
        assembler = ContextAssembler()
        result = assembler.build_field_context([])
        assert result == "无字段信息"

    def test_build_field_context_respects_token_budget(self):
        """Token 预算验证"""
        assembler = ContextAssembler()
        enc = tiktoken.get_encoding("cl100k_base") if tiktoken else None

        # 创建大量字段
        fields = [
            {
                "field_name": f"Field_{i}",
                "field_caption": f"字段_{i}",
                "data_type": "REAL",
                "role": "measure",
            }
            for i in range(100)
        ]

        result = assembler.build_field_context(fields, max_tokens=500)
        # 验证输出 token 数不超过预算
        if enc:
            tokens = len(enc.encode(result))
            assert tokens <= 600  # 留一定余量

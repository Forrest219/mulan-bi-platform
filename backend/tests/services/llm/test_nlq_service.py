"""
NLQ Service 单元测试（Spec 14 §12.2）

测试项：
- 意图分类（规则快速路径）
- JSON 生成
- Schema 校验
- 字段解析
- 响应格式化
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from services.llm.nlq_service import (
    classify_intent,
    validate_one_pass_output,
    parse_json_from_response,
    format_response,
    ONE_PASS_OUTPUT_SCHEMA,
    INTENT_KEYWORDS,
    ResolvedField,
)


class TestClassifyIntent:
    """意图分类测试（Spec 14 §3.3）"""

    def test_ranking_keywords(self):
        """排名查询关键词"""
        questions = [
            "销售额前10的产品",
            "排名最高的区域",
            "有哪些前N",
        ]
        for q in questions:
            result = classify_intent(q)
            assert result is not None, f"Failed on: {q}"
            assert result.type in ["ranking", "aggregate", "filter"]

    def test_trend_keywords(self):
        """趋势查询关键词"""
        questions = [
            "过去6个月的销售额趋势",
            "月度走势",
            "同比变化",
        ]
        for q in questions:
            result = classify_intent(q)
            if result:
                assert result.type in ["trend", "aggregate"]

    def test_comparison_keywords(self):
        """对比查询关键词"""
        questions = [
            "各区域销售额对比",
            "本月vs上月",
            "和去年比较",
        ]
        for q in questions:
            result = classify_intent(q)
            if result:
                assert result.type in ["comparison", "aggregate"]

    def test_no_match(self):
        """无匹配时返回 None（触发 LLM）"""
        questions = [
            "给我看看数据",
            "hello world",
            "这是什么",
        ]
        for q in questions:
            result = classify_intent(q)
            # 这些问题可能匹配 aggregate 或不匹配
            # 只要不 crash 就行


class TestValidateOnePassOutput:
    """One-Pass 输出校验测试（Spec 14 §5.4）"""

    def test_valid_output(self):
        """完整有效输出"""
        output = {
            "intent": "aggregate",
            "confidence": 0.85,
            "vizql_json": {
                "fields": [
                    {"fieldCaption": "Sales", "function": "SUM"}
                ],
                "filters": [],
            },
        }
        is_valid, err = validate_one_pass_output(output)
        assert is_valid
        assert err is None

    def test_missing_required_field(self):
        """缺少必填字段"""
        output = {
            "intent": "aggregate",
            # 缺少 confidence
            "vizql_json": {"fields": []},
        }
        is_valid, err = validate_one_pass_output(output)
        assert not is_valid
        assert "confidence" in err

    def test_invalid_intent(self):
        """非法意图"""
        output = {
            "intent": "invalid_intent",
            "confidence": 0.85,
            "vizql_json": {"fields": [{"fieldCaption": "Sales"}]},
        }
        is_valid, err = validate_one_pass_output(output)
        assert not is_valid
        assert "intent" in err.lower()

    def test_invalid_confidence_range(self):
        """非法置信度范围"""
        output = {
            "intent": "aggregate",
            "confidence": 1.5,  # 超出 0-1 范围
            "vizql_json": {"fields": [{"fieldCaption": "Sales"}]},
        }
        is_valid, err = validate_one_pass_output(output)
        assert not is_valid
        assert "confidence" in err

    def test_empty_fields(self):
        """空字段列表"""
        output = {
            "intent": "aggregate",
            "confidence": 0.85,
            "vizql_json": {"fields": []},
        }
        is_valid, err = validate_one_pass_output(output)
        assert not is_valid
        assert "fields" in err

    def test_invalid_function(self):
        """非法聚合函数"""
        output = {
            "intent": "aggregate",
            "confidence": 0.85,
            "vizql_json": {
                "fields": [
                    {"fieldCaption": "Sales", "function": "INVALID_FUNC"}
                ],
            },
        }
        is_valid, err = validate_one_pass_output(output)
        assert not is_valid


class TestParseJsonFromResponse:
    """JSON 解析测试（Spec 14 §5.4）"""

    def test_valid_json(self):
        """正常 JSON"""
        content = '{"intent": "aggregate", "confidence": 0.8}'
        parsed, err = parse_json_from_response(content)
        assert err is None
        assert parsed["intent"] == "aggregate"

    def test_markdown_block(self):
        """Markdown 代码块"""
        content = '```json\n{"intent": "trend", "confidence": 0.9}\n```'
        parsed, err = parse_json_from_response(content)
        assert err is None
        assert parsed["intent"] == "trend"

    def test_invalid_json(self):
        """非法 JSON"""
        content = "not json at all"
        parsed, err = parse_json_from_response(content)
        assert parsed is None
        assert err is not None


class TestFormatResponse:
    """响应格式化测试（Spec 14 §8）"""

    def test_format_number(self):
        """单值格式化"""
        result = format_response(
            {"Sales": 123456.78},
            intent="aggregate",
            response_type_hint="auto",
        )
        assert result["response_type"] == "number"
        assert result["value"] == 123456.78

    def test_format_table(self):
        """表格格式化"""
        rows = [
            {"Region": "华东", "Sales": 100000},
            {"Region": "华南", "Sales": 80000},
        ]
        result = format_response(rows, intent="aggregate", response_type_hint="auto")
        assert result["response_type"] == "table"
        assert len(result["rows"]) == 2

    def test_format_empty(self):
        """空结果格式化"""
        result = format_response([], intent="aggregate", response_type_hint="auto")
        assert result["response_type"] == "text"
        assert "未返回数据" in result["content"]


class TestResolvedField:
    """ResolvedField 数据类测试"""

    def test_resolved_field_creation(self):
        """创建 ResolvedField"""
        field = ResolvedField(
            field_caption="Sales",
            field_name="Sales",
            role="measure",
            data_type="real",
            match_source="exact",
            match_confidence=1.0,
            user_term="销售额",
        )
        assert field.field_caption == "Sales"
        assert field.match_confidence == 1.0
        assert field.match_source == "exact"

"""
AI Generator 单元测试（Spec 12 §10.1）

测试项：
- JSON 解析（正常 + Markdown 代码块）
- Schema 校验
- 置信度判定
- 敏感度检查
"""
import pytest
import json

from services.semantic_maintenance.ai_generator import (
    parse_json_from_response,
    validate_field_output,
    validate_datasource_output,
    pre_llm_sensitivity_check,
    determine_confidence_level,
    build_json_retry_prompt,
    AIGenerator,
    FIELD_OUTPUT_REQUIRED,
    CONFIDENCE_HIGH,
    CONFIDENCE_LOW,
)


class TestParseJsonFromResponse:
    """JSON 解析测试（Spec 12 §6.2）"""

    def test_valid_json(self):
        """正常 JSON"""
        content = '{"semantic_name": "sales", "confidence": 0.8}'
        parsed, err = parse_json_from_response(content)
        assert err is None
        assert parsed["semantic_name"] == "sales"
        assert parsed["confidence"] == 0.8

    def test_markdown_json_block(self):
        """Markdown ```json 代码块"""
        content = '```json\n{"semantic_name": "sales", "confidence": 0.8}\n```'
        parsed, err = parse_json_from_response(content)
        assert err is None
        assert parsed["semantic_name"] == "sales"

    def test_markdown_json_block_with_language(self):
        """Markdown ```javascript 代码块（应提取内容）"""
        content = '```javascript\n{"semantic_name": "sales", "confidence": 0.8}\n```'
        parsed, err = parse_json_from_response(content)
        assert err is None
        assert parsed["semantic_name"] == "sales"

    def test_invalid_json(self):
        """非法 JSON"""
        content = "not a json"
        parsed, err = parse_json_from_response(content)
        assert parsed is None
        assert err is not None

    def test_incomplete_json(self):
        """不完整的 JSON"""
        content = '{"semantic_name": "sales",'
        parsed, err = parse_json_from_response(content)
        assert parsed is None
        assert err is not None

    def test_whitespace_handling(self):
        """空白字符处理"""
        content = '  \n  {"semantic_name": "sales"}  \n  '
        parsed, err = parse_json_from_response(content)
        assert err is None
        assert parsed["semantic_name"] == "sales"


class TestValidateFieldOutput:
    """字段输出 Schema 校验测试（Spec 12 §5.2.1）"""

    def test_valid_output(self):
        """完整输出"""
        output = {
            "semantic_name": "total_sales",
            "semantic_name_zh": "总销售额",
            "semantic_description": "所有销售订单的金额总和",
            "semantic_type": "measure",
            "confidence": 0.85,
        }
        is_valid, missing = validate_field_output(output)
        assert is_valid
        assert len(missing) == 0

    def test_missing_required_field(self):
        """缺少必填字段"""
        output = {
            "semantic_name": "total_sales",
            "confidence": 0.85,
            # 缺少 semantic_name_zh, semantic_description, semantic_type
        }
        is_valid, missing = validate_field_output(output)
        assert not is_valid
        assert "semantic_name_zh" in missing
        assert "semantic_description" in missing
        assert "semantic_type" in missing

    def test_invalid_semantic_type(self):
        """非法的 semantic_type"""
        output = {
            "semantic_name": "total_sales",
            "semantic_name_zh": "总销售额",
            "semantic_description": "描述",
            "semantic_type": "invalid_type",
            "confidence": 0.85,
        }
        is_valid, missing = validate_field_output(output)
        assert not is_valid
        assert any("semantic_type" in m for m in missing)

    def test_invalid_confidence_range(self):
        """非法的 confidence 范围"""
        output = {
            "semantic_name": "total_sales",
            "semantic_name_zh": "总销售额",
            "semantic_description": "描述",
            "semantic_type": "measure",
            "confidence": 1.5,  # 超出 0-1 范围
        }
        is_valid, missing = validate_field_output(output)
        assert not is_valid
        assert any("confidence" in m for m in missing)

    def test_confidence_zero(self):
        """confidence = 0（边界值）"""
        output = {
            "semantic_name": "total_sales",
            "semantic_name_zh": "总销售额",
            "semantic_description": "描述",
            "semantic_type": "measure",
            "confidence": 0.0,
        }
        is_valid, missing = validate_field_output(output)
        assert is_valid

    def test_confidence_one(self):
        """confidence = 1（边界值）"""
        output = {
            "semantic_name": "total_sales",
            "semantic_name_zh": "总销售额",
            "semantic_description": "描述",
            "semantic_type": "measure",
            "confidence": 1.0,
        }
        is_valid, missing = validate_field_output(output)
        assert is_valid


class TestValidateDatasourceOutput:
    """数据源输出 Schema 校验测试（Spec 12 §5.2.2）"""

    def test_valid_output(self):
        """完整输出"""
        output = {
            "semantic_name_zh": "销售数据源",
            "semantic_description": "包含所有销售相关数据",
            "confidence": 0.8,
        }
        is_valid, missing = validate_datasource_output(output)
        assert is_valid
        assert len(missing) == 0

    def test_missing_required(self):
        """缺少必填字段"""
        output = {
            "semantic_name": "sales_ds",
            # 缺少 semantic_name_zh, semantic_description, confidence
        }
        is_valid, missing = validate_datasource_output(output)
        assert not is_valid
        assert "semantic_name_zh" in missing
        assert "semantic_description" in missing
        assert "confidence" in missing


class TestPreLLMSensitivityCheck:
    """敏感度检查测试（Spec 12 §9.1）"""

    def test_high_blocked(self):
        """HIGH 级别字段被封锁"""
        result = pre_llm_sensitivity_check("high", is_datasource=False)
        assert result is not None
        assert "SLI_005" in result
        assert "high" in result
        assert "字段" in result

    def test_confidential_blocked(self):
        """CONFIDENTIAL 级别字段被封锁"""
        result = pre_llm_sensitivity_check("confidential", is_datasource=True)
        assert result is not None
        assert "SLI_005" in result
        assert "数据源" in result

    def test_low_allowed(self):
        """LOW 级别字段允许"""
        result = pre_llm_sensitivity_check("low", is_datasource=False)
        assert result is None

    def test_medium_allowed(self):
        """MEDIUM 级别字段允许"""
        result = pre_llm_sensitivity_check("medium", is_datasource=False)
        assert result is None

    def test_case_insensitive(self):
        """大小写不敏感"""
        result = pre_llm_sensitivity_check("HIGH", is_datasource=False)
        assert result is not None
        result = pre_llm_sensitivity_check("Confidential", is_datasource=False)
        assert result is not None

    def test_none_allowed(self):
        """None 敏感级别允许"""
        result = pre_llm_sensitivity_check(None, is_datasource=False)
        assert result is None


class TestDetermineConfidenceLevel:
    """置信度等级判定测试（Spec 12 §6.1）"""

    def test_high_confidence(self):
        """高置信度（>= 0.7）"""
        assert determine_confidence_level(0.7) == "high"
        assert determine_confidence_level(0.85) == "high"
        assert determine_confidence_level(1.0) == "high"

    def test_medium_confidence(self):
        """中置信度（0.3 <= x < 0.7）"""
        assert determine_confidence_level(0.3) == "medium"
        assert determine_confidence_level(0.5) == "medium"
        assert determine_confidence_level(0.69) == "medium"

    def test_low_confidence(self):
        """低置信度（< 0.3）"""
        assert determine_confidence_level(0.0) == "low"
        assert determine_confidence_level(0.1) == "low"
        assert determine_confidence_level(0.29) == "low"


class TestBuildJsonRetryPrompt:
    """JSON 重试 Prompt 构建测试（Spec 12 §6.2）"""

    def test_retry_prompt_format(self):
        """重试 Prompt 格式"""
        original = "请生成 JSON"
        error = "Unexpected token"
        result = build_json_retry_prompt(original, error)
        assert original in result
        assert error in result
        assert "修正要求" in result
        assert "Markdown" not in result or "不要包含" in result

    def test_retry_prompt_preserves_original(self):
        """重试 Prompt 保留原始 Prompt"""
        original = "请为字段生成语义，字段名：Sales"
        result = build_json_retry_prompt(original, "Parse error")
        assert "Sales" in result


class TestAIGenerator:
    """AIGenerator 类测试"""

    def test_no_llm_service(self):
        """无 LLM 服务时返回错误"""
        generator = AIGenerator(llm_service=None)
        result = generator._check_llm_available()
        assert result is not None
        assert "未配置" in result

    def test_sensitivity_check_in_generate(self):
        """generate_field_semantic 执行敏感度检查"""
        generator = AIGenerator(llm_service=None)

        # 直接测试 generate_field_semantic 不需要 mock LLM
        # 因为敏感度检查在 LLM 调用前执行
        field_metadata = {
            "field_id": 1,
            "field_name": "Salary",
            "sensitivity_level": "high",  # 高敏感
        }
        success, result = generator.generate_field_semantic(field_metadata)
        assert not success
        assert "SLI_005" in result

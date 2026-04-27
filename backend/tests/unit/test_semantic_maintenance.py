"""单元测试：SemanticMaintenanceService — 纯逻辑方法

覆盖范围：
- _pre_llm_sensitivity_check: 敏感度拦截
- _parse_llm_json_response: JSON 解析（含 ```json 包裹）
- _semantic_fields_changed: 语义字段变更检测
- SemanticStatus: 状态常量 + 流转定义
- SemanticSource: 来源常量
- SensitivityLevel: 敏感度级别常量
- PublishStatus: 发布状态常量
"""
import os
import pytest
from unittest.mock import MagicMock

os.environ.setdefault("DATABASE_URL", "postgresql://mulan:mulan@localhost:5432/mulan_bi_test")
os.environ.setdefault("SESSION_SECRET", "test-session-secret-for-ci-!!")
os.environ.setdefault("DATASOURCE_ENCRYPTION_KEY", "test-datasource-key-32-bytes-ok!!")
os.environ.setdefault("TABLEAU_ENCRYPTION_KEY", "test-tableau-key-32-bytes-ok!!")
os.environ.setdefault("LLM_ENCRYPTION_KEY", "test-llm-key-32-bytes-ok!!!!")
os.environ.setdefault("ADMIN_USERNAME", "admin")
os.environ.setdefault("ADMIN_PASSWORD", "")

from services.semantic_maintenance.models import (
    SemanticStatus,
    SemanticSource,
    SensitivityLevel,
    PublishStatus,
)
from services.semantic_maintenance.service import SemanticMaintenanceService


# =====================================================================
# SemanticStatus 常量测试
# =====================================================================


class TestSemanticStatus:
    """状态常量和流转定义测试"""

    def test_status_constants(self):
        assert SemanticStatus.DRAFT == "draft"
        assert SemanticStatus.AI_GENERATED == "ai_generated"
        assert SemanticStatus.REVIEWED == "reviewed"
        assert SemanticStatus.APPROVED == "approved"
        assert SemanticStatus.PUBLISHED == "published"
        assert SemanticStatus.REJECTED == "rejected"

    def test_all_statuses_complete(self):
        """ALL 列表包含所有状态"""
        expected = {"draft", "ai_generated", "reviewed", "approved", "published", "rejected"}
        assert set(SemanticStatus.ALL) == expected

    def test_transitions_defined_for_all_states(self):
        """每个状态都有流转定义"""
        for status in SemanticStatus.ALL:
            assert status in SemanticStatus.TRANSITIONS

    def test_draft_transitions(self):
        """draft 可以转到 ai_generated 和 reviewed"""
        assert SemanticStatus.AI_GENERATED in SemanticStatus.TRANSITIONS[SemanticStatus.DRAFT]
        assert SemanticStatus.REVIEWED in SemanticStatus.TRANSITIONS[SemanticStatus.DRAFT]

    def test_approved_can_publish(self):
        """approved 可以转到 published"""
        assert SemanticStatus.PUBLISHED in SemanticStatus.TRANSITIONS[SemanticStatus.APPROVED]

    def test_rejected_can_return_to_draft(self):
        """rejected 可以回到 draft"""
        assert SemanticStatus.DRAFT in SemanticStatus.TRANSITIONS[SemanticStatus.REJECTED]

    def test_published_can_rollback(self):
        """published 可以回到 draft"""
        assert SemanticStatus.DRAFT in SemanticStatus.TRANSITIONS[SemanticStatus.PUBLISHED]


# =====================================================================
# SemanticSource 常量测试
# =====================================================================


class TestSemanticSource:
    """来源常量测试"""

    def test_source_constants(self):
        assert SemanticSource.SYNC == "sync"
        assert SemanticSource.MANUAL == "manual"
        assert SemanticSource.AI == "ai"
        assert SemanticSource.IMPORTED == "imported"


# =====================================================================
# SensitivityLevel 常量测试
# =====================================================================


class TestSensitivityLevel:
    """敏感度级别常量测试"""

    def test_level_constants(self):
        assert SensitivityLevel.LOW == "low"
        assert SensitivityLevel.MEDIUM == "medium"
        assert SensitivityLevel.HIGH == "high"
        assert SensitivityLevel.CONFIDENTIAL == "confidential"

    def test_all_levels_complete(self):
        expected = {"low", "medium", "high", "confidential"}
        assert set(SensitivityLevel.ALL) == expected


# =====================================================================
# PublishStatus 常量测试
# =====================================================================


class TestPublishStatus:
    """发布状态常量测试"""

    def test_status_constants(self):
        assert PublishStatus.PENDING == "pending"
        assert PublishStatus.SUCCESS == "success"
        assert PublishStatus.FAILED == "failed"
        assert PublishStatus.ROLLED_BACK == "rolled_back"
        assert PublishStatus.NOT_SUPPORTED == "not_supported"


# =====================================================================
# _pre_llm_sensitivity_check
# =====================================================================


class TestPreLlmSensitivityCheck:
    """LLM 前置敏感度检查测试"""

    def _make_service(self):
        svc = SemanticMaintenanceService.__new__(SemanticMaintenanceService)
        svc.db = MagicMock()
        return svc

    def test_none_sensitivity_passes(self):
        """无敏感度设置通过"""
        svc = self._make_service()
        assert svc._pre_llm_sensitivity_check(None) is None

    def test_low_passes(self):
        """low 敏感度通过"""
        svc = self._make_service()
        assert svc._pre_llm_sensitivity_check("low") is None

    def test_medium_passes(self):
        """medium 敏感度通过"""
        svc = self._make_service()
        assert svc._pre_llm_sensitivity_check("medium") is None

    def test_high_blocks(self):
        """high 敏感度被拦截"""
        svc = self._make_service()
        result = svc._pre_llm_sensitivity_check("high")
        assert result is not None
        assert "SLI_005" in result

    def test_confidential_blocks(self):
        """confidential 敏感度被拦截"""
        svc = self._make_service()
        result = svc._pre_llm_sensitivity_check("confidential")
        assert result is not None
        assert "SLI_005" in result

    def test_is_datasource_label(self):
        """数据源标签正确"""
        svc = self._make_service()
        result = svc._pre_llm_sensitivity_check("high", is_datasource=True)
        assert "数据源" in result

    def test_is_field_label(self):
        """字段标签正确"""
        svc = self._make_service()
        result = svc._pre_llm_sensitivity_check("high", is_datasource=False)
        assert "字段" in result

    def test_case_insensitive(self):
        """大小写不敏感"""
        svc = self._make_service()
        result = svc._pre_llm_sensitivity_check("HIGH")
        assert result is not None
        assert "SLI_005" in result


# =====================================================================
# _parse_llm_json_response
# =====================================================================


class TestParseLlmJsonResponse:
    """LLM JSON 响应解析测试"""

    def _make_service(self):
        svc = SemanticMaintenanceService.__new__(SemanticMaintenanceService)
        svc.db = MagicMock()
        return svc

    def test_parse_plain_json(self):
        """解析纯 JSON 字符串"""
        svc = self._make_service()
        result = svc._parse_llm_json_response('{"semantic_name": "Revenue"}')
        assert result["semantic_name"] == "Revenue"

    def test_parse_json_with_code_block(self):
        """解析 ```json 包裹的 JSON"""
        svc = self._make_service()
        content = '```json\n{"semantic_name": "Revenue"}\n```'
        result = svc._parse_llm_json_response(content)
        assert result["semantic_name"] == "Revenue"

    def test_parse_json_with_plain_code_block(self):
        """解析 ``` 包裹的 JSON（无 json 标签）"""
        svc = self._make_service()
        content = '```\n{"semantic_name": "Cost"}\n```'
        result = svc._parse_llm_json_response(content)
        assert result["semantic_name"] == "Cost"

    def test_parse_invalid_json_raises(self):
        """无效 JSON 抛出 JSONDecodeError"""
        import json
        svc = self._make_service()
        with pytest.raises(json.JSONDecodeError):
            svc._parse_llm_json_response("not json at all")

    def test_parse_nested_json(self):
        """解析嵌套 JSON"""
        svc = self._make_service()
        content = '{"semantic_name": "Test", "tags_json": ["tag1", "tag2"]}'
        result = svc._parse_llm_json_response(content)
        assert result["tags_json"] == ["tag1", "tag2"]

    def test_parse_whitespace_padded(self):
        """前后有空白的 JSON"""
        svc = self._make_service()
        content = '  \n  {"key": "value"}  \n  '
        result = svc._parse_llm_json_response(content)
        assert result["key"] == "value"


# =====================================================================
# _semantic_fields_changed
# =====================================================================


class TestSemanticFieldsChanged:
    """语义字段变更检测测试"""

    def _make_service(self):
        svc = SemanticMaintenanceService.__new__(SemanticMaintenanceService)
        svc.db = MagicMock()
        return svc

    def _make_old_field(self, semantic_name="Revenue", semantic_name_zh="营收",
                        semantic_definition="Total revenue"):
        old = MagicMock()
        old.semantic_name = semantic_name
        old.semantic_name_zh = semantic_name_zh
        old.semantic_definition = semantic_definition
        return old

    def test_no_change(self):
        """无变化返回 False"""
        svc = self._make_service()
        old = self._make_old_field()
        new_data = {
            "semantic_name": "Revenue",
            "semantic_name_zh": "营收",
            "semantic_definition": "Total revenue",
        }
        assert svc._semantic_fields_changed(old, new_data) is False

    def test_name_changed(self):
        """semantic_name 变化返回 True"""
        svc = self._make_service()
        old = self._make_old_field()
        new_data = {"semantic_name": "New Revenue"}
        assert svc._semantic_fields_changed(old, new_data) is True

    def test_name_zh_changed(self):
        """semantic_name_zh 变化返回 True"""
        svc = self._make_service()
        old = self._make_old_field()
        new_data = {"semantic_name_zh": "新营收"}
        assert svc._semantic_fields_changed(old, new_data) is True

    def test_definition_changed(self):
        """semantic_definition 变化返回 True"""
        svc = self._make_service()
        old = self._make_old_field()
        new_data = {"semantic_definition": "Updated definition"}
        assert svc._semantic_fields_changed(old, new_data) is True

    def test_none_vs_empty_string(self):
        """None 与空字符串视为相同"""
        svc = self._make_service()
        old = self._make_old_field(semantic_name=None, semantic_name_zh=None,
                                    semantic_definition=None)
        new_data = {"semantic_name": "", "semantic_name_zh": "",
                    "semantic_definition": ""}
        assert svc._semantic_fields_changed(old, new_data) is False

    def test_non_semantic_field_ignored(self):
        """非语义字段变更不触发"""
        svc = self._make_service()
        old = self._make_old_field()
        new_data = {
            "semantic_name": "Revenue",
            "semantic_name_zh": "营收",
            "semantic_definition": "Total revenue",
            "tags_json": '["new_tag"]',  # 非语义字段
        }
        assert svc._semantic_fields_changed(old, new_data) is False

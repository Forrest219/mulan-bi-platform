import hashlib

import pytest

from services.data_agent.skill_prompt_loader import SkillPromptLoader


pytestmark = pytest.mark.skip_db


def test_skill_prompt_loader_returns_content_checksum_version_and_path(tmp_path):
    prompt_dir = tmp_path / "planning"
    prompt_dir.mkdir()
    content = """---
version: planning.test.v1
---

# 测试规划

只输出 JSON。
"""
    prompt_file = prompt_dir / "aggregate.md"
    prompt_file.write_text(content, encoding="utf-8")

    result = SkillPromptLoader(tmp_path).load_planning("aggregate")

    normalized = content.strip()
    assert result.ok is True
    assert result.content == normalized
    assert result.checksum == hashlib.sha256(normalized.encode("utf-8")).hexdigest()
    assert result.version == "planning.test.v1"
    assert result.source_path == str(prompt_file)
    assert result.metadata == {"version": "planning.test.v1"}
    assert result.error is None


def test_skill_prompt_loader_returns_structured_error_for_missing_file(tmp_path):
    result = SkillPromptLoader(tmp_path).load_rendering("answer_renderer")

    assert result.ok is False
    assert result.content is None
    assert result.checksum is None
    assert result.version is None
    assert result.error == {
        "code": "skill_prompt_not_found",
        "message": "skill prompt markdown file does not exist",
        "skill_key": "answer_renderer",
        "kind": "rendering",
        "source_path": str(tmp_path / "rendering" / "answer_renderer.md"),
    }


def test_skill_prompt_loader_rejects_path_like_skill_key(tmp_path):
    result = SkillPromptLoader(tmp_path).load_planning("../aggregate")

    assert result.ok is False
    assert result.error["code"] == "invalid_skill_key"


def test_default_skill_prompt_markdowns_are_loadable():
    loader = SkillPromptLoader()

    for skill_key in [
        "aggregate",
        "ranking",
        "customer_record",
        "trend_condition",
        "all_period_condition",
        "set_difference",
        "root_cause",
    ]:
        result = loader.load_planning(skill_key)
        assert result.ok is True
        assert result.content
        assert result.checksum
        assert result.version == "v1"
        assert result.metadata["skill_type"] == "planning_prompt"
        assert result.metadata["key"] == skill_key

    rendering = loader.load_rendering("answer_renderer")
    assert rendering.ok is True
    assert rendering.content
    assert rendering.version == "v1"
    assert rendering.metadata["skill_type"] == "rendering_prompt"


def test_default_planning_prompt_contracts_match_current_queryspec():
    loader = SkillPromptLoader()

    for skill_key in [
        "aggregate",
        "ranking",
        "customer_record",
        "trend_condition",
        "all_period_condition",
        "set_difference",
        "root_cause",
    ]:
        result = loader.load_planning(skill_key)
        assert result.ok is True
        content = result.content or ""
        assert f"operator: {skill_key}" in content
        assert f'"operator": "{skill_key}"' in content
        assert '"metrics": ["SUM(' not in content
        assert '"operator": "=="' not in content
        assert '"time_field"' not in content
        assert '"time_grain"' not in content
        assert "_analysis" not in content
        assert "_lookup" not in content

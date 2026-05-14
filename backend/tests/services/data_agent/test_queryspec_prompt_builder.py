import pytest

from services.data_agent.answer_prompt_builder import build_answer_prompt
from services.data_agent.queryspec_prompt_builder import build_queryspec_prompt


pytestmark = pytest.mark.skip_db


def test_queryspec_prompt_injects_queryable_fields_and_json_only_contract():
    messages = build_queryspec_prompt(
        question="按维度看指标排名前 5 的项目",
        intent="ranking",
        datasource={"name": "业务数据源", "luid": "ds-generic"},
        queryable_fields=[
            {"name": "维度X", "role": "dimension", "type": "string"},
            {"name": "指标Y", "role": "measure", "type": "number", "aggregations": ["SUM"]},
        ],
        analysis_context={"turn_no": 1, "query_plan": {"filters": []}},
        planning_skill_content="规划要求：只能输出 QuerySpec JSON。",
    )

    joined = "\n".join(message["content"] for message in messages)
    assert messages[0]["role"] == "system"
    assert "queryable_fields" in joined
    assert "维度X" in joined
    assert "指标Y" in joined
    assert "只输出一个 QuerySpec JSON object" in joined
    assert "json.loads" in joined
    assert "不得使用 metadata_fields" in joined


def test_queryspec_prompt_includes_datasource_intent_question_and_context():
    messages = build_queryspec_prompt(
        question="某周期指标是多少",
        intent="aggregate",
        datasource={"name": "通用数据源", "luid": "luid-1"},
        queryable_fields=["时间字段", "指标Y"],
        analysis_context={"scope": {"language": "zh-CN"}},
        planning_skill_content="聚合规划。",
    )

    joined = "\n".join(message["content"] for message in messages)
    assert "某周期指标是多少" in joined
    assert "intent: aggregate" in joined
    assert '"luid":"luid-1"' in joined
    assert '"language":"zh-CN"' in joined


def test_answer_prompt_forbids_facts_not_returned_by_mcp():
    messages = build_answer_prompt(
        mcp_result={
            "fields": ["维度X", "SUM(指标Y)"],
            "rows": [["项目A", 100]],
            "summary": "项目A为 100",
        },
        queryspec={
            "operator": "ranking",
            "metrics": [{"field": "指标Y", "aggregation": "SUM"}],
            "dimensions": ["维度X"],
        },
        rendering_skill_content="回答必须简短，并保留查询口径。",
    )

    joined = "\n".join(message["content"] for message in messages)
    assert "不得新增事实" in joined
    assert "不得补充外部知识" in joined
    assert "不得重新计算 MCP 结果中不存在的数值" in joined
    assert "只能复述、概括或排序 MCP JSON 中已经返回的事实" in joined
    assert "项目A" in joined
    assert "SUM(指标Y)" in joined

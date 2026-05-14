"""Tests for MCP-first controlled Data Agent main path."""

import json

import pytest

from services.data_agent import mcp_first_main
from services.data_agent.intent_classifier import IntentClassification
from services.data_agent.mcp_first_main import run_mcp_first_main_path
from services.data_agent.queryspec import QuerySpec
from services.data_agent.tool_base import ToolContext

pytestmark = pytest.mark.skip_db


class _FakeLLM:
    async def complete(self, *, prompt, system=None, timeout=None, purpose=None):
        if purpose == "data_agent_queryspec":
            return {
                "content": json.dumps({
                    "intent": "aggregate",
                    "operator": "aggregate",
                    "datasource": {"name": "测试数据源", "luid": "ds-1"},
                    "metrics": [{"field": "销售额", "aggregation": "SUM"}],
                    "dimensions": [],
                    "filters": [],
                    "time": None,
                    "sort": [],
                    "limit": 100,
                    "answer_contract": {
                        "max_chars": 80,
                        "must_include": ["销售额"],
                        "forbid": ["猜测原因", "明细列表"],
                    },
                }, ensure_ascii=False)
            }
        if purpose == "data_agent_answer":
            return {"content": "总销售额为 100。"}
        raise AssertionError(f"unexpected LLM purpose: {purpose}")


class _MissingDerivedMetricLLM:
    async def complete(self, *, prompt, system=None, timeout=None, purpose=None):
        if purpose == "data_agent_queryspec":
            return {
                "content": json.dumps({
                    "intent": "aggregate",
                    "operator": "aggregate",
                    "datasource": {"name": "测试数据源", "luid": "ds-1"},
                    "metrics": [
                        {"field": "销售额", "aggregation": "SUM"},
                        {"field": "利润", "aggregation": "SUM"},
                        {"field": "利润率", "aggregation": "AVG"},
                    ],
                    "dimensions": ["子类别"],
                    "filters": [],
                    "time": None,
                    "sort": [{"field": "SUM(销售额)", "direction": "DESC"}],
                    "limit": 100,
                    "answer_contract": {
                        "max_chars": 120,
                        "must_include": ["利润率"],
                        "forbid": ["猜测原因", "明细列表"],
                    },
                }, ensure_ascii=False)
            }
        if purpose == "data_agent_answer":
            return {"content": "已按子类别汇总销售额、利润和利润率。"}
        raise AssertionError(f"unexpected LLM purpose: {purpose}")


def _intent(intent: str = "aggregate") -> IntentClassification:
    return IntentClassification(intent=intent, confidence=0.9, route_reason="test")


@pytest.mark.parametrize(
    "question",
    [
        "统计一下每个子类别的销售额、利润和利润率",
        "整体的销售额、利润、利润率、客户数、客单价是什么样子",
    ],
)
def test_plain_aggregate_questions_do_not_prefer_deterministic_queryspec(question):
    assert mcp_first_main._should_prefer_deterministic_queryspec(
        question,
        _intent(),
        analysis_context=None,
    ) is False


@pytest.mark.parametrize(
    "question",
    [
        "哪个子类别利润每年都在持续增长",
        "2025 年没有销售记录的子类别",
        "为什么福建 2024 年巨亏",
        "利润最高的前 5 个子类别",
    ],
)
def test_complex_operators_prefer_deterministic_queryspec(question):
    assert mcp_first_main._should_prefer_deterministic_queryspec(
        question,
        _intent(),
        analysis_context=None,
    ) is True


def test_contextual_followup_prefers_deterministic_queryspec():
    assert mcp_first_main._should_prefer_deterministic_queryspec(
        "这个指标过去几年的趋势是什么样子",
        _intent(),
        analysis_context={"metric_names": ["销售额"], "dimension_names": ["子类别"]},
    ) is True


@pytest.mark.asyncio
async def test_mcp_first_main_path_uses_queryspec_validator_and_mcp(monkeypatch):
    monkeypatch.setattr(
        mcp_first_main,
        "_resolve_datasource",
        lambda question, context, datasource_name_hint: {"name": "测试数据源", "luid": "ds-1", "asset_id": 1},
    )
    monkeypatch.setattr(mcp_first_main, "_queryable_fields", lambda ds_info, connection_id=None: ["销售额"])

    async def _fake_execute_vizql(datasource_luid, vizql_json, context, question, *, limit):
        assert datasource_luid == "ds-1"
        assert vizql_json["fields"] == [{"fieldCaption": "销售额", "function": "SUM"}]
        assert limit == 100
        return {"fields": ["SUM(销售额)"], "rows": [[100]]}

    monkeypatch.setattr(mcp_first_main, "_execute_vizql", _fake_execute_vizql)

    events = [
        event
        async for event in run_mcp_first_main_path(
            question="总销售额是多少？",
            context=ToolContext(session_id="s1", user_id=1, connection_id=2, trace_id="trace-1"),
            intent_result=IntentClassification(intent="aggregate", confidence=0.9, route_reason="metric_keyword"),
            llm_service=_FakeLLM(),
        )
    ]

    tool_names = [
        event.content["tool"]
        for event in events
        if event.type in {"tool_call", "tool_result"} and isinstance(event.content, dict)
    ]
    assert "llm_queryspec" in tool_names
    assert "queryspec_fallback" not in tool_names
    assert "queryspec_validator" in tool_names
    assert "tableau_mcp" in tool_names
    assert "answer_renderer" in tool_names
    assert "schema" not in tool_names
    mcp_result = next(
        event.content["result"]["data"]
        for event in events
        if event.type == "tool_result" and isinstance(event.content, dict) and event.content.get("tool") == "tableau_mcp"
    )
    assert mcp_result["table_display"]["columns"][0]["label"] == "销售额"
    assert mcp_result["table_display"]["columns"][0]["semantic_type"] == "metric"
    assert mcp_result["table_display"]["columns"][0]["align"] == "right"
    assert events[-1].type == "answer"
    assert events[-1].content == "总销售额为 100。"


@pytest.mark.asyncio
async def test_mcp_first_main_lets_mcp_handle_calculation_metric_without_extra_aggregation(monkeypatch):
    monkeypatch.delenv("DATA_AGENT_QUERYSPEC_FALLBACK_ENABLED", raising=False)
    monkeypatch.setattr(
        mcp_first_main,
        "_resolve_datasource",
        lambda question, context, datasource_name_hint: {"name": "测试数据源", "luid": "ds-1", "asset_id": 1},
    )
    monkeypatch.setattr(mcp_first_main, "_queryable_fields", lambda ds_info, connection_id=None: ["销售额", "利润", "利润率", "子类别"])

    async def _fake_execute_vizql(datasource_luid, vizql_json, context, question, *, limit):
        assert datasource_luid == "ds-1"
        assert vizql_json["fields"][0] == {"fieldCaption": "子类别"}
        assert vizql_json["fields"][1]["fieldCaption"] == "销售额"
        assert vizql_json["fields"][1]["function"] == "SUM"
        assert vizql_json["fields"][1]["sortDirection"] == "DESC"
        assert vizql_json["fields"][2] == {"fieldCaption": "利润", "function": "SUM"}
        assert vizql_json["fields"][3] == {"fieldCaption": "利润率"}
        return {"fields": ["子类别", "SUM(销售额)", "SUM(利润)", "利润率"], "rows": [["家具", 200, 50, "25.00%"]]}

    monkeypatch.setattr(mcp_first_main, "_execute_vizql", _fake_execute_vizql)

    events = [
        event
        async for event in run_mcp_first_main_path(
            question="统计一下每个子类别的销售额、利润和利润率",
            context=ToolContext(session_id="s1", user_id=1, connection_id=2, trace_id="trace-derived"),
            intent_result=IntentClassification(intent="aggregate", confidence=0.9, route_reason="metric_keyword"),
            llm_service=_MissingDerivedMetricLLM(),
        )
    ]

    tool_names = [
        event.content["tool"]
        for event in events
        if event.type in {"tool_call", "tool_result"} and isinstance(event.content, dict)
    ]
    assert "queryspec_fallback" not in tool_names
    assert "tableau_mcp" in tool_names
    mcp_result = next(
        event.content["result"]["data"]
        for event in events
        if event.type == "tool_result" and isinstance(event.content, dict) and event.content.get("tool") == "tableau_mcp"
    )
    assert [metric["field"] for metric in mcp_result["queryspec"]["metrics"]] == ["销售额", "利润", "利润率"]
    assert mcp_result["queryspec"]["metrics"][2]["aggregation"] is None
    assert mcp_result["queryspec"]["derived_metrics"] == []
    assert mcp_result["fields"] == ["子类别", "SUM(销售额)", "SUM(利润)", "利润率"]
    assert mcp_result["rows"] == [["家具", 200, 50, "25.00%"]]
    assert events[-1].type == "answer"


def test_normalize_mcp_data_does_not_compute_missing_calculation_metric():
    spec = QuerySpec.model_validate({
        "intent": "aggregate",
        "operator": "aggregate",
        "metrics": [
            {"field": "销售额", "aggregation": "SUM"},
            {"field": "利润", "aggregation": "SUM"},
        ],
        "dimensions": ["子类别"],
        "derived_metrics": [
            {
                "name": "利润率",
                "formula": "registry_defined_formula",
                "result_type": "percent",
                "required_base_metrics": ["利润", "销售额"],
            }
        ],
    })

    data = mcp_first_main._normalize_mcp_data(
        {
            "fields": ["子类别", "SUM(销售额)", "SUM(利润)"],
            "rows": [["小计", 100, 10], ["大计", 200, 50]],
        },
        spec,
        {"name": "测试数据源", "luid": "ds-1"},
    )

    assert data["fields"] == ["子类别", "SUM(销售额)", "SUM(利润)"]
    assert data["rows"] == [["大计", 200, 50], ["小计", 100, 10]]

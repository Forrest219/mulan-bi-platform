"""Tests for deterministic QuerySpec fallback builders."""

import json

import pytest

from services.data_agent import mcp_first_main
from services.data_agent.intent_classifier import IntentClassification
from services.data_agent.queryspec import QuerySpec
from services.data_agent.queryspec_fallback import build_fallback_queryspec
from services.data_agent.queryspec_validator import validate_queryspec
from services.data_agent.tool_base import ToolContext

pytestmark = pytest.mark.skip_db

FIELDS = ["销售额", "子类别", "利润", "发货日期", "客户名称", "省/自治区", "类别"]
FIELDS_WITH_DERIVED_FIRST = [
    "客单价",
    "利润率",
    "客户数",
    "子类别",
    "发货年份",
    "发货日期",
    "销售额",
    "利润",
    "客户名称",
    "省/自治区",
    "类别",
]
DATASOURCE = {"name": "订单+ (示例 - 超市)", "luid": "ds-1"}


def _build(
    question: str,
    intent: str,
    *,
    analysis_context: dict | None = None,
    validate_with_question: bool = False,
    queryable_fields: list[str] | None = None,
) -> QuerySpec:
    fields = queryable_fields or FIELDS
    raw = build_fallback_queryspec(
        question=question,
        intent_result=IntentClassification(intent=intent, confidence=0.8, route_reason="test"),
        datasource=DATASOURCE,
        queryable_fields=fields,
        analysis_context=analysis_context,
    )
    assert raw is not None
    spec = QuerySpec.model_validate(raw)
    validation = validate_queryspec(
        spec,
        fields,
        DATASOURCE,
        {
            "accessible_datasource_luids": ["ds-1"],
            **({"question": question, "analysis_context": analysis_context or {}} if validate_with_question else {}),
        },
    )
    assert validation.passed, validation.to_dict()
    return spec


def test_fallback_builds_set_difference_without_detail_scan():
    spec = _build("2025 年没有销售记录的子类别有哪些？", "set_difference")

    assert spec.source == "deterministic_fallback"
    assert spec.effective_operator == "set_difference"
    assert spec.universe is not None
    assert spec.occurred is not None
    assert spec.universe.target_dimension == "子类别"
    assert spec.occurred.time is not None
    assert spec.occurred.time.range["value"] == 2025
    assert spec.raw_rows is False


def test_fallback_treats_customer_count_as_metric_not_dimension():
    spec = _build("整体的销售额、利润、利润率、客户数、客单价是什么样子", "aggregate")

    assert spec.effective_operator == "aggregate"
    assert spec.dimensions == []
    assert [metric.field for metric in spec.metrics] == ["销售额", "利润", "客户名称"]


def test_fallback_current_explicit_metrics_override_context_metrics():
    spec = _build(
        "统计一下每个子类别的销售额、利润和利润率",
        "aggregate",
        analysis_context={"metric_names": ["销售额"]},
        validate_with_question=True,
        queryable_fields=FIELDS_WITH_DERIVED_FIRST,
    )

    assert spec.effective_operator == "aggregate"
    assert [(metric.field, metric.aggregation) for metric in spec.metrics] == [
        ("销售额", "SUM"),
        ("利润", "SUM"),
        ("利润率", None),
    ]
    assert spec.derived_metrics == []
    assert spec.answer_contract is not None
    assert spec.answer_contract.must_include == ["销售额", "利润", "利润率"]


def test_fallback_profit_metric_does_not_match_profit_rate_field_first():
    spec = _build(
        "统计一下每个子类别的销售额、利润和利润率",
        "aggregate",
        analysis_context={"metric_names": ["销售额"]},
        validate_with_question=True,
        queryable_fields=FIELDS_WITH_DERIVED_FIRST,
    )

    assert [(metric.field, metric.aggregation) for metric in spec.metrics] == [
        ("销售额", "SUM"),
        ("利润", "SUM"),
        ("利润率", None),
    ]
    assert spec.derived_metrics == []


def test_fallback_builds_customer_average_derived_metric():
    spec = _build(
        "按类别统计销售额、客户数和客单价",
        "aggregate",
        validate_with_question=True,
        queryable_fields=FIELDS_WITH_DERIVED_FIRST,
    )

    assert [(metric.field, metric.aggregation) for metric in spec.metrics] == [
        ("销售额", "SUM"),
        ("客户名称", "COUNTD"),
        ("客单价", None),
    ]
    assert spec.derived_metrics == []
    assert spec.answer_contract is not None
    assert spec.answer_contract.must_include == ["销售额", "客户数", "客单价"]


def test_fallback_without_explicit_metric_still_uses_context_metric():
    spec = _build(
        "继续按子类别拆分",
        "aggregate",
        analysis_context={"metric_names": ["销售额"]},
        validate_with_question=True,
    )

    assert [(metric.field, metric.aggregation) for metric in spec.metrics] == [("销售额", "SUM")]
    assert spec.derived_metrics == []
    assert spec.answer_contract is not None
    assert spec.answer_contract.must_include == ["销售额"]


def test_fallback_treats_plain_trend_followup_as_time_aggregate():
    spec = _build("这个指标过去几年的趋势是什么样子", "trend_condition")

    assert spec.effective_operator == "aggregate"
    assert spec.time is not None
    assert spec.time.grain == "YEAR"


def test_fallback_builds_period_condition_with_complete_periods():
    spec = _build("哪些省份一直没挣到钱？利润是亏的", "aggregate")

    assert spec.effective_operator == "all_period_condition"
    assert spec.dimensions == ["省/自治区"]
    assert spec.operator_spec["condition"] == {"op": "<", "value": 0}
    assert spec.operator_spec["require_complete_periods"] is True
    assert spec.operator_spec["expected_periods"] == [2021, 2022, 2023, 2024]


def test_fallback_builds_trend_condition_for_continuous_growth():
    spec = _build("哪个子类别的利润每年都在持续增长？", "trend_condition")

    assert spec.effective_operator == "trend_condition"
    assert spec.dimensions == ["子类别"]
    assert spec.direction == "increasing"
    assert spec.operator_spec["strict"] is True
    assert spec.operator_spec["expected_periods"] == [2021, 2022, 2023, 2024]


def test_fallback_builds_root_cause_with_product_and_customer_breakdowns():
    spec = _build("为什么辽宁、福建 2024 年巨亏？看产品线和客户", "root_cause")

    assert spec.effective_operator == "root_cause"
    assert spec.time is not None
    assert spec.time.range["value"] == 2024
    assert {item.field for item in spec.filters} == {"省/自治区"}
    assert set(spec.breakdown_dimensions) >= {"子类别", "客户名称"}
    assert spec.sort[0].direction == "ASC"


def test_fallback_builds_customer_record_with_validator_scope():
    spec = _build("“邓保”这个客户的合作记录是什么样？最近还有合作吗？", "customer_record")

    assert spec.effective_operator == "customer_record"
    assert spec.focus_dimension == "客户名称"
    assert spec.operator_spec["entity_field"] == "客户名称"
    assert spec.operator_spec["entity_value"] == "邓保"


class _BadQuerySpecLLM:
    async def complete(self, *, prompt, system=None, timeout=None, purpose=None):
        if purpose == "data_agent_queryspec":
            return {"content": "无法生成 JSON"}
        if purpose == "data_agent_answer":
            return {"content": ""}
        raise AssertionError(f"unexpected LLM purpose: {purpose}")


class _HallucinatedAnswerLLM:
    async def complete(self, *, prompt, system=None, timeout=None, purpose=None):
        if purpose == "data_agent_queryspec":
            return {
                "content": json.dumps({
                    "intent": "aggregate",
                    "operator": "aggregate",
                    "datasource": {"name": "测试数据源", "luid": "ds-1"},
                    "metrics": [{"field": "销售额", "aggregation": "SUM"}],
                    "dimensions": [],
                    "limit": 100,
                    "answer_contract": {"must_include": ["销售额"], "forbid": ["猜测原因"]},
                }, ensure_ascii=False)
            }
        if purpose == "data_agent_answer":
            return {"content": "没有包含省份维度，无法直接回答哪个省最高。"}
        raise AssertionError(f"unexpected LLM purpose: {purpose}")


class _MissingMetricQuerySpecLLM:
    async def complete(self, *, prompt, system=None, timeout=None, purpose=None):
        if purpose == "data_agent_queryspec":
            return {
                "content": json.dumps({
                    "intent": "aggregate",
                    "operator": "aggregate",
                    "datasource": {"name": "测试数据源", "luid": "ds-1"},
                    "metrics": [{"field": "销售额", "aggregation": "SUM"}],
                    "dimensions": [],
                    "limit": 100,
                    "answer_contract": {"must_include": ["销售额"], "forbid": ["猜测原因"]},
                }, ensure_ascii=False)
            }
        if purpose == "data_agent_answer":
            return {"content": ""}
        raise AssertionError(f"unexpected LLM purpose: {purpose}")


class _AggregateForSetDifferenceLLM:
    async def complete(self, *, prompt, system=None, timeout=None, purpose=None):
        if purpose == "data_agent_queryspec":
            return {
                "content": json.dumps({
                    "intent": "aggregate",
                    "operator": "aggregate",
                    "datasource": {"name": "测试数据源", "luid": "ds-1"},
                    "metrics": [{"field": "销售额", "aggregation": "SUM"}],
                    "dimensions": ["子类别"],
                    "limit": 100,
                    "answer_contract": {"must_include": ["销售额", "子类别"], "forbid": ["明细列表"]},
                }, ensure_ascii=False)
            }
        if purpose == "data_agent_answer":
            return {"content": ""}
        raise AssertionError(f"unexpected LLM purpose: {purpose}")


@pytest.mark.asyncio
async def test_mcp_first_path_falls_back_when_llm_queryspec_is_invalid(monkeypatch):
    monkeypatch.setenv("DATA_AGENT_QUERYSPEC_FALLBACK_ENABLED", "true")
    monkeypatch.setattr(
        mcp_first_main,
        "_resolve_datasource",
        lambda question, context, datasource_name_hint: {"name": "测试数据源", "luid": "ds-1", "asset_id": 1},
    )
    monkeypatch.setattr(mcp_first_main, "_queryable_fields", lambda ds_info, connection_id=None: ["销售额"])

    async def _fake_execute_vizql(datasource_luid, vizql_json, context, question, *, limit):
        assert vizql_json["fields"] == [{"fieldCaption": "销售额", "function": "SUM"}]
        return {"fields": ["SUM(销售额)"], "rows": [[100]]}

    monkeypatch.setattr(mcp_first_main, "_execute_vizql", _fake_execute_vizql)

    events = [
        event
        async for event in mcp_first_main.run_mcp_first_main_path(
            question="总销售额是多少？",
            context=ToolContext(session_id="s1", user_id=1, connection_id=2, trace_id="trace-1"),
            intent_result=IntentClassification(intent="aggregate", confidence=0.9, route_reason="metric_keyword"),
            llm_service=_BadQuerySpecLLM(),
        )
    ]

    tool_names = [
        event.content["tool"]
        for event in events
        if event.type in {"tool_call", "tool_result"} and isinstance(event.content, dict)
    ]
    assert "queryspec_fallback" in tool_names
    assert events[-1].type == "answer"
    assert "销售额 100.00" in events[-1].content


@pytest.mark.asyncio
async def test_mcp_first_path_rejects_invalid_llm_queryspec_when_fallback_disabled(monkeypatch):
    monkeypatch.delenv("DATA_AGENT_QUERYSPEC_FALLBACK_ENABLED", raising=False)
    monkeypatch.setattr(
        mcp_first_main,
        "_resolve_datasource",
        lambda question, context, datasource_name_hint: {"name": "测试数据源", "luid": "ds-1", "asset_id": 1},
    )
    monkeypatch.setattr(mcp_first_main, "_queryable_fields", lambda ds_info, connection_id=None: ["销售额"])

    async def _unexpected_execute_vizql(datasource_luid, vizql_json, context, question, *, limit):
        raise AssertionError("fallback disabled invalid QuerySpec must not execute MCP")

    monkeypatch.setattr(mcp_first_main, "_execute_vizql", _unexpected_execute_vizql)

    events = [
        event
        async for event in mcp_first_main.run_mcp_first_main_path(
            question="总销售额是多少？",
            context=ToolContext(session_id="s1", user_id=1, connection_id=2, trace_id="trace-1"),
            intent_result=IntentClassification(intent="aggregate", confidence=0.9, route_reason="metric_keyword"),
            llm_service=_BadQuerySpecLLM(),
        )
    ]

    tool_names = [
        event.content["tool"]
        for event in events
        if event.type in {"tool_call", "tool_result"} and isinstance(event.content, dict)
    ]
    assert "queryspec_fallback" not in tool_names
    assert events[-1].type == "error"
    assert events[-1].content["fallback_type"] == "query_plan_rejected"
    assert events[-1].content["error_code"] == "QS_LLM_INVALID"
    assert events[-1].content["trace_id"] == "trace-1"
    assert events[-1].content["controlled_chain"]["detail"]["fallback_disabled"] is True


@pytest.mark.asyncio
async def test_mcp_first_path_rejects_semantic_metric_missing_when_fallback_disabled(monkeypatch):
    monkeypatch.delenv("DATA_AGENT_QUERYSPEC_FALLBACK_ENABLED", raising=False)
    monkeypatch.setattr(
        mcp_first_main,
        "_resolve_datasource",
        lambda question, context, datasource_name_hint: {"name": "测试数据源", "luid": "ds-1", "asset_id": 1},
    )
    monkeypatch.setattr(mcp_first_main, "_queryable_fields", lambda ds_info, connection_id=None: ["销售额", "利润"])

    async def _unexpected_execute_vizql(datasource_luid, vizql_json, context, question, *, limit):
        raise AssertionError("QS_SEMANTIC_METRIC_MISSING must reject before MCP execution")

    monkeypatch.setattr(mcp_first_main, "_execute_vizql", _unexpected_execute_vizql)

    events = [
        event
        async for event in mcp_first_main.run_mcp_first_main_path(
            question="总利润是多少？",
            context=ToolContext(session_id="s1", user_id=1, connection_id=2, trace_id="trace-semantic"),
            intent_result=IntentClassification(intent="aggregate", confidence=0.9, route_reason="metric_keyword"),
            llm_service=_MissingMetricQuerySpecLLM(),
        )
    ]

    tool_names = [
        event.content["tool"]
        for event in events
        if event.type in {"tool_call", "tool_result"} and isinstance(event.content, dict)
    ]
    assert "queryspec_fallback" not in tool_names
    assert events[-1].type == "error"
    assert events[-1].content["fallback_type"] == "query_plan_rejected"
    assert events[-1].content["error_code"] == "QS_SEMANTIC_METRIC_MISSING"
    assert events[-1].content["trace_id"] == "trace-semantic"
    assert events[-1].content["controlled_chain"]["detail"]["fallback_reason"] == (
        "queryspec_validation_failed: QS_SEMANTIC_METRIC_MISSING"
    )


@pytest.mark.asyncio
async def test_mcp_first_path_rejects_operator_mismatch_when_fallback_disabled(monkeypatch):
    monkeypatch.delenv("DATA_AGENT_QUERYSPEC_FALLBACK_ENABLED", raising=False)
    monkeypatch.setattr(
        mcp_first_main,
        "_resolve_datasource",
        lambda question, context, datasource_name_hint: {"name": "测试数据源", "luid": "ds-1", "asset_id": 1},
    )
    monkeypatch.setattr(
        mcp_first_main,
        "_queryable_fields",
        lambda ds_info, connection_id=None: ["销售额", "子类别", "发货日期"],
    )

    async def _unexpected_execute_vizql(datasource_luid, vizql_json, context, question, *, limit):
        raise AssertionError("operator mismatch must reject before MCP execution")

    monkeypatch.setattr(mcp_first_main, "_execute_vizql", _unexpected_execute_vizql)

    events = [
        event
        async for event in mcp_first_main.run_mcp_first_main_path(
            question="2025 年没有销售记录的子类别有哪些？",
            context=ToolContext(session_id="s1", user_id=1, connection_id=2, trace_id="trace-mismatch"),
            intent_result=IntentClassification(intent="set_difference", confidence=0.9, route_reason="missing_record"),
            llm_service=_AggregateForSetDifferenceLLM(),
        )
    ]

    tool_names = [
        event.content["tool"]
        for event in events
        if event.type in {"tool_call", "tool_result"} and isinstance(event.content, dict)
    ]
    assert "queryspec_fallback" not in tool_names
    assert events[-1].type == "error"
    assert events[-1].content["fallback_type"] == "query_plan_rejected"
    assert events[-1].content["error_code"] == "QS_OPERATOR_MISMATCH"
    assert events[-1].content["controlled_chain"]["detail"]["fallback_reason"] == (
        "llm_queryspec_operator_mismatch:aggregate->set_difference"
    )


@pytest.mark.asyncio
async def test_mcp_first_path_replaces_hallucinated_answer_renderer(monkeypatch):
    monkeypatch.setattr(
        mcp_first_main,
        "_resolve_datasource",
        lambda question, context, datasource_name_hint: {"name": "测试数据源", "luid": "ds-1", "asset_id": 1},
    )
    monkeypatch.setattr(mcp_first_main, "_queryable_fields", lambda ds_info, connection_id=None: ["销售额"])

    async def _fake_execute_vizql(datasource_luid, vizql_json, context, question, *, limit):
        return {"fields": ["SUM(销售额)"], "rows": [[100]]}

    monkeypatch.setattr(mcp_first_main, "_execute_vizql", _fake_execute_vizql)

    events = [
        event
        async for event in mcp_first_main.run_mcp_first_main_path(
            question="整体销售额是多少？",
            context=ToolContext(session_id="s1", user_id=1, connection_id=2, trace_id="trace-1"),
            intent_result=IntentClassification(intent="aggregate", confidence=0.9, route_reason="metric_keyword"),
            llm_service=_HallucinatedAnswerLLM(),
        )
    ]

    assert events[-1].type == "answer"
    assert "无法直接回答" not in events[-1].content
    assert "销售额 100.00" in events[-1].content


def test_deterministic_renderer_summarizes_time_table_without_row_echo():
    spec = QuerySpec.model_validate({
        "intent": "aggregate",
        "operator": "aggregate",
        "source": "deterministic_fallback",
        "time": {"field": "发货日期", "grain": "YEAR", "range": {"type": "range", "start": 2021, "end": 2024}},
        "metrics": [{"field": "销售额", "aggregation": "SUM"}, {"field": "利润", "aggregation": "SUM"}],
        "dimensions": [],
    })
    answer = mcp_first_main._render_deterministic_answer(
        {
            "fields": ["YEAR(发货日期)", "SUM(销售额)", "SUM(利润)"],
            "rows": [
                [2021, 3478604.98, 357467.13],
                [2022, 3496306.32, 459655.06],
                [2023, 4466389.58, 607630.72],
                [2024, 5387286.41, 687150.88],
            ],
        },
        spec,
    )

    assert "详细数据见下方表格" in answer
    assert "返回 4 行" not in answer
    assert "YEAR(发货日期)=" not in answer
    assert "SUM(" not in answer
    assert "2021 年" in answer
    assert "2024 年" in answer


def test_deterministic_renderer_keeps_single_row_metric_summary():
    spec = QuerySpec.model_validate({
        "intent": "aggregate",
        "operator": "aggregate",
        "source": "deterministic_fallback",
        "metrics": [
            {"field": "销售额", "aggregation": "SUM"},
            {"field": "利润", "aggregation": "SUM"},
            {"field": "客户名称", "aggregation": "COUNTD"},
        ],
    })
    answer = mcp_first_main._render_deterministic_answer(
        {
            "fields": ["SUM(销售额)", "SUM(利润)", "COUNTD(客户名称)"],
            "rows": [[16867374.07, 2119151.91, 771]],
        },
        spec,
    )

    assert "销售额 16,867,374.07" in answer
    assert "利润率" not in answer
    assert "详细数据见下方表格" not in answer


def test_deterministic_renderer_summarizes_ranking_table():
    spec = QuerySpec.model_validate({
        "intent": "ranking",
        "operator": "ranking",
        "source": "deterministic_fallback",
        "metrics": [{"field": "销售额", "aggregation": "SUM"}],
        "dimensions": ["客户名称"],
    })
    answer = mcp_first_main._render_deterministic_answer(
        {
            "fields": ["客户名称", "SUM(销售额)", "销售额占比"],
            "rows": [["李丽丽", 181562.11, "1.08%"], ["潘锦", 138128.58, "0.82%"], ["袁丽美", 109600.71, "0.65%"]],
        },
        spec,
    )

    assert "Top3" in answer
    assert "详细数据见下方表格" in answer
    assert "客户名称=李丽丽" not in answer


def test_grouped_aggregate_defaults_to_primary_metric_sort():
    spec = QuerySpec.model_validate({
        "intent": "aggregate",
        "operator": "aggregate",
        "metrics": [
            {"field": "销售额", "aggregation": "SUM"},
            {"field": "利润", "aggregation": "SUM"},
        ],
        "dimensions": ["子类别"],
        "sort": [],
    })

    vizql = mcp_first_main._vizql_from_queryspec(spec)

    assert vizql["fields"] == [
        {"fieldCaption": "子类别"},
        {"fieldCaption": "销售额", "function": "SUM", "sortDirection": "DESC", "sortPriority": 1},
        {"fieldCaption": "利润", "function": "SUM"},
    ]


def test_grouped_aggregate_does_not_compute_missing_profit_rate_and_sorts_rows():
    spec = QuerySpec.model_validate({
        "intent": "aggregate",
        "operator": "aggregate",
        "metrics": [
            {"field": "销售额", "aggregation": "SUM"},
            {"field": "利润", "aggregation": "SUM"},
        ],
        "dimensions": ["子类别"],
        "sort": [],
        "answer_contract": {"must_include": ["销售额", "利润", "利润率"]},
    })

    data = mcp_first_main._normalize_mcp_data(
        {
            "fields": ["子类别", "SUM(销售额)", "SUM(利润)"],
            "rows": [["小计", 100, 10], ["大计", 200, 50]],
        },
        spec,
        DATASOURCE,
    )

    assert data["fields"] == ["子类别", "SUM(销售额)", "SUM(利润)"]
    assert data["rows"] == [["大计", 200, 50], ["小计", 100, 10]]
    assert data["table_display"]["columns"][0]["align"] == "left"
    assert data["table_display"]["columns"][1]["label"] == "销售额"
    assert data["table_display"]["columns"][1]["align"] == "right"
    answer = mcp_first_main._render_deterministic_answer(data, spec)
    assert "子类别" in answer
    assert "利润率" not in answer

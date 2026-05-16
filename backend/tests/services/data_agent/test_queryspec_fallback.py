"""Tests for deterministic QuerySpec fallback builders."""

import json

import pytest

from services.data_agent import mcp_first_main
from services.data_agent.answer_prompt_builder import build_answer_prompt, build_renderer_input
from services.data_agent.intent_classifier import IntentClassification
from services.data_agent.queryspec import QuerySpec
from services.data_agent.queryspec_fallback import (
    SET_DIFFERENCE_MCP_FALLBACK_CHAIN_MODE,
    build_fallback_queryspec,
    build_set_difference_mcp_query_args,
    run_set_difference_mcp_fallback,
)
from services.data_agent.queryspec_validator import validate_queryspec
from services.data_agent.semantic_operators.set_difference import build_set_difference_response_data
from services.data_agent.table_display import infer_table_display_schema
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


def _selected_datasource_context() -> dict:
    return {"datasource": {"name": "测试数据源", "luid": "ds-1"}}


def _tool_names(events) -> list[str]:
    return [
        event.content["tool"]
        for event in events
        if event.type in {"tool_call", "tool_result"} and isinstance(event.content, dict)
    ]


def _assert_no_query_planning_or_fallback(events) -> None:
    blocked = {
        "llm_queryspec",
        "llm_queryspec_repair",
        "llm_mcp_args",
        "queryspec_fallback",
        "queryspec_mcp_fallback",
        "mcp_main_queryspec_fallback",
    }
    assert blocked.isdisjoint(_tool_names(events))


class _FakeHostCatalog:
    def __init__(self, *, fail: bool = False):
        self.fail = fail

    async def load_catalog(self, **kwargs):
        if self.fail:
            raise RuntimeError("catalog unavailable")
        return {
            "tools": [
                {
                    "name": "get-datasource-metadata",
                    "inputSchema": {
                        "type": "object",
                        "properties": {"datasourceLuid": {"type": "string"}},
                        "required": ["datasourceLuid"],
                    },
                },
                {
                    "name": "query-datasource",
                    "inputSchema": {
                        "type": "object",
                        "properties": {
                            "datasourceLuid": {"type": "string"},
                            "query": {"type": "object"},
                            "limit": {"type": "integer"},
                        },
                        "required": ["datasourceLuid", "query"],
                    },
                },
            ]
        }


class _FakeHostPlanner:
    def __init__(self, actions):
        self.actions = list(actions)

    async def plan(self, **kwargs):
        if not self.actions:
            raise AssertionError("unexpected planner call")
        return self.actions.pop(0)


class _FakeHostExecutor:
    def __init__(self, *, query_result=None, query_error=None):
        self.query_result = query_result or {"fields": ["Metric A"], "rows": [[100]]}
        self.query_error = query_error

    async def execute_tool(self, tool_name, arguments, context):
        if tool_name == "get-datasource-metadata":
            return {"fields": [{"name": "Metric A", "dataType": "REAL"}]}
        if self.query_error is not None:
            return self.query_error
        return self.query_result


def _host_query_action() -> dict:
    return {
        "action": "tool_call",
        "tool_call": {
            "tool": "query-datasource",
            "arguments": {
                "datasourceLuid": "ds-1",
                "query": {"fields": [{"fieldCaption": "Metric A", "function": "SUM"}]},
                "limit": 100,
            },
        },
    }


def _host_final_action() -> dict:
    return {"action": "final"}


def _patch_host(
    monkeypatch,
    *,
    catalog_fail: bool = False,
    query_result=None,
    query_error=None,
    actions=None,
) -> None:
    async def _load_components(**kwargs):
        return mcp_first_main._McpHostComponents(
            catalog=_FakeHostCatalog(fail=catalog_fail),
            executor=_FakeHostExecutor(query_result=query_result, query_error=query_error),
            planner=_FakeHostPlanner(actions or [_host_query_action(), _host_final_action()]),
        )

    monkeypatch.setattr(mcp_first_main, "_load_mcp_host_components", _load_components)


def test_renderer_input_does_not_leak_missing_metric_calculation_hints():
    messages = build_answer_prompt(
        question="给我一个汇总",
        response_data={
            "fields": ["SUM(销售额)", "SUM(利润)"],
            "rows": [[100, 25]],
            "queryspec": {"answer_contract": {"must_include": ["利润率"]}},
            "derived_columns": [{"name": "利润率", "value": 0.25}],
            "summary": "利润率 25%",
        },
        rendering_skill_content="只复述返回数据。",
    )

    joined = "\n".join(message["content"] for message in messages)
    assert "不得计算任何业务指标" in joined
    assert "SUM(销售额)" in joined
    assert "SUM(利润)" in joined
    assert "利润率" not in joined
    assert "0.25" not in joined
    assert "derived_columns" not in joined
    assert "answer_contract" not in joined


def test_renderer_input_surfaces_structured_mcp_error_without_queryspec_fallback():
    renderer_input = build_renderer_input(
        question="原始问题",
        response_data={
            "fields": [],
            "rows": [],
            "error": "mcp natural-language query tool unavailable",
            "error_code": "MCP_NL_TOOL_UNAVAILABLE",
            "message": "当前 Tableau MCP 未暴露自然语言查询工具。",
            "structured_error": {
                "error_code": "MCP_NL_TOOL_UNAVAILABLE",
                "message": "当前 Tableau MCP 未暴露自然语言查询工具。",
            },
            "queryspec_fallback": {"fallback_trace_event": "FALLBACK_TRIGGERED"},
            "diagnostics": {
                "mcp_tool_count": 3,
                "dynamic_column_engine_shadow": {"authoritative": False},
            },
        },
    )

    response_data = renderer_input["response_data"]
    assert response_data["error_code"] == "MCP_NL_TOOL_UNAVAILABLE"
    assert response_data["structured_error"]["error_code"] == "MCP_NL_TOOL_UNAVAILABLE"
    assert response_data["diagnostics"] == {"mcp_tool_count": 3}
    serialized = json.dumps(renderer_input, ensure_ascii=False)
    assert "queryspec_fallback" not in serialized
    assert "FALLBACK_TRIGGERED" not in serialized
    assert "dynamic_column_engine_shadow" not in serialized


def test_table_display_preserves_returned_business_field_names():
    schema = infer_table_display_schema(
        ["SUM(销售额)", "COUNTD(客户名称)", "利润率"],
        [[100, 2, "25%"]],
        metric_names=["利润率", "不存在的规划指标"],
    )

    assert [column["key"] for column in schema["columns"]] == ["SUM(销售额)", "COUNTD(客户名称)", "利润率"]
    assert [column["label"] for column in schema["columns"]] == ["SUM(销售额)", "COUNTD(客户名称)", "利润率"]
    assert "客户数" not in json.dumps(schema, ensure_ascii=False)


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


def test_generic_set_difference_response_data_uses_only_returned_dimension_values():
    response_data = build_set_difference_response_data(
        target_dimension="entity_key",
        universe_result={
            "fields": ["entity_key"],
            "rows": [["alpha"], ["beta"], ["gamma"], ["beta"]],
        },
        occurred_result={
            "fields": ["entity_key"],
            "rows": [["beta"], ["not_in_universe"]],
        },
        datasource_name="generic source",
        datasource_luid="ds-generic",
        fallback_detail={"fallback_trace_event": "FALLBACK_TRIGGERED", "fallback_reason": "proxy_unanswered"},
    )

    assert response_data["fields"] == ["entity_key"]
    assert response_data["rows"] == [["alpha"], ["gamma"]]
    assert response_data["operator"] == "set_difference"
    assert response_data["chain_mode"] == SET_DIFFERENCE_MCP_FALLBACK_CHAIN_MODE
    assert response_data["diagnostics"]["universe_count"] == 3
    assert response_data["diagnostics"]["occurred_count"] == 2
    assert response_data["diagnostics"]["difference_count"] == 2
    assert response_data["fallback_trace_event"] == "FALLBACK_TRIGGERED"
    assert response_data["table_display"]["columns"][0]["key"] == "entity_key"


def test_build_set_difference_mcp_query_args_is_generic_and_clamped():
    args = build_set_difference_mcp_query_args(
        datasource_luid="ds-generic",
        target_dimension="entity_key",
        universe_filters=[{"field": {"fieldCaption": "scope_key"}, "filterType": "SET", "values": ["all"]}],
        occurred_filters=[{"field": {"fieldCaption": "period_key"}, "filterType": "SET", "values": ["current"]}],
        limit=500,
    )

    assert list(args) == ["universe_keys", "occurred_keys"]
    assert args["universe_keys"]["query"]["fields"] == [{"fieldCaption": "entity_key"}]
    assert args["occurred_keys"]["query"]["fields"] == [{"fieldCaption": "entity_key"}]
    assert args["universe_keys"]["query"]["filters"][0]["field"]["fieldCaption"] == "scope_key"
    assert args["occurred_keys"]["query"]["filters"][0]["field"]["fieldCaption"] == "period_key"
    assert args["universe_keys"]["limit"] == 100
    assert args["occurred_keys"]["limit"] == 100


@pytest.mark.asyncio
async def test_set_difference_mcp_fallback_routes_queries_through_guardrail_and_returns_one_column():
    executed_args = []

    async def _execute(args, context):
        executed_args.append(args)
        assert args["query"]["fields"] == [{"fieldCaption": "entity_key"}]
        if len(executed_args) == 1:
            return {"fields": ["entity_key"], "rows": [["alpha"], ["beta"], ["gamma"]]}
        return {"fields": ["entity_key"], "rows": [["beta"]]}

    events = [
        event
        async for event in run_set_difference_mcp_fallback(
            question="Which entity keys are missing from the current period?",
            context=ToolContext(session_id="s1", user_id=1, connection_id=2, trace_id="trace-setdiff"),
            intent_result=IntentClassification(intent="set_difference", confidence=0.9, route_reason="missing_record"),
            datasource={"name": "generic source", "luid": "ds-generic"},
            queryable_fields=["entity_key", "period_key"],
            target_dimension="entity_key",
            occurred_filters=[
                {"field": {"fieldCaption": "period_key"}, "filterType": "SET", "values": ["current"]}
            ],
            reason="proxy_unanswered",
            original_error={"error": "direct_proxy_cannot_answer_set_difference"},
            execute=_execute,
        )
    ]

    fallback_event = next(
        event
        for event in events
        if event.type == "tool_result" and event.content.get("tool") == "set_difference_mcp_fallback"
    )
    guardrail_events = [
        event
        for event in events
        if event.type == "tool_result" and event.content.get("tool") == "mcp_args_guardrail"
    ]
    final_event = next(
        event
        for event in events
        if event.type == "tool_result" and event.content.get("tool") == "set_difference_operator"
    )
    guardrail_result_indices = [
        index
        for index, event in enumerate(events)
        if event.type == "tool_result" and event.content.get("tool") == "mcp_args_guardrail"
    ]
    tableau_call_indices = [
        index
        for index, event in enumerate(events)
        if event.type == "tool_call" and event.content.get("tool") == "tableau_mcp"
    ]

    assert fallback_event.content["result"]["event"] == "FALLBACK_TRIGGERED"
    assert [event.content["result"]["event"] for event in guardrail_events] == [
        "MCP_ARGS_GUARDRAIL_PASS",
        "MCP_ARGS_GUARDRAIL_PASS",
    ]
    assert guardrail_result_indices[0] < tableau_call_indices[0]
    assert guardrail_result_indices[1] < tableau_call_indices[1]
    assert len(executed_args) == 2
    response_data = final_event.content["result"]["data"]
    assert response_data["queryspec_used"] is False
    assert response_data["fields"] == ["entity_key"]
    assert response_data["rows"] == [["alpha"], ["gamma"]]
    assert response_data["controlled_fallback"]["fallback_reason"] == "proxy_unanswered"
    assert response_data["mcp_steps"]["universe_keys"]["mcp_args_guardrail"]["decision"] == "allow"
    assert response_data["mcp_steps"]["occurred_keys"]["mcp_args_guardrail"]["decision"] == "allow"
    assert events[-1].type == "answer"


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


class _BadQuerySpecThenMcpArgsLLM:
    async def complete(self, *, prompt, system=None, timeout=None, purpose=None):
        if purpose == "data_agent_queryspec":
            return {"content": "无法生成 JSON"}
        if purpose == "data_agent_mcp_proxy_args":
            return {
                "content": json.dumps(
                    {
                        "datasourceLuid": "ds-1",
                        "query": {"fields": [{"fieldCaption": "销售额", "function": "SUM"}]},
                        "limit": 100,
                    },
                    ensure_ascii=False,
                )
            }
        if purpose == "data_agent_answer":
            return {"content": ""}
        raise AssertionError(f"unexpected LLM purpose: {purpose}")


class _ValidQuerySpecThenMcpArgsLLM:
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
                    "limit": 100,
                    "answer_contract": {"must_include": ["销售额"], "forbid": ["猜测原因"]},
                }, ensure_ascii=False)
            }
        if purpose == "data_agent_mcp_proxy_args":
            return {
                "content": json.dumps(
                    {
                        "datasourceLuid": "ds-1",
                        "query": {"fields": [{"fieldCaption": "销售额", "function": "SUM"}]},
                        "limit": 100,
                    },
                    ensure_ascii=False,
                )
            }
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
                    "filters": [],
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
                    "filters": [],
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
                    "filters": [],
                    "limit": 100,
                    "answer_contract": {"must_include": ["销售额", "子类别"], "forbid": ["明细列表"]},
                }, ensure_ascii=False)
            }
        if purpose == "data_agent_answer":
            return {"content": ""}
        raise AssertionError(f"unexpected LLM purpose: {purpose}")


@pytest.mark.asyncio
async def test_mcp_first_path_surfaces_missing_nl_tool_without_queryspec_fallback(monkeypatch):
    monkeypatch.setenv("DATA_AGENT_QUERYSPEC_FALLBACK_ENABLED", "true")
    _patch_host(monkeypatch, catalog_fail=True)

    events = [
        event
        async for event in mcp_first_main.run_mcp_first_main_path(
            question="总销售额是多少？",
            context=ToolContext(session_id="s1", user_id=1, connection_id=2, trace_id="trace-1"),
            intent_result=IntentClassification(intent="aggregate", confidence=0.9, route_reason="metric_keyword"),
            analysis_context=_selected_datasource_context(),
            llm_service=_BadQuerySpecLLM(),
        )
    ]

    _assert_no_query_planning_or_fallback(events)
    assert _tool_names(events) == ["context_resolver", "context_resolver", "mcp_host_catalog", "mcp_host_catalog"]
    assert events[-1].type == "error"
    assert events[-1].content["fallback_type"] == "mcp_nl_passthrough_unavailable"
    assert events[-1].content["error_code"] == "MCP_HOST_CATALOG_UNAVAILABLE"
    assert events[-1].content["trace_id"] == "trace-1"


@pytest.mark.asyncio
async def test_mcp_first_path_does_not_query_plan_when_fallback_disabled(monkeypatch):
    monkeypatch.delenv("DATA_AGENT_QUERYSPEC_FALLBACK_ENABLED", raising=False)
    monkeypatch.setenv("DATA_AGENT_QUERYSPEC_MCP_FALLBACK_ENABLED", "false")
    _patch_host(monkeypatch, catalog_fail=True)

    events = [
        event
        async for event in mcp_first_main.run_mcp_first_main_path(
            question="总销售额是多少？",
            context=ToolContext(session_id="s1", user_id=1, connection_id=2, trace_id="trace-1"),
            intent_result=IntentClassification(intent="aggregate", confidence=0.9, route_reason="metric_keyword"),
            analysis_context=_selected_datasource_context(),
            llm_service=_BadQuerySpecLLM(),
        )
    ]

    _assert_no_query_planning_or_fallback(events)
    assert events[-1].type == "error"
    assert events[-1].content["fallback_type"] == "mcp_nl_passthrough_unavailable"
    assert events[-1].content["error_code"] == "MCP_HOST_CATALOG_UNAVAILABLE"
    assert events[-1].content["trace_id"] == "trace-1"
    assert events[-1].content["controlled_chain"]["detail"]["reason"] == "MCP_HOST_CATALOG_UNAVAILABLE"


@pytest.mark.asyncio
async def test_mcp_first_path_ignores_semantic_queryspec_llm_when_nl_tool_missing(monkeypatch):
    monkeypatch.delenv("DATA_AGENT_QUERYSPEC_FALLBACK_ENABLED", raising=False)
    monkeypatch.setenv("DATA_AGENT_QUERYSPEC_MCP_FALLBACK_ENABLED", "false")
    _patch_host(monkeypatch, catalog_fail=True)

    events = [
        event
        async for event in mcp_first_main.run_mcp_first_main_path(
            question="总利润是多少？",
            context=ToolContext(session_id="s1", user_id=1, connection_id=2, trace_id="trace-semantic"),
            intent_result=IntentClassification(intent="aggregate", confidence=0.9, route_reason="metric_keyword"),
            analysis_context=_selected_datasource_context(),
            llm_service=_MissingMetricQuerySpecLLM(),
        )
    ]

    _assert_no_query_planning_or_fallback(events)
    assert events[-1].type == "error"
    assert events[-1].content["fallback_type"] == "mcp_nl_passthrough_unavailable"
    assert events[-1].content["error_code"] == "MCP_HOST_CATALOG_UNAVAILABLE"
    assert events[-1].content["trace_id"] == "trace-semantic"


@pytest.mark.asyncio
async def test_mcp_first_path_ignores_operator_mismatch_queryspec_when_nl_tool_missing(monkeypatch):
    monkeypatch.delenv("DATA_AGENT_QUERYSPEC_FALLBACK_ENABLED", raising=False)
    monkeypatch.setenv("DATA_AGENT_QUERYSPEC_MCP_FALLBACK_ENABLED", "false")
    _patch_host(monkeypatch, catalog_fail=True)

    events = [
        event
        async for event in mcp_first_main.run_mcp_first_main_path(
            question="2025 年没有销售记录的子类别有哪些？",
            context=ToolContext(session_id="s1", user_id=1, connection_id=2, trace_id="trace-mismatch"),
            intent_result=IntentClassification(intent="set_difference", confidence=0.9, route_reason="missing_record"),
            analysis_context=_selected_datasource_context(),
            llm_service=_AggregateForSetDifferenceLLM(),
        )
    ]

    _assert_no_query_planning_or_fallback(events)
    assert events[-1].type == "error"
    assert events[-1].content["fallback_type"] == "mcp_nl_passthrough_unavailable"
    assert events[-1].content["error_code"] == "MCP_HOST_CATALOG_UNAVAILABLE"
    assert events[-1].content["controlled_chain"]["detail"]["reason"] == "MCP_HOST_CATALOG_UNAVAILABLE"


@pytest.mark.asyncio
async def test_mcp_first_path_surfaces_mcp_attempt_failure_without_queryspec_fallback(monkeypatch):
    monkeypatch.delenv("DATA_AGENT_QUERYSPEC_FALLBACK_ENABLED", raising=False)
    monkeypatch.delenv("DATA_AGENT_QUERYSPEC_MCP_FALLBACK_ENABLED", raising=False)

    async def _force_mcp_host_failure(**kwargs):
        return mcp_first_main._McpMainAttempt(
            success=False,
            events=[],
            reason="test_force_mcp_error",
            error_code="MCP_MAIN_TEST_BYPASS",
            original_error={"reason": "test_force_mcp_error"},
            message="MCP 测试错误。",
            user_hint="请检查 MCP。",
        )

    monkeypatch.setattr(mcp_first_main, "_run_mcp_host_route", _force_mcp_host_failure)

    events = [
        event
        async for event in mcp_first_main.run_mcp_first_main_path(
            question="总销售额是多少？",
            context=ToolContext(session_id="s1", user_id=1, connection_id=2, trace_id="trace-mcp-fallback"),
            intent_result=IntentClassification(intent="aggregate", confidence=0.9, route_reason="metric_keyword"),
            analysis_context=_selected_datasource_context(),
            llm_service=_BadQuerySpecThenMcpArgsLLM(),
        )
    ]

    _assert_no_query_planning_or_fallback(events)
    assert events[-1].type == "error"
    assert events[-1].content["fallback_type"] == "mcp_nl_passthrough_unavailable"
    assert events[-1].content["error_code"] == "MCP_MAIN_TEST_BYPASS"
    assert events[-1].content["controlled_chain"]["detail"]["reason"] == "test_force_mcp_error"


@pytest.mark.asyncio
async def test_mcp_first_path_surfaces_mcp_nl_execution_failure_without_queryspec_fallback(monkeypatch):
    monkeypatch.delenv("DATA_AGENT_QUERYSPEC_FALLBACK_ENABLED", raising=False)
    monkeypatch.delenv("DATA_AGENT_QUERYSPEC_MCP_FALLBACK_ENABLED", raising=False)
    _patch_host(
        monkeypatch,
        query_error={
            "success": False,
            "error_code": "MCP_HOST_TOOL_EXECUTION_FAILED",
            "error": "mcp execution failed",
        },
    )

    events = [
        event
        async for event in mcp_first_main.run_mcp_first_main_path(
            question="总销售额是多少？",
            context=ToolContext(session_id="s1", user_id=1, connection_id=2, trace_id="trace-exec-fallback"),
            intent_result=IntentClassification(intent="aggregate", confidence=0.9, route_reason="metric_keyword"),
            analysis_context=_selected_datasource_context(),
            llm_service=_ValidQuerySpecThenMcpArgsLLM(),
        )
    ]

    _assert_no_query_planning_or_fallback(events)
    assert "tableau_mcp" in _tool_names(events)
    assert events[-1].type == "error"
    assert events[-1].content["fallback_type"] == "mcp_nl_passthrough_unavailable"
    assert events[-1].content["error_code"] == "MCP_HOST_TOOL_EXECUTION_FAILED"
    assert events[-1].content["controlled_chain"]["detail"]["reason"] == "mcp_tool_execution_failed"


@pytest.mark.asyncio
async def test_mcp_first_path_restates_mcp_nl_response_without_llm_answer(monkeypatch):
    _patch_host(monkeypatch, query_result={"response_data": {"fields": ["Metric A"], "rows": [[100]]}})

    events = [
        event
        async for event in mcp_first_main.run_mcp_first_main_path(
            question="整体销售额是多少？",
            context=ToolContext(session_id="s1", user_id=1, connection_id=2, trace_id="trace-1"),
            intent_result=IntentClassification(intent="aggregate", confidence=0.9, route_reason="metric_keyword"),
            analysis_context=_selected_datasource_context(),
            llm_service=_HallucinatedAnswerLLM(),
        )
    ]

    _assert_no_query_planning_or_fallback(events)
    tableau_event = next(
        event
        for event in events
        if event.type == "tool_result" and isinstance(event.content, dict) and event.content.get("tool") == "mcp_host_final_response"
    )
    response_data = tableau_event.content["result"]["data"]
    assert response_data["fields"] == ["Metric A"]
    assert response_data["rows"] == [[100]]
    assert response_data["mcp_host"] is True
    assert response_data["table_display"]["columns"][0]["label"] == "Metric A"
    assert events[-1].type == "answer"
    assert "无法直接回答" not in events[-1].content
    assert events[-1].content == "查询已完成，返回 1 行结果。"


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
    assert data["table_display"]["columns"][1]["label"] == "SUM(销售额)"
    assert data["table_display"]["columns"][1]["align"] == "right"
    answer = mcp_first_main._render_deterministic_answer(data, spec)
    assert "子类别" in answer
    assert "利润率" not in answer

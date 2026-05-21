"""Tests for MCP-first controlled Data Agent main path."""

import json

import pytest

pytest.skip(
    "TDE-06/TDE-09: legacy mcp_first_main private/path tests are decommissioned; "
    "deletion target is removal of mcp_first_main production reachability under TDE-24/TDE-30. "
    "Business coverage is migrating to mcp_proxy_main top-level tests.",
    allow_module_level=True,
)

from services.data_agent import mcp_first_main, mcp_proxy_main
from services.data_agent.intent_classifier import IntentClassification
from services.data_agent.mcp_first_main import run_mcp_first_main_path
from services.data_agent.queryspec import QuerySpec
from services.data_agent.tool_base import ToolContext

pytestmark = pytest.mark.skip_db


class _FakeLLM:
    async def complete(self, *, prompt, system=None, timeout=None, purpose=None):
        if purpose == "data_agent_mcp_proxy_args":
            return {
                "content": json.dumps({
                    "datasourceLuid": "ds-1",
                    "query": {"fields": [{"fieldCaption": "销售额", "function": "SUM"}], "filters": []},
                    "limit": 100,
                }, ensure_ascii=False)
            }
        if purpose == "data_agent_queryspec":
            raise AssertionError("QuerySpec must not run when MCP main route succeeds")
        raise AssertionError(f"unexpected LLM purpose: {purpose}")


class _MissingDerivedMetricLLM:
    async def complete(self, *, prompt, system=None, timeout=None, purpose=None):
        if purpose == "data_agent_mcp_proxy_args":
            return {
                "content": json.dumps({
                    "datasourceLuid": "ds-1",
                    "query": {
                        "fields": [
                            {"fieldCaption": "子类别"},
                            {"fieldCaption": "销售额", "function": "SUM", "sortDirection": "DESC"},
                            {"fieldCaption": "利润", "function": "SUM"},
                            {"fieldCaption": "利润率"},
                        ],
                        "filters": [],
                    },
                    "limit": 100,
                }, ensure_ascii=False)
            }
        if purpose == "data_agent_queryspec":
            raise AssertionError("QuerySpec must not run when MCP main route succeeds")
        raise AssertionError(f"unexpected LLM purpose: {purpose}")


class _McpArgsOnlyLLM:
    def __init__(self, payload):
        self.payload = payload

    async def complete(self, *, prompt, system=None, timeout=None, purpose=None):
        if purpose == "data_agent_mcp_proxy_args":
            return {"content": json.dumps(self.payload, ensure_ascii=False)}
        if purpose == "data_agent_queryspec":
            raise AssertionError("QuerySpec must not run when MCP main route succeeds")
        raise AssertionError(f"unexpected LLM purpose: {purpose}")


class _BadMcpArgsThenQuerySpecLLM:
    async def complete(self, *, prompt, system=None, timeout=None, purpose=None):
        if purpose == "data_agent_mcp_proxy_args":
            return {"content": "not-json"}
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


def _intent(intent: str = "aggregate") -> IntentClassification:
    return IntentClassification(intent=intent, confidence=0.9, route_reason="test")


def _tool_names(events):
    return [
        event.content["tool"]
        for event in events
        if event.type in {"tool_call", "tool_result"} and isinstance(event.content, dict)
    ]


def _selected_datasource_context(trace_id: str = "trace-1") -> ToolContext:
    context = ToolContext(session_id="s1", user_id=1, connection_id=2, trace_id=trace_id)
    context.datasource_luid = "ds-1"
    context.datasource_name = "测试数据源"
    return context


def _patch_nl_tool(monkeypatch, *, result=None):
    calls = []

    async def _discover(context):
        return "ask-datasource"

    async def _call(tool_name, arguments, context):
        calls.append({"tool_name": tool_name, "arguments": dict(arguments), "context": context})
        return result or {"fields": ["SUM(销售额)"], "rows": [[100]]}

    monkeypatch.setattr(mcp_first_main, "_discover_mcp_nl_query_tool", _discover)
    monkeypatch.setattr(mcp_first_main, "_call_mcp_nl_query_tool", _call)
    return calls


def _patch_missing_nl_tool(monkeypatch):
    async def _discover(context):
        return None

    async def _unexpected_call(*args, **kwargs):
        raise AssertionError("MCP NL tool call must not run when no NL tool is available")

    monkeypatch.setattr(mcp_first_main, "_discover_mcp_nl_query_tool", _discover)
    monkeypatch.setattr(mcp_first_main, "_call_mcp_nl_query_tool", _unexpected_call)


class _FakeHostCatalog:
    async def list_tools(self):
        return {
            "tools": [
                {
                    "name": "get-datasource-metadata",
                    "inputSchema": {
                        "type": "object",
                        "required": ["datasourceLuid"],
                        "properties": {"datasourceLuid": {"type": "string"}},
                    },
                },
                {
                    "name": "query-datasource",
                    "inputSchema": {
                        "type": "object",
                        "required": ["datasourceLuid", "query"],
                        "properties": {
                            "datasourceLuid": {"type": "string"},
                            "query": {"type": "object"},
                            "limit": {"type": "integer"},
                        },
                    },
                },
            ]
        }


class _FakeHostExecutor:
    def __init__(self, *, query_results=None, query_errors=None, metadata_result=None):
        self.calls = []
        self.query_results = list(query_results or [{"fields": ["Metric A"], "rows": [[100]]}])
        self.query_errors = list(query_errors or [])
        self.metadata_result = metadata_result or {"fields": [{"name": "Metric A", "dataType": "REAL"}]}

    async def execute_tool(self, tool_name, arguments, context):
        self.calls.append({"tool_name": tool_name, "arguments": dict(arguments), "context": context})
        if tool_name == "get-datasource-metadata":
            return self.metadata_result
        if self.query_errors:
            return self.query_errors.pop(0)
        if self.query_results:
            return self.query_results.pop(0)
        return {"fields": ["Metric A"], "rows": [[100]]}


class _FakeHostPlanner:
    def __init__(self, actions):
        self.actions = list(actions)
        self.calls = []

    async def plan(self, **kwargs):
        self.calls.append(kwargs)
        if not self.actions:
            raise AssertionError("unexpected extra MCP Host planner call")
        action = self.actions.pop(0)
        if isinstance(action, Exception):
            raise action
        return action


def _query_tool_call(limit=100):
    return {
        "action": "tool_call",
        "tool_call": {
            "tool": "query-datasource",
            "arguments": {
                "datasourceLuid": "ds-1",
                "query": {"fields": [{"fieldCaption": "Metric A", "function": "SUM"}], "filters": []},
                "limit": limit,
            },
        },
    }


def _final_action():
    return {"action": "final", "answer": "Use response_data only."}


def _patch_host(monkeypatch, *, actions=None, query_results=None, query_errors=None, metadata_result=None):
    executor = _FakeHostExecutor(
        query_results=query_results,
        query_errors=query_errors,
        metadata_result=metadata_result,
    )
    planner = _FakeHostPlanner(actions or [_query_tool_call(), _final_action()])
    catalog = _FakeHostCatalog()

    async def _load_components(**kwargs):
        return mcp_first_main._McpHostComponents(catalog=catalog, executor=executor, planner=planner)

    monkeypatch.setattr(mcp_first_main, "_load_mcp_host_components", _load_components)
    return executor, planner


def _forbidden_main_path_markers():
    return {
        "mcp_nl_tool_discovery",
        "tableau_mcp_nl",
        "llm_mcp_args",
        "mcp_args_guardrail",
        "llm_queryspec",
        "llm_queryspec_repair",
        "queryspec_fallback",
        "queryspec_validator",
        "mcp_main_queryspec_fallback",
        "queryspec_mcp_fallback",
    }


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


def test_normalize_queryspec_converts_period_calculation_dimension_to_time_field():
    spec = QuerySpec.model_validate({
        "intent": "aggregate",
        "operator": "aggregate",
        "metrics": [{"field": "Amount", "aggregation": "SUM"}],
        "dimensions": ["Segment", "Ship Year"],
        "filters": [],
    })

    normalized = mcp_first_main._normalize_queryspec_for_mcp(
        spec,
        "continue by each year",
        ["Segment", "Ship Year", "Ship Date", "Amount"],
        {
            "metadata_fields": [
                {"name": "Ship Year", "dataType": "STRING", "formula": "STR(YEAR([Ship Date]))"},
                {"name": "Ship Date", "dataType": "DATE"},
                {"name": "Segment", "dataType": "STRING"},
                {"name": "Amount", "dataType": "REAL"},
            ]
        },
    )

    assert normalized.dimensions == ["Segment"]
    assert normalized.time is not None
    assert normalized.time.field == "Ship Date"
    assert normalized.time.grain == "YEAR"


def test_normalize_queryspec_converts_period_calculation_filter_time_field():
    spec = QuerySpec.model_validate({
        "intent": "set_difference",
        "operator": "set_difference",
        "metrics": [],
        "dimensions": ["Segment"],
        "universe": {"target_dimension": "Segment", "filters": []},
        "occurred": {
            "target_dimension": "Segment",
            "filters": [],
            "time": {"field": "Ship Year", "grain": "YEAR", "range": {"type": "year", "value": 2025}},
        },
    })

    normalized = mcp_first_main._normalize_queryspec_for_mcp(
        spec,
        "segments with no records in 2025",
        ["Segment", "Ship Year", "Ship Date"],
        {
            "metadata_fields": [
                {"name": "Ship Year", "dataType": "STRING", "formula": "STR(YEAR([Ship Date]))"},
                {"name": "Ship Date", "dataType": "DATE"},
                {"name": "Segment", "dataType": "STRING"},
            ]
        },
    )

    assert normalized.occurred is not None
    assert normalized.occurred.time is not None
    assert normalized.occurred.time.field == "Ship Date"
    assert normalized.occurred.time.grain == "YEAR"


def test_normalize_queryspec_inherits_context_dimension_for_followup_split():
    spec = QuerySpec.model_validate({
        "intent": "aggregate",
        "operator": "aggregate",
        "time": {"field": "Ship Year", "grain": "YEAR", "range": {"type": "year", "value": "ALL"}},
        "metrics": [{"field": "Amount", "aggregation": "SUM"}],
        "dimensions": ["Ship Year"],
        "filters": [],
    })

    normalized = mcp_first_main._normalize_queryspec_for_mcp(
        spec,
        "继续按每个年份拆分",
        ["Segment", "Ship Year", "Ship Date", "Amount", "Ratio"],
        {
            "metadata_fields": [
                {"name": "Ship Year", "dataType": "STRING", "role": "DIMENSION", "formula": "STR(YEAR([Ship Date]))"},
                {"name": "Ship Date", "dataType": "DATE", "role": "DIMENSION"},
                {"name": "Segment", "dataType": "STRING", "role": "DIMENSION"},
                {"name": "Amount", "dataType": "REAL", "role": "MEASURE"},
                {"name": "Ratio", "dataType": "REAL", "role": "MEASURE"},
            ]
        },
        {"dimension_names": ["Segment", "Ratio"], "metric_names": ["Amount"]},
    )

    assert normalized.time is not None
    assert normalized.time.field == "Ship Date"
    assert normalized.time.grain == "YEAR"
    assert normalized.dimensions == ["Segment"]


@pytest.mark.asyncio
async def test_mcp_first_main_path_uses_mcp_host_loop(monkeypatch):
    executor, planner = _patch_host(monkeypatch)

    events = [
        event
        async for event in run_mcp_first_main_path(
            question="overall Metric A",
            context=_selected_datasource_context(),
            intent_result=IntentClassification(intent="aggregate", confidence=0.9, route_reason="metric_keyword"),
            llm_service=_FakeLLM(),
        )
    ]

    tool_names = _tool_names(events)
    assert "mcp_host_catalog" in tool_names
    assert "mcp_host_planner" in tool_names
    assert "tableau_mcp" in tool_names
    assert "mcp_host_final_response" in tool_names
    assert _forbidden_main_path_markers().isdisjoint(tool_names)
    assert [call["tool_name"] for call in executor.calls] == ["get-datasource-metadata", "query-datasource"]
    assert executor.calls[0]["arguments"] == {"datasourceLuid": "ds-1"}
    assert planner.calls[0]["datasource"] == {"name": "测试数据源", "luid": "ds-1"}
    assert planner.calls[0]["metadata"] == {"fields": [{"name": "Metric A", "dataType": "REAL"}]}

    response_data = next(
        event.content["result"]["data"]
        for event in events
        if event.type == "tool_result"
        and isinstance(event.content, dict)
        and event.content.get("tool") == "mcp_host_final_response"
    )
    assert response_data["main_chain_mode"] == "mcp_first_mcp_main"
    assert response_data["mcp_host"] is True
    assert response_data["mcp_tool"] == "query-datasource"
    assert response_data["fields"] == ["Metric A"]
    assert response_data["rows"] == [[100]]
    assert response_data["table_display"]["columns"][0]["semantic_type"] == "metric"
    assert events[-1].type == "answer"
    assert events[-1].content == "查询已完成，返回 1 行结果。"


@pytest.mark.asyncio
async def test_mcp_first_main_preserves_mcp_response_data_without_extra_aggregation(monkeypatch):
    _patch_host(monkeypatch, query_results=[{"fields": ["Dimension A", "Metric A", "Metric B", "Rate A"], "rows": [["x", 200, 50, "25.00%"]]}])

    events = [
        event
        async for event in run_mcp_first_main_path(
            question="group Metric A Metric B and Rate A by Dimension A",
            context=_selected_datasource_context("trace-derived"),
            intent_result=IntentClassification(intent="aggregate", confidence=0.9, route_reason="metric_keyword"),
            llm_service=_MissingDerivedMetricLLM(),
        )
    ]

    tool_names = _tool_names(events)
    assert _forbidden_main_path_markers().isdisjoint(tool_names)
    response_data = next(
        event.content["result"]["data"]
        for event in events
        if event.type == "tool_result"
        and isinstance(event.content, dict)
        and event.content.get("tool") == "mcp_host_final_response"
    )
    assert response_data["fields"] == ["Dimension A", "Metric A", "Metric B", "Rate A"]
    assert response_data["rows"] == [["x", 200, 50, "25.00%"]]
    assert events[-1].type == "answer"


@pytest.mark.asyncio
async def test_q1_q4_like_questions_use_host_events_without_queryspec_markers(monkeypatch):
    for index, question in enumerate(
        [
            "overall Metric A",
            "Metric A trend",
            "Metric A by Dimension A",
            "continue by year",
        ]
    ):
        _patch_host(monkeypatch)
        events = [
            event
            async for event in run_mcp_first_main_path(
                question=question,
                context=_selected_datasource_context(f"trace-q{index + 1}"),
                intent_result=IntentClassification(intent="aggregate", confidence=0.9, route_reason="host_test"),
                analysis_context={"response_data": {"fields": ["Metric A"], "rows": [[100]]}} if index == 3 else None,
                llm_service=_McpArgsOnlyLLM({}),
            )
        ]
        tool_names = _tool_names(events)
        assert {"mcp_host_catalog", "mcp_host_planner", "tableau_mcp", "mcp_host_final_response"}.issubset(set(tool_names))
        assert _forbidden_main_path_markers().isdisjoint(tool_names)
        assert events[-1].type == "answer"


@pytest.mark.asyncio
async def test_mcp_host_canonicalizes_simple_calculated_field_labels(monkeypatch):
    metadata = {
        "fields": [
            {
                "name": "Customer Count",
                "columnClass": "CALCULATION",
                "role": "MEASURE",
                "formula": "COUNTD([Customer Name])",
            },
            {
                "name": "Ship Year",
                "columnClass": "CALCULATION",
                "role": "DIMENSION",
                "formula": "STR(YEAR([Ship Date]))",
            },
        ]
    }
    _patch_host(
        monkeypatch,
        metadata_result=metadata,
        query_results=[
            {
                "data": [
                    {"Ship Year": "2024", "Customer Count": 7},
                ]
            }
        ],
    )

    events = [
        event
        async for event in run_mcp_first_main_path(
            question="customer count by year",
            context=_selected_datasource_context("trace-canonical"),
            intent_result=IntentClassification(intent="aggregate", confidence=0.9, route_reason="host_test"),
            llm_service=_McpArgsOnlyLLM({}),
        )
    ]

    response_data = next(
        event.content["result"]["data"]
        for event in events
        if event.type == "tool_result"
        and isinstance(event.content, dict)
        and event.content.get("tool") == "mcp_host_final_response"
    )
    assert response_data["fields"] == ["YEAR(Ship Date)", "COUNTD(Customer Name)"]
    assert response_data["rows"] == [[2024, 7]]
    assert response_data["data"] == [{"YEAR(Ship Date)": 2024, "COUNTD(Customer Name)": 7}]


@pytest.mark.asyncio
async def test_mcp_host_followup_inherits_previous_dimensions_and_drops_invented_set_filters(monkeypatch):
    metadata = {
        "fields": [
            {"name": "Dimension A", "role": "DIMENSION"},
            {"name": "Year A", "role": "DIMENSION"},
            {"name": "Metric A", "role": "MEASURE"},
            {"name": "Rate A", "role": "MEASURE", "columnClass": "CALCULATION", "formula": "SUM([Metric A])/SUM([Metric B])"},
        ]
    }
    executor, _planner = _patch_host(
        monkeypatch,
        metadata_result=metadata,
        actions=[
            {
                "action": "tool_call",
                "tool_call": {
                    "tool": "query-datasource",
                    "arguments": {
                        "datasourceLuid": "ds-1",
                        "query": {
                            "fields": [
                                {"fieldCaption": "Year A"},
                                {"fieldCaption": "Metric A", "function": "SUM"},
                                {"fieldCaption": "logical_table_123", "function": "COUNT"},
                            ],
                            "filters": [
                                {
                                    "field": {"fieldCaption": "Year A"},
                                    "filterType": "SET",
                                    "values": ["2021", "2022"],
                                }
                            ],
                        },
                    },
                },
            }
        ],
    )

    events = [
        event
        async for event in run_mcp_first_main_path(
            question="continue breakdown by year",
            context=_selected_datasource_context("trace-followup"),
            intent_result=IntentClassification(intent="aggregate", confidence=0.9, route_reason="host_test"),
            analysis_context={
                "response_data": {
                    "fields": ["Dimension A", "SUM(Metric A)", "Rate A"],
                    "rows": [["x", 100, 0.1]],
                }
            },
            llm_service=_McpArgsOnlyLLM({}),
        )
    ]

    query_call = next(call for call in executor.calls if call["tool_name"] == "query-datasource")
    assert query_call["arguments"]["query"]["fields"] == [
        {"fieldCaption": "Dimension A"},
        {"fieldCaption": "Year A"},
        {"fieldCaption": "Metric A", "function": "SUM"},
    ]
    assert query_call["arguments"]["query"]["filters"] == []
    assert events[-1].type == "answer"


@pytest.mark.asyncio
async def test_mcp_host_retries_once_after_invalid_planner_output(monkeypatch):
    executor, planner = _patch_host(
        monkeypatch,
        actions=[ValueError("invalid action"), _query_tool_call()],
    )

    events = [
        event
        async for event in run_mcp_first_main_path(
            question="overall Metric A",
            context=_selected_datasource_context("trace-planner-repair"),
            intent_result=IntentClassification(intent="aggregate", confidence=0.9, route_reason="host_test"),
            llm_service=_McpArgsOnlyLLM({}),
        )
    ]

    tool_names = _tool_names(events)
    assert "mcp_host_repair" in tool_names
    assert [call["tool_name"] for call in executor.calls] == ["get-datasource-metadata", "query-datasource"]
    assert len(planner.calls) == 2
    assert events[-1].type == "answer"


@pytest.mark.asyncio
async def test_mcp_host_followup_trend_inherits_previous_aggregate_metrics(monkeypatch):
    executor, _planner = _patch_host(
        monkeypatch,
        actions=[
            {
                "action": "tool_call",
                "tool_call": {
                    "tool": "query-datasource",
                    "arguments": {
                        "datasourceLuid": "ds-1",
                        "query": {
                            "fields": [
                                {"fieldCaption": "Year A"},
                                {"fieldCaption": "Metric A", "function": "SUM"},
                            ],
                        },
                    },
                },
            }
        ],
        metadata_result={
            "fields": [
                {"name": "Year A", "role": "DIMENSION"},
                {"name": "Metric A", "role": "MEASURE"},
                {"name": "Metric B", "role": "MEASURE"},
                {"name": "Customer Name", "role": "DIMENSION"},
            ]
        },
    )

    events = [
        event
        async for event in run_mcp_first_main_path(
            question="show these metrics trend by year",
            context=_selected_datasource_context("trace-metric-inherit"),
            intent_result=IntentClassification(intent="trend_condition", confidence=0.9, route_reason="host_test"),
            analysis_context={
                "response_data": {
                    "fields": ["SUM(Metric A)", "SUM(Metric B)", "COUNTD(Customer Name)"],
                    "rows": [[100, 30, 7]],
                }
            },
            llm_service=_McpArgsOnlyLLM({}),
        )
    ]

    query_call = next(call for call in executor.calls if call["tool_name"] == "query-datasource")
    assert query_call["arguments"]["query"]["fields"] == [
        {"fieldCaption": "Year A"},
        {"fieldCaption": "Metric A", "function": "SUM"},
        {"fieldCaption": "Metric B", "function": "SUM"},
        {"fieldCaption": "Customer Name", "function": "COUNTD"},
    ]
    assert events[-1].type == "answer"


@pytest.mark.asyncio
async def test_mcp_host_followup_trend_inherits_countd_metric_from_context_names(monkeypatch):
    executor, _planner = _patch_host(
        monkeypatch,
        actions=[
            {
                "action": "tool_call",
                "tool_call": {
                    "tool": "query-datasource",
                    "arguments": {
                        "datasourceLuid": "ds-1",
                        "query": {
                            "fields": [
                                {"fieldCaption": "Year A"},
                                {"fieldCaption": "Metric A", "function": "SUM"},
                                {"fieldCaption": "Metric B", "function": "SUM"},
                            ],
                        },
                    },
                },
            }
        ],
        metadata_result={
            "fields": [
                {"name": "Year A", "role": "DIMENSION"},
                {"name": "Metric A", "role": "MEASURE", "defaultAggregation": "SUM"},
                {"name": "Metric B", "role": "MEASURE", "defaultAggregation": "SUM"},
                {"name": "Entity A", "role": "DIMENSION"},
            ]
        },
    )

    events = [
        event
        async for event in run_mcp_first_main_path(
            question="show these metrics trend by year",
            context=_selected_datasource_context("trace-context-countd-inherit"),
            intent_result=IntentClassification(intent="trend_condition", confidence=0.9, route_reason="host_test"),
            analysis_context={
                "metric_names": ["Metric A", "Metric B", "Entity A"],
            },
            llm_service=_McpArgsOnlyLLM({}),
        )
    ]

    query_call = next(call for call in executor.calls if call["tool_name"] == "query-datasource")
    assert query_call["arguments"]["query"]["fields"] == [
        {"fieldCaption": "Year A"},
        {"fieldCaption": "Metric A", "function": "SUM"},
        {"fieldCaption": "Metric B", "function": "SUM"},
        {"fieldCaption": "Entity A", "function": "COUNTD"},
    ]
    assert events[-1].type == "answer"


@pytest.mark.asyncio
async def test_mcp_host_followup_final_without_query_uses_context_metrics(monkeypatch):
    executor, _planner = _patch_host(
        monkeypatch,
        actions=[
            {
                "action": "final",
                "response": "The referenced metric is ambiguous.",
            }
        ],
        metadata_result={
            "fields": [
                {
                    "name": "Year A",
                    "role": "DIMENSION",
                    "columnClass": "CALCULATION",
                    "formula": "STR(YEAR([Date A]))",
                },
                {"name": "Metric A", "role": "MEASURE", "defaultAggregation": "SUM"},
                {"name": "Metric B", "role": "MEASURE", "defaultAggregation": "SUM"},
                {"name": "Entity A", "role": "DIMENSION"},
            ]
        },
    )

    events = [
        event
        async for event in run_mcp_first_main_path(
            question="这个指标过去几年的趋势",
            context=_selected_datasource_context("trace-final-context-rescue"),
            intent_result=IntentClassification(intent="trend_condition", confidence=0.9, route_reason="host_test"),
            analysis_context={
                "metric_names": ["Metric A", "Metric B", "Entity A"],
            },
            llm_service=_McpArgsOnlyLLM({}),
        )
    ]

    query_call = next(call for call in executor.calls if call["tool_name"] == "query-datasource")
    assert query_call["arguments"]["query"]["fields"] == [
        {"fieldCaption": "Year A", "sortDirection": "ASC", "sortPriority": 1},
        {"fieldCaption": "Metric A", "function": "SUM"},
        {"fieldCaption": "Metric B", "function": "SUM"},
        {"fieldCaption": "Entity A", "function": "COUNTD"},
    ]
    assert events[-1].type == "answer"


@pytest.mark.asyncio
async def test_mcp_host_retries_transient_mcp_tool_error_once(monkeypatch):
    executor, _planner = _patch_host(
        monkeypatch,
        query_errors=[
            {
                "success": False,
                "error_code": "NLQ_006",
                "error": "Client network socket disconnected before secure TLS connection was established",
            }
        ],
    )

    events = [
        event
        async for event in run_mcp_first_main_path(
            question="overall Metric A",
            context=_selected_datasource_context("trace-transient-retry"),
            intent_result=IntentClassification(intent="aggregate", confidence=0.9, route_reason="host_test"),
            llm_service=_McpArgsOnlyLLM({}),
        )
    ]

    assert [call["tool_name"] for call in executor.calls] == [
        "get-datasource-metadata",
        "query-datasource",
        "query-datasource",
    ]
    assert "mcp_host_repair" in _tool_names(events)
    assert events[-1].type == "answer"


@pytest.mark.asyncio
async def test_mcp_host_uses_context_followup_rescue_when_planner_refuses(monkeypatch):
    executor, _planner = _patch_host(
        monkeypatch,
        actions=[
            ValueError("invalid action"),
            {"action": "repair_unavailable", "message": "missing metric"},
        ],
        metadata_result={
            "fields": [
                {
                    "name": "Year A",
                    "role": "DIMENSION",
                    "columnClass": "CALCULATION",
                    "formula": "STR(YEAR([Date A]))",
                },
                {"name": "Metric A", "role": "MEASURE", "defaultAggregation": "SUM"},
                {"name": "Metric B", "role": "MEASURE", "defaultAggregation": "SUM"},
                {"name": "Customer Name", "role": "DIMENSION"},
            ]
        },
    )

    events = [
        event
        async for event in run_mcp_first_main_path(
            question="这个指标过去几年的趋势",
            context=_selected_datasource_context("trace-context-rescue"),
            intent_result=IntentClassification(intent="trend_condition", confidence=0.9, route_reason="host_test"),
            analysis_context={
                "metric_names": ["Metric A", "Metric B", "Customer Name"],
                "response_data": {
                    "fields": ["SUM(Metric A)", "SUM(Metric B)", "COUNTD(Customer Name)"],
                    "rows": [[100, 30, 7]],
                },
            },
            llm_service=_McpArgsOnlyLLM({}),
        )
    ]

    query_call = next(call for call in executor.calls if call["tool_name"] == "query-datasource")
    assert query_call["arguments"]["query"]["fields"] == [
        {"fieldCaption": "Year A", "sortDirection": "ASC", "sortPriority": 1},
        {"fieldCaption": "Metric A", "function": "SUM"},
        {"fieldCaption": "Metric B", "function": "SUM"},
        {"fieldCaption": "Customer Name", "function": "COUNTD"},
    ]
    assert "mcp_host_repair" in _tool_names(events)
    assert events[-1].type == "answer"


@pytest.mark.asyncio
async def test_mcp_first_main_repairs_schema_or_argument_error_once(monkeypatch):
    executor, planner = _patch_host(
        monkeypatch,
        actions=[_query_tool_call(limit=10000), _query_tool_call(limit=100), _final_action()],
        query_errors=[
            {
                "success": False,
                "error_code": "SCHEMA_VALIDATION_FAILED",
                "error": "limit is above schema maximum",
            }
        ],
    )

    events = [
        event
        async for event in run_mcp_first_main_path(
            question="overall Metric A",
            context=_selected_datasource_context("trace-repair"),
            intent_result=IntentClassification(intent="aggregate", confidence=0.9, route_reason="metric_keyword"),
            llm_service=_McpArgsOnlyLLM({}),
        )
    ]

    tool_names = _tool_names(events)
    assert "mcp_host_repair" in tool_names
    assert _forbidden_main_path_markers().isdisjoint(tool_names)
    assert [call["tool_name"] for call in executor.calls] == [
        "get-datasource-metadata",
        "query-datasource",
        "query-datasource",
    ]
    assert len(planner.calls) == 2
    assert planner.calls[1]["error"]["error_code"] == "SCHEMA_VALIDATION_FAILED"
    assert events[-1].type == "answer"


@pytest.mark.asyncio
async def test_mcp_first_main_mcp_errors_surface_without_queryspec_fallback(monkeypatch):
    _patch_host(
        monkeypatch,
        query_errors=[
            {
                "success": False,
                "error_code": "MCP_UPSTREAM_ERROR",
                "error": "upstream unavailable",
            }
        ],
    )

    events = [
        event
        async for event in run_mcp_first_main_path(
            question="overall Metric A",
            context=_selected_datasource_context("trace-queryspec-fallback"),
            intent_result=IntentClassification(intent="aggregate", confidence=0.9, route_reason="metric_keyword"),
            llm_service=_BadMcpArgsThenQuerySpecLLM(),
        )
    ]

    tool_names = _tool_names(events)
    assert "tableau_mcp" in tool_names
    assert _forbidden_main_path_markers().isdisjoint(tool_names)
    assert events[-1].type == "error"
    assert events[-1].content["error_code"] == "MCP_UPSTREAM_ERROR"


@pytest.mark.asyncio
async def test_mcp_first_main_requires_explicit_datasource(monkeypatch):
    async def _unexpected_components(**kwargs):
        raise AssertionError("Host runtime must not load without an explicit datasource")

    monkeypatch.setattr(mcp_first_main, "_load_mcp_host_components", _unexpected_components)

    events = [
        event
        async for event in run_mcp_first_main_path(
            question="overall Metric A",
            context=ToolContext(session_id="s1", user_id=1, connection_id=2, trace_id="trace-no-ds"),
            intent_result=IntentClassification(intent="aggregate", confidence=0.9, route_reason="metric_keyword"),
            datasource_name_hint="not explicit enough",
            llm_service=_FakeLLM(),
        )
    ]

    tool_names = _tool_names(events)
    assert "mcp_host_catalog" not in tool_names
    assert events[-1].type == "error"
    assert events[-1].content["error_code"] == "MCP_EXPLICIT_DATASOURCE_REQUIRED"


def test_normalize_mcp_data_keeps_requested_registry_derived_metric_shadow_only(monkeypatch):
    monkeypatch.setenv("DATA_AGENT_DCE_SHADOW_ENABLED", "true")
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
    shadow = data["diagnostics"]["dynamic_column_engine_shadow"]
    assert shadow["metadata"][0]["status"] == "computed"
    assert shadow["shadow_fields"] == ["子类别", "SUM(销售额)", "SUM(利润)", "利润率"]
    assert shadow["shadow_rows_sample"] == [["小计", 100, 10, 0.1], ["大计", 200, 50, 0.25]]

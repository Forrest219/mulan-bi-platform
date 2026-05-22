import json
import uuid

import pytest

from services.data_agent import mcp_first_main, mcp_proxy_main
from services.data_agent.mcp_host.builtins import MULAN_LIST_TABLEAU_ASSETS_TOOL_NAME
from services.data_agent.intent_classifier import IntentClassification, classify_intent
from services.data_agent.models import BiAgentRun
from services.data_agent.tableau_mcp_plan_compiler import CompileResult
from services.data_agent.response import AgentEvent
from services.data_agent.router_guardrail import RouteDecision
from services.data_agent.runner import run_agent
from services.data_agent.session import AgentSession
from services.data_agent.tool_base import ToolContext

pytestmark = pytest.mark.skip_db


class _FakeLLM:
    def __init__(self, payload):
        self.payload = payload
        self.calls = []

    async def complete(self, *, prompt, system=None, timeout=None, purpose=None):
        assert purpose == "data_agent_mcp_proxy_args"
        assert "QuerySpec" in system
        self.calls.append({"prompt": prompt, "system": system, "timeout": timeout, "purpose": purpose})
        if isinstance(self.payload, dict) and {"tool_name", "args", "reason", "confidence", "needs_clarification", "clarification"}.issubset(self.payload):
            payload = self.payload
        else:
            payload = {
                "tool_name": "query-datasource",
                "args": self.payload,
                "reason": "test_plan",
                "confidence": 0.9,
                "needs_clarification": False,
                "clarification": None,
            }
        return {"content": json.dumps(payload, ensure_ascii=False)}


def _intent(intent: str = "aggregate") -> IntentClassification:
    return IntentClassification(intent=intent, confidence=0.9, route_reason="test")


def _context() -> ToolContext:
    context = ToolContext(session_id="s1", user_id=7, connection_id=2, trace_id="trace-proxy")
    context.datasource_luid = "ds-1"
    context.datasource_name = "测试数据源"
    context.selected_datasource = {
        "luid": "ds-1",
        "name": "测试数据源",
        "metadata_fields": [
            {"caption": "Metric A", "name": "metric_a", "role": "MEASURE", "dataType": "REAL", "defaultAggregation": "SUM"},
            {"caption": "Dimension A", "name": "dimension_a", "role": "DIMENSION", "dataType": "STRING"},
            {"caption": "销售额", "name": "sales", "role": "MEASURE", "dataType": "REAL", "defaultAggregation": "SUM"},
            {"caption": "省份", "name": "province", "role": "DIMENSION", "dataType": "STRING"},
            {"caption": "日期字段", "name": "date_field", "role": "DIMENSION", "dataType": "DATE"},
            {"caption": "指标一", "name": "metric_one", "role": "MEASURE", "dataType": "REAL", "defaultAggregation": "SUM"},
            {"caption": "Sales", "name": "sales_en", "role": "MEASURE", "dataType": "REAL", "defaultAggregation": "SUM"},
            {"caption": "Customer", "name": "customer", "role": "DIMENSION", "dataType": "STRING"},
        ],
    }
    return context


def _tool_names(events):
    return [
        event.content["tool"]
        for event in events
        if event.type in {"tool_call", "tool_result"} and isinstance(event.content, dict)
    ]


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
                        "properties": {"datasourceLuid": {"type": "string"}, "query": {"type": "object"}},
                    },
                },
            ]
        }


class _FakeHostExecutor:
    def __init__(self, *, query_result=None, query_error=None):
        self.calls = []
        self.query_result = query_result or {"fields": ["Metric A"], "rows": [[100]]}
        self.query_error = query_error

    async def execute_tool(self, tool_name, arguments, context):
        self.calls.append({"tool_name": tool_name, "arguments": dict(arguments), "context": context})
        if tool_name == "get-datasource-metadata":
            return {"fields": [{"name": "Metric A", "dataType": "REAL"}]}
        if self.query_error:
            return self.query_error
        return self.query_result


class _FakeHostPlanner:
    def __init__(self, actions=None):
        self.actions = list(actions or [_query_tool_call(), {"action": "final", "answer": "Use response_data only."}])
        self.calls = []

    async def plan(self, **kwargs):
        self.calls.append(kwargs)
        if not self.actions:
            raise AssertionError("unexpected extra MCP Host planner call")
        return self.actions.pop(0)


def _query_tool_call():
    return {
        "action": "tool_call",
        "tool_call": {
            "tool": "query-datasource",
            "arguments": {
                "datasourceLuid": "ds-1",
                "query": {"fields": [{"fieldCaption": "Metric A", "function": "SUM"}], "filters": []},
                "limit": 50,
            },
        },
    }


class _FakeTableauMcpClient:
    def __init__(self):
        self.list_calls = []
        self.call_calls = []

    def list_tools(self, **kwargs):
        self.list_calls.append(kwargs)
        return [
            {
                "name": "get-datasource-metadata",
                "inputSchema": {
                    "type": "object",
                    "required": ["datasourceLuid"],
                    "properties": {"datasourceLuid": {"type": "string"}},
                },
            }
        ]

    def call_tool(self, **kwargs):
        self.call_calls.append(kwargs)
        return {"fields": [{"name": "Sales", "role": "MEASURE"}], "metadata_freshness": "2026-05-20T00:00:00Z"}


def _patch_host(monkeypatch, *, query_result=None, query_error=None, actions=None):
    executor = _FakeHostExecutor(query_result=query_result, query_error=query_error)
    planner = _FakeHostPlanner(actions=actions)
    catalog = _FakeHostCatalog()

    async def _load_components(**kwargs):
        return mcp_first_main._McpHostComponents(catalog=catalog, executor=executor, planner=planner)

    monkeypatch.setattr(mcp_first_main, "_load_mcp_host_components", _load_components)
    return executor, planner


def _patch_proxy_executor(monkeypatch, *, query_result=None, query_error=None):
    calls = []

    async def _execute(**kwargs):
        calls.append(kwargs)
        if query_error is not None:
            raise RuntimeError(str(query_error.get("error") or query_error.get("error_code") or query_error))
        if kwargs.get("tool_name") == "get-datasource-metadata":
            return {"fields": [{"name": "Metric A", "dataType": "REAL"}]}
        return query_result or {"fields": ["Metric A"], "rows": [[100]]}

    monkeypatch.setattr(mcp_proxy_main, "_execute_mcp_host_tool", _execute)
    return calls


def _forbidden_main_path_markers():
    return {
        "mcp_nl_tool_discovery",
        "tableau_mcp_nl",
        "llm_mcp_args",
        "llm_queryspec",
        "llm_queryspec_repair",
        "queryspec_fallback",
        "queryspec_validator",
        "mcp_main_queryspec_fallback",
        "queryspec_mcp_fallback",
    }


@pytest.mark.asyncio
async def test_mcp_proxy_calls_mcp_host_loop_without_llm_args(monkeypatch):
    calls = _patch_proxy_executor(monkeypatch)

    events = [
        event
        async for event in mcp_proxy_main.run_mcp_proxy_main_path(
            question="overall Metric A",
            context=_context(),
            intent_result=_intent(),
            llm_service=_FakeLLM(
                {
                    "datasourceLuid": "ds-1",
                    "query": {"fields": [{"fieldCaption": "销售额", "function": "SUM"}], "filters": []},
                    "limit": 50,
                }
            ),
        )
    ]

    tool_names = _tool_names(events)
    assert "mcp_args_guardrail" in tool_names
    assert "tableau_mcp" in tool_names
    assert "mcp_host_planner" not in tool_names
    assert _forbidden_main_path_markers().isdisjoint(tool_names)
    assert [call["tool_name"] for call in calls] == ["query-datasource"]

    response_data = next(
        event.content["result"]["data"]
        for event in events
        if event.type == "tool_result" and event.content.get("tool") == "tableau_mcp"
    )
    assert response_data["chain_mode"] == "mcp_proxy"
    assert response_data["strategy"] in {"deterministic_plan_compiler", "llm_planner"}
    assert response_data["fields"] == ["Metric A"]
    assert response_data["rows"] == [[100]]
    assert response_data["table_display"]["columns"][0]["semantic_type"] == "metric"
    assert events[-1].type == "answer"


@pytest.mark.asyncio
async def test_mcp_proxy_mcp_error_returns_structured_error_without_queryspec(monkeypatch):
    _patch_proxy_executor(
        monkeypatch,
        query_error={"success": False, "error_code": "MCP_UPSTREAM_ERROR", "error": "upstream unavailable"},
    )

    events = [
        event
        async for event in mcp_proxy_main.run_mcp_proxy_main_path(
            question="Metric A by Dimension A",
            context=_context(),
            intent_result=_intent(),
            llm_service=_FakeLLM(
                {
                    "datasourceLuid": "ds-1",
                    "query": {
                        "fields": [{"fieldCaption": "省份"}, {"fieldCaption": "销售额", "function": "SUM"}],
                        "filters": [],
                    },
                }
            ),
        )
    ]

    tool_names = _tool_names(events)
    assert "tableau_mcp" in tool_names
    assert _forbidden_main_path_markers().isdisjoint(tool_names)
    assert events[-1].type == "answer"
    failed_tool = next(
        event.content["result"]["data"]
        for event in events
        if event.type == "tool_result" and event.content.get("tool") == "tableau_mcp"
    )
    assert failed_tool["response_type"] == "tool_unavailable"
    assert failed_tool["response_data"]["error_code"] in {"MCP_PROXY_PLANNED_TOOL_FAILED", "MCP_PROXY_QUERY_FAILED"}


@pytest.mark.asyncio
async def test_mcp_proxy_followup_context_is_passed_to_host_not_used_to_construct_fields(monkeypatch):
    monkeypatch.setattr(
        mcp_proxy_main._PLAN_COMPILER,
        "compile",
        lambda *args, **kwargs: CompileResult.unsupported(reason="complex_followup"),
    )
    calls = _patch_proxy_executor(
        monkeypatch,
        query_result={
            "fields": ["Dimension A", "Year A", "Metric A", "Metric B"],
            "rows": [["x", 2025, 10, 4]],
        },
    )
    llm = _FakeLLM(
        {
            "datasourceLuid": "ds-1",
            "query": {
                "fields": [
                    {"fieldCaption": "日期字段", "function": "YEAR"},
                    {"fieldCaption": "指标一", "function": "SUM"},
                ],
                "filters": [],
            },
            "limit": 100,
        }
    )

    events = [
        event
        async for event in mcp_proxy_main.run_mcp_proxy_main_path(
            question="continue by year",
            context=_context(),
            intent_result=_intent(),
            analysis_context={
                "datasource_name": "测试数据源",
                "response_data": {"fields": ["Metric A"], "rows": [[100]]},
            },
            llm_service=llm,
        )
    ]

    assert calls[0]["tool_name"] == "query-datasource"
    assert calls[0]["args"] == llm.payload
    assert events[-1].type == "answer"
    assert llm.calls
    assert '"response_data"' in llm.calls[0]["prompt"]


@pytest.mark.asyncio
async def test_mcp_proxy_q1_like_question_enters_host_not_llm_or_queryspec(monkeypatch):
    _patch_proxy_executor(monkeypatch)

    events = [
        event
        async for event in mcp_proxy_main.run_mcp_proxy_main_path(
            question="Metric A by Dimension A",
            context=_context(),
            intent_result=_intent(),
            llm_service=_FakeLLM(
                {
                    "datasourceLuid": "ds-1",
                    "query": {
                        "fields": [{"fieldCaption": "不存在字段"}, {"fieldCaption": "销售额", "function": "SUM"}],
                        "filters": [],
                    },
                    "limit": 20,
                }
            ),
        )
    ]

    tool_names = _tool_names(events)
    assert {"mcp_args_guardrail", "tableau_mcp"}.issubset(set(tool_names))
    assert "mcp_host_planner" not in tool_names
    assert _forbidden_main_path_markers().isdisjoint(tool_names)
    assert events[-1].type == "answer"


@pytest.mark.asyncio
async def test_mcp_proxy_simple_aggregate_uses_deterministic_compiler_not_host_planner(monkeypatch):
    async def _unexpected_components(**kwargs):
        raise AssertionError("simple aggregate must not enter MCP Host planner")

    calls = []

    async def _fake_execute(**kwargs):
        calls.append(kwargs)
        return {"fields": ["Region", "Sales"], "rows": [["East", 100]]}

    context = _context()
    context.selected_datasource = {
        "luid": "ds-1",
        "name": "测试数据源",
        "metadata_fields": [
            {"caption": "Sales", "name": "sales", "role": "MEASURE", "dataType": "REAL", "defaultAggregation": "SUM"},
            {"caption": "Region", "name": "region", "role": "DIMENSION", "dataType": "STRING"},
        ],
        "queryable_fields": ["Sales", "Region"],
    }
    monkeypatch.setattr(mcp_first_main, "_load_mcp_host_components", _unexpected_components)
    monkeypatch.setattr(mcp_proxy_main, "_execute_mcp_host_tool", _fake_execute)

    events = [
        event
        async for event in mcp_proxy_main.run_mcp_proxy_main_path(
            question="show Sales by Region",
            context=context,
            intent_result=_intent(),
        )
    ]

    tool_names = _tool_names(events)
    assert "deterministic_plan_compiler" in tool_names
    assert "mcp_host_planner" not in tool_names
    assert calls[0]["tool_name"] == "query-datasource"
    assert calls[0]["args"]["query"]["fields"] == [
        {"fieldCaption": "Region"},
        {"fieldCaption": "Sales", "function": "SUM"},
    ]
    final_data = next(
        event.content["result"]["data"]
        for event in events
        if event.type == "tool_result" and event.content.get("tool") == "mcp_host_final_response"
    )
    assert final_data["strategy"] == "deterministic_plan_compiler"
    assert final_data["compile"]["pattern"] == "metric_by_dimension"
    assert final_data["fields"] == ["Region", "Sales"]


@pytest.mark.asyncio
async def test_mcp_proxy_resolved_followup_context_can_fast_path_without_llm(monkeypatch):
    calls = _patch_proxy_executor(
        monkeypatch,
        query_result={"fields": ["Region", "YEAR(Order Date)", "Sales", "Profit"], "rows": [["East", 2024, 100, 20]]},
    )
    context = _context()
    context.selected_datasource = {
        "luid": "ds-1",
        "name": "测试数据源",
        "metadata_fields": [
            {"caption": "Sales", "name": "sales", "role": "MEASURE", "dataType": "REAL", "defaultAggregation": "SUM"},
            {"caption": "Profit", "name": "profit", "role": "MEASURE", "dataType": "REAL", "defaultAggregation": "SUM"},
            {"caption": "Region", "name": "region", "role": "DIMENSION", "dataType": "STRING"},
            {"caption": "Order Date", "name": "order_date", "role": "DIMENSION", "dataType": "DATE"},
        ],
        "queryable_fields": ["Sales", "Profit", "Region", "Order Date"],
    }
    llm = _FakeLLM({})

    events = [
        event
        async for event in mcp_proxy_main.run_mcp_proxy_main_path(
            question="continue by year",
            context=context,
            intent_result=_intent(),
            analysis_context={
                "is_follow_up": True,
                "requested_metrics": ["Sales", "Profit"],
                "requested_dimensions": ["Region"],
                "unresolved_references": False,
            },
            llm_service=llm,
        )
    ]

    assert llm.calls == []
    assert calls[0]["tool_name"] == "query-datasource"
    assert calls[0]["execution_source"] == "compiler_fast_path"
    assert calls[0]["args"]["query"]["fields"] == [
        {"fieldCaption": "Region"},
        {"fieldCaption": "Order Date", "function": "YEAR", "sortDirection": "ASC", "sortPriority": 1},
        {"fieldCaption": "Sales", "function": "SUM"},
        {"fieldCaption": "Profit", "function": "SUM"},
    ]
    assert "tableau_mcp" in _tool_names(events)
    assert events[-1].type == "answer"


@pytest.mark.asyncio
async def test_mcp_proxy_regression_multi_metric_question_calls_tableau_mcp(monkeypatch):
    calls = _patch_proxy_executor(
        monkeypatch,
        query_result={
            "data": [{"SUM(销售额)": 1000, "SUM(利润)": 200, "利润率": 0.2, "客户数": 50, "客单价": 20}],
        },
    )
    context = _context()
    context.selected_datasource = {
        "luid": "ds-1",
        "name": "测试数据源",
        "metadata_fields": [
            {"caption": "销售额", "name": "sales", "role": "MEASURE", "dataType": "REAL", "defaultAggregation": "SUM"},
            {"caption": "利润", "name": "profit", "role": "MEASURE", "dataType": "REAL", "defaultAggregation": "SUM"},
            {"caption": "利润率", "name": "profit_rate", "role": "MEASURE", "dataType": "REAL", "formula": "[利润]/[销售额]"},
            {"caption": "客户数", "name": "customer_count", "role": "MEASURE", "dataType": "INTEGER", "defaultAggregation": "COUNTD"},
            {"caption": "客单价", "name": "aov", "role": "MEASURE", "dataType": "REAL", "formula": "[销售额]/[客户数]"},
        ],
        "queryable_fields": ["销售额", "利润", "利润率", "客户数", "客单价"],
    }

    events = [
        event
        async for event in mcp_proxy_main.run_mcp_proxy_main_path(
            question="整体的销售额、利润、利润率、客户数、客单价是什么样子",
            context=context,
            intent_result=_intent(),
        )
    ]

    tool_names = _tool_names(events)
    assert "tableau_mcp" in tool_names
    assert all(event.content != "匹配到多个可能字段，请选择一个后继续。" for event in events if event.type == "answer")
    assert calls[0]["tool_name"] == "query-datasource"
    assert [field["fieldCaption"] for field in calls[0]["args"]["query"]["fields"]] == ["销售额", "利润", "利润率", "客户数", "客单价"]
    response_data = next(
        event.content["result"]["data"]
        for event in events
        if event.type == "tool_result" and event.content.get("tool") == "tableau_mcp"
    )
    assert response_data["response_type"] == "query_result"
    assert response_data["fields"] == ["SUM(销售额)", "SUM(利润)", "利润率", "客户数", "客单价"]
    assert response_data["rows"] == [[1000, 200, 0.2, 50, 20]]
    assert len(response_data["table_display"]["columns"]) == len(response_data["fields"])
    assert response_data["execution_source"] == "compiler_fast_path"


@pytest.mark.asyncio
async def test_mcp_proxy_unsupported_passes_compiler_advisory_to_planner(monkeypatch):
    monkeypatch.setattr(
        mcp_proxy_main._PLAN_COMPILER,
        "compile",
        lambda *args, **kwargs: CompileResult.unsupported(
            reason="complex_question",
            advisory={
                "status": "unsupported",
                "reason": "complex_question",
                "matched_metrics": [{"fieldCaption": "Metric A"}],
                "ambiguous_metrics": [],
                "candidate_dimensions": [],
                "candidate_filters": [],
                "rejected_fast_path_reason": "complex_question",
            },
        ),
    )
    _patch_proxy_executor(monkeypatch)
    llm = _FakeLLM(
        {
            "datasourceLuid": "ds-1",
            "query": {"fields": [{"fieldCaption": "Metric A", "function": "SUM"}], "filters": []},
            "limit": 50,
        }
    )

    events = [
        event
        async for event in mcp_proxy_main.run_mcp_proxy_main_path(
            question="why Metric A changed",
            context=_context(),
            intent_result=_intent(),
            llm_service=llm,
        )
    ]

    assert events[-1].type == "answer"
    assert llm.calls
    assert '"compiler_advisory"' in llm.calls[0]["prompt"]
    assert '"rejected_fast_path_reason": "complex_question"' in llm.calls[0]["prompt"]


@pytest.mark.asyncio
async def test_mcp_proxy_keeps_router_and_compiler_advisories_distinct(monkeypatch):
    compiler_advisory = {
        "status": "unsupported",
        "reason": "complex_question",
        "rejected_fast_path_reason": "complex_question",
    }
    router_advisory = {
        "status": "ambiguous",
        "action": "advisory",
        "reason": "low_confidence_route",
        "is_authoritative": False,
        "allowed_tool_hints": ["schema", "query"],
    }
    monkeypatch.setattr(
        mcp_proxy_main._PLAN_COMPILER,
        "compile",
        lambda *args, **kwargs: CompileResult.unsupported(
            reason="complex_question",
            advisory=compiler_advisory,
        ),
    )
    _patch_proxy_executor(monkeypatch)
    llm = _FakeLLM(
        {
            "datasourceLuid": "ds-1",
            "query": {"fields": [{"fieldCaption": "Metric A", "function": "SUM"}], "filters": []},
            "limit": 50,
        }
    )

    events = [
        event
        async for event in mcp_proxy_main.run_mcp_proxy_main_path(
            question="你有哪些看板？",
            context=_context(),
            intent_result=_intent(),
            analysis_context={"router_advisory": router_advisory},
            llm_service=llm,
        )
    ]

    assert events[-1].type == "answer"
    assert llm.calls
    planner_payload = json.loads(llm.calls[0]["prompt"])
    assert planner_payload["analysis_context"]["router_advisory"] == router_advisory
    assert planner_payload["compiler_advisory"]["reason"] == compiler_advisory["reason"]
    assert planner_payload["compiler_advisory"]["rejected_fast_path_reason"] == compiler_advisory["rejected_fast_path_reason"]
    assert "router_advisory" not in planner_payload["compiler_advisory"]


@pytest.mark.asyncio
async def test_mcp_proxy_merges_context_router_advisory_before_datasource_gate(monkeypatch):
    router_advisory = {
        "status": "ambiguous",
        "action": "advisory",
        "reason": "low_confidence_route",
        "is_authoritative": False,
        "allowed_tool_hints": ["asset", "query"],
    }
    context = ToolContext(session_id="s1", user_id=7, connection_id=2, trace_id="trace-proxy")
    context.analysis_context["router_advisory"] = router_advisory
    calls = _patch_proxy_executor(monkeypatch, query_result={"datasources": []})
    llm = _FakeLLM(
        {
            "tool_name": "list-datasources",
            "args": {"connectionId": 2, "limit": 50},
            "reason": "router advisory allows asset inventory planning",
            "confidence": 0.9,
            "needs_clarification": False,
            "clarification": None,
        }
    )

    events = [
        event
        async for event in mcp_proxy_main.run_mcp_proxy_main_path(
            question="你有哪些看板？",
            context=context,
            intent_result=_intent("unknown"),
            llm_service=llm,
        )
    ]

    assert llm.calls
    planner_payload = json.loads(llm.calls[0]["prompt"])
    assert planner_payload["router_advisory"] == router_advisory
    assert planner_payload["analysis_context"]["router_advisory"] == router_advisory
    assert calls and calls[0]["tool_name"] == "list-datasources"
    planner_events = [
        event for event in events
        if event.type == "tool_result"
        and event.content.get("tool") == "tableau_mcp_llm_planner"
    ]
    assert planner_events[-1].content["result"]["data"]["planner_received_route_advisory"] is True


@pytest.mark.asyncio
async def test_mcp_proxy_dashboard_inventory_uses_mulan_builtin_asset_tool(monkeypatch):
    router_advisory = {
        "status": "ambiguous",
        "action": "advisory",
        "reason": "low_confidence_route",
        "is_authoritative": False,
        "allowed_tool_hints": ["asset", "query"],
    }
    context = ToolContext(session_id="s1", user_id=7, connection_id=2, trace_id="trace-proxy")
    context.analysis_context["router_advisory"] = router_advisory
    calls = _patch_proxy_executor(
        monkeypatch,
        query_result={
            "response_type": "asset_candidates",
            "response_data": {
                "source": "tableau_asset_catalog",
                "connection_id": 2,
                "reason": "asset_inventory",
                "total_count": 1,
                "shown_count": 1,
                "candidates": [{"asset_id": 1, "asset_type": "dashboard", "name": "销售看板"}],
            },
        },
    )
    llm = _FakeLLM(
        {
            "tool_name": MULAN_LIST_TABLEAU_ASSETS_TOOL_NAME,
            "args": {"connectionId": 2, "assetTypes": ["dashboard"], "limit": 50},
            "reason": "The user asks for Tableau dashboard assets.",
            "confidence": 0.9,
            "needs_clarification": False,
            "clarification": None,
        }
    )

    events = [
        event
        async for event in mcp_proxy_main.run_mcp_proxy_main_path(
            question="你有哪些看板？",
            context=context,
            intent_result=_intent("unknown"),
            llm_service=llm,
        )
    ]

    assert calls and calls[0]["tool_name"] == MULAN_LIST_TABLEAU_ASSETS_TOOL_NAME
    final_data = events[-2].content["result"]["data"]
    assert final_data["response_type"] == "asset_candidates"
    assert final_data["response_data"]["source"] == "tableau_asset_catalog"
    assert final_data["response_data"]["candidates"][0]["asset_type"] == "dashboard"
    assert "Planner 未能生成可执行计划" not in events[-1].content
    assert "当前连接可见的 Tableau 资产" in events[-1].content


@pytest.mark.asyncio
async def test_mcp_proxy_planner_contract_failure_returns_standard_clarification(monkeypatch):
    class BadClarificationLLM:
        def __init__(self):
            self.calls = []

        async def complete(self, *, prompt, system=None, timeout=None, purpose=None):
            self.calls.append({"prompt": prompt, "system": system, "timeout": timeout, "purpose": purpose})
            return {
                "content": json.dumps(
                    {
                        "tool_name": None,
                        "args": {},
                        "reason": "Internal planner reason that must not be shown.",
                        "confidence": 0.72,
                        "needs_clarification": True,
                    },
                    ensure_ascii=False,
                )
            }

    async def _unexpected_execute(**kwargs):
        raise AssertionError("invalid planner contract must not execute a tool")

    router_advisory = {"status": "ambiguous", "action": "advisory", "is_authoritative": False}
    context = ToolContext(session_id="s1", user_id=7, connection_id=2, trace_id="trace-proxy")
    context.analysis_context["router_advisory"] = router_advisory
    monkeypatch.setattr(mcp_proxy_main, "_execute_mcp_host_tool", _unexpected_execute)
    llm = BadClarificationLLM()

    events = [
        event
        async for event in mcp_proxy_main.run_mcp_proxy_main_path(
            question="你有哪些看板？",
            context=context,
            intent_result=_intent("unknown"),
            llm_service=llm,
        )
    ]

    assert len(llm.calls) == 2
    assert events[-1].type == "answer"
    assert "您是想查询业务数据" in events[-1].content
    assert "Internal planner reason" not in events[-1].content
    response_data = events[-2].content["result"]["data"]
    assert response_data["response_type"] == "clarification"
    assert response_data["response_data"]["error_code"] == "PLANNER_CONTRACT_FAILURE"


@pytest.mark.asyncio
async def test_mcp_proxy_soft_ambiguity_passes_compiler_advisory_to_planner(monkeypatch):
    monkeypatch.setattr(
        mcp_proxy_main._PLAN_COMPILER,
        "compile",
        lambda *args, **kwargs: CompileResult.ambiguous(
            reason="soft_contains_metric_match",
            ambiguity_level="soft",
            clarification={"message": "soft only", "candidates": [{"fieldCaption": "Metric A"}]},
            advisory={
                "status": "ambiguous",
                "reason": "soft_contains_metric_match",
                "matched_metrics": [],
                "ambiguous_metrics": [{"ambiguity_level": "soft", "candidates": [{"fieldCaption": "Metric A"}]}],
                "candidate_dimensions": [],
                "candidate_filters": [],
                "rejected_fast_path_reason": "soft_contains_metric_match",
            },
        ),
    )
    _patch_proxy_executor(monkeypatch)
    llm = _FakeLLM(
        {
            "datasourceLuid": "ds-1",
            "query": {"fields": [{"fieldCaption": "Metric A", "function": "SUM"}], "filters": []},
            "limit": 50,
        }
    )

    events = [
        event
        async for event in mcp_proxy_main.run_mcp_proxy_main_path(
            question="show metr by Dimension A",
            context=_context(),
            intent_result=_intent(),
            llm_service=llm,
        )
    ]

    assert events[-1].type == "answer"
    assert '"ambiguity_level": "soft"' in llm.calls[0]["prompt"]
    assert "tableau_mcp" in _tool_names(events)


@pytest.mark.asyncio
async def test_mcp_proxy_hard_ambiguity_returns_clarification_without_mcp(monkeypatch):
    async def _unexpected_execute(**kwargs):
        raise AssertionError("hard compiler ambiguity must not call MCP")

    monkeypatch.setattr(
        mcp_proxy_main._PLAN_COMPILER,
        "compile",
        lambda *args, **kwargs: CompileResult.ambiguous(
            reason="metric_field_ambiguous",
            ambiguity_level="hard",
            clarification={"message": "匹配到多个可能字段，请选择一个后继续。", "candidates": [{"fieldCaption": "A"}, {"fieldCaption": "B"}]},
        ),
    )
    monkeypatch.setattr(mcp_proxy_main, "_execute_mcp_host_tool", _unexpected_execute)

    events = [
        event
        async for event in mcp_proxy_main.run_mcp_proxy_main_path(
            question="show ambiguous metric",
            context=_context(),
            intent_result=_intent(),
            llm_service=_FakeLLM({}),
        )
    ]

    assert events[-1].type == "answer"
    assert "匹配到多个可能字段" in events[-1].content
    assert "tableau_mcp" not in _tool_names(events)


@pytest.mark.asyncio
async def test_mcp_proxy_blocks_detail_scan_result_before_renderer(monkeypatch):
    _patch_proxy_executor(
        monkeypatch,
        query_result={"fields": ["Customer", "Sales"], "rows": [[f"c{i}", i] for i in range(250)]},
    )

    events = [
        event
        async for event in mcp_proxy_main.run_mcp_proxy_main_path(
            question="top Customer by Metric A",
            context=_context(),
            intent_result=_intent(),
            llm_service=_FakeLLM(
                {
                    "datasourceLuid": "ds-1",
                    "query": {
                        "fields": [{"fieldCaption": "Customer"}, {"fieldCaption": "Metric A", "function": "SUM"}],
                        "filters": [],
                    },
                    "limit": 250,
                }
            ),
        )
    ]

    assert events[-1].type == "error"
    assert events[-1].content["error_code"] == "DETAIL_SCAN_BLOCKED"


@pytest.mark.asyncio
async def test_mcp_proxy_requires_explicit_datasource(monkeypatch):
    async def _unexpected_components(**kwargs):
        raise AssertionError("Host runtime must not load without an explicit datasource")

    monkeypatch.setattr(mcp_first_main, "_load_mcp_host_components", _unexpected_components)

    events = [
        event
        async for event in mcp_proxy_main.run_mcp_proxy_main_path(
            question="整体销售额和利润率是多少",
            context=ToolContext(session_id="s1", user_id=7, connection_id=2, trace_id="trace-proxy"),
            intent_result=_intent(),
            llm_service=_FakeLLM(
                {
                    "datasourceLuid": "ds-1",
                    "query": {"fields": ["销售额", "利润率"], "filters": []},
                    "limit": 20,
                }
            ),
        )
    ]

    error = events[-1]
    assert error.type == "error"
    assert error.content["error_code"] == "MCP_EXPLICIT_DATASOURCE_REQUIRED"
    tool_names = _tool_names(events)
    assert "mcp_host_catalog" not in tool_names
    assert "llm_mcp_args" not in tool_names


@pytest.mark.asyncio
async def test_mcp_proxy_unique_datasource_intro_calls_metadata_tool(monkeypatch):
    calls = []

    async def _fake_execute(**kwargs):
        calls.append(kwargs)
        return {"fields": [{"name": "科目", "caption": "科目"}, {"name": "金额", "caption": "金额"}]}

    monkeypatch.setattr(
        mcp_proxy_main,
        "_resolve_datasource_candidates",
        lambda question, context: [
            {
                "asset_id": 1,
                "connection_id": 2,
                "datasource_luid": "ds-expense",
                "luid": "ds-expense",
                "name": "管理费用数据源",
                "project_name": "财务",
            }
        ],
    )
    monkeypatch.setattr(mcp_proxy_main, "_execute_mcp_host_tool", _fake_execute)

    events = [
        event
        async for event in mcp_proxy_main.run_mcp_proxy_main_path(
            question="介绍管理费用数据源",
            context=ToolContext(session_id="s1", user_id=7, connection_id=2, trace_id="trace-proxy"),
            intent_result=_intent("asset_inventory"),
        )
    ]

    assert calls[0]["tool_name"] == "get-datasource-metadata"
    assert calls[0]["datasource_luid"] == "ds-expense"
    assert "query-datasource" not in [call["tool_name"] for call in calls]
    final_data = events[-2].content["result"]["data"]
    assert final_data["response_type"] == "asset_metadata"
    assert final_data["response_data"]["source"] == "mcp"
    assert final_data["response_data"]["datasource_luid"] == "ds-expense"


@pytest.mark.asyncio
async def test_mcp_proxy_metadata_tool_uses_connection_scoped_cache(monkeypatch):
    client = _FakeTableauMcpClient()
    mcp_proxy_main._MCP_CACHE.cache.clear()
    monkeypatch.setattr("services.tableau.mcp_client.get_tableau_mcp_client", lambda connection_id=None: client)
    context = ToolContext(session_id="s1", user_id=7, connection_id=2, trace_id="trace-proxy")

    first = await mcp_proxy_main._execute_mcp_host_tool(
        tool_name="get-datasource-metadata",
        args={"datasourceLuid": "ds-cache", "connectionId": 2},
        context=context,
        datasource_luid="ds-cache",
    )
    second = await mcp_proxy_main._execute_mcp_host_tool(
        tool_name="get-datasource-metadata",
        args={"datasourceLuid": "ds-cache", "connectionId": 2},
        context=context,
        datasource_luid="ds-cache",
    )

    assert first == second
    assert len(client.list_calls) == 1
    assert len(client.call_calls) == 1


def test_mcp_proxy_metadata_response_extracts_field_groups_and_suggestions():
    result = {
        "content": [
            {
                "type": "text",
                "text": json.dumps(
                    {
                        "fieldCount": 5,
                        "fieldGroups": [
                            {
                                "name": "维度",
                                "fields": [
                                    {
                                        "name": "财务期间",
                                        "dataType": "DATE",
                                        "role": "DIMENSION",
                                        "logicalTableId": "lt-date",
                                    },
                                    {
                                        "name": "公司名称",
                                        "dataType": "STRING",
                                        "role": "DIMENSION",
                                        "logicalTableId": "lt-company",
                                    },
                                ],
                            },
                            {
                                "name": "指标",
                                "fields": [
                                    {
                                        "name": "预算金额",
                                        "dataType": "REAL",
                                        "role": "MEASURE",
                                        "defaultAggregation": "SUM",
                                        "logicalTableId": "lt-budget",
                                    },
                                    {
                                        "name": "还原后金额",
                                        "dataType": "REAL",
                                        "role": "MEASURE",
                                        "defaultAggregation": "SUM",
                                        "formula": "[金额] * [还原系数]",
                                        "logicalTableId": "lt-restored",
                                    },
                                    {
                                        "name": "与预算比",
                                        "dataType": "REAL",
                                        "role": "MEASURE",
                                        "defaultAggregation": "AVG",
                                        "formula": "[还原后金额] / [预算金额]",
                                        "logicalTableId": "lt-ratio",
                                    },
                                ],
                            },
                        ],
                    },
                    ensure_ascii=False,
                ),
            }
        ]
    }

    response = mcp_proxy_main._asset_metadata_response_from_mcp(
        result,
        {"datasource_luid": "ds-expense", "name": "管理费用数据源", "field_count": 5},
    )

    data = response["response_data"]
    assert response["response_type"] == "asset_metadata"
    assert data["field_count"] == 5
    assert data["raw_field_count"] == 5
    assert data["metadata_quality"]["status"] == "complete"
    assert [field["name"] for field in data["fields"]] == ["财务期间", "公司名称", "预算金额", "还原后金额", "与预算比"]
    budget_field = next(field for field in data["fields"] if field["name"] == "预算金额")
    restored_field = next(field for field in data["fields"] if field["name"] == "还原后金额")
    assert budget_field["dataType"] == "REAL"
    assert budget_field["role"] == "MEASURE"
    assert budget_field["defaultAggregation"] == "SUM"
    assert budget_field["logicalTableId"] == "lt-budget"
    assert restored_field["formula"] == "[金额] * [还原系数]"

    group_ids = {group["id"] for group in data["field_groups"]}
    assert {"measures", "dimensions", "time", "calculations"}.issubset(group_ids)

    suggested_fields = {
        field
        for suggestion in data["analysis_suggestions"]
        for field in suggestion["fields"]
    }
    assert {"预算金额", "还原后金额", "与预算比", "财务期间", "公司名称"}.issubset(suggested_fields)


def test_mcp_proxy_metadata_quality_marks_partial_count_mismatch():
    response = mcp_proxy_main._asset_metadata_response_from_mcp(
        {"field_count": 3, "fields": [{"name": "预算金额", "dataType": "REAL", "role": "MEASURE"}]},
        {"datasource_luid": "ds-expense", "name": "管理费用数据源"},
    )

    data = response["response_data"]
    assert data["field_count"] == 1
    assert data["raw_field_count"] == 3
    assert data["metadata_quality"]["status"] == "partial"
    assert data["metadata_quality"]["field_count"] == 1
    assert data["metadata_quality"]["expected_field_count"] == 3


def test_mcp_proxy_metadata_quality_empty_does_not_masquerade_as_complete():
    response = mcp_proxy_main._asset_metadata_response_from_mcp(
        {"field_count": 15, "fieldGroups": []},
        {"datasource_luid": "ds-expense", "name": "管理费用数据源", "field_count": 15},
    )

    data = response["response_data"]
    assert data["fields"] == []
    assert data["field_count"] == 0
    assert data["raw_field_count"] == 15
    assert data["metadata_quality"]["status"] == "empty"
    assert data["metadata_quality"]["expected_field_count"] == 15


@pytest.mark.asyncio
async def test_mcp_proxy_multi_datasource_candidates_clarifies_without_query(monkeypatch):
    async def _unexpected_execute(**kwargs):
        raise AssertionError("must not call MCP when resolver returns multiple candidates")

    monkeypatch.setattr(
        mcp_proxy_main,
        "_resolve_datasource_candidates",
        lambda question, context: [
            {"datasource_luid": "ds-a", "name": "管理费用明细数据源"},
            {"datasource_luid": "ds-b", "name": "管理费用汇总数据源"},
        ],
    )
    monkeypatch.setattr(mcp_proxy_main, "_execute_mcp_host_tool", _unexpected_execute)

    events = [
        event
        async for event in mcp_proxy_main.run_mcp_proxy_main_path(
            question="介绍管理费用数据源",
            context=ToolContext(session_id="s1", user_id=7, connection_id=2, trace_id="trace-proxy"),
            intent_result=_intent("asset_inventory"),
        )
    ]

    final_data = events[-2].content["result"]["data"]
    assert final_data["response_type"] == "asset_candidates"
    assert len(final_data["response_data"]["candidates"]) == 2
    assert "query-datasource" not in _tool_names(events)


@pytest.mark.asyncio
async def test_mcp_proxy_zero_datasource_candidate_returns_not_found_not_list(monkeypatch):
    async def _unexpected_execute(**kwargs):
        raise AssertionError("must not call list-datasources for failed asset intro")

    monkeypatch.setattr(mcp_proxy_main, "_resolve_datasource_candidates", lambda question, context: [])
    monkeypatch.setattr(mcp_proxy_main, "_execute_mcp_host_tool", _unexpected_execute)

    events = [
        event
        async for event in mcp_proxy_main.run_mcp_proxy_main_path(
            question="介绍不存在数据源",
            context=ToolContext(session_id="s1", user_id=7, connection_id=2, trace_id="trace-proxy"),
            intent_result=_intent("asset_inventory"),
        )
    ]

    final_data = events[-2].content["result"]["data"]
    assert final_data["response_type"] == "asset_not_found"
    assert final_data["response_data"]["candidates"] == []
    assert "list-datasources" not in _tool_names(events)


@pytest.mark.asyncio
async def test_mcp_proxy_metadata_failure_uses_complete_catalog_cache(monkeypatch):
    async def _fake_execute(**kwargs):
        raise RuntimeError("mcp unavailable")

    monkeypatch.setattr(
        mcp_proxy_main,
        "_resolve_datasource_candidates",
        lambda question, context: [{"asset_id": 1, "datasource_luid": "ds-expense", "luid": "ds-expense", "name": "管理费用数据源"}],
    )
    monkeypatch.setattr(mcp_proxy_main, "_execute_mcp_host_tool", _fake_execute)
    monkeypatch.setattr(
        mcp_proxy_main,
        "_asset_metadata_response_from_catalog_cache",
        lambda candidate, context: {
            "response_type": "asset_metadata",
            "response_data": {
                "source": "catalog_cache",
                "datasource_luid": "ds-expense",
                "datasource_name": "管理费用数据源",
                "fields": [{"name": "科目"}],
                "field_count": 1,
                "metadata_freshness": "2026-05-20T12:00:00",
            },
        },
    )

    events = [
        event
        async for event in mcp_proxy_main.run_mcp_proxy_main_path(
            question="介绍管理费用数据源",
            context=ToolContext(session_id="s1", user_id=7, connection_id=2, trace_id="trace-proxy"),
            intent_result=_intent("asset_inventory"),
        )
    ]

    final_data = events[-2].content["result"]["data"]
    assert final_data["response_type"] == "asset_metadata"
    assert final_data["response_data"]["source"] == "catalog_cache"
    assert "缓存" in events[-1].content


@pytest.mark.asyncio
async def test_mcp_proxy_metadata_failure_without_cache_returns_structured_failure(monkeypatch):
    async def _fake_execute(**kwargs):
        raise RuntimeError("mcp unavailable")

    monkeypatch.setattr(
        mcp_proxy_main,
        "_resolve_datasource_candidates",
        lambda question, context: [{"asset_id": 1, "datasource_luid": "ds-expense", "luid": "ds-expense", "name": "管理费用数据源"}],
    )
    monkeypatch.setattr(mcp_proxy_main, "_execute_mcp_host_tool", _fake_execute)
    monkeypatch.setattr(mcp_proxy_main, "_asset_metadata_response_from_catalog_cache", lambda candidate, context: None)

    events = [
        event
        async for event in mcp_proxy_main.run_mcp_proxy_main_path(
            question="介绍管理费用数据源",
            context=ToolContext(session_id="s1", user_id=7, connection_id=2, trace_id="trace-proxy"),
            intent_result=_intent("asset_inventory"),
        )
    ]

    final_data = events[-2].content["result"]["data"]
    assert final_data["response_type"] == "tool_unavailable"
    assert final_data["response_data"]["error_code"] == "MCP_PROXY_METADATA_UNAVAILABLE"
    assert "schema" not in _tool_names(events)


@pytest.mark.asyncio
async def test_mcp_proxy_explicit_datasource_list_calls_list_datasources(monkeypatch):
    calls = []

    async def _fake_execute(**kwargs):
        calls.append(kwargs)
        return {"datasources": [{"luid": "ds-1", "name": "销售数据源"}]}

    monkeypatch.setattr(mcp_proxy_main, "_execute_mcp_host_tool", _fake_execute)
    monkeypatch.setattr(mcp_proxy_main, "_connection_is_accessible", lambda context: True)

    events = [
        event
        async for event in mcp_proxy_main.run_mcp_proxy_main_path(
            question="列出有哪些数据源",
            context=ToolContext(session_id="s1", user_id=7, connection_id=2, trace_id="trace-proxy"),
            intent_result=_intent("asset_inventory"),
        )
    ]

    assert calls[0]["tool_name"] == "list-datasources"
    final_data = events[-2].content["result"]["data"]
    assert final_data["response_type"] == "asset_candidates"
    assert final_data["response_data"]["source"] == "mcp"
    assert final_data["response_data"]["candidates"][0]["datasource_luid"] == "ds-1"
    assert "当前连接的数据源清单" in events[-1].content


@pytest.mark.asyncio
async def test_mcp_proxy_datasource_list_falls_back_to_catalog_cache_when_mcp_empty(monkeypatch):
    calls = []

    async def _fake_execute(**kwargs):
        calls.append(kwargs)
        return {"datasources": []}

    monkeypatch.setattr(mcp_proxy_main, "_execute_mcp_host_tool", _fake_execute)
    monkeypatch.setattr(mcp_proxy_main, "_connection_is_accessible", lambda context: True)
    monkeypatch.setattr(
        mcp_proxy_main,
        "_load_local_datasource_assets",
        lambda connection_id: [
            {"datasource_luid": "ds-1", "name": "管理费用数据源", "project_name": "财务"},
            {"datasource_luid": "ds-2", "name": "订单明细表", "project_name": "数据源"},
        ],
    )

    events = [
        event
        async for event in mcp_proxy_main.run_mcp_proxy_main_path(
            question="你有哪些数据源？",
            context=ToolContext(session_id="s1", user_id=7, connection_id=2, trace_id="trace-proxy"),
            intent_result=_intent("asset_inventory"),
        )
    ]

    assert calls[0]["tool_name"] == "list-datasources"
    final_data = events[-2].content["result"]["data"]
    assert final_data["response_type"] == "asset_candidates"
    assert final_data["response_data"]["source"] == "catalog_cache"
    assert final_data["response_data"]["total_count"] == 2
    assert [item["name"] for item in final_data["response_data"]["candidates"]] == ["管理费用数据源", "订单明细表"]
    assert "本地 catalog cache 缓存清单" in events[-1].content


@pytest.mark.asyncio
async def test_mcp_proxy_datasource_list_rejects_inaccessible_connection(monkeypatch):
    async def _unexpected_execute(**kwargs):
        raise AssertionError("must not call MCP for inaccessible connection")

    monkeypatch.setattr(mcp_proxy_main, "_execute_mcp_host_tool", _unexpected_execute)
    monkeypatch.setattr(mcp_proxy_main, "_connection_is_accessible", lambda context: False)

    events = [
        event
        async for event in mcp_proxy_main.run_mcp_proxy_main_path(
            question="列出有哪些数据源",
            context=ToolContext(session_id="s1", user_id=7, connection_id=2, trace_id="trace-proxy"),
            intent_result=_intent("asset_inventory"),
        )
    ]

    assert events[-1].type == "error"
    assert events[-1].content["error_code"] == "MCP_PROXY_CONNECTION_FORBIDDEN"
    assert "tableau_mcp" not in _tool_names(events)


class _FakeDb:
    def __init__(self):
        self.added = []
        self.updates = []

    def add(self, obj):
        self.added.append(obj)

    def commit(self):
        pass

    def refresh(self, obj):
        if getattr(obj, "id", None) is None:
            obj.id = uuid.uuid4()

    def query(self, model):
        return _FakeQuery(self)


class _FakeQuery:
    def __init__(self, db):
        self.db = db

    def filter(self, *args):
        return self

    def update(self, values, synchronize_session=False):
        self.db.updates.append(values)
        return 1


class _FakeSessionManager:
    def __init__(self):
        self.messages = []

    def persist_message(self, **kwargs):
        self.messages.append(kwargs)

    def get_conversation_messages(self, **kwargs):
        return []


class _NoEngine:
    async def run(self, *args, **kwargs):
        raise AssertionError("controlled path should handle data intents")
        yield AgentEvent(type="answer", content="unreachable")


@pytest.mark.asyncio
async def test_runner_keeps_legacy_path_when_mcp_proxy_flag_is_off(monkeypatch):
    monkeypatch.setenv("DATA_AGENT_CHAIN_MODE", "mcp_proxy")
    monkeypatch.delenv("DATA_AGENT_MCP_PROXY_ENABLED", raising=False)

    async def _legacy_path(**kwargs):
        yield AgentEvent(type="thinking", content="legacy")
        yield AgentEvent(type="answer", content="legacy answer")

    async def _proxy_path(**kwargs):
        raise AssertionError("DATA_AGENT_MCP_PROXY_ENABLED=false must not enter mcp_proxy")

    monkeypatch.setattr("services.data_agent.runner.run_mcp_first_main_path", _legacy_path)
    monkeypatch.setattr("services.data_agent.runner.run_mcp_proxy_main_path", _proxy_path)

    db = _FakeDb()
    session_mgr = _FakeSessionManager()
    session = AgentSession(conversation_id=uuid.uuid4(), user_id=7)
    context = ToolContext(session_id=str(session.conversation_id), user_id=7, connection_id=2, trace_id="t-legacy")

    events = [
        event
        async for event in run_agent(
            engine=_NoEngine(),
            context=context,
            session_mgr=session_mgr,
            session=session,
            question="整体销售额是多少",
            trace_id="t-legacy",
            current_user={"id": 7},
            db=db,
            connection_id=2,
            intent_result=classify_intent("整体销售额是多少", connection_type="tableau"),
            enforce_controlled_data_path=True,
        )
    ]

    assert [event.type for event in events] == ["metadata", "thinking", "thinking", "done"]
    assert "DATA_AGENT_MCP_PROXY_ENABLED" in events[1].content
    assert events[-1].content["answer"] == "legacy answer"
    assert db.updates[-1][BiAgentRun.status] == "completed"


@pytest.mark.asyncio
async def test_runner_emits_query_result_contract_for_mcp_proxy_table(monkeypatch):
    monkeypatch.setenv("DATA_AGENT_CHAIN_MODE", "mcp_proxy")
    monkeypatch.setenv("DATA_AGENT_MCP_PROXY_ENABLED", "true")

    async def _proxy_path(**kwargs):
        data = {
            "fields": ["指标"],
            "rows": [[100]],
            "chain_mode": "mcp_proxy",
            "table_display": {"columns": [{"name": "指标", "semantic_type": "metric"}]},
        }
        yield AgentEvent(type="tool_call", content={"tool": "tableau_mcp", "params": {}})
        yield AgentEvent(type="tool_result", content={"tool": "mcp_host_final_response", "result": {"data": data}})
        yield AgentEvent(type="answer", content="查询已完成")

    monkeypatch.setattr("services.data_agent.runner.run_mcp_proxy_main_path", _proxy_path)

    db = _FakeDb()
    session_mgr = _FakeSessionManager()
    session = AgentSession(conversation_id=uuid.uuid4(), user_id=7)
    context = ToolContext(session_id=str(session.conversation_id), user_id=7, connection_id=2, trace_id="t-proxy")

    events = [
        event
        async for event in run_agent(
            engine=_NoEngine(),
            context=context,
            session_mgr=session_mgr,
            session=session,
            question="整体销售额是多少",
            trace_id="t-proxy",
            current_user={"id": 7},
            db=db,
            connection_id=2,
            intent_result=classify_intent("整体销售额是多少", connection_type="tableau"),
            enforce_controlled_data_path=True,
        )
    ]

    done = events[-1].content
    assert done["response_type"] == "query_result"
    assert done["response_data"]["fields"] == ["指标"]
    assert done["response_data"]["rows"] == [[100]]
    assert done["response_data"]["table_display"]["columns"][0]["name"] == "指标"


@pytest.mark.asyncio
async def test_runner_routes_asset_question_decision_to_mcp_proxy(monkeypatch):
    monkeypatch.setenv("DATA_AGENT_CHAIN_MODE", "mcp_proxy")
    monkeypatch.setenv("DATA_AGENT_MCP_PROXY_ENABLED", "true")

    async def _proxy_path(**kwargs):
        yield AgentEvent(type="tool_result", content={
            "tool": "datasource_candidate_resolver",
            "result": {
                "data": {
                    "response_type": "asset_not_found",
                    "response_data": {"source": "catalog_cache", "message": "not found"},
                }
            },
        })
        yield AgentEvent(type="answer", content="not found")

    monkeypatch.setattr("services.data_agent.runner.run_mcp_proxy_main_path", _proxy_path)

    db = _FakeDb()
    session_mgr = _FakeSessionManager()
    session = AgentSession(conversation_id=uuid.uuid4(), user_id=7)
    context = ToolContext(session_id=str(session.conversation_id), user_id=7, connection_id=2, trace_id="t-asset")
    route_decision = RouteDecision(
        question_type="asset_question",
        confidence=0.95,
        route="schema_inventory",
        allowed_tools=["schema"],
        forbidden_tools=["query"],
        fallback_policy="schema_only",
        reason="asset_metadata_pattern",
        mode="enforce",
    )

    events = [
        event
        async for event in run_agent(
            engine=_NoEngine(),
            context=context,
            session_mgr=session_mgr,
            session=session,
            question="介绍管理费用数据源",
            trace_id="t-asset",
            current_user={"id": 7},
            db=db,
            connection_id=2,
            route_decision=route_decision,
            intent_result=IntentClassification(intent="unknown", confidence=0.35, route_reason="test"),
            enforce_controlled_data_path=True,
        )
    ]

    done = events[-1].content
    assert done["response_type"] == "asset_not_found"
    assert done["response_data"]["source"] == "catalog_cache"


@pytest.mark.asyncio
async def test_runner_routes_datasource_list_schema_inventory_decision_to_mcp_proxy(monkeypatch):
    monkeypatch.setenv("DATA_AGENT_CHAIN_MODE", "mcp_proxy")
    monkeypatch.setenv("DATA_AGENT_MCP_PROXY_ENABLED", "true")

    async def _proxy_path(**kwargs):
        yield AgentEvent(type="tool_result", content={
            "tool": "tableau_mcp",
            "result": {
                "data": {
                    "response_type": "asset_candidates",
                    "response_data": {
                        "source": "mcp",
                        "candidates": [{"datasource_luid": "ds-1", "name": "销售数据源"}],
                    },
                }
            },
        })
        yield AgentEvent(type="answer", content="listed")

    monkeypatch.setattr("services.data_agent.runner.run_mcp_proxy_main_path", _proxy_path)

    db = _FakeDb()
    session_mgr = _FakeSessionManager()
    session = AgentSession(conversation_id=uuid.uuid4(), user_id=7)
    context = ToolContext(session_id=str(session.conversation_id), user_id=7, connection_id=2, trace_id="t-list")
    route_decision = RouteDecision(
        question_type="asset_question",
        confidence=0.95,
        route="schema_inventory",
        allowed_tools=["schema"],
        forbidden_tools=["query"],
        fallback_policy="schema_only",
        reason="datasource_list_pattern",
        mode="enforce",
    )

    events = [
        event
        async for event in run_agent(
            engine=_NoEngine(),
            context=context,
            session_mgr=session_mgr,
            session=session,
            question="有哪些数据源",
            trace_id="t-list",
            current_user={"id": 7},
            db=db,
            connection_id=2,
            route_decision=route_decision,
            intent_result=IntentClassification(intent="unknown", confidence=0.35, route_reason="test"),
            enforce_controlled_data_path=True,
        )
    ]

    done = events[-1].content
    assert done["response_type"] == "asset_candidates"
    assert done["response_data"]["source"] == "mcp"
    assert done["response_data"]["candidates"][0]["datasource_luid"] == "ds-1"

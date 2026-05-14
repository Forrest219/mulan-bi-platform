import json

import pytest

from services.data_agent import mcp_proxy_main
from services.data_agent.intent_classifier import IntentClassification
from services.data_agent.tool_base import ToolContext


pytestmark = pytest.mark.skip_db


class _FakeLLM:
    def __init__(self, payload):
        self.payload = payload

    async def complete(self, *, prompt, system=None, timeout=None, purpose=None):
        assert purpose == "data_agent_mcp_proxy_args"
        assert "Do not create QuerySpec" in system
        return {"content": json.dumps(self.payload, ensure_ascii=False)}


def _intent(intent: str = "aggregate") -> IntentClassification:
    return IntentClassification(intent=intent, confidence=0.95, route_reason="mcp proxy baseline")


def _context() -> ToolContext:
    return ToolContext(session_id="eval-session", user_id=7, connection_id=2, trace_id="trace-mcp-p0")


def _datasource(**overrides):
    payload = {"name": "Superstore", "luid": "ds-1", "asset_id": 1}
    payload.update(overrides)
    return payload


def _patch_datasource(monkeypatch, *, fields, datasource=None):
    monkeypatch.setattr(
        mcp_proxy_main,
        "_resolve_datasource",
        lambda question, context, datasource_name_hint: datasource or _datasource(),
    )
    monkeypatch.setattr(
        mcp_proxy_main,
        "_queryable_fields",
        lambda ds_info, connection_id=None: fields,
    )


async def _run_proxy(monkeypatch, *, question, llm_args, fields, mcp_result=None, datasource=None):
    _patch_datasource(monkeypatch, fields=fields, datasource=datasource)
    executed_args = {}

    async def _fake_execute(args, context):
        executed_args.update(args)
        if isinstance(mcp_result, Exception):
            raise mcp_result
        return mcp_result or {"fields": ["value"], "rows": [[1]]}

    monkeypatch.setattr(mcp_proxy_main, "_execute_query_datasource_args", _fake_execute)

    events = [
        event
        async for event in mcp_proxy_main.run_mcp_proxy_main_path(
            question=question,
            context=_context(),
            intent_result=_intent(),
            llm_service=_FakeLLM(llm_args),
        )
    ]
    return events, executed_args


def _tool_names(events):
    return [
        event.content["tool"]
        for event in events
        if event.type in {"tool_call", "tool_result"} and isinstance(event.content, dict)
    ]


def _guardrail_payload(events):
    return next(
        event.content["result"]["data"]
        for event in events
        if event.type == "tool_result" and event.content.get("tool") == "mcp_args_guardrail"
    )


def _mcp_payload(events):
    return next(
        event.content["result"]["data"]
        for event in events
        if event.type == "tool_result" and event.content.get("tool") == "tableau_mcp"
    )


def _assert_no_legacy_fallback(events):
    names = _tool_names(events)
    assert "llm_queryspec" not in names
    assert "queryspec_validator" not in names
    assert "queryspec_fallback" not in names


@pytest.mark.asyncio
async def test_p0_profit_rate_does_not_add_customer_count(monkeypatch):
    events, executed_args = await _run_proxy(
        monkeypatch,
        question="按地区看利润率",
        fields=["地区", "利润率", "销售额", "利润", "客户数"],
        llm_args={
            "datasourceLuid": "ds-1",
            "query": {
                "fields": [{"fieldCaption": "地区"}, {"fieldCaption": "利润率", "function": "AVG"}],
                "filters": [],
            },
            "limit": 20,
        },
        mcp_result={"fields": ["地区", "AVG(利润率)"], "rows": [["华东", 0.18]]},
    )

    _assert_no_legacy_fallback(events)
    assert _guardrail_payload(events)["decision"] == "allow"
    serialized_args = json.dumps(executed_args, ensure_ascii=False)
    assert "利润率" in serialized_args
    assert "客户数" not in serialized_args


@pytest.mark.asyncio
async def test_p0_negative_semantics_not_rewritten_to_positive_sales_topn(monkeypatch):
    events, executed_args = await _run_proxy(
        monkeypatch,
        question="最近 30 天没有发生销售的客户 Top 10",
        fields=["客户名称", "销售额"],
        llm_args={
            "datasourceLuid": "ds-1",
            "query": {
                "fields": [{"fieldCaption": "客户名称"}, {"fieldCaption": "销售额", "function": "SUM"}],
                "order_by": [{"fieldCaption": "销售额", "direction": "DESC"}],
                "filters": [{"fieldCaption": "销售额", "operator": ">", "value": 0}],
            },
            "limit": 10,
        },
    )

    _assert_no_legacy_fallback(events)
    assert executed_args == {}
    assert events[-1].type == "error"
    assert events[-1].content["error_code"] == "MCP_ARGS_SEMANTIC_MISMATCH"
    assert events[-1].content["fallback_type"] == "guardrail_rejected"


@pytest.mark.asyncio
async def test_p0_topn_ranks_by_requested_metric_not_order_id(monkeypatch):
    events, executed_args = await _run_proxy(
        monkeypatch,
        question="销售额最高的前 5 个客户",
        fields=["客户名称", "销售额", "订单 ID"],
        llm_args={
            "datasourceLuid": "ds-1",
            "query": {
                "fields": [{"fieldCaption": "客户名称"}, {"fieldCaption": "销售额", "function": "SUM"}],
                "order_by": [{"fieldCaption": "销售额", "direction": "DESC"}],
            },
            "limit": 5,
        },
        mcp_result={"fields": ["客户名称", "SUM(销售额)"], "rows": [["A", 1000], ["B", 900]]},
    )

    _assert_no_legacy_fallback(events)
    assert _guardrail_payload(events)["decision"] == "allow"
    serialized_args = json.dumps(executed_args, ensure_ascii=False)
    assert "销售额" in serialized_args
    assert "订单 ID" not in serialized_args


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("question", "granularity"),
    [
        ("按月看 2025 年销售趋势", "month"),
        ("按年看销售趋势", "year"),
    ],
)
async def test_p0_trend_uses_requested_time_granularity(monkeypatch, question, granularity):
    events, executed_args = await _run_proxy(
        monkeypatch,
        question=question,
        fields=["订单日期", "销售额"],
        llm_args={
            "datasourceLuid": "ds-1",
            "query": {
                "fields": [
                    {"fieldCaption": "订单日期", "date_part": granularity},
                    {"fieldCaption": "销售额", "function": "SUM"},
                ],
                "granularity": granularity,
            },
            "limit": 24,
        },
        mcp_result={"fields": ["订单日期", "SUM(销售额)"], "rows": [["2025-01", 100]]},
    )

    _assert_no_legacy_fallback(events)
    assert _guardrail_payload(events)["decision"] == "allow"
    assert executed_args["query"]["granularity"] == granularity
    assert executed_args["query"]["fields"][0]["date_part"] == granularity


@pytest.mark.asyncio
async def test_p0_attribution_does_not_invent_causality(monkeypatch):
    events, executed_args = await _run_proxy(
        monkeypatch,
        question="为什么华东利润率下降？",
        fields=["地区", "月份", "利润率", "销售额", "折扣"],
        llm_args={
            "datasourceLuid": "ds-1",
            "query": {
                "fields": [
                    {"fieldCaption": "月份"},
                    {"fieldCaption": "利润率", "function": "AVG"},
                    {"fieldCaption": "销售额", "function": "SUM"},
                    {"fieldCaption": "折扣", "function": "AVG"},
                ],
                "filters": [{"fieldCaption": "地区", "operator": "=", "value": "华东"}],
            },
            "limit": 12,
        },
        mcp_result={
            "fields": ["月份", "AVG(利润率)", "SUM(销售额)", "AVG(折扣)"],
            "rows": [["2025-01", 0.21, 1000, 0.08], ["2025-02", 0.18, 1200, 0.1]],
        },
    )

    _assert_no_legacy_fallback(events)
    assert executed_args
    assert "因为" not in events[-1].content
    assert "导致" not in events[-1].content
    assert "原因" not in events[-1].content
    assert _mcp_payload(events)["rows"] == [["2025-01", 0.21, 1000, 0.08], ["2025-02", 0.18, 1200, 0.1]]


@pytest.mark.asyncio
async def test_p0_field_hallucination_can_map_but_must_record_repair(monkeypatch):
    events, executed_args = await _run_proxy(
        monkeypatch,
        question="按订单日期看月度销售额",
        fields=["发货日期", "销售额"],
        datasource=_datasource(safe_field_synonyms={"订单日期": "发货日期"}),
        llm_args={
            "datasourceLuid": "ds-1",
            "query": {
                "fields": [{"fieldCaption": "订单日期"}, {"fieldCaption": "销售额", "function": "SUM"}],
                "granularity": "month",
            },
            "limit": 12,
        },
        mcp_result={"fields": ["发货日期", "SUM(销售额)"], "rows": [["2025-01", 100]]},
    )

    _assert_no_legacy_fallback(events)
    guardrail = _guardrail_payload(events)
    assert guardrail["decision"] == "repair"
    assert guardrail["repairs"][0]["type"] == "field_mapping"
    assert guardrail["repairs"][0]["before"] == "订单日期"
    assert guardrail["repairs"][0]["after"] == "发货日期"
    assert executed_args["query"]["fields"][0]["fieldCaption"] == "发货日期"


@pytest.mark.asyncio
@pytest.mark.parametrize("limit_payload", [{}, {"limit": 10000}])
async def test_p0_detail_scan_without_safe_limit_is_rejected(monkeypatch, limit_payload):
    llm_args = {
        "datasourceLuid": "ds-1",
        "query": {
            "operation": "detail",
            "fields": [{"fieldCaption": "订单 ID"}, {"fieldCaption": "客户名称"}, {"fieldCaption": "销售额"}],
        },
        **limit_payload,
    }
    events, executed_args = await _run_proxy(
        monkeypatch,
        question="导出所有订单明细",
        fields=["订单 ID", "客户名称", "销售额"],
        llm_args=llm_args,
    )

    _assert_no_legacy_fallback(events)
    assert executed_args == {}
    assert events[-1].type == "error"
    assert events[-1].content["error_code"] == "MCP_ARGS_UNSAFE_DETAIL_SCAN"
    assert "明细扫描" in events[-1].content["message"]


@pytest.mark.asyncio
async def test_p0_forbidden_non_current_datasource_is_rejected(monkeypatch):
    events, executed_args = await _run_proxy(
        monkeypatch,
        question="查询另一个数据源的销售额",
        fields=["销售额"],
        llm_args={
            "datasourceLuid": "ds-2",
            "query": {"fields": [{"fieldCaption": "销售额", "function": "SUM"}]},
            "limit": 20,
        },
    )

    _assert_no_legacy_fallback(events)
    assert executed_args == {}
    assert events[-1].type == "error"
    assert events[-1].content["error_code"] == "MCP_ARGS_DATASOURCE_FORBIDDEN"
    assert events[-1].content["user_hint"]


@pytest.mark.asyncio
async def test_p0_large_result_is_rejected_with_explanation(monkeypatch):
    fields = [f"字段{i}" for i in range(1, 22)]
    events, executed_args = await _run_proxy(
        monkeypatch,
        question="给我一个很宽的汇总结果",
        fields=fields,
        llm_args={
            "datasourceLuid": "ds-1",
            "query": {"fields": [{"fieldCaption": field} for field in fields]},
            "limit": 50,
        },
    )

    _assert_no_legacy_fallback(events)
    assert executed_args == {}
    assert events[-1].type == "error"
    assert events[-1].content["error_code"] == "MCP_ARGS_RESULT_TOO_WIDE"
    assert "字段数过多" in events[-1].content["message"]


@pytest.mark.asyncio
async def test_p0_mcp_failure_returns_standard_fallback_without_old_metric_completion(monkeypatch):
    events, executed_args = await _run_proxy(
        monkeypatch,
        question="整体销售额是多少？",
        fields=["销售额", "利润", "客户数"],
        llm_args={
            "datasourceLuid": "ds-1",
            "query": {"fields": [{"fieldCaption": "销售额", "function": "SUM"}]},
            "limit": 20,
        },
        mcp_result=RuntimeError("mcp timeout"),
    )

    _assert_no_legacy_fallback(events)
    assert executed_args["query"]["fields"] == [{"fieldCaption": "销售额", "function": "SUM"}]
    assert events[-1].type == "error"
    assert events[-1].content["fallback_type"] == "guardrail_rejected"
    assert events[-1].content["error_code"] == "MCP_PROXY_EXECUTION_FAILED"
    assert "客户数" not in json.dumps(events[-1].content, ensure_ascii=False)

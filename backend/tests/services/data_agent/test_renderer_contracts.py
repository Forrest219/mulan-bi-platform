"""Renderer and table contract tests that are independent of legacy QuerySpec routes."""

import json

import pytest

from services.data_agent.answer_prompt_builder import build_answer_prompt, build_renderer_input
from services.data_agent.semantic_operators.set_difference import build_set_difference_response_data
from services.data_agent.table_display import infer_table_display_schema

pytestmark = pytest.mark.skip_db


def test_renderer_input_does_not_leak_missing_metric_calculation_hints():
    messages = build_answer_prompt(
        question="Give me a summary",
        response_data={
            "fields": ["SUM(Sales)", "SUM(Profit)"],
            "rows": [[100, 25]],
            "derived_columns": [{"name": "Profit Rate", "value": 0.25}],
            "summary": "Profit Rate 25%",
        },
        rendering_skill_content="Only restate returned data.",
    )

    joined = "\n".join(message["content"] for message in messages)
    assert "不得计算任何业务指标" in joined
    assert "SUM(Sales)" in joined
    assert "SUM(Profit)" in joined
    assert "0.25" not in joined
    assert "derived_columns" not in joined


def test_renderer_input_surfaces_structured_mcp_error_without_fallback_diagnostics():
    renderer_input = build_renderer_input(
        question="original question",
        response_data={
            "fields": [],
            "rows": [],
            "error": "mcp natural-language query tool unavailable",
            "error_code": "MCP_NL_TOOL_UNAVAILABLE",
            "message": "MCP tool unavailable.",
            "structured_error": {
                "error_code": "MCP_NL_TOOL_UNAVAILABLE",
                "message": "MCP tool unavailable.",
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

    assert [column["key"] for column in schema["columns"]] == [
        "SUM(销售额)",
        "COUNTD(客户名称)",
        "利润率",
    ]
    assert [column["label"] for column in schema["columns"]] == ["销售额", "客户数", "利润率"]
    assert "COUNTD(客户名称)" in json.dumps(schema, ensure_ascii=False)


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
    assert response_data["diagnostics"]["universe_count"] == 3
    assert response_data["diagnostics"]["occurred_count"] == 2
    assert response_data["diagnostics"]["difference_count"] == 2
    assert response_data["fallback_trace_event"] == "FALLBACK_TRIGGERED"
    assert response_data["table_display"]["columns"][0]["key"] == "entity_key"

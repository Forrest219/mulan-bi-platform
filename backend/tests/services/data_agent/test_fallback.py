from services.data_agent.fallback import (
    fallback_from_tool_result,
    fallback_type_from_error,
    make_clarification_fallback,
    make_router_blocked_fallback,
)
from services.data_agent.router_guardrail import classify_homepage_question


def test_clarification_fallback_has_standard_shape():
    decision = classify_homepage_question("???")
    fallback = make_clarification_fallback(trace_id="t1", route_decision=decision).to_dict()

    assert fallback["type"] == "fallback"
    assert fallback["fallback_type"] == "clarification_required"
    assert fallback["error_code"] == "ROUTER_CLARIFY_REQUIRED"
    assert fallback["trace_id"] == "t1"
    assert fallback["tools_used"] == []
    assert fallback["suggested_actions"] == ["查看数据资产/字段结构", "查询业务数据/指标"]


def test_router_blocked_fallback_records_guardrail_error():
    decision = classify_homepage_question("2024 年销售额是多少？")
    fallback = make_router_blocked_fallback(
        tool_name="schema",
        trace_id="t2",
        route_decision=decision,
    ).to_dict()

    assert fallback["fallback_type"] == "router_guardrail_blocked"
    assert fallback["error_code"] == "ROUTER_GUARDRAIL_BLOCKED"
    assert fallback["tools_used"] == ["schema"]
    assert fallback["route_decision"]["question_type"] == "data_question"


def test_fallback_from_query_tool_field_unavailable():
    fallback = fallback_from_tool_result(
        {
            "success": True,
            "data": {
                "field_unavailable": {
                    "requested": "国家/地区",
                    "suggestion": "省/自治区",
                }
            },
        },
        trace_id="t3",
    ).to_dict()

    assert fallback["fallback_type"] == "field_unavailable"
    assert fallback["error_code"] == "QUERY_001"
    assert "国家/地区" in fallback["message"]
    assert "省/自治区" in fallback["user_hint"]


def test_fallback_type_from_error_maps_timeout_and_auth():
    assert fallback_type_from_error(error_code="NLQ_007") == "query_timeout"
    assert fallback_type_from_error(error_code="NLQ_009") == "auth_or_permission_failed"
    assert fallback_type_from_error(message="[NLQ_008] 无法找到匹配的数据源") == "datasource_not_matched"

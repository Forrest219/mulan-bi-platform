import pytest

from services.data_agent.router_guardrail import classify_homepage_question, validate_tool_allowed


def _guardrail_action(decision):
    return getattr(decision, "guardrail_action", decision.route)


def _route_advisory(decision):
    return getattr(decision, "route_advisory", None)


def _assert_not_router_clarification(decision):
    assert _guardrail_action(decision) in {"allow", "advisory"}
    assert decision.route != "clarify"
    assert decision.fallback_policy != "clarify_only"


@pytest.mark.parametrize(
    "question",
    [
        "当前连接有哪些数据源？",
        "订单+ (示例 - 超市) 有哪些字段？",
        "请查看 Tableau 数据资产 月度指标汇总表 的表结构",
        "这个 workbook 的所有者和更新时间是什么？",
    ],
)
def test_asset_question_routes_schema_only(question):
    decision = classify_homepage_question(question)

    assert decision.question_type == "asset_question"
    assert decision.route == "schema_inventory"
    assert decision.allowed_tools == ["schema"]
    assert "query" in decision.forbidden_tools
    assert decision.fallback_policy == "schema_only"
    assert _guardrail_action(decision) == "allow"
    assert _route_advisory(decision) is None


@pytest.mark.parametrize(
    "question",
    [
        "2024 年销售额是多少？",
        "过去几年利润趋势是什么样子？",
        "2025 年没有销售记录的子类别有哪些？",
        "Top 10 大客户是谁？",
        "哪些省份一直亏损？",
        "辽宁、福建 2024 巨亏原因是什么？",
        "画一个过去四年销售额趋势图",
    ],
)
def test_data_question_routes_query_only(question):
    decision = classify_homepage_question(question)

    assert decision.question_type == "data_question"
    assert decision.route == "data_query"
    assert decision.allowed_tools == ["query"]
    assert "schema" in decision.forbidden_tools
    assert decision.fallback_policy == "data_only"
    assert _guardrail_action(decision) == "allow"
    assert _route_advisory(decision) is None


@pytest.mark.parametrize(
    ("question", "expected_type"),
    [
        ("月度指标汇总表 有哪些字段", "asset_question"),
        ("2024 年月度指标汇总表销售额", "data_question"),
        ("哪些渠道过去几年利润一直在涨", "data_question"),
    ],
)
def test_conflict_resolution(question, expected_type):
    assert classify_homepage_question(question).question_type == expected_type


@pytest.mark.parametrize("question", ["帮我查一下", "看看数据", "看一下", "这个怎么样", "大屏在哪"])
def test_low_confidence_ambiguous_question_returns_advisory(question):
    decision = classify_homepage_question(question)

    assert decision.question_type == "ambiguous"
    assert decision.route == "advisory"
    assert _guardrail_action(decision) == "advisory"
    assert decision.needs_clarification is False
    assert decision.allowed_tools == ["schema", "query"]
    assert decision.forbidden_tools == []
    assert decision.fallback_policy == "advisory"
    advisory = _route_advisory(decision)
    assert isinstance(advisory, dict)
    assert advisory.get("action") == "advisory"
    assert advisory.get("is_authoritative") is False
    assert set(advisory.get("allowed_tool_hints") or []) >= {"schema", "query"}


def test_dashboard_inventory_question_is_asset_or_advisory_not_clarification():
    decision = classify_homepage_question("你有哪些看板？")

    _assert_not_router_clarification(decision)
    if _guardrail_action(decision) == "advisory":
        advisory = _route_advisory(decision)
        assert isinstance(advisory, dict)
        assert advisory.get("action") == "advisory"
        assert advisory.get("is_authoritative") is False


@pytest.mark.parametrize("question", ["", "???", "!", "hi", "删除所有数据", "有哪些字段销售额是多少？"])
def test_hard_ambiguous_question_requires_clarification(question):
    decision = classify_homepage_question(question)

    assert decision.question_type == "ambiguous"
    assert decision.route == "clarify"
    assert _guardrail_action(decision) == "clarify"
    assert decision.needs_clarification is True
    assert decision.fallback_policy == "clarify_only"
    assert "schema" in decision.forbidden_tools
    assert "query" in decision.forbidden_tools
    assert _route_advisory(decision) is None
    assert validate_tool_allowed("schema", decision)[0] is False
    assert validate_tool_allowed("query", decision)[0] is False


def test_validate_tool_allowed_blocks_forbidden_schema_for_data_question():
    decision = classify_homepage_question("2024 年各省份销售额是多少？")

    allowed, reason = validate_tool_allowed("schema", decision)

    assert allowed is False
    assert reason == "tool_forbidden_by_route"
    assert validate_tool_allowed("query", decision) == (True, None)


@pytest.mark.parametrize("tool_name", ["schema", "query"])
def test_validate_tool_allowed_does_not_block_advisory_handoff(tool_name):
    decision = classify_homepage_question("你有哪些看板？")

    assert validate_tool_allowed(tool_name, decision) == (True, None)

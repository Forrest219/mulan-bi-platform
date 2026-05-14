import pytest

from services.data_agent.router_guardrail import classify_homepage_question, validate_tool_allowed


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


@pytest.mark.parametrize("question", ["帮我查一下", "看看数据", "有哪些", "介绍一下这个数据源"])
def test_ambiguous_question_requires_clarification(question):
    decision = classify_homepage_question(question)

    assert decision.question_type == "ambiguous"
    assert decision.route == "clarify"
    assert decision.fallback_policy == "clarify_only"
    assert "schema" in decision.forbidden_tools
    assert "query" in decision.forbidden_tools


def test_validate_tool_allowed_blocks_forbidden_schema_for_data_question():
    decision = classify_homepage_question("2024 年各省份销售额是多少？")

    allowed, reason = validate_tool_allowed("schema", decision)

    assert allowed is False
    assert reason == "tool_forbidden_by_route"
    assert validate_tool_allowed("query", decision) == (True, None)

import pytest

from services.data_agent.intent_classifier import classify_intent


pytestmark = pytest.mark.skip_db


@pytest.mark.parametrize(
    ("question", "intent"),
    [
        ("统计每个区域的收入合计", "aggregate"),
        ("按利润列出前十个产品", "ranking"),
        ("列出最近有交易记录的客户名单", "customer_record"),
        ("过去六个月的订单量走势", "trend_condition"),
        ("哪些渠道每个月利润都为正", "all_period_condition"),
        ("找出去年有订单但今年没有订单的客户", "set_difference"),
        ("为什么本季度毛利下降", "root_cause"),
        ("当前连接有哪些数据源", "asset_inventory"),
    ],
)
def test_classifies_supported_generic_bi_intents(question, intent):
    result = classify_intent(question, connection_type="tableau")

    assert result.intent == intent
    assert result.confidence > 0.5
    assert result.route_reason


@pytest.mark.parametrize(
    "question",
    [
        "你好",
        "随便看看",
        "今天天气如何",
    ],
)
def test_classifies_low_signal_or_non_bi_questions_as_unknown(question):
    result = classify_intent(question)

    assert result.intent == "unknown"
    assert result.confidence <= 0.35


def test_schema_inventory_wins_over_metric_like_asset_wording():
    result = classify_intent("请查看这个数据资产有哪些字段", connection_type="tableau")

    assert result.intent == "asset_inventory"
    assert result.is_asset_inventory is True

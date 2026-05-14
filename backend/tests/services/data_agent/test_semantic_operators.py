from dataclasses import asdict

import pytest

from services.data_agent.query_plan import QueryPlanContext
from services.data_agent.semantic_operators.all_period_condition import AllPeriodConditionOperator
from services.data_agent.semantic_operators.contribution_share import ContributionShareOperator
from services.data_agent.semantic_operators.customer_record import CustomerRecordOperator
from services.data_agent.semantic_operators.ranking import RankingOperator
from services.data_agent.semantic_operators.registry import default_registry
from services.data_agent.semantic_operators.root_cause import RootCauseOperator
from services.data_agent.semantic_operators.set_difference import SetDifferenceOperator
from services.data_agent.semantic_operators.trend_condition import TrendConditionOperator


@pytest.fixture
def base_ctx():
    return QueryPlanContext(
        question="2024 年 Top10 大客户及占比",
        datasource_luid="ds1",
        datasource_name="订单",
        connection_id=1,
        fields=["订单日期", "客户名称", "省/自治区", "类别", "销售额", "利润"],
        metric="销售额",
        dimensions=["客户名称"],
        time_field="订单日期",
        filters=[
            {
                "field": {"fieldCaption": "订单日期"},
                "filterType": "QUANTITATIVE_DATE",
                "quantitativeFilterType": "RANGE",
                "minDate": "2024-01-01",
                "maxDate": "2024-12-31",
            }
        ],
    )


def test_registry_matches_contribution_share_before_ranking(base_ctx):
    match = default_registry().match(base_ctx)

    assert match is not None
    assert match.operator.name == "contribution_share"


def test_ranking_builds_sorted_limited_topn_step(base_ctx):
    ctx = QueryPlanContext(
        **{**asdict(base_ctx), "question": "销售额最高的 5 个客户", "params": {"n": 5}}
    )
    step = RankingOperator().build_steps(ctx)[0]

    assert step.result_shape == "ranked_table"
    assert step.max_fetch_rows == 5
    assert step.vizql_json["fields"][1]["sortDirection"] == "DESC"


def test_ranking_builds_bottomn_ascending_step(base_ctx):
    ctx = QueryPlanContext(
        **{**asdict(base_ctx), "question": "利润最低的 3 个客户", "metric": "利润", "params": {"n": 3}}
    )
    step = RankingOperator().build_steps(ctx)[0]

    assert step.max_fetch_rows == 3
    assert step.vizql_json["fields"][1]["fieldCaption"] == "利润"
    assert step.vizql_json["fields"][1]["sortDirection"] == "ASC"


def test_ranking_reduce_adds_generic_share(base_ctx):
    result = RankingOperator().reduce(
        QueryPlanContext(**{**asdict(base_ctx), "params": {"n": 2}}),
        {
            "ranked_groups": {"fields": ["客户名称", "SUM(销售额)"], "rows": [["A", 30], ["B", 20]]},
            "total_metric": {"fields": ["SUM(销售额)"], "rows": [[100]]},
        },
    )

    assert result.fields == ["客户名称", "SUM(销售额)", "销售额占比"]
    assert result.rows == [["A", 30, "30.00%"], ["B", 20, "20.00%"]]
    assert result.diagnostics["denominator"] == 100
    assert result.table_display is not None
    assert result.table_display["columns"][0]["align"] == "left"
    assert result.table_display["columns"][1]["label"] == "销售额"
    assert result.table_display["columns"][1]["align"] == "right"
    assert result.table_display["columns"][2]["semantic_type"] == "derived_metric"
    assert result.table_display["columns"][2]["value_type"] == "percent"
    assert result.table_display["columns"][2]["format"] == "percent"
    assert result.table_display["columns"][2]["align"] == "right"


def test_contribution_share_builds_group_and_total_steps(base_ctx):
    steps = ContributionShareOperator().build_steps(base_ctx)

    assert [step.name for step in steps] == ["group_metric", "total_metric"]
    assert steps[0].vizql_json["fields"][1]["sortDirection"] == "DESC"
    assert steps[0].max_fetch_rows == 11
    assert steps[1].vizql_json["fields"] == [{"fieldCaption": "销售额", "function": "SUM"}]


def test_contribution_share_reduce_uses_total_denominator(base_ctx):
    result = ContributionShareOperator().reduce(
        base_ctx,
        {
            "group_metric": {"fields": ["客户名称", "SUM(销售额)"], "rows": [["A", 30], ["B", 20]]},
            "total_metric": {"fields": ["SUM(销售额)"], "rows": [[100]]},
        },
    )

    assert result.fields == ["客户名称", "销售额", "销售额占比"]
    assert result.rows == [["A", 30.0, "30.00%"], ["B", 20.0, "20.00%"]]
    assert result.diagnostics["denominator"] == 100
    assert result.table_display is not None
    assert result.table_display["columns"][0]["align"] == "left"
    assert result.table_display["columns"][1]["label"] == "销售额"
    assert result.table_display["columns"][1]["align"] == "right"
    assert result.table_display["columns"][2]["semantic_type"] == "derived_metric"
    assert result.table_display["columns"][2]["value_type"] == "percent"
    assert result.table_display["columns"][2]["format"] == "percent"
    assert result.table_display["columns"][2]["align"] == "right"


def test_set_difference_returns_count_and_sample(base_ctx):
    ctx = QueryPlanContext(
        **{
            **asdict(base_ctx),
            "question": "2025 年没有销售记录的子类别有哪些？",
            "dimensions": ["子类别"],
            "params": {"definition": "全量子类别 - 2025 有销售子类别"},
        }
    )
    result = SetDifferenceOperator().reduce(
        ctx,
        {
            "base_keys": {"fields": ["子类别"], "rows": [["电话"], ["椅子"], ["桌子"]]},
            "compare_keys": {"fields": ["子类别"], "rows": [["椅子"]]},
        },
    )

    assert result.rows == [["桌子"], ["电话"]]
    assert result.diagnostics["difference_count"] == 2
    assert result.result_shape == "key_set"


def test_set_difference_builds_universe_minus_occurred_steps(base_ctx):
    ctx = QueryPlanContext(
        **{
            **asdict(base_ctx),
            "dimensions": ["子类别"],
            "params": {
                "target_dimension": "子类别",
                "universe_filters": [{"field": {"fieldCaption": "类别"}, "filterType": "SET", "values": ["技术"]}],
                "exclude_filters": [{"field": {"fieldCaption": "订单日期"}, "filterType": "DATE", "values": ["2025"]}],
            },
        }
    )
    steps = SetDifferenceOperator().build_steps(ctx)

    assert [step.name for step in steps] == ["universe_keys", "occurred_keys"]
    assert steps[0].vizql_json["fields"] == [{"fieldCaption": "子类别"}]
    assert steps[1].vizql_json["filters"] == [
        {"field": {"fieldCaption": "类别"}, "filterType": "SET", "values": ["技术"]},
        {"field": {"fieldCaption": "订单日期"}, "filterType": "DATE", "values": ["2025"]},
    ]


def test_trend_condition_reduce_returns_monotonic_growth_matches(base_ctx):
    ctx = QueryPlanContext(
        **{
            **asdict(base_ctx),
            "question": "哪个子类别利润每年持续增长？",
            "metric": "利润",
            "dimensions": ["子类别"],
        }
    )
    result = TrendConditionOperator().reduce(
        ctx,
        {
            "series_by_dimension": {
                "fields": ["YEAR(订单日期)", "子类别", "SUM(利润)"],
                "rows": [
                    [2022, "电话", 10],
                    [2023, "电话", 20],
                    [2024, "电话", 30],
                    [2022, "椅子", 5],
                    [2023, "椅子", 4],
                ],
            }
        },
    )

    assert result.rows[0][:5] == ["电话", True, 3, 10.0, 30.0]
    assert len(result.rows) == 1


def test_trend_condition_uses_target_dimension_and_complete_periods(base_ctx):
    ctx = QueryPlanContext(
        **{
            **asdict(base_ctx),
            "question": "哪个子类别指标每年非严格递增？",
            "dimensions": ["类别", "子类别"],
            "params": {
                "target_dimension": "子类别",
                "direction": "increasing",
                "strict": False,
                "expected_periods": [2022, 2023, 2024],
            },
        }
    )
    step = TrendConditionOperator().build_steps(ctx)[0]
    result = TrendConditionOperator().reduce(
        ctx,
        {
            "series_by_dimension": {
                "fields": ["YEAR(订单日期)", "类别", "子类别", "SUM(销售额)"],
                "rows": [
                    [2022, "技术", "电话", 10],
                    [2023, "技术", "电话", 10],
                    [2024, "技术", "电话", 20],
                    [2022, "家具", "椅子", 5],
                    [2024, "家具", "椅子", 6],
                ],
            }
        },
    )

    assert step.vizql_json["fields"][1] == {"fieldCaption": "子类别"}
    assert result.rows == [["电话", True, 3, 10.0, 20.0, 1.0]]
    assert result.explain["direction"] == "non_decreasing"
    assert result.explain["complete_periods"] is True


def test_all_period_condition_reduce_finds_always_loss(base_ctx):
    ctx = QueryPlanContext(
        **{
            **asdict(base_ctx),
            "question": "哪些省份一直亏损？",
            "metric": "利润",
            "dimensions": ["省/自治区"],
        }
    )
    result = AllPeriodConditionOperator().reduce(
        ctx,
        {
            "period_metric_by_dimension": {
                "fields": ["YEAR(订单日期)", "省/自治区", "SUM(利润)"],
                "rows": [
                    [2022, "辽宁", -10],
                    [2023, "辽宁", -20],
                    [2024, "辽宁", -30],
                    [2022, "福建", -5],
                    [2023, "福建", 1],
                ],
            }
        },
    )

    assert result.rows == [["辽宁", True, 3, []]]
    assert result.explain["predicate"] == {"op": "<", "value": 0}


def test_all_period_condition_uses_generic_predicate_and_period_coverage(base_ctx):
    ctx = QueryPlanContext(
        **{
            **asdict(base_ctx),
            "question": "哪些区域每期均满足条件？",
            "metric": "销售额",
            "dimensions": ["区域"],
            "params": {
                "target_dimension": "区域",
                "predicate": {"op": ">=", "value": 10},
                "expected_periods": [2022, 2023],
            },
        }
    )
    result = AllPeriodConditionOperator().reduce(
        ctx,
        {
            "period_metric_by_dimension": {
                "fields": ["YEAR(订单日期)", "区域", "SUM(销售额)"],
                "rows": [
                    [2022, "东区", 10],
                    [2023, "东区", 12],
                    [2022, "西区", 11],
                    [2023, "西区", 9],
                    [2022, "北区", 20],
                ],
            }
        },
    )

    assert result.rows == [["东区", True, 2, []]]
    assert result.explain["predicate"] == {"op": ">=", "value": 10}
    assert result.explain["complete_periods"] is True


def test_customer_record_builds_entity_period_metric_step_and_reduces_last_period(base_ctx):
    ctx = QueryPlanContext(
        **{
            **asdict(base_ctx),
            "operator_hint": "customer_record",
            "params": {
                "entity_field": "客户名称",
                "entity_value": "样例客户",
                "metrics": [
                    {"field": "销售额", "aggregation": "SUM"},
                    {"field": "利润", "aggregation": "SUM"},
                ],
            },
        }
    )
    step = CustomerRecordOperator().build_steps(ctx)[0]
    result = CustomerRecordOperator().reduce(
        ctx,
        {
            "entity_period_metrics": {
                "fields": ["YEAR(订单日期)", "SUM(销售额)", "SUM(利润)"],
                "rows": [[2022, 10, 1], [2024, 0, 0], [2023, 20, 2]],
            }
        },
    )

    assert step.vizql_json["fields"] == [
        {"fieldCaption": "订单日期", "function": "YEAR"},
        {"fieldCaption": "销售额", "function": "SUM"},
        {"fieldCaption": "利润", "function": "SUM"},
    ]
    assert step.vizql_json["filters"][-1] == {
        "field": {"fieldCaption": "客户名称"},
        "filterType": "SET",
        "values": ["样例客户"],
    }
    assert result.rows == [[2022, 10.0, 1.0], [2023, 20.0, 2.0], [2024, 0.0, 0.0]]
    assert result.explain["last_record_period"] == 2023


def test_root_cause_reduce_computes_delta_contribution(base_ctx):
    ctx = QueryPlanContext(
        **{
            **asdict(base_ctx),
            "question": "辽宁、福建 2024 巨亏原因",
            "metric": "利润",
            "dimensions": ["子类别"],
            "params": {"candidate_dimensions": ["子类别"], "top_n": 2, "focus": "loss"},
        }
    )
    result = RootCauseOperator().reduce(
        ctx,
        {
            "current_total": {"fields": ["SUM(利润)"], "rows": [[-100]]},
            "baseline_total": {"fields": ["SUM(利润)"], "rows": [[20]]},
            "current_by_子类别": {"fields": ["子类别", "SUM(利润)"], "rows": [["电话", -80], ["椅子", -20]]},
            "baseline_by_子类别": {"fields": ["子类别", "SUM(利润)"], "rows": [["电话", 10], ["椅子", 10]]},
        },
    )

    assert result.fields == ["dimension", "segment", "current_value", "baseline_value", "delta", "delta_contribution"]
    assert result.rows[0][0:5] == ["子类别", "电话", -80.0, 10.0, -90.0]
    assert result.explain["total_delta"] == -120.0
    assert result.table_display is not None
    assert result.table_display["columns"][5]["semantic_type"] == "derived_metric"
    assert result.table_display["columns"][5]["value_type"] == "percent"
    assert result.table_display["columns"][5]["align"] == "right"


def test_root_cause_builds_and_reduces_breakdown_contributors(base_ctx):
    ctx = QueryPlanContext(
        **{
            **asdict(base_ctx),
            "question": "按多个维度分析指标主要贡献",
            "metric": "销售额",
            "params": {"breakdown_dimensions": ["类别", "区域"], "limit": 2, "sort_direction": "DESC"},
        }
    )
    steps = RootCauseOperator().build_steps(ctx)
    result = RootCauseOperator().reduce(
        ctx,
        {
            "breakdown_by_类别": {"fields": ["类别", "SUM(销售额)"], "rows": [["技术", 60], ["家具", 40]]},
            "breakdown_by_区域": {"fields": ["区域", "SUM(销售额)"], "rows": [["东区", 70], ["西区", 30]]},
        },
    )

    assert [step.name for step in steps] == ["breakdown_by_类别", "breakdown_by_区域"]
    assert steps[0].vizql_json["fields"][1]["sortDirection"] == "DESC"
    assert result.fields == ["分析维度", "维度取值", "销售额", "贡献占比", "排名"]
    assert result.rows == [
        ["类别", "技术", 60.0, "60.00%", 1],
        ["类别", "家具", 40.0, "40.00%", 2],
        ["区域", "东区", 70.0, "70.00%", 1],
        ["区域", "西区", 30.0, "30.00%", 2],
    ]
    assert result.table_display is not None
    assert result.table_display["columns"][3]["semantic_type"] == "derived_metric"
    assert result.table_display["columns"][3]["value_type"] == "percent"
    assert result.table_display["columns"][4]["semantic_type"] == "rank"
    assert result.table_display["columns"][4]["align"] == "right"

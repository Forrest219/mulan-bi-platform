import pytest

from services.data_agent.tableau_mcp_plan_compiler import DeterministicPlanCompiler

pytestmark = pytest.mark.skip_db


def _fields():
    return [
        {"caption": "Sales", "name": "sales", "role": "MEASURE", "dataType": "REAL", "defaultAggregation": "SUM"},
        {"caption": "Profit", "name": "profit", "role": "MEASURE", "dataType": "REAL", "defaultAggregation": "SUM"},
        {"caption": "Region", "name": "region", "role": "DIMENSION", "dataType": "STRING"},
        {"caption": "Category", "name": "category", "role": "DIMENSION", "dataType": "STRING"},
        {"caption": "Order Date", "name": "order_date", "role": "DIMENSION", "dataType": "DATE"},
    ]


def _compile(
    question,
    *,
    fields=None,
    queryable=None,
    datasource=None,
    analysis_context=None,
    requested_metrics=None,
    requested_dimensions=None,
    requested_filters=None,
):
    return DeterministicPlanCompiler().compile(
        question=question,
        metadata_fields=fields if fields is not None else _fields(),
        queryable_fields=queryable if queryable is not None else [field["caption"] for field in _fields()],
        datasource_context={"luid": "ds-1"} if datasource is None else datasource,
        analysis_context=analysis_context,
        requested_metrics=requested_metrics,
        requested_dimensions=requested_dimensions,
        requested_filters=requested_filters,
    )


def test_compiles_metric_by_dimension_to_query_datasource_args():
    result = _compile("show Sales by Region")

    assert result.status == "matched_executable"
    assert result.tool_name == "query-datasource"
    assert result.pattern == "metric_by_dimension"
    assert result.query_args == {
        "datasourceLuid": "ds-1",
        "query": {
            "fields": [{"fieldCaption": "Region"}, {"fieldCaption": "Sales", "function": "SUM"}],
            "filters": [],
        },
        "limit": 100,
    }


def test_returns_clarification_when_metric_is_not_found():
    result = _compile("show revenue by Region")

    assert result.status == "unsupported"
    assert result.compile_reason == "metric_not_found"
    assert result.compiler_advisory["rejected_fast_path_reason"] == "metric_not_found"


def test_returns_clarification_when_field_match_is_ambiguous():
    fields = [
        {"caption": "Sales Amount", "name": "sales_amount", "role": "MEASURE", "dataType": "REAL"},
        {"caption": "Sales Tax", "name": "sales_tax", "role": "MEASURE", "dataType": "REAL"},
        {"caption": "Region", "name": "region", "role": "DIMENSION", "dataType": "STRING"},
    ]

    result = _compile("show Sales by Region", fields=fields, queryable=[field["caption"] for field in fields])

    assert result.status == "ambiguous"
    assert result.ambiguity_level == "hard"
    assert result.compile_reason == "metric_field_ambiguous"
    assert result.clarification["field_role"] == "metric"
    assert [candidate["fieldCaption"] for candidate in result.clarification["candidates"]] == [
        "Sales Amount",
        "Sales Tax",
    ]


def test_compiles_top_n_metric_by_dimension():
    result = _compile("top 5 Region by Sales")

    assert result.status == "matched_executable"
    assert result.pattern == "top_n_metric_by_dimension"
    fields = result.query_args["query"]["fields"]
    assert fields == [
        {"fieldCaption": "Region"},
        {"fieldCaption": "Sales", "function": "SUM", "sortDirection": "DESC", "sortPriority": 1},
    ]
    assert result.query_args["limit"] == 5


def test_compiles_metric_time_trend_with_date_part():
    result = _compile("monthly Sales trend by Order Date")

    assert result.status == "matched_executable"
    assert result.pattern == "metric_by_time"
    assert result.query_args["query"]["fields"] == [
        {"fieldCaption": "Order Date", "function": "MONTH", "sortDirection": "ASC", "sortPriority": 1},
        {"fieldCaption": "Sales", "function": "SUM"},
    ]


def test_compiles_single_metric_with_filter():
    result = _compile("total Sales where Region = East")

    assert result.status == "matched_executable"
    assert result.pattern == "single_metric_with_filters"
    assert result.query_args["query"]["fields"] == [{"fieldCaption": "Sales", "function": "SUM"}]
    assert result.query_args["query"]["filters"] == [
        {"field": {"fieldCaption": "Region"}, "filterType": "SET", "values": ["East"]}
    ]
    assert result.query_args["limit"] == 1


def test_returns_unsupported_without_datasource_luid():
    result = _compile("show Sales by Region", datasource={})

    assert result.status == "unsupported"
    assert result.compile_reason == "missing_datasource_luid"


def test_compiles_multiple_explicit_metrics_to_one_query_datasource_payload():
    result = _compile("overall Sales and Profit")

    assert result.status == "matched_executable"
    assert result.pattern == "multi_metric"
    assert result.query_args["query"]["fields"] == [
        {"fieldCaption": "Sales", "function": "SUM"},
        {"fieldCaption": "Profit", "function": "SUM"},
    ]
    assert result.query_args["limit"] == 1


def test_multi_metric_with_missing_metric_does_not_partially_execute():
    result = _compile("overall Sales and Revenue")

    assert result.status == "unsupported"
    assert result.query_args is None
    assert result.compiler_advisory["matched_metrics"][0]["fieldCaption"] == "Sales"
    assert result.compiler_advisory["rejected_fast_path_reason"] == "partial_metric_match"


def test_queryable_derived_metric_is_selected_without_mulan_formula():
    fields = [
        {"caption": "Sales", "name": "sales", "role": "MEASURE", "dataType": "REAL", "defaultAggregation": "SUM"},
        {"caption": "Profit Rate", "name": "profit_rate", "role": "MEASURE", "dataType": "REAL", "formula": "[Profit]/[Sales]"},
    ]

    result = _compile("overall Sales and Profit Rate", fields=fields, queryable=[field["caption"] for field in fields])

    assert result.status == "matched_executable"
    assert result.query_args["query"]["fields"] == [
        {"fieldCaption": "Sales", "function": "SUM"},
        {"fieldCaption": "Profit Rate"},
    ]


def test_derived_metric_requiring_mulan_formula_is_unsupported():
    result = _compile("overall Sales and profit rate")

    assert result.status == "unsupported"
    assert result.query_args is None


def test_soft_ambiguous_metric_returns_advisory_semantics():
    fields = [
        {"caption": "Sales Amount", "name": "sales_amount", "role": "MEASURE", "dataType": "REAL"},
        {"caption": "Region", "name": "region", "role": "DIMENSION", "dataType": "STRING"},
    ]

    result = _compile("show sales by Region", fields=fields, queryable=[field["caption"] for field in fields])

    assert result.status == "ambiguous"
    assert result.ambiguity_level == "soft"
    assert result.query_args is None
    assert result.compiler_advisory["status"] == "ambiguous"
    assert result.compiler_advisory["ambiguous_metrics"][0]["ambiguity_level"] == "soft"


def test_chinese_multi_metric_regression_fast_paths_without_field_hardcoding():
    fields = [
        {"caption": "销售额", "name": "sales", "role": "MEASURE", "dataType": "REAL", "defaultAggregation": "SUM"},
        {"caption": "利润", "name": "profit", "role": "MEASURE", "dataType": "REAL", "defaultAggregation": "SUM"},
        {"caption": "利润率", "name": "profit_rate", "role": "MEASURE", "dataType": "REAL", "formula": "[利润]/[销售额]"},
        {"caption": "客户数", "name": "customer_count", "role": "MEASURE", "dataType": "INTEGER", "defaultAggregation": "COUNTD"},
        {"caption": "客单价", "name": "aov", "role": "MEASURE", "dataType": "REAL", "formula": "[销售额]/[客户数]"},
    ]

    result = _compile(
        "整体的销售额、利润、利润率、客户数、客单价是什么样子",
        fields=fields,
        queryable=[field["caption"] for field in fields],
    )

    assert result.status == "matched_executable"
    assert [field["fieldCaption"] for field in result.query_args["query"]["fields"]] == ["销售额", "利润", "利润率", "客户数", "客单价"]


def test_current_turn_requested_fields_from_resolver_fast_path_statelessly():
    result = _compile(
        "show those by that",
        analysis_context={
            "requested_metrics": ["Sales"],
            "requested_dimensions": ["Region"],
            "requested_filters": [{"fieldCaption": "Category", "values": ["Furniture"]}],
        },
    )

    assert result.status == "matched_executable"
    assert result.pattern == "metric_by_dimension"
    assert result.query_args["query"]["fields"] == [
        {"fieldCaption": "Region"},
        {"fieldCaption": "Sales", "function": "SUM"},
    ]
    assert result.query_args["query"]["filters"] == [
        {"field": {"fieldCaption": "Category"}, "filterType": "SET", "values": ["Furniture"]}
    ]


def test_current_turn_requested_dimension_combines_with_current_time_grain():
    result = _compile(
        "继续拆分到每个年份",
        analysis_context={
            "requested_metrics": ["Sales", "Profit"],
            "requested_dimensions": ["Region"],
        },
    )

    assert result.status == "matched_executable"
    assert result.pattern == "metrics_by_dimensions"
    assert result.query_args["query"]["fields"] == [
        {"fieldCaption": "Region"},
        {"fieldCaption": "Order Date", "function": "YEAR", "sortDirection": "ASC", "sortPriority": 1},
        {"fieldCaption": "Sales", "function": "SUM"},
        {"fieldCaption": "Profit", "function": "SUM"},
    ]


def test_explicit_current_turn_requested_fields_are_accepted_without_analysis_context():
    result = _compile(
        "show those by that",
        requested_metrics=["Profit"],
        requested_dimensions=["Category"],
    )

    assert result.status == "matched_executable"
    assert result.query_args["query"]["fields"] == [
        {"fieldCaption": "Category"},
        {"fieldCaption": "Profit", "function": "SUM"},
    ]


def test_unresolved_followup_references_do_not_use_prior_context_fields():
    result = _compile(
        "break that down by Category",
        analysis_context={
            "metric_names": ["Sales"],
            "dimension_names": ["Region"],
            "query_plan": {"metrics": [{"field": "Sales"}], "dimensions": ["Region"]},
        },
    )

    assert result.status == "unsupported"
    assert result.query_args is None
    assert result.compile_reason == "metric_not_found"
    assert result.compiler_advisory["rejected_fast_path_reason"] == "metric_not_found"


def test_compiler_does_not_reuse_previous_compile_result_as_state():
    compiler = DeterministicPlanCompiler()
    first = compiler.compile(
        question="show Sales by Region",
        metadata_fields=_fields(),
        queryable_fields=[field["caption"] for field in _fields()],
        datasource_context={"luid": "ds-1"},
    )
    second = compiler.compile(
        question="show that by Category",
        metadata_fields=_fields(),
        queryable_fields=[field["caption"] for field in _fields()],
        datasource_context={"luid": "ds-1"},
    )

    assert first.status == "matched_executable"
    assert second.status == "unsupported"
    assert second.compile_reason == "metric_not_found"

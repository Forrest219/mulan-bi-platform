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


def _compile(question, *, fields=None, queryable=None, datasource=None):
    return DeterministicPlanCompiler().compile(
        question=question,
        metadata_fields=fields if fields is not None else _fields(),
        queryable_fields=queryable if queryable is not None else [field["caption"] for field in _fields()],
        datasource_context={"luid": "ds-1"} if datasource is None else datasource,
    )


def test_compiles_metric_by_dimension_to_query_datasource_args():
    result = _compile("show Sales by Region")

    assert result.status == "matched"
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

    assert result.status == "clarification"
    assert result.compile_reason == "metric_not_found"
    assert result.clarification["type"] == "missing_metric"
    assert {candidate["fieldCaption"] for candidate in result.clarification["candidates"]} >= {"Sales", "Profit"}


def test_returns_clarification_when_field_match_is_ambiguous():
    fields = [
        {"caption": "Sales Amount", "name": "sales_amount", "role": "MEASURE", "dataType": "REAL"},
        {"caption": "Sales Tax", "name": "sales_tax", "role": "MEASURE", "dataType": "REAL"},
        {"caption": "Region", "name": "region", "role": "DIMENSION", "dataType": "STRING"},
    ]

    result = _compile("show Sales by Region", fields=fields, queryable=[field["caption"] for field in fields])

    assert result.status == "clarification"
    assert result.compile_reason == "metric_field_ambiguous"
    assert result.clarification["field_role"] == "metric"
    assert [candidate["fieldCaption"] for candidate in result.clarification["candidates"]] == [
        "Sales Amount",
        "Sales Tax",
    ]


def test_compiles_top_n_metric_by_dimension():
    result = _compile("top 5 Region by Sales")

    assert result.status == "matched"
    assert result.pattern == "top_n_metric_by_dimension"
    fields = result.query_args["query"]["fields"]
    assert fields == [
        {"fieldCaption": "Region"},
        {"fieldCaption": "Sales", "function": "SUM", "sortDirection": "DESC", "sortPriority": 1},
    ]
    assert result.query_args["limit"] == 5


def test_compiles_metric_time_trend_with_date_part():
    result = _compile("monthly Sales trend by Order Date")

    assert result.status == "matched"
    assert result.pattern == "metric_by_time"
    assert result.query_args["query"]["fields"] == [
        {"fieldCaption": "Order Date", "function": "MONTH", "sortDirection": "ASC", "sortPriority": 1},
        {"fieldCaption": "Sales", "function": "SUM"},
    ]


def test_compiles_single_metric_with_filter():
    result = _compile("total Sales where Region = East")

    assert result.status == "matched"
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

import pytest

from services.data_agent.table_display import infer_table_display_schema

pytestmark = pytest.mark.skip_db


def _column(schema, label):
    for column in schema["columns"]:
        if column["label"] == label:
            return column
    raise AssertionError(f"missing column label: {label}")


def test_infers_percent_metric_and_aggregate_label():
    schema = infer_table_display_schema(
        ["客户名称", "SUM(销售额)", "销售额占比"],
        [["李丽丽", 181562.11, "1.08%"]],
        operator="ranking",
        metric_names=["销售额"],
    )

    assert schema["columns"][0] == {
        "key": "客户名称",
        "label": "客户名称",
        "semantic_type": "dimension",
        "value_type": "string",
        "align": "left",
        "format": "plain",
    }
    assert _column(schema, "销售额")["semantic_type"] == "metric"
    assert _column(schema, "销售额")["align"] == "right"
    assert _column(schema, "销售额占比")["semantic_type"] == "derived_metric"
    assert _column(schema, "销售额占比")["value_type"] == "percent"
    assert _column(schema, "销售额占比")["align"] == "right"
    assert _column(schema, "销售额占比")["format"] == "percent"


def test_infers_numeric_percent_from_rate_label():
    schema = infer_table_display_schema(
        ["类别", "利润率"],
        [["技术", 0.25], ["家具", 0.1]],
        metric_names=["利润率"],
    )

    column = _column(schema, "利润率")
    assert column["semantic_type"] == "derived_metric"
    assert column["value_type"] == "percent"
    assert column["format"] == "percent"
    assert column["align"] == "right"


def test_infers_safe_count_distinct_label():
    schema = infer_table_display_schema(
        ["COUNTD(客户名称)"],
        [[771]],
    )

    column = schema["columns"][0]
    assert column["key"] == "COUNTD(客户名称)"
    assert column["label"] == "客户数"
    assert column["semantic_type"] == "metric"
    assert column["value_type"] == "number"
    assert column["align"] == "right"

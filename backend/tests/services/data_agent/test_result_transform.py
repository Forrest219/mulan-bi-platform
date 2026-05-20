"""Deterministic previous-result table transformations."""

import pytest

from services.data_agent.result_transform import (
    can_transform_previous_result,
    transform_previous_result,
)


pytestmark = pytest.mark.skip_db


def _previous_result(metric_name: str = "Revenue") -> dict:
    return {
        "fields": ["Period", metric_name],
        "rows": [
            ["2026-01", 100.0],
            ["2026-02", 125.0],
            ["2026-03", 150.0],
        ],
        "col_types": ["string", "numeric"],
        "table_display": {
            "columns": [
                {"key": "Period", "label": "Period", "semantic_type": "period", "value_type": "date", "format": "date"},
                {"key": metric_name, "label": metric_name, "semantic_type": "metric", "value_type": "number", "format": "number"},
            ],
        },
        "response_type": "query_result",
    }


def test_transform_adds_period_delta_and_change_rate_without_field_specific_rules():
    result = transform_previous_result("增加一列环比金额、环比金额变化率", _previous_result("Revenue"))

    assert result["source"] == "previous_result_transform"
    assert result["fields"] == ["Period", "Revenue", "环比金额", "环比金额变化率"]
    assert result["rows"][0] == ["2026-01", 100.0, None, None]
    assert result["rows"][1] == ["2026-02", 125.0, 25.0, 0.25]
    assert result["rows"][2] == ["2026-03", 150.0, 25.0, 0.2]
    assert result["col_types"] == ["string", "numeric", "numeric", "numeric"]
    assert [column["key"] for column in result["table_display"]["columns"]] == result["fields"]
    assert [
        {
            "type": item["type"],
            "base_metric": item["base_metric"],
            "period_field": item["period_field"],
            "output_field": item["output_field"],
        }
        for item in result["transformations"]
    ] == [
        {
            "type": "period_delta",
            "base_metric": "Revenue",
            "period_field": "Period",
            "output_field": "环比金额",
        },
        {
            "type": "period_change_rate",
            "base_metric": "Revenue",
            "period_field": "Period",
            "output_field": "环比金额变化率",
        },
    ]


def test_transform_rate_uses_previous_metric_and_handles_zero_previous():
    previous = _previous_result("Amount")
    previous["rows"] = [["2026-01", 0], ["2026-02", 50], ["2026-03", 75]]

    result = transform_previous_result("新增环比金额变化率", previous)

    assert result["rows"][0][-1] is None
    assert result["rows"][1][-1] is None
    assert result["rows"][2][-1] == 0.5


def test_can_transform_requires_previous_result_period_and_metric():
    assert can_transform_previous_result("增加一列环比金额、环比金额变化率", _previous_result("Metric")) is True
    assert can_transform_previous_result("增加一列环比金额", None) is False
    assert can_transform_previous_result("增加一列环比金额", {"fields": ["Period"], "rows": [["2026-01"]]}) is False
    assert can_transform_previous_result(
        "增加一列环比金额",
        {
            "fields": ["Period", "Label"],
            "rows": [["2026-01", "A"], ["2026-02", "B"]],
            "col_types": ["string", "string"],
            "table_display": {
                "columns": [
                    {"key": "Period", "semantic_type": "period"},
                    {"key": "Label", "value_type": "string"},
                ],
            },
        },
    ) is False


def test_transform_returns_structured_error_without_period():
    result = transform_previous_result(
        "增加一列环比金额",
        {
            "fields": ["Metric"],
            "rows": [[100], [120]],
            "col_types": ["numeric"],
        },
    )

    assert result["source"] == "previous_result_transform"
    assert result["error_code"] == "RESULT_TRANSFORM_UNSUPPORTED"
    assert "时间列" in result["message"]

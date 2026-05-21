"""Tests for Data Agent QuerySpec validation."""

import pytest

pytest.skip(
    "TDE-06/TDE-09: legacy QuerySpec validator internals no longer define Tableau MCP correctness; "
    "deletion target is QuerySpec fallback decommission under TDE-26/TDE-30. "
    "Non-Tableau QuerySpec coverage must move to explicit contract tests before this file is removed.",
    allow_module_level=True,
)

from services.data_agent.queryspec import QuerySpec
from services.data_agent.queryspec_validator import validate_queryspec

pytestmark = pytest.mark.skip_db


QUERYABLE_FIELDS = [
    "订单日期",
    "发货日期",
    "销售额",
    "利润",
    "省/自治区",
    "类别",
    "子类别",
    "客户名称",
]

CURRENT_DATASOURCE = {
    "name": "订单+ (示例 - 超市)",
    "luid": "ds-1",
    "metadata_fields": ["内部备注", "历史分区"],
}


def _root_cause_spec(**overrides):
    spec = {
        "intent": "root_cause",
        "operator": "root_cause",
        "datasource": {"name": "订单+ (示例 - 超市)", "luid": "ds-1"},
        "time": {"field": "发货日期", "grain": "YEAR", "range": {"type": "year", "value": 2024}},
        "metrics": [{"field": "利润", "aggregation": "SUM"}],
        "dimensions": ["类别", "子类别", "客户名称"],
        "filters": [{"field": "省/自治区", "op": "IN", "values": ["任意省份"]}],
        "sort": [{"field": "SUM(利润)", "direction": "ASC"}],
        "limit": 10,
        "answer_contract": {
            "max_chars": 80,
            "must_include": ["主要贡献维度"],
            "forbid": ["猜测原因", "引用未返回字段", "输出明细列表"],
        },
    }
    spec.update(overrides)
    return spec


def test_valid_root_cause_queryspec_passes():
    result = validate_queryspec(_root_cause_spec(), QUERYABLE_FIELDS, CURRENT_DATASOURCE)

    assert result.passed is True
    assert result.code == "QS_VALID"
    assert result.detail["operator"] == "root_cause"


def test_queryspec_model_normalizes_aggregation_and_sort_direction():
    spec = QuerySpec.model_validate({
        "intent": "aggregate",
        "operator": "aggregate",
        "metrics": [{"field": "销售额", "aggregation": "sum"}],
        "sort": [{"field": "SUM(销售额)", "direction": "desc"}],
    })

    assert spec.metrics[0].aggregation == "SUM"
    assert spec.sort[0].direction == "DESC"


def test_explicit_profit_rate_must_not_be_dropped():
    spec = {
        "intent": "aggregate",
        "operator": "aggregate",
        "datasource": {"luid": "ds-1"},
        "metrics": [
            {"field": "销售额", "aggregation": "SUM"},
            {"field": "利润", "aggregation": "SUM"},
        ],
    }

    result = validate_queryspec(
        spec,
        QUERYABLE_FIELDS,
        CURRENT_DATASOURCE,
        {"question": "看一下利润率"},
    )

    assert result.passed is False
    assert result.code == "QS_SEMANTIC_METRIC_MISSING"
    assert result.detail["missing"] == ["利润率"]


def test_unrequested_customer_count_is_rejected():
    spec = {
        "intent": "aggregate",
        "operator": "aggregate",
        "datasource": {"luid": "ds-1"},
        "metrics": [
            {"field": "销售额", "aggregation": "SUM"},
            {"field": "客户名称", "aggregation": "COUNTD", "alias": "客户数"},
        ],
    }

    result = validate_queryspec(
        spec,
        QUERYABLE_FIELDS,
        CURRENT_DATASOURCE,
        {"question": "销售额是多少"},
    )

    assert result.passed is False
    assert result.code == "QS_SEMANTIC_METRIC_UNREQUESTED"
    assert result.detail["unexpected"] == ["客户数"]


def test_derived_metric_covers_explicit_profit_rate():
    spec = {
        "intent": "aggregate",
        "operator": "aggregate",
        "datasource": {"luid": "ds-1"},
        "metrics": [
            {"field": "销售额", "aggregation": "SUM"},
            {"field": "利润", "aggregation": "SUM"},
        ],
        "derived_metrics": [
            {
                "name": "利润率",
                "formula": "registry_defined_formula",
                "result_type": "percentage",
                "required_base_metrics": ["利润", "销售额"],
            }
        ],
    }

    result = validate_queryspec(
        spec,
        QUERYABLE_FIELDS,
        CURRENT_DATASOURCE,
        {"question": "利润率是多少"},
    )

    assert result.passed is True


def test_derived_metric_covers_explicit_customer_average():
    spec = {
        "intent": "aggregate",
        "operator": "aggregate",
        "datasource": {"luid": "ds-1"},
        "metrics": [
            {"field": "销售额", "aggregation": "SUM"},
            {"field": "客户名称", "aggregation": "COUNTD"},
        ],
        "derived_metrics": [
            {
                "name": "客单价",
                "formula": "registry_defined_formula",
                "result_type": "number",
                "required_base_metrics": ["销售额", "客户名称"],
            }
        ],
    }

    result = validate_queryspec(
        spec,
        QUERYABLE_FIELDS,
        CURRENT_DATASOURCE,
        {"question": "按类别统计销售额、客户数和客单价"},
    )

    assert result.passed is True


def test_broad_overview_allows_default_metrics():
    spec = {
        "intent": "aggregate",
        "operator": "aggregate",
        "datasource": {"luid": "ds-1"},
        "metrics": [
            {"field": "销售额", "aggregation": "SUM"},
            {"field": "利润", "aggregation": "SUM"},
            {"field": "客户名称", "aggregation": "COUNTD", "alias": "客户数"},
        ],
        "derived_metrics": [
            {
                "name": "客单价",
                "formula": "SUM(销售额) / COUNTD(客户名称)",
                "result_type": "number",
                "required_base_metrics": ["销售额", "客户名称"],
            }
        ],
    }

    result = validate_queryspec(
        spec,
        QUERYABLE_FIELDS,
        CURRENT_DATASOURCE,
        {"question": "看一下经营概况"},
    )

    assert result.passed is True


def test_unknown_field_is_rejected():
    spec = _root_cause_spec(metrics=[{"field": "不存在字段", "aggregation": "SUM"}])

    result = validate_queryspec(spec, QUERYABLE_FIELDS, CURRENT_DATASOURCE)

    assert result.passed is False
    assert result.code == "QS_UNKNOWN_FIELD"
    assert result.detail["fields"] == ["不存在字段"]


def test_metadata_only_field_is_rejected_before_unknown_field():
    spec = _root_cause_spec(dimensions=["内部备注"])

    result = validate_queryspec(spec, QUERYABLE_FIELDS, CURRENT_DATASOURCE)

    assert result.passed is False
    assert result.code == "QS_METADATA_FIELD_NOT_QUERYABLE"
    assert result.detail["fields"] == ["内部备注"]


def test_raw_detail_rows_are_rejected_by_default():
    spec = {
        "intent": "aggregate",
        "operator": "aggregate",
        "datasource": {"luid": "ds-1"},
        "metrics": [{"field": "销售额", "aggregation": "SUM"}],
        "dimensions": ["客户名称"],
        "result_shape": "detail_table",
        "limit": 100,
    }

    result = validate_queryspec(spec, QUERYABLE_FIELDS, CURRENT_DATASOURCE)

    assert result.passed is False
    assert result.code == "QS_RAW_ROWS_REJECTED"


def test_root_cause_requires_breakdown_dimensions():
    spec = _root_cause_spec(dimensions=[], breakdown_dimensions=[])

    result = validate_queryspec(spec, QUERYABLE_FIELDS, CURRENT_DATASOURCE)

    assert result.passed is False
    assert result.code == "QS_ROOT_CAUSE_MISSING_REQUIRED_FIELDS"
    assert "breakdown_dimensions" in result.detail["missing"]


def test_trend_condition_requires_time_dimension_metric_and_direction():
    spec = {
        "intent": "trend_condition",
        "operator": "trend_condition",
        "datasource": {"luid": "ds-1"},
    }

    result = validate_queryspec(spec, QUERYABLE_FIELDS, CURRENT_DATASOURCE)

    assert result.passed is False
    assert result.code == "QS_TREND_CONDITION_MISSING_REQUIRED_FIELDS"
    assert set(result.detail["missing"]) >= {"time.field", "metrics", "direction"}


def test_set_difference_requires_universe_and_occurred_constraints():
    spec = {
        "intent": "set_difference",
        "operator": "set_difference",
        "datasource": {"luid": "ds-1"},
    }

    result = validate_queryspec(spec, QUERYABLE_FIELDS, CURRENT_DATASOURCE)

    assert result.passed is False
    assert result.code == "QS_SET_DIFFERENCE_MISSING_REQUIRED_FIELDS"
    assert result.detail["missing"] == ["universe", "occurred"]

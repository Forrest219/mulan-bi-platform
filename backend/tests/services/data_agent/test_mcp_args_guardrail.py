import logging

import pytest

from services.data_agent.mcp_args_guardrail import (
    MCP_ARGS_GUARDRAIL_PASS,
    MCP_ARGS_GUARDRAIL_REJECT,
    McpArgsGuardrailInput,
    McpArgsGuardrailRejected,
    execute_query_datasource_with_guardrail,
    query_datasource_tool_schema,
    validate_mcp_args,
)


def _schema(**properties):
    base_properties = {
        "datasource_luid": {"type": "string"},
        "connection_id": {"type": "integer"},
        "fields": {"type": "array"},
        "filters": {"type": "array"},
        "limit": {"type": "integer"},
    }
    base_properties.update(properties)
    return {
        "type": "object",
        "properties": base_properties,
        "additionalProperties": True,
    }


def _request(args, *, schema=None, fields=None, question="各省份销售额是多少？", current_datasource=None, user_context=None):
    return McpArgsGuardrailInput(
        question=question,
        tool_name="query_datasource",
        tool_schema=schema or _schema(),
        args=args,
        queryable_fields=fields or ["省份", "销售额", "订单日期", "类别"],
        current_datasource=current_datasource or {"luid": "ds-1", "connection_id": 7},
        user_context=user_context or {
            "accessible_datasource_luids": ["ds-1"],
            "accessible_connection_ids": [7],
        },
    )


def test_allow_valid_args():
    result = validate_mcp_args(
        _request(
            {
                "datasource_luid": "ds-1",
                "connection_id": 7,
                "fields": [{"fieldCaption": "省份"}, {"fieldCaption": "销售额", "function": "SUM"}],
                "limit": 50,
            }
        )
    )

    assert result.decision == "allow"
    assert result.args["limit"] == 50
    assert result.repairs == []


def test_repairs_missing_limit_to_default():
    result = validate_mcp_args(
        _request(
            {
                "datasource_luid": "ds-1",
                "connection_id": 7,
                "fields": [{"fieldCaption": "省份"}, {"fieldCaption": "销售额", "function": "SUM"}],
            }
        )
    )

    assert result.decision == "repair"
    assert result.args["limit"] == 100
    assert [repair.type for repair in result.repairs] == ["limit_default"]


def test_repairs_limit_over_threshold_by_clamping():
    result = validate_mcp_args(
        _request(
            {
                "datasource_luid": "ds-1",
                "connection_id": 7,
                "fields": [{"fieldCaption": "省份"}, {"fieldCaption": "销售额", "function": "SUM"}],
                "limit": 10000,
            }
        )
    )

    assert result.decision == "repair"
    assert result.args["limit"] == 100
    assert result.repairs[0].type == "limit_clamp"
    assert result.repairs[0].before == 10000


def test_repairs_field_case_and_space():
    result = validate_mcp_args(
        _request(
            {
                "datasource_luid": "ds-1",
                "connection_id": 7,
                "fields": [{"fieldCaption": "  sales amount "}],
                "limit": 20,
            },
            fields=["Sales Amount"],
        )
    )

    assert result.decision == "repair"
    assert result.args["fields"][0]["fieldCaption"] == "Sales Amount"
    assert result.repairs[0].type == "field_case"


def test_repairs_unique_safe_field_synonym():
    result = validate_mcp_args(
        _request(
            {
                "datasource_luid": "ds-1",
                "connection_id": 7,
                "fields": ["订单日期"],
                "limit": 20,
            },
            fields=["发货日期"],
            current_datasource={
                "luid": "ds-1",
                "connection_id": 7,
                "field_synonyms": {"订单日期": ["发货日期"]},
            },
        )
    )

    assert result.decision == "repair"
    assert result.args["fields"] == ["发货日期"]
    assert result.repairs[0].type == "field_mapping"


def test_rejects_unknown_field():
    result = validate_mcp_args(
        _request(
            {
                "datasource_luid": "ds-1",
                "connection_id": 7,
                "fields": [{"fieldCaption": "不存在字段"}],
                "limit": 20,
            }
        )
    )

    assert result.decision == "reject"
    assert result.reject_code == "MCP_ARGS_UNKNOWN_FIELD"
    assert result.args is None
    assert result.message
    assert result.user_hint


def test_rejects_unsafe_detail_scan_without_original_limit():
    result = validate_mcp_args(
        _request(
            {
                "datasource_luid": "ds-1",
                "connection_id": 7,
                "result_shape": "detail_table",
                "fields": [{"fieldCaption": "省份"}, {"fieldCaption": "订单日期"}],
            },
            question="列出订单明细",
        )
    )

    assert result.decision == "reject"
    assert result.reject_code == "MCP_ARGS_UNSAFE_DETAIL_SCAN"


def test_rejects_unsafe_operation():
    result = validate_mcp_args(
        _request(
            {
                "datasource_luid": "ds-1",
                "connection_id": 7,
                "operation": "DELETE",
                "fields": [{"fieldCaption": "省份"}],
                "limit": 20,
            }
        )
    )

    assert result.decision == "reject"
    assert result.reject_code == "MCP_ARGS_UNSAFE_OPERATION"


def test_rejects_forbidden_datasource():
    result = validate_mcp_args(
        _request(
            {
                "datasource_luid": "ds-2",
                "connection_id": 7,
                "fields": [{"fieldCaption": "省份"}],
                "limit": 20,
            }
        )
    )

    assert result.decision == "reject"
    assert result.reject_code == "MCP_ARGS_DATASOURCE_FORBIDDEN"


def test_repairs_enum_case():
    result = validate_mcp_args(
        _request(
            {
                "datasource_luid": "ds-1",
                "connection_id": 7,
                "fields": [{"fieldCaption": "销售额", "function": "SUM"}],
                "sortDirection": "desc",
                "limit": 20,
            },
            schema=_schema(sortDirection={"type": "string", "enum": ["ASC", "DESC"]}),
        )
    )

    assert result.decision == "repair"
    assert result.args["sortDirection"] == "DESC"
    assert result.repairs[0].type == "enum_case"


def test_does_not_auto_add_missing_business_metric():
    result = validate_mcp_args(
        _request(
            {
                "datasource_luid": "ds-1",
                "connection_id": 7,
                "fields": [{"fieldCaption": "省份"}],
                "limit": 20,
            },
            question="按省份统计销售额",
            fields=["省份", "销售额"],
        )
    )

    assert result.decision == "allow"
    assert result.args["fields"] == [{"fieldCaption": "省份"}]
    assert result.repairs == []


def test_does_not_split_profit_rate_metric():
    result = validate_mcp_args(
        _request(
            {
                "datasource_luid": "ds-1",
                "connection_id": 7,
                "fields": [{"fieldCaption": "利润率"}],
                "limit": 20,
            },
            question="按类别看利润率",
            fields=["利润率", "销售额", "利润", "客户数"],
        )
    )

    assert result.decision == "allow"
    assert result.args["fields"] == [{"fieldCaption": "利润率"}]


def test_rejects_official_query_fields_string_array_before_tableau_mcp():
    result = validate_mcp_args(
        _request(
            {
                "datasourceLuid": "ds-1",
                "connection_id": 7,
                "query": {"fields": ["销售额", "利润率"], "filters": []},
                "limit": 20,
            },
            schema=query_datasource_tool_schema(),
            fields=["销售额", "利润率"],
            current_datasource={"luid": "ds-1", "connection_id": 7},
        )
    )

    assert result.decision == "reject"
    assert result.reject_code == "MCP_ARGS_FIELD_SCHEMA_INVALID"
    assert result.args is None


def test_execute_query_datasource_rejects_invalid_query_field_contract_before_execute():
    def _execute(args):
        raise AssertionError("invalid query.fields contract must not reach Tableau MCP")

    with pytest.raises(McpArgsGuardrailRejected) as exc_info:
        execute_query_datasource_with_guardrail(
            question="整体销售额和利润率是多少？",
            datasource_luid="ds-1",
            query={"fields": ["销售额", "利润率"], "filters": []},
            limit=20,
            timeout=30,
            connection_id=7,
            queryable_fields=["销售额", "利润率"],
            current_datasource={"luid": "ds-1", "connection_id": 7},
            user_context={
                "accessible_datasource_luids": ["ds-1"],
                "accessible_connection_ids": [7],
            },
            execute=_execute,
            trace_id="trace-invalid-contract",
            chain_mode="mcp_first",
        )

    assert exc_info.value.result.reject_code == "MCP_ARGS_FIELD_SCHEMA_INVALID"


def test_execute_query_datasource_rejects_nested_unsafe_detail_scan_before_execute():
    def _execute(args):
        raise AssertionError("unsafe detail scan must not reach Tableau MCP")

    with pytest.raises(McpArgsGuardrailRejected) as exc_info:
        execute_query_datasource_with_guardrail(
            question="列出订单明细",
            datasource_luid="ds-1",
            query={
                "result_shape": "detail_table",
                "fields": [{"fieldCaption": "省份"}, {"fieldCaption": "订单日期"}],
                "filters": [],
            },
            limit=None,
            timeout=30,
            connection_id=7,
            queryable_fields=["省份", "订单日期"],
            current_datasource={"luid": "ds-1", "connection_id": 7},
            user_context={
                "accessible_datasource_luids": ["ds-1"],
                "accessible_connection_ids": [7],
            },
            execute=_execute,
            trace_id="trace-detail-scan",
            chain_mode="mcp_first",
        )

    assert exc_info.value.result.reject_code == "MCP_ARGS_UNSAFE_DETAIL_SCAN"


def test_normalizes_safe_official_query_field_object_key():
    result = validate_mcp_args(
        _request(
            {
                "datasourceLuid": "ds-1",
                "connection_id": 7,
                "query": {"fields": [{"name": "销售额", "function": "SUM"}], "filters": []},
                "limit": 20,
            },
            schema=query_datasource_tool_schema(),
            fields=["销售额"],
            current_datasource={"luid": "ds-1", "connection_id": 7},
        )
    )

    assert result.decision == "repair"
    assert result.args["query"]["fields"][0]["fieldCaption"] == "销售额"
    assert result.repairs[0].type == "field_object_key"


def test_normalizes_query_field_aggregation_alias_to_function():
    result = validate_mcp_args(
        _request(
            {
                "datasourceLuid": "ds-1",
                "connection_id": 7,
                "query": {"fields": [{"fieldCaption": "销售额", "aggregation": "sum"}], "filters": []},
                "limit": 20,
            },
            schema=query_datasource_tool_schema(),
            fields=["销售额"],
            current_datasource={"luid": "ds-1", "connection_id": 7},
        )
    )

    assert result.decision == "repair"
    assert result.args["query"]["fields"][0] == {"fieldCaption": "销售额", "function": "SUM"}
    assert {repair.type for repair in result.repairs} == {"aggregation_case", "field_object_function_key"}


def test_removes_outer_function_from_aggregate_calculated_field_metadata():
    result = validate_mcp_args(
        _request(
            {
                "datasourceLuid": "ds-1",
                "connection_id": 7,
                "query": {"fields": [{"fieldCaption": "Calculated Metric", "function": "AVG"}], "filters": []},
                "limit": 20,
            },
            schema=query_datasource_tool_schema(),
            fields=["Calculated Metric"],
            current_datasource={
                "luid": "ds-1",
                "connection_id": 7,
                "fields": [
                    {
                        "field_caption": "Calculated Metric",
                        "formula": "SUM([Base A]) / SUM([Base B])",
                        "is_calculated": True,
                    }
                ],
            },
        )
    )

    assert result.decision == "repair"
    assert result.args["query"]["fields"][0] == {"fieldCaption": "Calculated Metric"}
    assert [repair.type for repair in result.repairs] == ["aggregate_calculation_function_removed"]


def test_rejects_result_too_wide():
    fields = [f"字段{i}" for i in range(21)]
    result = validate_mcp_args(
        _request(
            {
                "datasource_luid": "ds-1",
                "connection_id": 7,
                "fields": [{"fieldCaption": field} for field in fields],
                "limit": 20,
            },
            fields=fields,
        )
    )

    assert result.decision == "reject"
    assert result.reject_code == "MCP_ARGS_RESULT_TOO_WIDE"


def test_rejects_schema_without_repairing_business_operator():
    result = validate_mcp_args(
        _request(
            {
                "datasource_luid": "ds-1",
                "connection_id": 7,
                "fields": [{"fieldCaption": "销售额", "function": "SUM"}],
                "operator": "NEQ",
                "limit": 20,
            },
            schema=_schema(operator={"type": "string", "enum": ["EQ", "GT", "LT"]}),
        )
    )

    assert result.decision == "reject"
    assert result.reject_code == "MCP_ARGS_SCHEMA_INVALID"
    assert result.args is None


def test_rejects_illegal_aggregation():
    result = validate_mcp_args(
        _request(
            {
                "datasource_luid": "ds-1",
                "connection_id": 7,
                "fields": [{"fieldCaption": "销售额", "function": "PERCENTILE"}],
                "limit": 20,
            }
        )
    )

    assert result.decision == "reject"
    assert result.reject_code == "MCP_ARGS_ILLEGAL_AGGREGATION"


def test_execute_query_datasource_with_guardrail_passes_and_traces(caplog):
    executed = {}

    def _execute(args):
        executed.update(args)
        return {"fields": ["SUM(销售额)"], "rows": [[100]]}

    with caplog.at_level(logging.INFO, logger="services.data_agent.mcp_args_guardrail"):
        result = execute_query_datasource_with_guardrail(
            question="总销售额是多少？",
            datasource_luid="ds-1",
            query={"fields": [{"fieldCaption": "销售额", "function": "SUM"}]},
            limit=50,
            timeout=30,
            connection_id=7,
            queryable_fields=["销售额"],
            execute=_execute,
            trace_id="trace-guardrail",
            chain_mode="test_chain",
        )

    assert executed["datasourceLuid"] == "ds-1"
    assert executed["query"]["fields"][0]["fieldCaption"] == "销售额"
    assert result["mcp_args_guardrail"]["decision"] == "allow"
    assert any(MCP_ARGS_GUARDRAIL_PASS in record.message for record in caplog.records)


def test_execute_query_datasource_with_guardrail_rejects_before_execute(caplog):
    def _execute(args):
        raise AssertionError("guardrail reject must not execute MCP")

    with caplog.at_level(logging.INFO, logger="services.data_agent.mcp_args_guardrail"):
        with pytest.raises(McpArgsGuardrailRejected) as exc_info:
            execute_query_datasource_with_guardrail(
                question="按不存在字段看销售额",
                datasource_luid="ds-1",
                query={"fields": [{"fieldCaption": "不存在字段"}]},
                limit=50,
                timeout=30,
                connection_id=7,
                queryable_fields=["销售额"],
                execute=_execute,
                trace_id="trace-guardrail",
                chain_mode="test_chain",
            )

    assert exc_info.value.result.reject_code == "MCP_ARGS_UNKNOWN_FIELD"
    assert any(MCP_ARGS_GUARDRAIL_REJECT in record.message for record in caplog.records)

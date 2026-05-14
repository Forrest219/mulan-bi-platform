from services.data_agent.mcp_args_guardrail import McpArgsGuardrailInput, validate_mcp_args


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

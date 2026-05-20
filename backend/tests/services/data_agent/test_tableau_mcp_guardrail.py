import pytest

from services.data_agent.mcp_args_guardrail import MAX_LIMIT, MAX_RESULT_FIELDS
from services.data_agent.tableau_mcp_guardrail import (
    TableauMcpGuardrailRequest,
    TableauMcpGuardrailService,
)
from services.data_agent.tableau_mcp_resolver import DatasourceCandidateResolver
from services.data_agent.tool_base import ToolContext

pytestmark = pytest.mark.skip_db


def _context(connection_id=7, user_id=42, role=None):
    return ToolContext(session_id="s1", user_id=user_id, connection_id=connection_id, user_role=role)


def _resolver(*, accessible=True, belongs=True):
    return DatasourceCandidateResolver(
        datasource_asset_loader=lambda connection_id: [],
        connection_access_checker=lambda connection_id, user_id, user_role: accessible,
        datasource_connection_checker=lambda datasource_luid, connection_id: belongs,
    )


def _service(*, accessible=True, belongs=True):
    return TableauMcpGuardrailService(resolver=_resolver(accessible=accessible, belongs=belongs))


def _query_request(args, *, fields=None, current_datasource=None, context=None):
    return TableauMcpGuardrailRequest(
        question="按省份统计销售额",
        tool_name="query-datasource",
        args=args,
        context=context or _context(),
        current_datasource=current_datasource or {"luid": "ds-1", "connection_id": 7},
        queryable_fields=fields if fields is not None else ["省份", "销售额", "订单日期"],
    )


def test_rejects_missing_connection_id():
    decision = _service().validate(
        TableauMcpGuardrailRequest(
            question="列出数据源",
            tool_name="list-datasources",
            args={},
            context=ToolContext(session_id="s1", user_id=42),
        )
    )

    assert decision.decision == "reject"
    assert decision.reject_code == "TABLEAU_MCP_CONNECTION_REQUIRED"


def test_rejects_forbidden_connection():
    decision = _service(accessible=False).validate(
        TableauMcpGuardrailRequest(
            question="列出数据源",
            tool_name="list-datasources",
            args={"connectionId": 7},
            context=_context(),
        )
    )

    assert decision.decision == "reject"
    assert decision.reject_code == "TABLEAU_MCP_CONNECTION_FORBIDDEN"


def test_rejects_unknown_tool_before_runtime():
    decision = _service().validate(
        TableauMcpGuardrailRequest(
            question="删除数据源",
            tool_name="delete-datasource",
            args={"connectionId": 7},
            context=_context(),
        )
    )

    assert decision.decision == "reject"
    assert decision.reject_code == "TABLEAU_MCP_TOOL_FORBIDDEN"


def test_rejects_datasource_outside_connection():
    decision = _service(belongs=False).validate(
        _query_request(
            {
                "datasourceLuid": "ds-other",
                "query": {"fields": [{"fieldCaption": "销售额", "function": "SUM"}]},
                "limit": 10,
            }
        )
    )

    assert decision.decision == "reject"
    assert decision.reject_code == "TABLEAU_MCP_DATASOURCE_FORBIDDEN"


def test_rejects_unknown_query_field():
    decision = _service().validate(
        _query_request(
            {
                "datasourceLuid": "ds-1",
                "query": {"fields": [{"fieldCaption": "不存在字段", "function": "SUM"}]},
                "limit": 10,
            }
        )
    )

    assert decision.decision == "reject"
    assert decision.reject_code == "MCP_ARGS_UNKNOWN_FIELD"


def test_repairs_limit_over_threshold_by_clamping():
    decision = _service().validate(
        _query_request(
            {
                "datasourceLuid": "ds-1",
                "query": {"fields": [{"fieldCaption": "销售额", "function": "SUM"}]},
                "limit": MAX_LIMIT + 900,
            }
        )
    )

    assert decision.decision == "repair"
    assert decision.args["limit"] == MAX_LIMIT
    assert decision.repairs[0].type == "limit_clamp"


def test_repairs_timeout_over_threshold_by_clamping():
    decision = _service().validate(
        _query_request(
            {
                "datasourceLuid": "ds-1",
                "query": {"fields": [{"fieldCaption": "销售额", "function": "SUM"}]},
                "limit": 10,
                "timeout": 999,
            }
        )
    )

    assert decision.decision == "repair"
    assert decision.args["timeout"] == 60
    assert any(repair.type == "timeout_clamp" for repair in decision.repairs)


def test_rejects_too_many_query_fields():
    fields = [f"字段{index}" for index in range(MAX_RESULT_FIELDS + 1)]
    decision = _service().validate(
        _query_request(
            {
                "datasourceLuid": "ds-1",
                "query": {"fields": [{"fieldCaption": field} for field in fields]},
                "limit": 10,
            },
            fields=fields,
        )
    )

    assert decision.decision == "reject"
    assert decision.reject_code == "MCP_ARGS_RESULT_TOO_WIDE"


def test_allows_metadata_tool_for_datasource_in_connection():
    decision = _service().validate(
        TableauMcpGuardrailRequest(
            question="介绍订单数据源",
            tool_name="get-datasource-metadata",
            args={"datasourceLuid": "ds-1", "connectionId": 7},
            context=_context(),
            current_datasource={"luid": "ds-1", "connection_id": 7},
        )
    )

    assert decision.decision == "allow"
    assert decision.args["datasourceLuid"] == "ds-1"

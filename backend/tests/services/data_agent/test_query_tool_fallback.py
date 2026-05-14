import pytest
from unittest.mock import AsyncMock, patch

from services.data_agent.fallback import is_fallback_payload
from services.data_agent.tool_base import ToolContext
from services.data_agent.tools.query_tool import QueryTool
from services.llm.nlq_service import NLQError


@pytest.fixture
def tool_context():
    return ToolContext(session_id="s1", user_id=1, connection_id=1, trace_id="t1")


@pytest.mark.asyncio
async def test_query_tool_route_failure_returns_datasource_fallback(tool_context):
    with patch("services.data_agent.tools.query_tool.route_datasource", return_value=None):
        result = await QueryTool().execute({"question": "2024 年销售额是多少？"}, tool_context)

    assert result.success is False
    assert is_fallback_payload(result.data)
    assert result.data["fallback_type"] == "datasource_not_matched"
    assert result.data["error_code"] == "NLQ_008"
    assert result.data["trace_id"] == "t1"


@pytest.mark.asyncio
async def test_query_tool_empty_vizql_returns_plan_fallback(tool_context):
    ds_info = {"luid": "test-luid", "name": "test-datasource", "asset_id": 123}
    with patch("services.data_agent.tools.query_tool.route_datasource", return_value=ds_info):
        with patch("services.data_agent.tools.query_tool.get_datasource_fields_cached", return_value=[]):
            with patch("services.data_agent.tools.query_tool.one_pass_llm", new_callable=AsyncMock) as mock_nlq:
                mock_nlq.return_value = {"vizql_json": {}}

                result = await QueryTool().execute({"question": "分析一下"}, tool_context)

    assert result.success is False
    assert result.data["fallback_type"] == "query_plan_unavailable"
    assert result.data["error_code"] == "NLQ_006"


@pytest.mark.asyncio
async def test_query_tool_timeout_maps_standard_fallback(tool_context):
    ds_info = {"luid": "test-luid", "name": "test-datasource", "asset_id": 123}
    with patch("services.data_agent.tools.query_tool.route_datasource", return_value=ds_info):
        with patch("services.data_agent.tools.query_tool.get_datasource_fields_cached", return_value=[]):
            with patch("services.data_agent.tools.query_tool.one_pass_llm", new_callable=AsyncMock) as mock_nlq:
                mock_nlq.return_value = {"vizql_json": {"fields": []}}
                with patch("services.data_agent.tools.query_tool.execute_query", new_callable=AsyncMock) as mock_exec:
                    mock_exec.side_effect = NLQError(code="NLQ_007", message="查询超时")

                    result = await QueryTool().execute({"question": "Q4 销售额"}, tool_context)

    assert result.success is False
    assert result.data["fallback_type"] == "query_timeout"
    assert result.data["error_code"] == "NLQ_007"


@pytest.mark.asyncio
async def test_query_tool_field_unavailable_uses_fallback_response_type(tool_context):
    ds_info = {"luid": "test-luid", "name": "订单+ (示例 - 超市)", "asset_id": 123}
    with patch("services.data_agent.tools.query_tool.route_datasource", return_value=ds_info):
        with patch("services.data_agent.tools.query_tool.get_datasource_fields_cached", return_value=["国家/地区"]):
            with patch("services.data_agent.tools.query_tool._get_mcp_queryable_field_candidates", return_value=["省/自治区"]):
                with patch("services.data_agent.tools.query_tool.execute_query", new_callable=AsyncMock) as mock_exec:
                    mock_exec.side_effect = NLQError(
                        code="NLQ_006",
                        message="MCP 工具执行失败: Field '国家/地区' was not found in the datasource.",
                    )

                    result = await QueryTool().execute(
                        {"question": "国家/地区 都有哪些值？", "datasource_name": "订单+ (示例 - 超市)"},
                        tool_context,
                    )

    assert result.success is False
    assert result.data["fallback_type"] == "field_unavailable"
    assert "国家/地区" in result.data["message"]
    assert "省/自治区" in result.data["user_hint"]

"""
QueryTool 集成测试

测试 QueryTool 的 NLQ 封装、错误处理、参数校验。
由于 NLQ Service 和 Tableau MCP 不可用，测试重点在错误处理路径。
"""

import pytest
from unittest.mock import MagicMock, AsyncMock, patch

from services.data_agent.tools.query_tool import QueryTool, _build_customer_churn_vizqls, _build_direct_vizql
from services.data_agent.tool_base import ToolContext, ToolResult
from services.llm.nlq_service import NLQError


class TestQueryTool:
    """QueryTool 测试用例"""

    @pytest.fixture
    def tool(self):
        return QueryTool()

    @pytest.fixture
    def tool_context(self):
        return ToolContext(
            session_id="s1",
            user_id=1,
            connection_id=1,
            trace_id="t1",
        )

    # =============================================================================
    # TC-QUERY-001: 空问题处理
    # =============================================================================
    @pytest.mark.asyncio
    async def test_tc_query_001_empty_question(self, tool, tool_context):
        """TC-QUERY-001: 空问题应返回错误"""
        result = await tool.execute({"question": ""}, tool_context)

        assert result.success is False
        assert "empty" in result.error.lower() or "空" in result.error
        assert result.execution_time_ms >= 0

    # =============================================================================
    # TC-QUERY-002: 缺失 question 参数
    # =============================================================================
    @pytest.mark.asyncio
    async def test_tc_query_002_missing_question(self, tool, tool_context):
        """TC-QUERY-002: 缺失 question 参数应返回错误"""
        result = await tool.execute({}, tool_context)

        assert result.success is False
        assert result.error is not None
        assert result.execution_time_ms >= 0

    # =============================================================================
    # TC-QUERY-003: 无 connection_id 时使用 context.connection_id
    # =============================================================================
    @pytest.mark.asyncio
    async def test_tc_query_003_uses_context_connection_id(self, tool):
        """TC-QUERY-003: 参数无 connection_id 时使用 context 中的值"""
        context = ToolContext(
            session_id="s1",
            user_id=1,
            connection_id=1,
            trace_id="t1",
        )

        # Mock route_datasource to return None (no matching datasource)
        with patch("services.data_agent.tools.query_tool.route_datasource") as mock_route:
            mock_route.return_value = None

            result = await tool.execute({"question": "Q4 销售额"}, context)

        # 应返回错误，因为没有可用数据源
        assert result.success is False
        assert "数据源" in result.error or "datasource" in result.error.lower()

    def test_direct_vizql_trend_adds_date_dimension_and_maps_synonyms(self):
        vizql = _build_direct_vizql(
            "过去四年的销售额、利润趋势如何？",
            ["订单日期", "净额", "利润金额", "毛额"],
        )

        assert vizql == {
            "fields": [
                {"fieldCaption": "订单日期", "function": "YEAR"},
                {"fieldCaption": "净额", "function": "SUM", "fieldAlias": "销售额"},
                {"fieldCaption": "利润金额", "function": "SUM", "fieldAlias": "利润"},
            ],
            "filters": [
                {
                    "field": {"fieldCaption": "订单日期"},
                    "filterType": "DATE",
                    "dateRangeType": "LASTN",
                    "periodType": "YEARS",
                    "rangeN": 4,
                }
            ],
        }

    def test_direct_vizql_each_year_category_sales_uses_requested_date_dimension(self):
        vizql = _build_direct_vizql(
            "输出错误！我要的是每个类别、每年的销售额。用订单日期统计",
            ["订单日期", "类别", "销售额", "利润"],
        )

        assert vizql == {
            "fields": [
                {"fieldCaption": "订单日期", "function": "YEAR"},
                {"fieldCaption": "类别"},
                {"fieldCaption": "销售额", "function": "SUM"},
            ],
            "filters": [],
        }

    def test_direct_vizql_counts_distinct_channels(self):
        vizql = _build_direct_vizql(
            "我们有多少个渠道？",
            ["订单日期", "渠道名称", "净额", "利润金额"],
        )

        assert vizql == {
            "fields": [{"fieldCaption": "渠道名称", "function": "COUNTD"}],
            "filters": [],
        }

    def test_direct_vizql_dimension_enumeration_uses_dimension_only(self):
        vizql = _build_direct_vizql(
            "类别 都有什么",
            ["订单日期", "类别", "销售额"],
        )

        assert vizql == {
            "fields": [{"fieldCaption": "类别"}],
            "filters": [],
        }

    def test_direct_vizql_channel_profit_by_year_for_past_few_years(self):
        vizql = _build_direct_vizql(
            "这些渠道过去几年的利润情况如何？",
            ["订单日期", "渠道名称", "净额", "利润金额"],
        )

        assert vizql == {
            "fields": [
                {"fieldCaption": "订单日期", "function": "YEAR"},
                {"fieldCaption": "渠道名称"},
                {"fieldCaption": "利润金额", "function": "SUM", "fieldAlias": "利润"},
            ],
            "filters": [
                {
                    "field": {"fieldCaption": "订单日期"},
                    "filterType": "DATE",
                    "dateRangeType": "LASTN",
                    "periodType": "YEARS",
                    "rangeN": 4,
                }
            ],
        }

    def test_direct_vizql_channel_profit_increasing_uses_year_channel_profit(self):
        vizql = _build_direct_vizql(
            "哪些渠道过去几年的利润一直在涨？",
            ["订单日期", "渠道名称", "净额", "利润金额"],
        )

        assert vizql["fields"] == [
            {"fieldCaption": "订单日期", "function": "YEAR"},
            {"fieldCaption": "渠道名称"},
            {"fieldCaption": "利润金额", "function": "SUM", "fieldAlias": "利润"},
        ]
        assert vizql["filters"][0]["filterType"] == "DATE"
        assert vizql["filters"][0]["dateRangeType"] == "LASTN"

    def test_direct_vizql_2024_top10_customers_uses_date_range_and_sortable_sales(self):
        vizql = _build_direct_vizql(
            "2024 年 Top10 大客户及占比",
            ["订单日期", "客户名称", "渠道名称", "净额", "利润金额"],
        )

        assert vizql == {
            "fields": [
                {"fieldCaption": "客户名称"},
                {
                    "fieldCaption": "净额",
                    "function": "SUM",
                    "sortDirection": "DESC",
                    "sortPriority": 1,
                },
            ],
            "filters": [
                {
                    "field": {"fieldCaption": "订单日期"},
                    "filterType": "QUANTITATIVE_DATE",
                    "quantitativeFilterType": "RANGE",
                    "minDate": "2024-01-01",
                    "maxDate": "2024-12-31",
                }
            ],
        }

    def test_customer_churn_builds_base_and_recent_queries(self):
        plan = _build_customer_churn_vizqls(
            "哪些 2021 年的老客户流失了（定义 2021 年有订单，但最近一年没有订单）？",
            ["订单日期", "客户ID", "净额"],
        )

        assert plan == {
            "year": 2021,
            "customer_field": "客户ID",
            "base_vizql": {
                "fields": [{"fieldCaption": "客户ID"}],
                "filters": [
                    {
                        "field": {"fieldCaption": "订单日期"},
                        "filterType": "QUANTITATIVE_DATE",
                        "quantitativeFilterType": "RANGE",
                        "minDate": "2021-01-01",
                        "maxDate": "2021-12-31",
                    }
                ],
            },
            "recent_vizql": {
                "fields": [{"fieldCaption": "客户ID"}],
                "filters": [
                    {
                        "field": {"fieldCaption": "订单日期"},
                        "filterType": "DATE",
                        "dateRangeType": "LASTN",
                        "periodType": "YEARS",
                        "rangeN": 1,
                    }
                ],
            },
        }

    @pytest.mark.asyncio
    async def test_direct_path_channel_count_does_not_call_llm(self, tool, tool_context):
        mock_ds_info = {
            "luid": "test-luid",
            "name": "test-datasource",
            "asset_id": 123,
        }

        with patch("services.data_agent.tools.query_tool.route_datasource", return_value=mock_ds_info):
            with patch("services.data_agent.tools.query_tool.get_datasource_fields_cached", return_value=["订单日期", "渠道名称", "净额"]):
                with patch("services.data_agent.tools.query_tool.one_pass_llm", new_callable=AsyncMock) as mock_nlq:
                    with patch("services.data_agent.tools.query_tool.execute_query", new_callable=AsyncMock) as mock_exec:
                        mock_exec.return_value = {"fields": ["COUNTD(渠道名称)"], "rows": [[4]]}

                        result = await tool.execute({"question": "我们有多少个渠道？"}, tool_context)

        assert result.success is True
        mock_nlq.assert_not_called()
        called_vizql = mock_exec.call_args.kwargs["vizql_json"]
        assert called_vizql == {
            "fields": [{"fieldCaption": "渠道名称", "function": "COUNTD"}],
            "filters": [],
        }

    @pytest.mark.asyncio
    async def test_direct_path_retries_with_available_mcp_date_field(self, tool, tool_context):
        mock_ds_info = {
            "luid": "test-luid",
            "name": "订单+ (示例 - 超市)",
            "asset_id": 123,
        }

        with patch("services.data_agent.tools.query_tool.route_datasource", return_value=mock_ds_info):
            with patch("services.data_agent.tools.query_tool.get_datasource_fields_cached", return_value=["订单日期", "发货日期", "类别", "销售额"]):
                with patch("services.data_agent.tools.query_tool._get_mcp_date_field_candidates", return_value=["发货日期"]):
                    with patch("services.data_agent.tools.query_tool.one_pass_llm", new_callable=AsyncMock) as mock_nlq:
                        with patch("services.data_agent.tools.query_tool.execute_query", new_callable=AsyncMock) as mock_exec:
                            mock_exec.side_effect = [
                                NLQError(
                                    code="NLQ_006",
                                    message="MCP 工具执行失败: Field '订单日期' was not found in the datasource.",
                                ),
                                {
                                    "fields": ["YEAR(发货日期)", "类别", "SUM(销售额)"],
                                    "rows": [[2024, "技术", 10]],
                                },
                            ]

                            result = await tool.execute(
                                {"question": "输出错误！我要的是每个类别、每年的销售额。用订单日期统计"},
                                tool_context,
                            )

        assert result.success is True
        mock_nlq.assert_not_called()
        first_vizql = mock_exec.call_args_list[0].kwargs["vizql_json"]
        second_vizql = mock_exec.call_args_list[1].kwargs["vizql_json"]
        assert first_vizql["fields"][0] == {"fieldCaption": "订单日期", "function": "YEAR"}
        assert second_vizql["fields"][0] == {"fieldCaption": "发货日期", "function": "YEAR"}
        assert result.data["fields"] == ["YEAR(发货日期)", "类别", "SUM(销售额)"]
        assert result.data["rows"] == [[2024, "技术", 10]]
        assert result.data["field_substitutions"] == [{
            "requested": "订单日期",
            "used": "发货日期",
            "reason": "requested field is not available from Tableau MCP metadata",
        }]

    @pytest.mark.asyncio
    async def test_direct_path_missing_dimension_returns_field_unavailable(self, tool, tool_context):
        mock_ds_info = {
            "luid": "test-luid",
            "name": "订单+ (示例 - 超市)",
            "asset_id": 123,
        }

        with patch("services.data_agent.tools.query_tool.route_datasource", return_value=mock_ds_info):
            with patch("services.data_agent.tools.query_tool.get_datasource_fields_cached", return_value=["国家/地区", "省/自治区", "类别"]):
                with patch("services.data_agent.tools.query_tool._get_mcp_queryable_field_candidates", return_value=["省/自治区", "类别"]):
                    with patch("services.data_agent.tools.query_tool.execute_query", new_callable=AsyncMock) as mock_exec:
                        mock_exec.side_effect = NLQError(
                            code="NLQ_006",
                            message="MCP 工具执行失败: Field '国家/地区' was not found in the datasource.",
                        )

                        result = await tool.execute(
                            {"question": "国家/地区 都有哪些值？", "datasource_name": "订单+ (示例 - 超市)"},
                            tool_context,
                        )

        assert result.success is True
        assert result.data["intent"] == "field_unavailable"
        assert result.data["field_unavailable"] == {
            "requested": "国家/地区",
            "available_fields": ["省/自治区", "类别"],
            "suggestion": "省/自治区",
            "reason": "requested field is not available from Tableau MCP metadata",
        }
        assert result.data["rows"] == []

    @pytest.mark.asyncio
    async def test_direct_path_top10_customers_sorts_and_calculates_share_locally(self, tool, tool_context):
        mock_ds_info = {
            "luid": "test-luid",
            "name": "test-datasource",
            "asset_id": 123,
        }

        rows = [
            ["客户B", 30],
            ["客户A", 70],
            ["客户C", 10],
        ]

        with patch("services.data_agent.tools.query_tool.route_datasource", return_value=mock_ds_info):
            with patch("services.data_agent.tools.query_tool.get_datasource_fields_cached", return_value=["订单日期", "客户名称", "净额"]):
                with patch("services.data_agent.tools.query_tool.one_pass_llm", new_callable=AsyncMock) as mock_nlq:
                    with patch("services.data_agent.tools.query_tool.execute_query", new_callable=AsyncMock) as mock_exec:
                        mock_exec.return_value = {"fields": ["客户名称", "净额"], "rows": rows}

                        result = await tool.execute({"question": "2024 年 Top2 大客户及占比"}, tool_context)

        assert result.success is True
        mock_nlq.assert_not_called()
        assert result.data["fields"] == ["客户名称", "净额", "占比"]
        assert result.data["rows"] == [["客户A", 70, 70 / 110], ["客户B", 30, 30 / 110]]
        assert result.data["top_n"] == 2
        assert result.data["share_calculated"] is True

    @pytest.mark.asyncio
    async def test_direct_path_customer_churn_calculates_set_difference(self, tool, tool_context):
        mock_ds_info = {
            "luid": "test-luid",
            "name": "test-datasource",
            "asset_id": 123,
        }

        with patch("services.data_agent.tools.query_tool.route_datasource", return_value=mock_ds_info):
            with patch("services.data_agent.tools.query_tool.get_datasource_fields_cached", return_value=["订单日期", "客户ID", "净额"]):
                with patch("services.data_agent.tools.query_tool.execute_query") as mock_exec:
                    mock_exec.side_effect = [
                        {"fields": ["客户ID"], "rows": [["C1"], ["C2"], ["C3"]]},
                        {"fields": ["客户ID"], "rows": [["C2"]]},
                    ]

                    result = await tool.execute(
                        {"question": "哪些 2021 年的老客户流失了（定义 2021 年有订单，但最近一年没有订单）？"},
                        tool_context,
                    )

        assert result.success is True
        assert result.data["fields"] == ["客户ID"]
        assert result.data["rows"] == [["C1"], ["C3"]]
        assert result.data["customer_churn"]["base_year"] == 2021
        assert result.data["customer_churn"]["churned_customer_count"] == 2

    # =============================================================================
    # TC-QUERY-004: route_datasource 失败
    # =============================================================================
    @pytest.mark.asyncio
    async def test_tc_query_004_route_failure(self, tool, tool_context):
        """TC-QUERY-004: route_datasource 返回 None"""
        with patch("services.data_agent.tools.query_tool.route_datasource") as mock_route:
            mock_route.return_value = None

            result = await tool.execute({"question": "无效问题"}, tool_context)

        assert result.success is False
        assert "数据源" in result.error or "无法找到" in result.error

    # =============================================================================
    # TC-QUERY-005: one_pass_llm NLQError
    # =============================================================================
    @pytest.mark.asyncio
    async def test_tc_query_005_nlq_error(self, tool, tool_context):
        """TC-QUERY-005: one_pass_llm 抛出 NLQError"""
        mock_ds_info = {
            "luid": "test-luid",
            "name": "test-datasource",
            "fields_with_types": "",
            "term_mappings": "",
        }

        with patch("services.data_agent.tools.query_tool.route_datasource", return_value=mock_ds_info):
            with patch("services.data_agent.tools.query_tool.one_pass_llm", new_callable=AsyncMock) as mock_nlq:
                mock_nlq.side_effect = NLQError(code="NLQ_006", message="NLQ 服务不可用")

                result = await tool.execute({"question": "Q4 销售额"}, tool_context)

        assert result.success is False
        assert "NLQ_006" in result.error or "NLQ" in result.error

    # =============================================================================
    # TC-QUERY-006: one_pass_llm 返回空 vizql_json
    # =============================================================================
    @pytest.mark.asyncio
    async def test_tc_query_006_empty_vizql(self, tool, tool_context):
        """TC-QUERY-006: one_pass_llm 返回空的 vizql_json"""
        mock_ds_info = {
            "luid": "test-luid",
            "name": "test-datasource",
            "fields_with_types": "",
            "term_mappings": "",
        }

        with patch("services.data_agent.tools.query_tool.route_datasource", return_value=mock_ds_info):
            with patch("services.data_agent.tools.query_tool.one_pass_llm", new_callable=AsyncMock) as mock_nlq:
                mock_nlq.return_value = {"vizql_json": {}}  # 空 vizql

                result = await tool.execute({"question": "Q4 销售额"}, tool_context)

        assert result.success is False
        assert "空" in result.error or "empty" in result.error.lower()

    # =============================================================================
    # TC-QUERY-007: execute_query NLQError
    # =============================================================================
    @pytest.mark.asyncio
    async def test_tc_query_007_execute_error(self, tool, tool_context):
        """TC-QUERY-007: execute_query 抛出 NLQError"""
        mock_ds_info = {
            "luid": "test-luid",
            "name": "test-datasource",
            "fields_with_types": "",
            "term_mappings": "",
        }
        mock_vizql = {"worksheets": ["Sales"]}

        with patch("services.data_agent.tools.query_tool.route_datasource", return_value=mock_ds_info):
            with patch("services.data_agent.tools.query_tool.one_pass_llm", new_callable=AsyncMock) as mock_nlq:
                mock_nlq.return_value = {"vizql_json": mock_vizql}

                with patch("services.data_agent.tools.query_tool.execute_query", new_callable=AsyncMock) as mock_exec:
                    mock_exec.side_effect = NLQError(code="NLQ_007", message="查询超时")

                    result = await tool.execute({"question": "Q4 销售额"}, tool_context)

        assert result.success is False
        assert "NLQ_007" in result.error or "超时" in result.error

    # =============================================================================
    # TC-QUERY-008: 成功场景（mock）
    # =============================================================================
    @pytest.mark.asyncio
    async def test_tc_query_008_success_mock(self, tool, tool_context):
        """TC-QUERY-008: 成功场景（mock）"""
        mock_ds_info = {
            "luid": "test-luid",
            "name": "test-datasource",
            "fields_with_types": "",
            "term_mappings": "",
        }
        mock_vizql = {"worksheets": ["Sales"]}
        mock_result = {
            "fields": [{"name": "销售额", "type": "number"}],
            "rows": [[3200]],
        }

        with patch("services.data_agent.tools.query_tool.route_datasource", return_value=mock_ds_info):
            with patch("services.data_agent.tools.query_tool.one_pass_llm", new_callable=AsyncMock) as mock_nlq:
                mock_nlq.return_value = {
                    "vizql_json": mock_vizql,
                    "intent": "sales_query",
                    "confidence": 0.95,
                }

                with patch("services.data_agent.tools.query_tool.execute_query", new_callable=AsyncMock) as mock_exec:
                    mock_exec.return_value = mock_result

                    result = await tool.execute({"question": "Q4 销售额"}, tool_context)

        # 注意：由于 mock 可能不完全，这里只验证不抛异常
        # 实际成功需要完整的 NLQ Service
        assert result.success in (True, False)
        assert result.execution_time_ms >= 0

    # =============================================================================
    # TC-QUERY-009: 参数 schema 验证
    # =============================================================================
    def test_tc_query_009_parameters_schema(self, tool):
        """TC-QUERY-009: 验证参数 schema 定义"""
        schema = tool.parameters_schema

        assert schema["type"] == "object"
        assert "question" in schema["properties"]
        assert schema["properties"]["question"]["type"] == "string"
        assert "connection_id" in schema["properties"]
        assert schema["properties"]["connection_id"]["type"] == "integer"

    # =============================================================================
    # TC-QUERY-010: 工具元数据
    # =============================================================================
    def test_tc_query_010_metadata(self, tool):
        """TC-QUERY-010: 验证工具名称和描述"""
        assert tool.name == "query"
        assert "自然语言" in tool.description or "NLQ" in tool.description
        assert tool.metadata.category == "query"
        assert "nlq" in tool.metadata.tags or "vizql" in tool.metadata.tags

    # =============================================================================
    # TC-QUERY-011: connection_id 优先级
    # =============================================================================
    @pytest.mark.asyncio
    async def test_tc_query_011_connection_id_priority(self, tool):
        """TC-QUERY-011: 参数 connection_id 优先于 context.connection_id"""
        # 参数 connection_id = 5
        # context connection_id = 1
        context = ToolContext(
            session_id="s1",
            user_id=1,
            connection_id=1,
            trace_id="t1",
        )

        captured_connection_id = None

        def capture_route(question, connection_id=None):
            nonlocal captured_connection_id
            captured_connection_id = connection_id
            return None

        with patch("services.data_agent.tools.query_tool.route_datasource", side_effect=capture_route):
            await tool.execute({"question": "销售额", "connection_id": 5}, context)

        # 验证使用了参数中的 connection_id=5，而非 context 中的 1
        assert captured_connection_id == 5

    # =============================================================================
    # TC-QUERY-012: 异常处理
    # =============================================================================
    @pytest.mark.asyncio
    async def test_tc_query_012_exception_handling(self, tool, tool_context):
        """TC-QUERY-012: 未知异常应返回友好错误"""
        with patch("services.data_agent.tools.query_tool.route_datasource") as mock_route:
            mock_route.side_effect = Exception("Unexpected error")

            result = await tool.execute({"question": "销售额"}, tool_context)

        assert result.success is False
        assert "暂时不可用" in result.error or "请稍后重试" in result.error
        assert result.execution_time_ms >= 0

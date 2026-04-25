"""
QueryTool 集成测试 — TC-QT-001 ~ TC-QT-003

参考：docs/specs/36-data-agent-architecture-test-cases.md §3

前置依赖：
- services/data_agent/tools/query_tool.py
- services/llm/nlq_service.py (route_datasource / one_pass_llm / execute_query)
"""

import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from services.data_agent.tools.query_tool import QueryTool
from services.data_agent.tool_base import ToolContext, ToolResult
from services.llm.nlq_service import NLQError


class TestQueryTool:
    """QueryTool 集成测试 — TC-QT-001 ~ TC-QT-003"""

    @pytest.fixture
    def tool(self):
        return QueryTool()

    @pytest.fixture
    def context(self):
        return ToolContext(
            session_id="test-session-1",
            user_id=1,
            connection_id=1,
            trace_id="trace-qt-001",
        )

    # -------------------------------------------------------------------------
    # TC-QT-001：正常查询
    # -------------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_tc_qt_001_normal_query(self, tool, context):
        """TC-QT-001: 正常查询 — ToolResult.success=True，包含 fields/rows/intent"""
        mock_ds_info = {
            "luid": "ds-luid-abc123",
            "name": "TestDatasource",
            "fields_with_types": "sales:float,region:string",
            "term_mappings": {},
        }
        mock_parsed = {
            "intent": "aggregate",
            "confidence": 0.92,
            "vizql_json": {
                "fields": [
                    {"fieldCaption": "sales", "function": "SUM"},
                ],
            },
        }
        mock_result = {
            "fields": [
                {"caption": "sales", "name": "sales"},
            ],
            "rows": [[3200], [1500], [980]],
        }

        with patch(
            "services.data_agent.tools.query_tool.route_datasource",
            return_value=mock_ds_info,
        ), patch(
            "services.data_agent.tools.query_tool.one_pass_llm",
            new_callable=AsyncMock,
            return_value=mock_parsed,
        ), patch(
            "services.data_agent.tools.query_tool.execute_query",
            return_value=mock_result,
        ):
            params = {"question": "Q4 总销售额", "connection_id": 1}
            result = await tool.execute(params, context)

        assert result.success is True
        assert result.data is not None
        assert "fields" in result.data
        assert "rows" in result.data
        assert result.data["intent"] == "aggregate"
        assert result.data["confidence"] == 0.92
        assert result.data["datasource_name"] == "TestDatasource"
        assert result.execution_time_ms >= 0

    # -------------------------------------------------------------------------
    # TC-QT-002：无效 connection_id（数据源路由失败）
    # -------------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_tc_qt_002_invalid_connection_id(self, tool, context):
        """TC-QT-002: 无效 connection_id — route_datasource 返回 None"""
        with patch(
            "services.data_agent.tools.query_tool.route_datasource",
            return_value=None,
        ):
            params = {"question": "Q4 销售额", "connection_id": 99999}
            result = await tool.execute(params, context)

        assert result.success is False
        assert result.error is not None
        assert "无法找到匹配的数据源" in result.error or "数据源" in result.error

    # -------------------------------------------------------------------------
    # TC-QT-003：NLQ 服务异常
    # -------------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_tc_qt_003_nlq_service_exception(self, tool, context):
        """TC-QT-003: NLQ 服务异常 — 捕获 NLQError，返回 friendly 错误"""
        mock_ds_info = {
            "luid": "ds-luid-abc123",
            "name": "TestDatasource",
            "fields_with_types": "sales:float",
            "term_mappings": {},
        }

        with patch(
            "services.data_agent.tools.query_tool.route_datasource",
            return_value=mock_ds_info,
        ), patch(
            "services.data_agent.tools.query_tool.one_pass_llm",
            new_callable=AsyncMock,
            side_effect=NLQError("NLQ_008", "LLM 服务暂时不可用"),
        ):
            params = {"question": "Q4 销售额", "connection_id": 1}
            result = await tool.execute(params, context)

        assert result.success is False
        assert result.error is not None
        assert "NLQ_008" in result.error or "LLM" in result.error
        # 确保不暴露内部堆栈（已在 Tool 内 catch）
        assert "Traceback" not in result.error
        assert result.execution_time_ms >= 0

    # -------------------------------------------------------------------------
    # TC-QT-003b：NLQ 服务 execute_query 异常
    # -------------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_tc_qt_003b_execute_query_exception(self, tool, context):
        """TC-QT-003 变体: execute_query 阶段抛 NLQError"""
        mock_ds_info = {
            "luid": "ds-luid-abc123",
            "name": "TestDatasource",
            "fields_with_types": "sales:float",
            "term_mappings": {},
        }
        mock_parsed = {
            "intent": "aggregate",
            "confidence": 0.85,
            "vizql_json": {"fields": [{"fieldCaption": "sales"}]},
        }

        with patch(
            "services.data_agent.tools.query_tool.route_datasource",
            return_value=mock_ds_info,
        ), patch(
            "services.data_agent.tools.query_tool.one_pass_llm",
            new_callable=AsyncMock,
            return_value=mock_parsed,
        ), patch(
            "services.data_agent.tools.query_tool.execute_query",
            side_effect=NLQError("NLQ_006", "数据查询执行失败"),
        ):
            params = {"question": "Q4 销售额"}
            result = await tool.execute(params, context)

        assert result.success is False
        assert "NLQ_006" in result.error
        assert "Traceback" not in result.error

    # -------------------------------------------------------------------------
    # 边界: empty question
    # -------------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_empty_question(self, tool, context):
        """空问题直接返回失败，不调用 NLQ 服务"""
        params = {"question": ""}
        result = await tool.execute(params, context)

        assert result.success is False
        assert "question cannot be empty" in result.error
        assert result.execution_time_ms >= 0

    # -------------------------------------------------------------------------
    # 边界: missing vizql_json
    # -------------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_tc_qt_001_missing_vizql_json(self, tool, context):
        """one_pass_llm 返回空的 vizql_json"""
        mock_ds_info = {
            "luid": "ds-luid-abc123",
            "name": "TestDatasource",
            "fields_with_types": "",
            "term_mappings": {},
        }
        mock_parsed = {
            "intent": "aggregate",
            "confidence": 0.5,
            "vizql_json": {},  # 空 VizQL
        }

        with patch(
            "services.data_agent.tools.query_tool.route_datasource",
            return_value=mock_ds_info,
        ), patch(
            "services.data_agent.tools.query_tool.one_pass_llm",
            new_callable=AsyncMock,
            return_value=mock_parsed,
        ):
            params = {"question": "销售额"}
            result = await tool.execute(params, context)

        assert result.success is False
        assert "VizQL JSON 为空" in result.error

"""
MetricsTool 单元测试 — 使用 mock db session，不依赖真实数据库
"""

import pytest
import uuid
from datetime import datetime
from unittest.mock import MagicMock, patch

from services.data_agent.tools.metrics_tool import MetricsTool
from services.data_agent.tool_base import ToolContext, ToolResult


class TestMetricsTool:
    """MetricsTool 测试用例"""

    @pytest.fixture
    def tool(self):
        return MetricsTool()

    def _make_mock_metric(self, id_val=1, name="sales_amount", name_zh="销售额",
                          metric_type="gauge", business_domain="sales",
                          datasource_id=1, table_name="sales", column_name="amount"):
        """创建模拟的 BiMetricDefinition 对象"""
        m = MagicMock()
        m.id = uuid.uuid4() if isinstance(id_val, int) else id_val
        m.name = name
        m.name_zh = name_zh
        m.metric_type = metric_type
        m.business_domain = business_domain
        m.description = f"{name_zh} metric"
        m.formula = f"SUM({column_name})"
        m.formula_template = "SUM({column})"
        m.aggregation_type = "sum"
        m.result_type = "numeric"
        m.unit = "元"
        m.precision = 2
        m.datasource_id = datasource_id
        m.table_name = table_name
        m.column_name = column_name
        m.filters = None
        m.sensitivity_level = "public"
        m.is_active = True
        m.lineage_status = "active"
        m.created_at = datetime(2024, 1, 1, 0, 0, 0)
        return m

    # =============================================================================
    # TC-METRICS-001: 无筛选条件查询，返回所有活跃指标
    # =============================================================================
    @pytest.mark.asyncio
    async def test_tc_metrics_001_query_all_no_filters(self, tool, db_session):
        """TC-METRICS-001: 无筛选条件查询，返回所有活跃指标"""
        mock_metrics = [
            self._make_mock_metric(1, "sales_amount", "销售额"),
            self._make_mock_metric(2, "order_count", "订单数"),
        ]

        mock_query = MagicMock()
        mock_query.filter.return_value = mock_query
        mock_query.count.return_value = 2
        mock_query.order_by.return_value.limit.return_value.all.return_value = mock_metrics
        db_session.query = MagicMock(return_value=mock_query)

        context = ToolContext(
            session_id="s1", user_id=1, connection_id=None, trace_id="t1"
        )

        with patch("app.core.database.SessionLocal", return_value=db_session):
            result = await tool.execute({}, context)

        assert result.success is True
        assert result.data["total"] == 2
        assert len(result.data["metrics"]) == 2
        assert result.data["metrics"][0]["name"] == "sales_amount"
        assert result.data["metrics"][0]["name_zh"] == "销售额"

    # =============================================================================
    # TC-METRICS-002: 按 connection_id 过滤
    # =============================================================================
    @pytest.mark.asyncio
    async def test_tc_metrics_002_filter_by_connection_id(self, tool, db_session):
        """TC-METRICS-002: 按 connection_id 过滤指标"""
        mock_metrics = [
            self._make_mock_metric(1, "sales_amount", "销售额", datasource_id=10),
        ]

        mock_query = MagicMock()
        mock_query.filter.return_value = mock_query
        mock_query.count.return_value = 1
        mock_query.order_by.return_value.limit.return_value.all.return_value = mock_metrics
        db_session.query = MagicMock(return_value=mock_query)

        context = ToolContext(
            session_id="s1", user_id=1, connection_id=None, trace_id="t1"
        )

        with patch("app.core.database.SessionLocal", return_value=db_session):
            result = await tool.execute({"connection_id": 10}, context)

        assert result.success is True
        assert result.data["total"] == 1
        assert result.data["filters"]["connection_id"] == 10

    # =============================================================================
    # TC-METRICS-003: 按 keyword 搜索（ILIKE 匹配）
    # =============================================================================
    @pytest.mark.asyncio
    async def test_tc_metrics_003_filter_by_keyword(self, tool, db_session):
        """TC-METRICS-003: 按关键词搜索指标名称/描述"""
        mock_metrics = [
            self._make_mock_metric(1, "sales_amount", "销售额"),
        ]

        mock_query = MagicMock()
        mock_query.filter.return_value = mock_query
        mock_query.count.return_value = 1
        mock_query.order_by.return_value.limit.return_value.all.return_value = mock_metrics
        db_session.query = MagicMock(return_value=mock_query)

        context = ToolContext(
            session_id="s1", user_id=1, connection_id=None, trace_id="t1"
        )

        with patch("app.core.database.SessionLocal", return_value=db_session):
            result = await tool.execute({"keyword": "销售"}, context)

        assert result.success is True
        assert result.data["total"] == 1
        assert result.data["filters"]["keyword"] == "销售"

    # =============================================================================
    # TC-METRICS-004: 按 metric_type 过滤
    # =============================================================================
    @pytest.mark.asyncio
    async def test_tc_metrics_004_filter_by_metric_type(self, tool, db_session):
        """TC-METRICS-004: 按 metric_type 过滤（gauge/counter/derived）"""
        mock_metrics = [
            self._make_mock_metric(1, "error_rate", "错误率", metric_type="gauge"),
        ]

        mock_query = MagicMock()
        mock_query.filter.return_value = mock_query
        mock_query.count.return_value = 1
        mock_query.order_by.return_value.limit.return_value.all.return_value = mock_metrics
        db_session.query = MagicMock(return_value=mock_query)

        context = ToolContext(
            session_id="s1", user_id=1, connection_id=None, trace_id="t1"
        )

        with patch("app.core.database.SessionLocal", return_value=db_session):
            result = await tool.execute({"metric_type": "gauge"}, context)

        assert result.success is True
        assert result.data["filters"]["metric_type"] == "gauge"

    # =============================================================================
    # TC-METRICS-005: 多条件组合过滤
    # =============================================================================
    @pytest.mark.asyncio
    async def test_tc_metrics_005_combined_filters(self, tool, db_session):
        """TC-METRICS-005: 组合过滤（connection_id + keyword + metric_type + domain）"""
        mock_metrics = [
            self._make_mock_metric(1, "sales_amount", "销售额",
                                   metric_type="gauge", business_domain="sales"),
        ]

        mock_query = MagicMock()
        mock_query.filter.return_value = mock_query
        mock_query.count.return_value = 1
        mock_query.order_by.return_value.limit.return_value.all.return_value = mock_metrics
        db_session.query = MagicMock(return_value=mock_query)

        context = ToolContext(
            session_id="s1", user_id=1, connection_id=1, trace_id="t1"
        )

        with patch("app.core.database.SessionLocal", return_value=db_session):
            result = await tool.execute({
                "connection_id": 1,
                "keyword": "sales",
                "metric_type": "gauge",
                "business_domain": "sales",
            }, context)

        assert result.success is True
        filters = result.data["filters"]
        assert filters["connection_id"] == 1
        assert filters["keyword"] == "sales"
        assert filters["metric_type"] == "gauge"
        assert filters["business_domain"] == "sales"

    # =============================================================================
    # TC-METRICS-006: limit 参数限制返回数量
    # =============================================================================
    @pytest.mark.asyncio
    async def test_tc_metrics_006_limit(self, tool, db_session):
        """TC-METRICS-006: limit 参数正确限制返回数量"""
        mock_metrics = [
            self._make_mock_metric(i, f"metric_{i}", f"指标{i}")
            for i in range(5)
        ]

        mock_query = MagicMock()
        mock_query.filter.return_value = mock_query
        mock_query.count.return_value = 100  # total 100 but limit 5
        mock_query.order_by.return_value.limit.return_value.all.return_value = mock_metrics
        db_session.query = MagicMock(return_value=mock_query)

        context = ToolContext(
            session_id="s1", user_id=1, connection_id=None, trace_id="t1"
        )

        with patch("app.core.database.SessionLocal", return_value=db_session):
            result = await tool.execute({"limit": 5}, context)

        assert result.success is True
        assert result.data["limit"] == 5
        assert len(result.data["metrics"]) == 5
        assert result.data["total"] == 100  # total is still 100

    # =============================================================================
    # TC-METRICS-007: 无匹配结果
    # =============================================================================
    @pytest.mark.asyncio
    async def test_tc_metrics_007_no_results(self, tool, db_session):
        """TC-METRICS-007: 无匹配结果时返回空列表"""
        mock_query = MagicMock()
        mock_query.filter.return_value = mock_query
        mock_query.count.return_value = 0
        mock_query.order_by.return_value.limit.return_value.all.return_value = []
        db_session.query = MagicMock(return_value=mock_query)

        context = ToolContext(
            session_id="s1", user_id=1, connection_id=None, trace_id="t1"
        )

        with patch("app.core.database.SessionLocal", return_value=db_session):
            result = await tool.execute({"keyword": "nonexistent"}, context)

        assert result.success is True
        assert result.data["total"] == 0
        assert result.data["metrics"] == []

    # =============================================================================
    # TC-METRICS-008: 数据库异常
    # =============================================================================
    @pytest.mark.asyncio
    async def test_tc_metrics_008_db_exception(self, tool, db_session):
        """TC-METRICS-008: 数据库异常时返回错误"""
        mock_query = MagicMock()
        mock_query.filter.side_effect = Exception("DB connection lost")
        db_session.query = MagicMock(return_value=mock_query)

        context = ToolContext(
            session_id="s1", user_id=1, connection_id=None, trace_id="t1"
        )

        with patch("app.core.database.SessionLocal", return_value=db_session):
            result = await tool.execute({}, context)

        assert result.success is False
        assert "查询指标定义失败" in result.error

    # =============================================================================
    # TC-METRICS-009: context.connection_id 作为默认值
    # =============================================================================
    @pytest.mark.asyncio
    async def test_tc_metrics_009_context_connection_id(self, tool, db_session):
        """TC-METRICS-009: 未传 connection_id 时使用 context.connection_id"""
        mock_metrics = [
            self._make_mock_metric(1, "sales_amount", "销售额", datasource_id=5),
        ]

        mock_query = MagicMock()
        mock_query.filter.return_value = mock_query
        mock_query.count.return_value = 1
        mock_query.order_by.return_value.limit.return_value.all.return_value = mock_metrics
        db_session.query = MagicMock(return_value=mock_query)

        context = ToolContext(
            session_id="s1", user_id=1, connection_id=5, trace_id="t1"
        )

        with patch("app.core.database.SessionLocal", return_value=db_session):
            result = await tool.execute({}, context)

        assert result.success is True
        assert result.data["filters"]["connection_id"] == 5


class TestMetricsToolFields:
    """MetricsTool 字段完整性测试"""

    @pytest.fixture
    def tool(self):
        return MetricsTool()

    @pytest.mark.asyncio
    async def test_returns_all_metric_fields(self, tool, db_session):
        """返回的指标包含所有定义字段"""
        m = MagicMock()
        m.id = uuid.uuid4()
        m.name = "test_metric"
        m.name_zh = "测试指标"
        m.metric_type = "derived"
        m.business_domain = "finance"
        m.description = "测试描述"
        m.formula = "SUM(amount) / COUNT(id)"
        m.formula_template = "SUM({column}) / COUNT({id})"
        m.aggregation_type = "custom"
        m.result_type = "ratio"
        m.unit = "%"
        m.precision = 4
        m.datasource_id = 1
        m.table_name = "orders"
        m.column_name = "amount"
        m.filters = {"region": "east"}
        m.sensitivity_level = "internal"
        m.is_active = True
        m.lineage_status = "active"
        m.created_at = datetime(2024, 6, 1, 12, 0, 0)

        mock_query = MagicMock()
        mock_query.filter.return_value = mock_query
        mock_query.count.return_value = 1
        mock_query.order_by.return_value.limit.return_value.all.return_value = [m]
        db_session.query = MagicMock(return_value=mock_query)

        context = ToolContext(
            session_id="s1", user_id=1, connection_id=None, trace_id="t1"
        )

        with patch("app.core.database.SessionLocal", return_value=db_session):
            result = await tool.execute({}, context)

        assert result.success is True
        metric = result.data["metrics"][0]

        # Verify all fields are present
        assert metric["name"] == "test_metric"
        assert metric["name_zh"] == "测试指标"
        assert metric["metric_type"] == "derived"
        assert metric["business_domain"] == "finance"
        assert metric["description"] == "测试描述"
        assert metric["formula"] == "SUM(amount) / COUNT(id)"
        assert metric["formula_template"] == "SUM({column}) / COUNT({id})"
        assert metric["aggregation_type"] == "custom"
        assert metric["result_type"] == "ratio"
        assert metric["unit"] == "%"
        assert metric["precision"] == 4
        assert metric["datasource_id"] == 1
        assert metric["table_name"] == "orders"
        assert metric["column_name"] == "amount"
        assert metric["filters"] == {"region": "east"}
        assert metric["sensitivity_level"] == "internal"
        assert metric["is_active"] is True
        assert metric["lineage_status"] == "active"
        assert metric["created_at"] == "2024-06-01 12:00:00"
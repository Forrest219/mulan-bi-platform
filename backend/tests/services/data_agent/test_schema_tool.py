"""
SchemaTool 单元测试 — Tableau-only 首页 Agent schema 查询。
"""

from unittest.mock import MagicMock, patch

import pytest

from services.data_agent.tool_base import ToolContext
from services.data_agent.tools.schema_tool import SchemaTool
from services.tableau.models import TableauAsset, TableauConnection, TableauDatasourceField


def _criterion_value(criteria, column_key):
    """Extract simple SQLAlchemy binary-expression values from mock filters."""
    for criterion in criteria:
        left = getattr(criterion, "left", None)
        if getattr(left, "key", None) == column_key:
            right = getattr(criterion, "right", None)
            return getattr(right, "value", None)
    return None


def _mock_tableau_schema_db(connection=None, assets=None, fields=None):
    """Mock enough of Session.query for Tableau schema lookups."""
    assets = [] if assets is None else assets
    fields = [] if fields is None else fields

    class MockQuery:
        def __init__(self, model):
            self.model = model
            self.criteria = []
            self._limit = None

        def filter(self, *criteria):
            self.criteria.extend(criteria)
            return self

        def order_by(self, *args):
            return self

        def limit(self, limit):
            self._limit = limit
            return self

        def all(self):
            if self.model is TableauAsset:
                rows = assets
                asset_type = _criterion_value(self.criteria, "asset_type")
                if asset_type is not None:
                    rows = [asset for asset in rows if asset.asset_type == asset_type]
            elif self.model is TableauDatasourceField:
                asset_id = _criterion_value(self.criteria, "asset_id")
                rows = [field for field in fields if field.asset_id == asset_id]
            else:
                rows = []
            return rows[: self._limit] if self._limit else rows

        def first(self):
            if self.model is TableauConnection:
                wanted_id = _criterion_value(self.criteria, "id")
                if connection and connection.id == wanted_id and connection.is_active:
                    return connection
                return None

            if self.model is TableauAsset:
                name = _criterion_value(self.criteria, "name")
                asset_type = _criterion_value(self.criteria, "asset_type")
                rows = assets
                if asset_type is not None:
                    rows = [asset for asset in rows if asset.asset_type == asset_type]
                if name is None:
                    return rows[0] if rows else None
                return next((asset for asset in rows if asset.name == name), None)

            return None

    mock_db = MagicMock()
    mock_db.query.side_effect = lambda model: MockQuery(model)
    return mock_db


def _tableau_connection(connection_id=1, is_active=True):
    return TableauConnection(
        id=connection_id,
        name="Tableau-online",
        server_url="https://online.tableau.com",
        site="zy_bi",
        token_name="token",
        token_encrypted="encrypted",
        owner_id=1,
        is_active=is_active,
    )


def _tableau_asset(asset_id=101, name="orders-订单明细表", asset_type="datasource"):
    return TableauAsset(
        id=asset_id,
        connection_id=1,
        asset_type=asset_type,
        tableau_id="ds-101",
        name=name,
        project_name="数据源",
        web_url="https://online.tableau.com/#/datasources/101",
        is_deleted=False,
    )


class TestSchemaTool:
    @pytest.fixture
    def tool(self):
        return SchemaTool()

    @pytest.mark.asyncio
    async def test_missing_connection_id(self, tool):
        context = ToolContext(session_id="s1", user_id=1, connection_id=None, trace_id="t1")

        result = await tool.execute({}, context)

        assert result.success is False
        assert "connection_id is required" in result.error

    @pytest.mark.asyncio
    async def test_inactive_or_missing_tableau_connection_returns_clear_error(self, tool):
        mock_db = _mock_tableau_schema_db(connection=None)
        context = ToolContext(session_id="s1", user_id=1, connection_id=999, trace_id="t1")

        with patch("services.data_agent.tools.schema_tool.SessionLocal", return_value=mock_db):
            result = await tool.execute({}, context)

        assert result.success is False
        assert result.error == "Tableau 连接不存在或已停用"

    @pytest.mark.asyncio
    async def test_list_tableau_assets(self, tool):
        asset = _tableau_asset()
        mock_db = _mock_tableau_schema_db(connection=_tableau_connection(), assets=[asset])
        context = ToolContext(session_id="s1", user_id=1, connection_id=1, trace_id="t1")

        with patch("services.data_agent.tools.schema_tool.SessionLocal", return_value=mock_db):
            result = await tool.execute({}, context)

        assert result.success is True
        assert result.data["db_type"] == "tableau"
        assert result.data["tables"][0]["name"] == "orders-订单明细表"
        assert result.data["asset_summary"] == {"datasource": 1}

    @pytest.mark.asyncio
    async def test_list_tableau_assets_defaults_to_published_datasources_only(self, tool):
        datasource = _tableau_asset(asset_id=101, name="orders-订单明细表", asset_type="datasource")
        view = _tableau_asset(asset_id=102, name="Orders View", asset_type="view")
        workbook = _tableau_asset(asset_id=103, name="Orders Workbook", asset_type="workbook")
        mock_db = _mock_tableau_schema_db(
            connection=_tableau_connection(),
            assets=[datasource, view, workbook],
        )
        context = ToolContext(session_id="s1", user_id=1, connection_id=1, trace_id="t1")

        with patch("services.data_agent.tools.schema_tool.SessionLocal", return_value=mock_db):
            result = await tool.execute({}, context)

        assert result.success is True
        assert [table["type"] for table in result.data["tables"]] == ["datasource"]
        assert result.data["tables"][0]["name"] == "orders-订单明细表"
        assert result.data["asset_summary"] == {"datasource": 1}

    @pytest.mark.asyncio
    async def test_list_tableau_assets_can_include_views_when_explicitly_requested(self, tool):
        datasource = _tableau_asset(asset_id=101, name="orders-订单明细表", asset_type="datasource")
        view = _tableau_asset(asset_id=102, name="Orders View", asset_type="view")
        workbook = _tableau_asset(asset_id=103, name="Orders Workbook", asset_type="workbook")
        mock_db = _mock_tableau_schema_db(
            connection=_tableau_connection(),
            assets=[datasource, view, workbook],
        )
        context = ToolContext(session_id="s1", user_id=1, connection_id=1, trace_id="t1")

        with patch("services.data_agent.tools.schema_tool.SessionLocal", return_value=mock_db):
            result = await tool.execute({"include_all_asset_types": True}, context)

        assert result.success is True
        assert [table["type"] for table in result.data["tables"]] == ["datasource", "view", "workbook"]
        assert result.data["asset_summary"] == {"datasource": 1, "view": 1, "workbook": 1}

    def test_tableau_table_name_matches_asset_suffix_with_empty_fields_warning(self, tool, monkeypatch):
        """table_name='订单明细表' 应匹配 TableauAsset.name='orders-订单明细表'。"""
        asset = _tableau_asset()
        mock_db = _mock_tableau_schema_db(assets=[asset], fields=[])
        monkeypatch.setattr(
            tool,
            "_sync_missing_tableau_fields",
            lambda db, tc, asset: {"synced": 0, "error": "Tableau 未返回字段列表"},
        )

        data = tool._query_tableau_schema(
            mock_db,
            _tableau_connection(),
            table_name="订单明细表",
            limit=100,
        )

        assert data["fields"] == {"orders-订单明细表": []}
        assert data["matched_asset"]["name"] == "orders-订单明细表"
        assert data["field_count"] == 0
        assert data["warning"] == "已匹配到 Tableau 资产，但自动同步字段元数据未返回字段：Tableau 未返回字段列表"

    def test_tableau_empty_fields_auto_syncs_before_return(self, tool, monkeypatch):
        asset = _tableau_asset()
        synced_field = TableauDatasourceField(
            asset_id=asset.id,
            datasource_luid=asset.tableau_id,
            field_name="[销售额]",
            field_caption="销售额",
            data_type="real",
            role="measure",
            is_calculated=False,
        )
        fields = []
        mock_db = _mock_tableau_schema_db(assets=[asset], fields=fields)

        def fake_sync(db, tc, matched_asset):
            fields.append(synced_field)
            return {"synced": 1}

        monkeypatch.setattr(tool, "_sync_missing_tableau_fields", fake_sync)

        data = tool._query_tableau_schema(
            mock_db,
            _tableau_connection(),
            table_name="订单明细表",
            limit=100,
        )

        assert data["fields"]["orders-订单明细表"][0]["caption"] == "销售额"
        assert data["field_count"] == 1
        assert "warning" not in data

    def test_tableau_exact_match_returns_fields(self, tool):
        asset = _tableau_asset()
        field = TableauDatasourceField(
            asset_id=asset.id,
            datasource_luid=asset.tableau_id,
            field_name="[订单 ID]",
            field_caption="订单 ID",
            data_type="string",
            role="dimension",
            is_calculated=False,
        )
        mock_db = _mock_tableau_schema_db(assets=[asset], fields=[field])

        data = tool._query_tableau_schema(
            mock_db,
            _tableau_connection(),
            table_name="orders-订单明细表",
            limit=100,
        )

        assert data["fields"]["orders-订单明细表"][0]["caption"] == "订单 ID"
        assert data["field_count"] == 1
        assert "warning" not in data

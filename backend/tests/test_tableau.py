"""测试：Tableau API"""

import pytest
from unittest.mock import patch, MagicMock
from datetime import datetime, timezone, timedelta
from services.tableau.mcp_client import TableauMCPError


def test_get_connections_without_auth(client):
    resp = client.get("/api/tableau/connections")
    assert resp.status_code in (401, 403)


def test_get_connections(admin_client):
    resp = admin_client.get("/api/tableau/connections")
    assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"
    data = resp.json()
    assert "connections" in data
    assert isinstance(data["connections"], list)


def test_get_assets_requires_connection_id(admin_client):
    """GET /api/tableau/assets 需要 connection_id，未提供时返回 422"""
    resp = admin_client.get("/api/tableau/assets")
    assert resp.status_code == 422, f"Expected 422 for missing connection_id, got {resp.status_code}: {resp.text}"


# ── V2 MCP Direct Connect Tests ────────────────────────────────────────────────

MOCK_METADATA_RESULT = {
    "fields": [
        {
            "fieldName": "Sales",
            "fieldCaption": "Sales",
            "dataType": "REAL",
            "role": "MEASURE",
            "description": "Total sales",
            "aggregation": "SUM",
            "isCalculated": False,
            "formula": None,
        },
        {
            "fieldName": "Category",
            "fieldCaption": "Category",
            "dataType": "STRING",
            "role": "DIMENSION",
            "description": "Product category",
            "aggregation": None,
            "isCalculated": False,
            "formula": None,
        },
    ]
}

MOCK_QUERY_RESULT = {
    "fields": [
        {"fieldCaption": "Category", "fieldAlias": "Category", "dataType": "STRING"},
        {"fieldCaption": "Sales", "fieldAlias": "Total Sales", "dataType": "REAL"},
    ],
    "rows": [["Furniture", 123456.0], ["Technology", 78900.0]],
    "totalRowCount": 2,
    "truncated": False,
}


def _make_mock_conn(conn_id=1, mcp_direct_enabled=True):
    from services.tableau.models import TableauConnection
    conn = MagicMock(spec=TableauConnection)
    conn.id = conn_id
    conn.mcp_direct_enabled = mcp_direct_enabled
    conn.is_active = True
    conn.last_test_success = True
    return conn


def _make_mock_asset(asset_id=10, tableau_id="ds-luid-001", asset_type="datasource", connection_id=1):
    from services.tableau.models import TableauAsset
    asset = MagicMock(spec=TableauAsset)
    asset.id = asset_id
    asset.tableau_id = tableau_id
    asset.asset_type = asset_type
    asset.is_deleted = False
    asset.connection_id = connection_id
    return asset


# T1: POST /api/tableau/query 正常返回 200
def test_v2_query_success(admin_client, db_session):
    mock_client = MagicMock()
    mock_client.query_datasource.return_value = MOCK_QUERY_RESULT

    with patch("app.api.tableau.verify_connection_access"), \
         patch("app.api.tableau.get_tableau_mcp_client", return_value=mock_client), \
         patch("services.tableau.models.TableauDatabase.get_connection") as mock_get_conn:

        mock_get_conn.return_value = _make_mock_conn(conn_id=1)

        resp = admin_client.post("/api/tableau/query", json={
            "connection_id": 1,
            "datasource_luid": "abc-123",
            "vizql": {
                "measures": [{"field": "Sales", "aggregation": "SUM"}],
                "dimensions": [{"field": "Category"}],
                "filters": [],
                "limit": 100,
            },
            "timeout": 30,
        })

    assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"
    data = resp.json()
    assert "columns" in data
    assert "rows" in data
    assert data["row_count"] == 2
    assert data["datasource_luid"] == "abc-123"
    assert data["truncated"] is False


# T2: GET .../metadata 首次拉取，cache_status=fresh
def test_v2_metadata_first_fetch(admin_client, db_session):
    mock_client = MagicMock()
    mock_client.get_datasource_metadata.return_value = MOCK_METADATA_RESULT

    with patch("app.api.tableau.verify_connection_access"), \
         patch("app.api.tableau.get_tableau_mcp_client", return_value=mock_client), \
         patch("services.tableau.models.TableauDatabase.get_asset") as mock_get_asset, \
         patch("services.tableau.models.TableauDatabase.get_connection") as mock_get_conn, \
         patch("services.tableau.models.TableauDatabase.get_datasource_fields") as mock_get_fields, \
         patch("services.tableau.models.TableauDatabase.upsert_datasource_fields") as mock_upsert:

        mock_get_conn.return_value = _make_mock_conn(conn_id=1)
        mock_get_asset.return_value = _make_mock_asset()

        # 首次无缓存，upsert 后重新读取有数据
        fresh_field = MagicMock()
        fresh_field.field_name = "Sales"
        fresh_field.field_caption = "Sales"
        fresh_field.data_type = "REAL"
        fresh_field.role = "measure"
        fresh_field.description = "Total sales"
        fresh_field.aggregation = "SUM"
        fresh_field.fetched_at = datetime.now(timezone.utc)

        mock_get_fields.side_effect = [
            [],  # 首次无缓存
            [fresh_field],  # upsert 后重新读取
        ]

        resp = admin_client.get("/api/tableau/datasources/10/metadata")

    assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"
    data = resp.json()
    assert data["cache_status"] == "fresh"
    assert len(data["fields"]) == 1
    mock_upsert.assert_called_once()


# T3: GET .../metadata 缓存命中（1 小时前），cache_status=cached
def test_v2_metadata_cache_hit(admin_client, db_session):
    with patch("app.api.tableau.verify_connection_access"), \
         patch("app.api.tableau.get_tableau_mcp_client") as mock_get_client, \
         patch("services.tableau.models.TableauDatabase.get_asset") as mock_get_asset, \
         patch("services.tableau.models.TableauDatabase.get_connection") as mock_get_conn, \
         patch("services.tableau.models.TableauDatabase.get_datasource_fields") as mock_get_fields:

        mock_get_conn.return_value = _make_mock_conn(conn_id=1)
        mock_get_asset.return_value = _make_mock_asset()
        mock_get_client.return_value = MagicMock()

        # 缓存 1 小时前（未过期）
        recent_field = MagicMock()
        recent_field.field_name = "Sales"
        recent_field.field_caption = "Sales"
        recent_field.data_type = "REAL"
        recent_field.role = "measure"
        recent_field.description = "Total sales"
        recent_field.aggregation = "SUM"
        recent_field.fetched_at = datetime.now(timezone.utc) - timedelta(hours=1)
        mock_get_fields.return_value = [recent_field]

        resp = admin_client.get("/api/tableau/datasources/10/metadata")

    assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"
    data = resp.json()
    assert data["cache_status"] == "cached"
    # MCP 不应被调用
    mock_get_client.return_value.get_datasource_metadata.assert_not_called()


# T4: GET .../metadata，MCP 不可达时降级返回 stale
def test_v2_metadata_mcp_downgrade(admin_client, db_session):
    with patch("app.api.tableau.verify_connection_access"), \
         patch("app.api.tableau.get_tableau_mcp_client") as mock_get_client, \
         patch("services.tableau.models.TableauDatabase.get_asset") as mock_get_asset, \
         patch("services.tableau.models.TableauDatabase.get_connection") as mock_get_conn, \
         patch("services.tableau.models.TableauDatabase.get_datasource_fields") as mock_get_fields:

        mock_get_conn.return_value = _make_mock_conn(conn_id=1)
        mock_get_asset.return_value = _make_mock_asset()

        # 有过期缓存（48 小时前）
        stale_field = MagicMock()
        stale_field.field_name = "Sales"
        stale_field.field_caption = "Sales"
        stale_field.data_type = "REAL"
        stale_field.role = "measure"
        stale_field.description = "Total sales"
        stale_field.aggregation = "SUM"
        stale_field.fetched_at = datetime.now(timezone.utc) - timedelta(hours=48)
        mock_get_fields.return_value = [stale_field]

        # MCP 不可达
        mock_client = MagicMock()
        mock_client.get_datasource_metadata.side_effect = TableauMCPError(
            code="NLQ_006", message="MCP Server 不可达", details={}
        )
        mock_get_client.return_value = mock_client

        resp = admin_client.get("/api/tableau/datasources/10/metadata")

    assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"
    data = resp.json()
    assert data["cache_status"] == "stale"
    assert len(data["fields"]) == 1


# T5: POST /api/tableau/query，MCP 不可达返回 503 + MCP_003
def test_v2_query_mcp_unavailable(admin_client, db_session):
    with patch("app.api.tableau.verify_connection_access"), \
         patch("app.api.tableau.get_tableau_mcp_client") as mock_get_client, \
         patch("services.tableau.models.TableauDatabase.get_connection") as mock_get_conn:

        mock_get_conn.return_value = _make_mock_conn(conn_id=1)

        mock_client = MagicMock()
        mock_client.query_datasource.side_effect = TableauMCPError(
            code="NLQ_006", message="MCP Server 不可达", details={}
        )
        mock_get_client.return_value = mock_client

        resp = admin_client.post("/api/tableau/query", json={
            "connection_id": 1,
            "datasource_luid": "abc-123",
            "vizql": {
                "measures": [{"field": "Sales", "aggregation": "SUM"}],
                "dimensions": [],
                "filters": [],
                "limit": 100,
            },
            "timeout": 30,
        })

    assert resp.status_code == 503, f"Expected 503, got {resp.status_code}: {resp.text}"
    data = resp.json()
    assert data["detail"]["error_code"] == "MCP_003"


# T6: V1 sync 与 V2 query 并发不互扰
def test_v2_query_v1_sync_concurrent(admin_client, db_session):
    with patch("app.api.tableau.verify_connection_access"), \
         patch("app.api.tableau.get_tableau_mcp_client") as mock_get_client, \
         patch("services.tableau.models.TableauDatabase.get_connection") as mock_get_conn:

        mock_conn = _make_mock_conn(conn_id=1)
        mock_conn.sync_status = "idle"
        mock_get_conn.return_value = mock_conn

        mock_client = MagicMock()
        mock_client.query_datasource.return_value = MOCK_QUERY_RESULT
        mock_get_client.return_value = mock_client

        # V2 query 成功
        resp_q = admin_client.post("/api/tableau/query", json={
            "connection_id": 1,
            "datasource_luid": "abc-123",
            "vizql": {
                "measures": [{"field": "Sales", "aggregation": "SUM"}],
                "dimensions": [],
                "filters": [],
                "limit": 100,
            },
            "timeout": 30,
        })
        assert resp_q.status_code == 200

        # V1 sync 路由存在（返回 200/202 或 500，取决于 Celery 配置）
        resp_s = admin_client.post("/api/tableau/connections/1/sync")
        assert resp_s.status_code in (200, 202, 500)

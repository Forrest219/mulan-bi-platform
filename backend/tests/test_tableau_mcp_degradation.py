"""
测试：Spec 13 §3.4 Tableau MCP Offline Degradation

T3.5: mock mcp_offline → 验证 degraded + 缓存可读 + 写入 503
"""
import pytest
from unittest.mock import patch, MagicMock
from datetime import datetime, timezone, timedelta

from services.tableau.connection_health import (
    MCPHealthStatus,
    get_mcp_health,
    set_mcp_health,
    reset_mcp_health,
    is_mcp_healthy,
    is_mcp_degraded,
    get_data_freshness,
    build_connection_status_response,
)
from services.mcp.site_health_monitor import SiteHealthMonitor


# ── Connection Health Tests ────────────────────────────────────────────────────

def test_get_mcp_health_default():
    """默认状态为 healthy"""
    # Use a fresh URL to avoid global state pollution
    url = f"http://test-default-{id(test_get_mcp_health_default)}.local:8080"
    reset_mcp_health(url)
    assert get_mcp_health(url) == MCPHealthStatus.HEALTHY
    assert is_mcp_healthy(url) is True
    assert is_mcp_degraded(url) is False


def test_set_mcp_health_degraded():
    """设置 degraded 状态"""
    url = f"http://test-degraded-{id(test_set_mcp_health_degraded)}.local:8080"
    reset_mcp_health(url)
    set_mcp_health(url, MCPHealthStatus.DEGRADED, consecutive_failures=2)
    assert get_mcp_health(url) == MCPHealthStatus.DEGRADED
    assert is_mcp_healthy(url) is False
    assert is_mcp_degraded(url) is True


def test_set_mcp_health_unhealthy():
    """设置 unhealthy 状态"""
    url = f"http://test-unhealthy-{id(test_set_mcp_health_unhealthy)}.local:8080"
    reset_mcp_health(url)
    set_mcp_health(url, MCPHealthStatus.UNHEALTHY, consecutive_failures=3)
    assert get_mcp_health(url) == MCPHealthStatus.UNHEALTHY
    assert is_mcp_degraded(url) is True


def test_reset_mcp_health_recovery():
    """恢复后重置为 healthy"""
    url = f"http://test-recovery-{id(test_reset_mcp_health_recovery)}.local:8080"
    set_mcp_health(url, MCPHealthStatus.DEGRADED, consecutive_failures=2)
    reset_mcp_health(url)
    assert get_mcp_health(url) == MCPHealthStatus.HEALTHY


def test_get_data_freshness_never_synced():
    """从未同步返回 unknown"""
    result = get_data_freshness(None)
    assert result["status"] == "unknown"
    assert result["hours_since_sync"] is None


def test_get_data_freshness_fresh():
    """2 小时内同步返回 fresh"""
    recent = datetime.now(timezone.utc) - timedelta(hours=2)
    result = get_data_freshness(recent, sync_interval_hours=24)
    assert result["status"] == "fresh"
    assert result["hours_since_sync"] == 2.0


def test_get_data_freshness_stale():
    """超过 36 小时返回 stale"""
    old = datetime.now(timezone.utc) - timedelta(hours=40)
    result = get_data_freshness(old, sync_interval_hours=24)
    assert result["status"] == "stale"
    assert result["hours_since_sync"] == 40.0


# ── SiteHealthMonitor MCP Health Check Tests ────────────────────────────────

def test_check_mcp_health_healthy(monkeypatch):
    """MCP 在线时返回 healthy"""
    monitor = SiteHealthMonitor()
    called = []
    
    def fake_send_heartbeat(self, url):
        called.append(url)
        return True
    
    monkeypatch.setattr(SiteHealthMonitor, "_send_heartbeat", fake_send_heartbeat)
    
    result = monitor.check_mcp_health("http://healthy.local:8080")
    assert result["is_healthy"] is True
    assert result["status"] == "healthy"
    assert result["consecutive_failures"] == 0


def test_check_mcp_health_degraded(monkeypatch):
    """MCP 离线时返回 degraded"""
    monitor = SiteHealthMonitor()
    
    def fake_send_heartbeat(self, url):
        return False
    
    monkeypatch.setattr(SiteHealthMonitor, "_send_heartbeat", fake_send_heartbeat)
    
    result = monitor.check_mcp_health("http://offline.local:8080")
    assert result["is_healthy"] is False
    assert result["status"] == "degraded"


def test_check_mcp_health_with_failures_accumulation(monkeypatch):
    """连续失败计数累积"""
    monitor = SiteHealthMonitor(max_consecutive_failures=3)
    
    def fake_send_heartbeat(self, url):
        return False
    
    monkeypatch.setattr(SiteHealthMonitor, "_send_heartbeat", fake_send_heartbeat)
    
    # 第 1 次失败 → degraded
    r1 = monitor.check_mcp_health_with_failures("http://offline.local:8080", current_failures=0)
    assert r1["status"] == "degraded"
    assert r1["consecutive_failures"] == 1
    
    # 第 2 次失败 → degraded
    r2 = monitor.check_mcp_health_with_failures("http://offline.local:8080", current_failures=1)
    assert r2["status"] == "degraded"
    assert r2["consecutive_failures"] == 2
    
    # 第 3 次失败 → unhealthy
    r3 = monitor.check_mcp_health_with_failures("http://offline.local:8080", current_failures=2)
    assert r3["status"] == "unhealthy"
    assert r3["consecutive_failures"] == 3
    
    # 恢复成功 → healthy
    def fake_send_healthy(self, url):
        return True
    
    monkeypatch.setattr(SiteHealthMonitor, "_send_heartbeat", fake_send_healthy)
    r4 = monitor.check_mcp_health_with_failures("http://offline.local:8080", current_failures=3)
    assert r4["status"] == "healthy"
    assert r4["consecutive_failures"] == 0


# ── Integration Tests: API Endpoints ────────────────────────────────────────

def _make_mock_conn(conn_id=1, name="Test Connection"):
    from services.tableau.models import TableauConnection
    conn = MagicMock(spec=TableauConnection)
    conn.id = conn_id
    conn.name = name
    conn.server_url = "http://tableau.local"
    conn.site = "test-site"
    conn.mcp_server_url = "http://mcp.local:8080"
    conn.mcp_direct_enabled = True
    conn.is_active = True
    conn.last_test_success = True
    conn.last_test_at = datetime.now(timezone.utc) - timedelta(hours=1)
    conn.last_sync_at = datetime.now(timezone.utc) - timedelta(hours=12)
    conn.sync_status = "idle"
    conn.sync_interval_hours = 24
    conn.auto_sync_enabled = True
    return conn


def test_connection_status_endpoint_healthy(admin_client, db_session):
    """GET /api/tableau/connections/{id}/status - healthy 状态"""
    with patch("app.api.tableau.verify_connection_access"), \
         patch("services.tableau.models.TableauDatabase.get_connection") as mock_get_conn, \
         patch("services.tableau.connection_health.get_mcp_health") as mock_health:
        
        mock_health.return_value = MCPHealthStatus.HEALTHY
        mock_get_conn.return_value = _make_mock_conn(conn_id=5, name="Test Conn")
        
        resp = admin_client.get("/api/tableau/connections/5/status")
        
    assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"
    data = resp.json()
    assert data["mcp_health"] == "healthy"
    assert data["connection_id"] == 5
    assert data["data_freshness"]["status"] == "fresh"


def test_connection_status_endpoint_degraded(admin_client, db_session):
    """GET /api/tableau/connections/{id}/status - degraded 状态"""
    with patch("app.api.tableau.verify_connection_access"), \
         patch("services.tableau.models.TableauDatabase.get_connection") as mock_get_conn, \
         patch("services.tableau.connection_health.get_mcp_health") as mock_health:
        
        mock_health.return_value = MCPHealthStatus.DEGRADED
        mock_get_conn.return_value = _make_mock_conn(conn_id=7, name="Degraded Conn")
        
        resp = admin_client.get("/api/tableau/connections/7/status")
        
    assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"
    data = resp.json()
    assert data["mcp_health"] == "degraded"
    assert data["data_freshness"]["status"] == "fresh"


def test_sync_endpoint_mcp_degraded_returns_503(admin_client, db_session):
    """POST /api/tableau/connections/{id}/sync - MCP degraded 返回 503"""
    with patch("app.api.tableau.verify_connection_access"), \
         patch("services.tableau.models.TableauDatabase.get_connection") as mock_get_conn, \
         patch("services.tableau.connection_health.is_mcp_degraded") as mock_degraded:
        
        mock_degraded.return_value = True  # degraded 状态
        mock_get_conn.return_value = _make_mock_conn(conn_id=3)
        
        resp = admin_client.post("/api/tableau/connections/3/sync")
        
    assert resp.status_code == 503, f"Expected 503, got {resp.status_code}: {resp.text}"
    data = resp.json()
    assert data["detail"]["error_code"] == "MCP_003"
    assert "degraded" in data["detail"]["message"]


def test_sync_endpoint_mcp_healthy_succeeds(admin_client, db_session):
    """POST /api/tableau/connections/{id}/sync - MCP healthy 正常提交"""
    with patch("app.api.tableau.verify_connection_access"), \
         patch("services.tableau.models.TableauDatabase.get_connection") as mock_get_conn, \
         patch("services.tableau.connection_health.is_mcp_degraded") as mock_degraded, \
         patch("services.tasks.tableau_tasks.sync_connection_task") as mock_task:
        
        mock_degraded.return_value = False  # healthy
        mock_get_conn.return_value = _make_mock_conn(conn_id=4)
        mock_task.delay.return_value = MagicMock(id="task-123")
        
        resp = admin_client.post("/api/tableau/connections/4/sync")
        
    assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"
    data = resp.json()
    assert data["status"] == "pending"
    assert data["task_id"] == "task-123"


def test_v2_query_read_cached_when_degraded(admin_client, db_session):
    """
    Spec 13 §3.4 T5: MCP degraded 时，已缓存数据的读操作仍可用。
    POST /api/tableau/query 在 degraded 时因为调用 MCP 而返回 503，
    但 GET /api/tableau/assets 返回缓存数据（不受 MCP 状态影响）。
    """
    with patch("app.api.tableau.verify_connection_access"), \
         patch("services.tableau.models.TableauDatabase.get_connection") as mock_get_conn, \
         patch("services.tableau.models.TableauDatabase.get_assets") as mock_get_assets, \
         patch("services.tableau.connection_health.is_mcp_degraded") as mock_degraded:
        
        mock_degraded.return_value = True  # MCP degraded
        mock_get_conn.return_value = _make_mock_conn(conn_id=2)
        
        # 模拟有缓存资产
        mock_asset = MagicMock()
        mock_asset.to_dict.return_value = {
            "id": 100,
            "name": "Cached Workbook",
            "asset_type": "workbook",
            "connection_id": 2,
            "is_deleted": False,
        }
        mock_get_assets.return_value = ([mock_asset], 1)
        
        resp = admin_client.get("/api/tableau/assets?connection_id=2")
        
    assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"
    data = resp.json()
    assert data["total"] == 1
    assert data["assets"][0]["name"] == "Cached Workbook"


# ── V2 Query Write Returns 503 When Degraded ───────────────────────────────

def test_v2_query_mcp_degraded_returns_503(admin_client, db_session):
    """
    Spec 13 §3.4 T2: V2 MCP 直连查询在 degraded 状态下应返回 503。
    注意：V2 query 直接调用 MCP，不是写操作，但同样受到 MCP 不可用影响。
    """
    with patch("app.api.tableau.verify_connection_access"), \
         patch("app.api.tableau.get_tableau_mcp_client") as mock_get_client, \
         patch("services.tableau.models.TableauDatabase.get_connection") as mock_get_conn, \
         patch("services.tableau.connection_health.is_mcp_degraded") as mock_degraded:
        
        mock_degraded.return_value = True  # MCP degraded
        mock_get_conn.return_value = _make_mock_conn(conn_id=1)
        
        from services.tableau.mcp_client import TableauMCPError
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

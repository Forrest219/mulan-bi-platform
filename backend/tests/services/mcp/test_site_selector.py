"""
Unit Tests: services/mcp/site_selector.py

Spec 22 P0: Multi-Site MCP Scheduling — Site Selection Logic

TDD Approach:
1. Write failing tests for site selector
2. Write minimal implementation
3. Verify tests pass
"""
import pytest
from unittest import mock


class TestSiteSelector:
    """Test SiteSelector selection strategies"""

    def test_select_by_datasource_luid(self):
        """Strategy 1: datasource_luid provided → route to owning site"""
        from services.mcp.site_selector import SiteSelector
        
        selector = SiteSelector()
        
        # Mock the database queries
        with mock.patch('services.mcp.site_selector.SessionLocal') as mock_session:
            mock_db = mock.MagicMock()
            mock_session.return_value = mock_db
            
            # Mock asset
            mock_asset = mock.MagicMock()
            mock_asset.tableau_id = "test-luid"
            mock_asset.connection_id = 1
            mock_asset.is_deleted = False
            
            # Mock connection
            mock_conn = mock.MagicMock()
            mock_conn.id = 1
            mock_conn.name = "Test Site"
            mock_conn.server_url = "https://tableau.example.com"
            mock_conn.site = "test-site"
            mock_conn.mcp_server_url = "https://mcp.example.com"
            mock_conn.is_active = True
            mock_conn.last_test_success = True
            
            # Setup query chain
            mock_db.query.return_value.filter.return_value.first.side_effect = [
                mock_asset,  # TableauAsset query
                mock_conn,    # TableauConnection query
            ]
            
            result = selector.select_site(
                datasource_luid="test-luid",
                query_type="ad-hoc",
                user_role="analyst",
            )
            
            assert result is not None
            assert result.site_id == "https://tableau.example.com|test-site"
            assert result.site_name == "test-site"
            assert result.connection_id == 1

    def test_select_default_metrics_site(self):
        """Strategy 2: query_type == 'metric' → default metrics site"""
        from services.mcp.site_selector import SiteSelector
        
        selector = SiteSelector()
        
        with mock.patch('services.mcp.site_selector.SessionLocal') as mock_session:
            mock_db = mock.MagicMock()
            mock_session.return_value = mock_db
            
            # Mock McpServer with is_default=True
            mock_mcp = mock.MagicMock()
            mock_mcp.id = 1
            mock_mcp.name = "Metrics MCP"
            mock_mcp.site_name = "Metrics Site"
            mock_mcp.server_url = "https://mcp.example.com"
            mock_mcp.is_active = True
            mock_mcp.is_default = True
            mock_mcp.priority = 10
            mock_mcp.health_status = "healthy"
            mock_mcp.consecutive_failures = 0
            
            mock_db.query.return_value.filter.return_value.first.return_value = mock_mcp
            
            result = selector.select_site(
                datasource_luid=None,
                query_type="metric",
                user_role="analyst",
            )
            
            assert result is not None
            assert result.is_default is True
            assert result.priority == 10

    def test_select_by_round_robin(self):
        """Strategy 3: round-robin across healthy sites"""
        from services.mcp.site_selector import SiteSelector
        
        selector = SiteSelector()
        
        with mock.patch('services.mcp.site_selector.SessionLocal') as mock_session:
            mock_db = mock.MagicMock()
            mock_session.return_value = mock_db
            
            # Mock connections
            mock_conn1 = mock.MagicMock()
            mock_conn1.id = 1
            mock_conn1.name = "Site 1"
            mock_conn1.server_url = "https://tableau1.example.com"
            mock_conn1.site = "site1"
            mock_conn1.mcp_server_url = "https://mcp1.example.com"
            mock_conn1.is_active = True
            mock_conn1.last_test_success = True
            
            mock_conn2 = mock.MagicMock()
            mock_conn2.id = 2
            mock_conn2.name = "Site 2"
            mock_conn2.server_url = "https://tableau2.example.com"
            mock_conn2.site = "site2"
            mock_conn2.mcp_server_url = "https://mcp2.example.com"
            mock_conn2.is_active = True
            mock_conn2.last_test_success = True
            
            mock_db.query.return_value.filter.return_value.all.return_value = [mock_conn1, mock_conn2]
            
            # First call - should get first site
            result1 = selector.select_site(
                datasource_luid=None,
                query_type="ad-hoc",
                user_role="analyst",
            )
            
            # Second call - should get second site (round-robin)
            result2 = selector.select_site(
                datasource_luid=None,
                query_type="ad-hoc",
                user_role="analyst",
            )
            
            assert result1 is not None
            assert result2 is not None
            # Results should be different due to round-robin
            assert result1.connection_id != result2.connection_id

    def test_select_skips_unhealthy_sites(self):
        """Round-robin should skip unhealthy sites"""
        from services.mcp.site_selector import SiteSelector
        
        selector = SiteSelector()
        
        with mock.patch('services.mcp.site_selector.SessionLocal') as mock_session:
            mock_db = mock.MagicMock()
            mock_session.return_value = mock_db
            
            # Only one healthy connection
            mock_conn = mock.MagicMock()
            mock_conn.id = 1
            mock_conn.name = "Healthy Site"
            mock_conn.server_url = "https://tableau.example.com"
            mock_conn.site = "healthy"
            mock_conn.mcp_server_url = "https://mcp.example.com"
            mock_conn.is_active = True
            mock_conn.last_test_success = True  # Healthy
            
            # But MCP server is unhealthy
            mock_mcp = mock.MagicMock()
            mock_mcp.id = 1
            mock_mcp.name = "Unhealthy MCP"
            mock_mcp.site_name = "Unhealthy"
            mock_mcp.server_url = "https://mcp-unhealthy.example.com"
            mock_mcp.is_active = True
            mock_mcp.health_status = "unhealthy"  # Unhealthy
            mock_mcp.consecutive_failures = 3
            mock_mcp.is_default = False
            mock_mcp.priority = 5
            
            # Setup query chains
            def mock_query_chain(*args):
                result = mock.MagicMock()
                if 'McpServer' in str(args):
                    result.filter.return_value.all.return_value = [mock_mcp]
                else:
                    result.filter.return_value.all.return_value = [mock_conn]
                result.filter.return_value.first = None
                return result
            
            mock_db.query.side_effect = mock_query_chain
            
            result = selector.select_site(
                datasource_luid=None,
                query_type="ad-hoc",
                user_role="analyst",
            )
            
            assert result is not None
            assert result.health_status == "healthy"


class TestSiteInfo:
    """Test SiteInfo dataclass"""

    def test_is_healthy_property(self):
        """Test the is_healthy property"""
        from services.mcp.models import SiteInfo
        
        healthy_site = SiteInfo(
            site_id="test-1",
            site_name="Test",
            site_url="https://example.com",
            health_status="healthy",
        )
        assert healthy_site.is_healthy is True
        
        unhealthy_site = SiteInfo(
            site_id="test-2",
            site_name="Test",
            site_url="https://example.com",
            health_status="unhealthy",
        )
        assert unhealthy_site.is_healthy is False
        
        unknown_site = SiteInfo(
            site_id="test-3",
            site_name="Test",
            site_url="https://example.com",
            health_status="unknown",
        )
        assert unknown_site.is_healthy is False

    def test_to_dict(self):
        """Test SiteInfo.to_dict()"""
        from services.mcp.models import SiteInfo
        
        site = SiteInfo(
            site_id="test-1",
            site_name="Test Site",
            site_url="https://example.com",
            is_default=True,
            priority=5,
            health_status="healthy",
            consecutive_failures=0,
            connection_id=1,
            tableau_site_name="test",
        )
        
        d = site.to_dict()
        assert d["site_id"] == "test-1"
        assert d["site_name"] == "Test Site"
        assert d["is_default"] is True
        assert d["priority"] == 5
        assert d["health_status"] == "healthy"

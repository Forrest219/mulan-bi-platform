"""
Unit Tests: services/mcp/concurrent_dispatcher.py

Spec 22 P0: Multi-Site MCP Scheduling — Concurrent Dispatch

TDD Approach:
1. Write failing tests for concurrent dispatcher
2. Write minimal implementation  
3. Verify tests pass
"""
import asyncio
import pytest
from unittest import mock


class TestConcurrentMCPDispatcher:
    """Test ConcurrentMCPDispatcher concurrent query execution"""

    @pytest.mark.asyncio
    async def test_query_multiple_sites_all_succeed(self):
        """All sites return successfully"""
        from services.mcp.concurrent_dispatcher import ConcurrentMCPDispatcher
        from services.mcp.models import SiteInfo
        
        dispatcher = ConcurrentMCPDispatcher(default_timeout=10.0)
        
        sites = [
            SiteInfo(site_id="site-1", site_name="Site 1", site_url="https://mcp1.example.com"),
            SiteInfo(site_id="site-2", site_name="Site 2", site_url="https://mcp2.example.com"),
        ]
        
        # Mock the _execute_mcp_query method
        async def mock_query(site, query, timeout):
            await asyncio.sleep(0.1)  # Simulate network delay
            return {"data": f"result from {site.site_id}"}
        
        dispatcher._execute_mcp_query = mock_query
        
        results = await dispatcher.query_multiple_sites(sites, "test query")
        
        assert len(results) == 2
        assert all(r.success for r in results)
        # Results should be sorted by elapsed time
        assert results[0].elapsed_ms <= results[1].elapsed_ms

    @pytest.mark.asyncio
    async def test_query_multiple_sites_partial_failure(self):
        """Some sites fail, others succeed"""
        from services.mcp.concurrent_dispatcher import ConcurrentMCPDispatcher
        from services.mcp.models import SiteInfo
        
        dispatcher = ConcurrentMCPDispatcher(default_timeout=10.0)
        
        sites = [
            SiteInfo(site_id="site-1", site_name="Site 1", site_url="https://mcp1.example.com"),
            SiteInfo(site_id="site-2", site_name="Site 2", site_url="https://mcp2.example.com"),
        ]
        
        async def mock_query(site, query, timeout):
            if site.site_id == "site-1":
                return {"data": "success"}
            else:
                raise RuntimeError("Connection failed")
        
        dispatcher._execute_mcp_query = mock_query
        
        results = await dispatcher.query_multiple_sites(sites, "test query")
        
        assert len(results) == 2
        # One success, one failure
        assert sum(1 for r in results if r.success) == 1
        assert sum(1 for r in results if not r.success) == 1

    @pytest.mark.asyncio
    async def test_query_multiple_sites_empty_list(self):
        """Empty site list returns empty results"""
        from services.mcp.concurrent_dispatcher import ConcurrentMCPDispatcher
        
        dispatcher = ConcurrentMCPDispatcher(default_timeout=10.0)
        
        results = await dispatcher.query_multiple_sites([], "test query")
        
        assert results == []

    @pytest.mark.asyncio
    async def test_query_multiple_sites_sorted_by_time(self):
        """Results are sorted by elapsed time (fastest first)"""
        from services.mcp.concurrent_dispatcher import ConcurrentMCPDispatcher
        from services.mcp.models import SiteInfo
        
        dispatcher = ConcurrentMCPDispatcher(default_timeout=10.0)
        
        sites = [
            SiteInfo(site_id="slow", site_name="Slow Site", site_url="https://slow.example.com"),
            SiteInfo(site_id="fast", site_name="Fast Site", site_url="https://fast.example.com"),
        ]
        
        async def mock_query(site, query, timeout):
            if site.site_id == "slow":
                await asyncio.sleep(0.2)
            else:
                await asyncio.sleep(0.05)
            return {"data": f"result from {site.site_id}"}
        
        dispatcher._execute_mcp_query = mock_query
        
        results = await dispatcher.query_multiple_sites(sites, "test query")
        
        assert len(results) == 2
        # Fast site should be first
        assert results[0].site_id == "fast"
        assert results[1].site_id == "slow"


class TestDeduplication:
    """Test result deduplication"""

    def test_deduplicate_same_content(self):
        """Same content hash → keep first (fastest)"""
        from services.mcp.concurrent_dispatcher import ConcurrentMCPDispatcher, QueryResult
        
        dispatcher = ConcurrentMCPDispatcher()
        
        results = [
            QueryResult(site_id="site-1", site_name="Site 1", success=True, 
                       data={"rows": [[1, 2, 3]]}, content_hash="abc123", elapsed_ms=100),
            QueryResult(site_id="site-2", site_name="Site 2", success=True,
                       data={"rows": [[1, 2, 3]]}, content_hash="abc123", elapsed_ms=200),  # Same hash
        ]
        
        deduped = dispatcher.deduplicate_results(results)
        
        assert len(deduped) == 1
        assert deduped[0].site_id == "site-1"  # Keep first (fastest)

    def test_deduplicate_different_content(self):
        """Different content hash → keep both"""
        from services.mcp.concurrent_dispatcher import ConcurrentMCPDispatcher, QueryResult
        
        dispatcher = ConcurrentMCPDispatcher()
        
        results = [
            QueryResult(site_id="site-1", site_name="Site 1", success=True,
                       data={"rows": [[1, 2, 3]]}, content_hash="abc123", elapsed_ms=100),
            QueryResult(site_id="site-2", site_name="Site 2", success=True,
                       data={"rows": [[4, 5, 6]]}, content_hash="def456", elapsed_ms=200),
        ]
        
        deduped = dispatcher.deduplicate_results(results)
        
        assert len(deduped) == 2

    def test_deduplicate_preserves_failures(self):
        """Failed results are preserved for error reporting"""
        from services.mcp.concurrent_dispatcher import ConcurrentMCPDispatcher, QueryResult
        
        dispatcher = ConcurrentMCPDispatcher()
        
        results = [
            QueryResult(site_id="site-1", site_name="Site 1", success=True,
                       data={"rows": [[1, 2, 3]]}, content_hash="abc123", elapsed_ms=100),
            QueryResult(site_id="site-2", site_name="Site 2", success=False,
                       error="Connection refused", elapsed_ms=50),
        ]
        
        deduped = dispatcher.deduplicate_results(results)
        
        assert len(deduped) == 2
        assert not deduped[1].success


class TestQueryResult:
    """Test QueryResult dataclass"""

    def test_query_result_fields(self):
        """Test QueryResult has all required fields"""
        from services.mcp.concurrent_dispatcher import QueryResult
        
        result = QueryResult(
            site_id="test-1",
            site_name="Test Site",
            success=True,
            data={"key": "value"},
            elapsed_ms=150.5,
            content_hash="hash123",
        )
        
        assert result.site_id == "test-1"
        assert result.site_name == "Test Site"
        assert result.success is True
        assert result.data == {"key": "value"}
        assert result.error is None
        assert result.elapsed_ms == 150.5
        assert result.content_hash == "hash123"

    def test_query_result_failure(self):
        """Test QueryResult with error"""
        from services.mcp.concurrent_dispatcher import QueryResult
        
        result = QueryResult(
            site_id="test-1",
            site_name="Test Site",
            success=False,
            error="Network timeout",
            elapsed_ms=10000,
        )
        
        assert result.success is False
        assert result.error == "Network timeout"
        assert result.data is None

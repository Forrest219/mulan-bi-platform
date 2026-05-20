import pytest

from services.data_agent.tableau_mcp_cache import MemoryTableauMcpTtlCache, TableauMcpCacheFacade

pytestmark = pytest.mark.skip_db


class _Clock:
    def __init__(self):
        self.now = 100.0

    def __call__(self):
        return self.now

    def advance(self, seconds):
        self.now += seconds


def test_cache_reports_miss_then_hit_with_connection_scoped_key():
    clock = _Clock()
    cache = MemoryTableauMcpTtlCache(clock=clock)

    miss = cache.get(connection_id=7, key="tools:v1")
    assert miss.cache_hit is False
    assert miss.cache_key == "tableau_mcp:tools:7:v1"
    assert miss.telemetry["event"] == "cache_miss"

    cache.set(connection_id=7, key="tools:v1", value={"tools": ["query-datasource"]}, ttl_seconds=60)
    hit = cache.get(connection_id=7, key="tools:v1")

    assert hit.cache_hit is True
    assert hit.value == {"tools": ["query-datasource"]}
    assert hit.source == "mcp"
    assert hit.telemetry["event"] == "cache_hit"
    assert cache.telemetry_snapshot().hits == 1
    assert cache.telemetry_snapshot().misses == 1


def test_cache_does_not_leak_between_connections():
    cache = MemoryTableauMcpTtlCache()
    cache.set(connection_id=1, key="metadata:ds-1:schema", value={"fields": ["Sales"]}, ttl_seconds=60)

    assert cache.get(connection_id=2, key="metadata:ds-1:schema").cache_hit is False
    assert cache.get(connection_id=1, key="metadata:ds-1:schema").cache_hit is True


def test_cache_expires_entries_and_records_telemetry():
    clock = _Clock()
    cache = MemoryTableauMcpTtlCache(clock=clock)
    cache.set(connection_id=7, key="metadata:ds-1:schema", value={"fields": ["Sales"]}, ttl_seconds=10)

    clock.advance(11)
    expired = cache.get(connection_id=7, key="metadata:ds-1:schema")

    assert expired.cache_hit is False
    assert expired.source == "expired"
    snapshot = cache.telemetry_snapshot()
    assert snapshot.expired == 1
    assert snapshot.misses == 1


def test_cache_invalidates_connection_scope_only():
    cache = MemoryTableauMcpTtlCache()
    cache.set(connection_id=1, key="tools:v1", value={"tools": [1]}, ttl_seconds=60)
    cache.set(connection_id=2, key="tools:v1", value={"tools": [2]}, ttl_seconds=60)

    assert cache.invalidate_connection(1) == 1

    assert cache.get(connection_id=1, key="tools:v1").cache_hit is False
    assert cache.get(connection_id=2, key="tools:v1").cache_hit is True


def test_facade_exposes_tools_and_metadata_cache_with_source_and_freshness():
    clock = _Clock()
    facade = TableauMcpCacheFacade(MemoryTableauMcpTtlCache(clock=clock))

    facade.set_tools_catalog(connection_id=7, gateway_version="2026.05", value={"tools": []}, ttl_seconds=300)
    tools = facade.get_tools_catalog(connection_id=7, gateway_version="2026.05")
    assert tools.cache_hit is True
    assert tools.cache_key == "tableau_mcp:tools:7:2026.05"

    facade.set_datasource_metadata(
        connection_id=7,
        datasource_luid="ds-1",
        schema_version="sync-1",
        value={"fields": [{"caption": "Sales"}]},
        ttl_seconds=600,
        source="catalog_cache",
        metadata_freshness="2026-05-20T08:00:00Z",
    )
    metadata = facade.get_datasource_metadata(connection_id=7, datasource_luid="ds-1", schema_version="sync-1")

    assert metadata.cache_hit is True
    assert metadata.source == "catalog_cache"
    assert metadata.metadata_freshness == "2026-05-20T08:00:00Z"

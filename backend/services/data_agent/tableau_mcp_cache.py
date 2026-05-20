"""Connection-scoped TTL cache primitives for Tableau MCP runtime data."""
# ruff: noqa: D101,D102,D107

from __future__ import annotations

import time
from copy import deepcopy
from dataclasses import dataclass
from typing import Any, Callable, Mapping


@dataclass(frozen=True)
class CacheTelemetrySnapshot:
    hits: int = 0
    misses: int = 0
    sets: int = 0
    expired: int = 0
    deletes: int = 0
    invalidations: int = 0
    last_event: dict[str, Any] | None = None


@dataclass(frozen=True)
class CacheLookupResult:
    value: Any
    cache_hit: bool
    cache_key: str
    source: str
    metadata_freshness: Any = None
    expires_at: float | None = None
    telemetry: dict[str, Any] | None = None


@dataclass
class _CacheEntry:
    value: Any
    expires_at: float
    source: str
    metadata_freshness: Any = None


class MemoryTableauMcpTtlCache:
    """Small in-process TTL cache with connection-scoped keys and hit/miss telemetry."""

    def __init__(self, *, clock: Callable[[], float] | None = None) -> None:
        self._clock = clock or time.monotonic
        self._entries: dict[str, _CacheEntry] = {}
        self._hits = 0
        self._misses = 0
        self._sets = 0
        self._expired = 0
        self._deletes = 0
        self._invalidations = 0
        self._last_event: dict[str, Any] | None = None

    def get(self, *, connection_id: str | int, key: str) -> CacheLookupResult:
        cache_key = self.scoped_key(connection_id=connection_id, key=key)
        entry = self._entries.get(cache_key)
        now = self._clock()
        if entry is None:
            self._record_miss(cache_key, source="miss")
            return self._lookup_result(cache_key=cache_key, hit=False, source="miss")
        if entry.expires_at <= now:
            self._entries.pop(cache_key, None)
            self._expired += 1
            self._record_miss(cache_key, source="expired")
            return self._lookup_result(cache_key=cache_key, hit=False, source="expired")
        self._hits += 1
        self._last_event = {"event": "cache_hit", "cache_hit": True, "cache_key": cache_key, "source": entry.source}
        return self._lookup_result(
            cache_key=cache_key,
            hit=True,
            source=entry.source,
            value=_safe_copy(entry.value),
            metadata_freshness=entry.metadata_freshness,
            expires_at=entry.expires_at,
        )

    def set(
        self,
        *,
        connection_id: str | int,
        key: str,
        value: Any,
        ttl_seconds: float,
        source: str = "mcp",
        metadata_freshness: Any = None,
    ) -> str:
        cache_key = self.scoped_key(connection_id=connection_id, key=key)
        ttl = max(float(ttl_seconds), 0.0)
        self._entries[cache_key] = _CacheEntry(
            value=_safe_copy(value),
            expires_at=self._clock() + ttl,
            source=source,
            metadata_freshness=metadata_freshness,
        )
        self._sets += 1
        self._last_event = {
            "event": "cache_set",
            "cache_hit": False,
            "cache_key": cache_key,
            "source": source,
            "ttl_seconds": ttl,
        }
        return cache_key

    def delete(self, *, connection_id: str | int, key: str) -> bool:
        cache_key = self.scoped_key(connection_id=connection_id, key=key)
        existed = cache_key in self._entries
        if existed:
            self._entries.pop(cache_key, None)
            self._deletes += 1
        self._last_event = {"event": "cache_delete", "cache_hit": False, "cache_key": cache_key, "deleted": existed}
        return existed

    def invalidate_connection(self, connection_id: str | int) -> int:
        prefixes = self.connection_prefixes(connection_id)
        keys = [key for key in self._entries if any(key.startswith(prefix) for prefix in prefixes)]
        for key in keys:
            self._entries.pop(key, None)
        self._invalidations += 1
        self._last_event = {
            "event": "cache_invalidate_connection",
            "cache_hit": False,
            "connection_id": str(connection_id),
            "invalidated": len(keys),
        }
        return len(keys)

    def clear(self) -> None:
        self._entries.clear()
        self._last_event = {"event": "cache_clear", "cache_hit": False}

    def telemetry_snapshot(self) -> CacheTelemetrySnapshot:
        return CacheTelemetrySnapshot(
            hits=self._hits,
            misses=self._misses,
            sets=self._sets,
            expired=self._expired,
            deletes=self._deletes,
            invalidations=self._invalidations,
            last_event=dict(self._last_event) if self._last_event else None,
        )

    def telemetry_dict(self) -> dict[str, Any]:
        snapshot = self.telemetry_snapshot()
        return {
            "hits": snapshot.hits,
            "misses": snapshot.misses,
            "sets": snapshot.sets,
            "expired": snapshot.expired,
            "deletes": snapshot.deletes,
            "invalidations": snapshot.invalidations,
            "last_event": snapshot.last_event,
        }

    def tools_catalog_key(self, *, connection_id: str | int, gateway_version: str) -> str:
        return f"tableau_mcp:tools:{connection_id}:{gateway_version}"

    def datasource_metadata_key(
        self,
        *,
        connection_id: str | int,
        datasource_luid: str,
        schema_version: str,
    ) -> str:
        return f"tableau_mcp:metadata:{connection_id}:{datasource_luid}:{schema_version}"

    def scoped_key(self, *, connection_id: str | int, key: str) -> str:
        raw = str(key or "").strip(":")
        cid = str(connection_id)
        if raw.startswith((f"tableau_mcp:tools:{cid}:", f"tableau_mcp:metadata:{cid}:", f"tableau_mcp:scoped:{cid}:")):
            return raw
        if raw.startswith("tools:"):
            return f"tableau_mcp:tools:{cid}:{raw.removeprefix('tools:')}"
        if raw.startswith("metadata:"):
            return f"tableau_mcp:metadata:{cid}:{raw.removeprefix('metadata:')}"
        raw = raw.removeprefix("tableau_mcp:")
        return f"tableau_mcp:scoped:{cid}:{raw}"

    @staticmethod
    def connection_prefixes(connection_id: str | int) -> tuple[str, str, str]:
        return (
            f"tableau_mcp:tools:{connection_id}:",
            f"tableau_mcp:metadata:{connection_id}:",
            f"tableau_mcp:scoped:{connection_id}:",
        )

    def _record_miss(self, cache_key: str, *, source: str) -> None:
        self._misses += 1
        self._last_event = {"event": "cache_miss", "cache_hit": False, "cache_key": cache_key, "source": source}

    def _lookup_result(
        self,
        *,
        cache_key: str,
        hit: bool,
        source: str,
        value: Any = None,
        metadata_freshness: Any = None,
        expires_at: float | None = None,
    ) -> CacheLookupResult:
        telemetry = dict(self._last_event) if self._last_event else None
        return CacheLookupResult(
            value=value,
            cache_hit=hit,
            cache_key=cache_key,
            source=source,
            metadata_freshness=metadata_freshness,
            expires_at=expires_at,
            telemetry=telemetry,
        )


class TableauMcpCacheFacade:
    """Named cache operations for tools catalog and datasource metadata."""

    def __init__(self, cache: MemoryTableauMcpTtlCache | None = None) -> None:
        self.cache = cache or MemoryTableauMcpTtlCache()

    def get_tools_catalog(self, *, connection_id: str | int, gateway_version: str) -> CacheLookupResult:
        return self.cache.get(connection_id=connection_id, key=f"tools:{gateway_version}")

    def set_tools_catalog(
        self,
        *,
        connection_id: str | int,
        gateway_version: str,
        value: Any,
        ttl_seconds: float,
        source: str = "mcp",
    ) -> str:
        return self.cache.set(
            connection_id=connection_id,
            key=f"tools:{gateway_version}",
            value=value,
            ttl_seconds=ttl_seconds,
            source=source,
        )

    def get_datasource_metadata(
        self,
        *,
        connection_id: str | int,
        datasource_luid: str,
        schema_version: str,
    ) -> CacheLookupResult:
        return self.cache.get(connection_id=connection_id, key=f"metadata:{datasource_luid}:{schema_version}")

    def set_datasource_metadata(
        self,
        *,
        connection_id: str | int,
        datasource_luid: str,
        schema_version: str,
        value: Mapping[str, Any],
        ttl_seconds: float,
        source: str = "mcp",
        metadata_freshness: Any = None,
    ) -> str:
        return self.cache.set(
            connection_id=connection_id,
            key=f"metadata:{datasource_luid}:{schema_version}",
            value=dict(value),
            ttl_seconds=ttl_seconds,
            source=source,
            metadata_freshness=metadata_freshness,
        )


def _safe_copy(value: Any) -> Any:
    try:
        return deepcopy(value)
    except Exception:
        return value


__all__ = [
    "CacheLookupResult",
    "CacheTelemetrySnapshot",
    "MemoryTableauMcpTtlCache",
    "TableauMcpCacheFacade",
]

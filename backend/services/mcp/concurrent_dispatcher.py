"""
ConcurrentMCPDispatcher — 并发多站点 MCP 查询调度器

Spec 22 P0: 实现多站点 MCP 并发调度

Fire queries to multiple sites concurrently.
Return results as they arrive (fastest first).
Aggregate and deduplicate if needed.
"""
import asyncio
import hashlib
import logging
import time
from dataclasses import dataclass
from typing import Any, Optional

import httpx

from services.mcp.models import SiteInfo

logger = logging.getLogger(__name__)


@dataclass
class QueryResult:
    """Single site query result"""
    site_id: str
    site_name: str
    success: bool
    data: Optional[dict] = None
    error: Optional[str] = None
    elapsed_ms: float = 0.0
    content_hash: Optional[str] = None


def _compute_content_hash(data: dict) -> str:
    """Compute a content hash for deduplication."""
    import json
    content_str = json.dumps(data, sort_keys=True, default=str)
    return hashlib.sha256(content_str.encode()).hexdigest()[:16]


class ConcurrentMCPDispatcher:
    """
    并发 MCP 查询调度器
    
    Spec 22 P0 特性：
    - 同时向多个站点发送相同查询
    - 按返回速度排序（最快优先）
    - 结果去重（基于 content hash）
    - 独立的认证和超时控制
    - 单站点超时：10秒默认值
    """

    def __init__(
        self,
        default_timeout: float = 10.0,
        max_concurrent: int = 5,
    ):
        """
        Initialize dispatcher.
        
        Args:
            default_timeout: Default timeout per site (seconds)
            max_concurrent: Maximum concurrent queries across all sites
        """
        self.default_timeout = default_timeout
        self.semaphore = asyncio.Semaphore(max_concurrent)

    async def query_multiple_sites(
        self,
        sites: list[SiteInfo],
        query: str,
        timeout: Optional[float] = None,
    ) -> list[QueryResult]:
        """
        Fire queries to multiple sites concurrently.
        
        Args:
            sites: List of SiteInfo to query
            query: Query string to execute
            timeout: Per-site timeout (defaults to self.default_timeout)
            
        Returns:
            List of QueryResult sorted by elapsed time (fastest first)
        """
        if not sites:
            return []
        
        timeout = timeout or self.default_timeout
        
        # Create tasks for all sites
        tasks = [
            self._query_single_site(site, query, timeout)
            for site in sites
        ]
        
        # Execute concurrently with asyncio.gather
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        # Process results, handling exceptions
        query_results: list[QueryResult] = []
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                site = sites[i]
                logger.error("Site %s query exception: %s", site.site_id, result)
                query_results.append(QueryResult(
                    site_id=site.site_id,
                    site_name=site.site_name,
                    success=False,
                    error=str(result),
                ))
            else:
                query_results.append(result)
        
        # Sort by elapsed time (fastest first)
        query_results.sort(key=lambda r: r.elapsed_ms)
        
        return query_results

    async def _query_single_site(
        self,
        site: SiteInfo,
        query: str,
        timeout: float,
    ) -> QueryResult:
        """
        Execute a single query against one site.
        
        This method:
        1. Acquires a semaphore slot (rate limiting)
        2. Initializes MCP session if needed
        3. Sends the query
        4. Returns the result with timing
        """
        async with self.semaphore:
            start = time.monotonic()
            
            try:
                result_data = await self._execute_mcp_query(site, query, timeout)
                elapsed_ms = (time.monotonic() - start) * 1000
                
                content_hash = None
                if result_data:
                    content_hash = _compute_content_hash(result_data)
                
                return QueryResult(
                    site_id=site.site_id,
                    site_name=site.site_name,
                    success=True,
                    data=result_data,
                    elapsed_ms=elapsed_ms,
                    content_hash=content_hash,
                )
                
            except Exception as e:
                elapsed_ms = (time.monotonic() - start) * 1000
                logger.error("Site %s query failed after %.1fms: %s", 
                           site.site_id, elapsed_ms, e)
                return QueryResult(
                    site_id=site.site_id,
                    site_name=site.site_name,
                    success=False,
                    error=str(e),
                    elapsed_ms=elapsed_ms,
                )

    async def _execute_mcp_query(
        self,
        site: SiteInfo,
        query: str,
        timeout: float,
    ) -> dict:
        """
        Execute MCP query against a single site.
        
        Uses the MCP JSON-RPC protocol to query the MCP server.
        """
        protocol_ver = "2025-06-18"
        session_id = f"concurrent-{site.site_id[:8]}"
        
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
            "MCP-Protocol-Version": protocol_ver,
            "MCP-Session-ID": session_id,
        }
        
        async with httpx.AsyncClient(timeout=timeout) as client:
            # Initialize
            init_resp = await client.post(
                site.site_url,
                json={
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "initialize",
                    "params": {
                        "protocolVersion": protocol_ver,
                        "clientInfo": {"name": "mulan-concurrent", "version": "1.0"},
                        "serverInfo": {"name": "tableau-mcp", "version": "1.0"},
                    },
                },
                headers=headers,
            )
            init_data = self._parse_response(init_resp)
            if "error" in init_data:
                raise RuntimeError(f"MCP initialize error: {init_data['error']}")
            
            # Send initialized notification
            await client.post(
                site.site_url,
                json={"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}},
                headers=headers,
            )
            
            # Execute query - try query-datasource first, fallback to search
            query_payload = {
                "jsonrpc": "2.0",
                "id": 2,
                "method": "tools/call",
                "params": {
                    "name": "query-datasource",
                    "arguments": {
                        "query": query,
                    },
                },
            }
            
            resp = await client.post(
                site.site_url,
                json=query_payload,
                headers=headers,
            )
            
            data = self._parse_response(resp)
            if "error" in data:
                raise RuntimeError(f"MCP query error: {data['error']}")
            
            result = data.get("result", {})
            content = result.get("content", [])
            text = "".join(c.get("text", "") for c in content if c.get("type") == "text")
            
            if text:
                import json as json_lib
                return json_lib.loads(text)
            
            return {}

    def _parse_response(self, resp) -> dict:
        """Parse MCP JSON-RPC response, handling SSE format."""
        import json as json_lib
        
        # Handle SSE format: "event: message\ndata: {...}"
        for line in resp.text.splitlines():
            line = line.strip()
            if line.startswith("data:"):
                payload = line[5:].strip()
                if payload and payload != "[DONE]":
                    return json_lib.loads(payload)
        
        # Fallback to regular JSON
        return resp.json()

    def deduplicate_results(
        self,
        results: list[QueryResult],
    ) -> list[QueryResult]:
        """
        Deduplicate results by content hash.
        
        When multiple sites return the same data (content_hash matches),
        keep only the first (fastest) result.
        """
        seen_hashes: set[str] = set()
        deduplicated: list[QueryResult] = []
        
        for result in results:
            if result.success and result.content_hash:
                if result.content_hash not in seen_hashes:
                    seen_hashes.add(result.content_hash)
                    deduplicated.append(result)
                else:
                    logger.debug("Deduplicated result from site %s (hash %s)",
                               result.site_id, result.content_hash)
            else:
                # Keep failed results for error reporting
                deduplicated.append(result)
        
        return deduplicated

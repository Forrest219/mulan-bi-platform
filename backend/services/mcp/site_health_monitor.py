"""
SiteHealthMonitor — 多站点 MCP 健康监控

Spec 22 P0: 实现站点健康状态监控

- Heartbeat check for each site every 5 minutes
- Mark site as unhealthy if 3 consecutive failures
- Auto-recover when heartbeat succeeds
- Cache health status in Redis
"""
import asyncio
import logging
import threading
import time
from typing import Optional

import httpx

from services.mcp.models import McpServer, SiteInfo

logger = logging.getLogger(__name__)


# Redis key prefix for site health
_HEALTH_CACHE_PREFIX = "mcp:site:health:"
_HEALTH_TTL = 300  # 5 minutes


class SiteHealthMonitor:
    """
    MCP 站点健康监控器
    
    Spec 22 P0 特性：
    - 每 5 分钟对每个站点执行心跳检测
    - 连续 3 次失败标记为 unhealthy
    - 心跳成功后自动恢复为 healthy
    - 健康状态缓存到 Redis
    """

    def __init__(
        self,
        heartbeat_interval: int = 300,  # 5 minutes
        max_consecutive_failures: int = 3,
    ):
        """
        Initialize health monitor.
        
        Args:
            heartbeat_interval: Seconds between heartbeat checks (default 300 = 5 min)
            max_consecutive_failures: Failures before marking unhealthy (default 3)
        """
        self.heartbeat_interval = heartbeat_interval
        self.max_consecutive_failures = max_consecutive_failures
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._lock = threading.Lock()

    def start(self) -> None:
        """Start the health monitoring thread."""
        with self._lock:
            if self._running:
                logger.warning("SiteHealthMonitor already running")
                return
            
            self._running = True
            self._thread = threading.Thread(target=self._run_loop, daemon=True)
            self._thread.start()
            logger.info("SiteHealthMonitor started (interval=%ds)", self.heartbeat_interval)

    def stop(self) -> None:
        """Stop the health monitoring thread."""
        with self._lock:
            if not self._running:
                return
            
            self._running = False
            if self._thread:
                self._thread.join(timeout=5)
            logger.info("SiteHealthMonitor stopped")

    def _run_loop(self) -> None:
        """Main health check loop (runs in background thread)."""
        while self._running:
            try:
                self._check_all_sites()
            except Exception as e:
                logger.error("Health check loop error: %s", e)
            
            # Sleep in small increments to allow fast shutdown
            for _ in range(self.heartbeat_interval):
                if not self._running:
                    break
                time.sleep(1)

    def _check_all_sites(self) -> None:
        """Check health of all registered sites."""
        from services.tableau.models import TableauConnection
        from app.core.database import SessionLocal
        
        session = SessionLocal()
        try:
            # Check McpServers
            servers = session.query(McpServer).filter(
                McpServer.is_active == True,
            ).all()
            
            for server in servers:
                self._check_server_health(server)
            
            # Check TableauConnections
            connections = session.query(TableauConnection).filter(
                TableauConnection.is_active == True,
            ).all()
            
            for conn in connections:
                self._check_connection_health(conn)
                
        finally:
            session.close()

    def _check_server_health(self, server: McpServer) -> None:
        """Check health of a single McpServer."""
        site_key = f"mcp_{server.id}"
        
        try:
            is_healthy = self._send_heartbeat(server.server_url)
            
            if is_healthy:
                self._record_success(server, site_key)
            else:
                self._record_failure(server, site_key)
                
        except Exception as e:
            logger.error("Health check failed for server %s: %s", server.name, e)
            self._record_failure(server, site_key)

    def _check_connection_health(self, conn) -> None:
        """Check health of a TableauConnection MCP endpoint."""
        site_key = f"{conn.server_url}|{conn.site}"
        
        # Determine MCP URL to check
        mcp_url = getattr(conn, 'mcp_server_url', None) or conn.server_url
        
        try:
            is_healthy = self._send_heartbeat(mcp_url)
            
            if is_healthy:
                self._record_connection_success(conn, site_key)
            else:
                self._record_connection_failure(conn, site_key)
                
        except Exception as e:
            logger.error("Health check failed for connection %s: %s", conn.name, e)
            self._record_connection_failure(conn, site_key)

    def _send_heartbeat(self, url: str) -> bool:
        """
        Send a heartbeat to an MCP server.
        
        Returns True if the server responds successfully, False otherwise.
        """
        protocol_ver = "2025-06-18"
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
            "MCP-Protocol-Version": protocol_ver,
        }
        
        try:
            with httpx.Client(timeout=5.0) as client:
                # Send initialize as heartbeat check
                resp = client.post(
                    url,
                    json={
                        "jsonrpc": "2.0",
                        "id": 1,
                        "method": "initialize",
                        "params": {
                            "protocolVersion": protocol_ver,
                            "clientInfo": {"name": "mulan-health", "version": "1.0"},
                            "serverInfo": {"name": "tableau-mcp", "version": "1.0"},
                        },
                    },
                    headers=headers,
                )
                
                if resp.status_code == 200:
                    # Check if we got a valid response
                    text = resp.text.strip()
                    if text and "error" not in text[:100].lower():
                        return True
                
                return False
                
        except Exception:
            return False

    def _record_success(self, server: McpServer, site_key: str) -> None:
        """Record a successful health check."""
        from app.core.database import SessionLocal
        
        session = SessionLocal()
        try:
            server = session.query(McpServer).filter(McpServer.id == server.id).first()
            if not server:
                return
            
            # Reset failure count
            server.consecutive_failures = 0
            server.health_status = "healthy"
            session.commit()
            
            # Update Redis cache
            self._cache_health(site_key, "healthy")
            
            logger.debug("Site %s health check: SUCCESS", site_key)
        finally:
            session.close()

    def _record_failure(self, server: McpServer, site_key: str) -> None:
        """Record a failed health check."""
        from app.core.database import SessionLocal
        
        session = SessionLocal()
        try:
            server = session.query(McpServer).filter(McpServer.id == server.id).first()
            if not server:
                return
            
            server.consecutive_failures = (server.consecutive_failures or 0) + 1
            
            if server.consecutive_failures >= self.max_consecutive_failures:
                server.health_status = "unhealthy"
                logger.warning("Site %s marked UNHEALTHY (consecutive_failures=%d)",
                             site_key, server.consecutive_failures)
                self._cache_health(site_key, "unhealthy")
            else:
                logger.debug("Site %s health check: FAILURE (%d/%d)",
                           site_key, server.consecutive_failures, self.max_consecutive_failures)
            
            session.commit()
        finally:
            session.close()

    def _record_connection_success(self, conn, site_key: str) -> None:
        """Record a successful health check for TableauConnection."""
        from app.core.database import SessionLocal
        
        session = SessionLocal()
        try:
            # Reload the connection
            conn = session.query(type(conn.__class__)).filter(
                type(conn.__class__).id == conn.id
            ).first()
            if not conn:
                return
            
            conn.last_test_success = True
            conn.last_test_at = time.time()
            conn.last_test_message = "Health check OK"
            session.commit()
            
            # Also update Redis cache
            self._cache_health(site_key, "healthy")
            
            logger.debug("Connection %s health check: SUCCESS", site_key)
        finally:
            session.close()

    def _record_connection_failure(self, conn, site_key: str) -> None:
        """Record a failed health check for TableauConnection."""
        from app.core.database import SessionLocal
        
        session = SessionLocal()
        try:
            # Reload the connection
            conn = session.query(type(conn.__class__)).filter(
                type(conn.__class__).id == conn.id
            ).first()
            if not conn:
                return
            
            conn.last_test_success = False
            conn.last_test_at = time.time()
            conn.last_test_message = "Health check failed"
            session.commit()
            
            self._cache_health(site_key, "unhealthy")
            
            logger.debug("Connection %s health check: FAILURE", site_key)
        finally:
            session.close()

    def _cache_health(self, site_key: str, status: str) -> None:
        """Cache health status in Redis."""
        try:
            from services.common.redis_cache import get_redis_client
            redis_client = get_redis_client()
            if redis_client:
                cache_key = f"{_HEALTH_CACHE_PREFIX}{site_key}"
                redis_client.setex(cache_key, _HEALTH_TTL, status)
        except Exception as e:
            logger.debug("Failed to cache health status in Redis: %s", e)

    def get_cached_health(self, site_key: str) -> Optional[str]:
        """Get cached health status from Redis."""
        try:
            from services.common.redis_cache import get_redis_client
            redis_client = get_redis_client()
            if redis_client:
                cache_key = f"{_HEALTH_CACHE_PREFIX}{site_key}"
                return redis_client.get(cache_key)
        except Exception:
            pass
        return None

    async def check_site_health_async(self, site: SiteInfo) -> bool:
        """
        Asynchronously check the health of a single site.
        
        Returns True if healthy, False otherwise.
        """
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, self._send_heartbeat, site.site_url)

    # ── Spec 13 §3.4: MCP Offline Degradation ──────────────────────────────────

    def check_mcp_health(self, server_url: str) -> dict:
        """
        同步检查 MCP Server 健康状态（Spec 13 §3.4 T1）。
        
        定期 ping MCP server，连续 N 次失败后标记为 degraded。
        
        Returns:
            dict with keys:
                - is_healthy: bool
                - consecutive_failures: int
                - status: 'healthy' | 'degraded' | 'unhealthy'
        """
        is_ok = self._send_heartbeat(server_url)
        if is_ok:
            return {"is_healthy": True, "consecutive_failures": 0, "status": "healthy"}
        return {"is_healthy": False, "consecutive_failures": 1, "status": "degraded"}

    def check_mcp_health_with_failures(
        self, server_url: str, current_failures: int = 0
    ) -> dict:
        """
        带失败计数累积的 MCP 健康检查（Spec 13 §3.4 T1）。
        
        Args:
            server_url: MCP server URL
            current_failures: 当前已累积的失败次数
        
        Returns:
            dict with keys:
                - is_healthy: bool
                - consecutive_failures: int
                - status: 'healthy' | 'degraded' | 'unhealthy'
        """
        is_ok = self._send_heartbeat(server_url)
        if is_ok:
            return {"is_healthy": True, "consecutive_failures": 0, "status": "healthy"}
        
        new_failures = current_failures + 1
        if new_failures >= self.max_consecutive_failures:
            status = "unhealthy"
        else:
            status = "degraded"
        return {"is_healthy": False, "consecutive_failures": new_failures, "status": status}

    def get_mcp_degraded_connections(self) -> list:
        """
        返回所有处于 degraded/unhealthy 状态的 MCP 连接（Spec 13 §3.4 T2）。
        
        Returns:
            List of (connection_id, server_url, health_status) tuples
        """
        from app.core.database import SessionLocal
        from services.tableau.models import TableauConnection
        
        degraded = []
        session = SessionLocal()
        try:
            connections = session.query(TableauConnection).filter(
                TableauConnection.is_active == True,
            ).all()
            for conn in connections:
                mcp_url = getattr(conn, 'mcp_server_url', None) or conn.server_url
                health = self.check_mcp_health(mcp_url)
                if not health["is_healthy"]:
                    degraded.append({
                        "connection_id": conn.id,
                        "connection_name": conn.name,
                        "server_url": mcp_url,
                        "health_status": health["status"],
                    })
        finally:
            session.close()
        return degraded


# Module-level singleton
site_health_monitor = SiteHealthMonitor()

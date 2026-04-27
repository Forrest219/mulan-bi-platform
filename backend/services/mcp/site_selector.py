"""
SiteSelector — 多站点 MCP 路由选择逻辑

Spec 22 P0: 实现多站点 MCP 并发调度前的站点选择逻辑

Selection strategy:
1. If datasource_luid provided → route to site owning that datasource
2. Else if query_type == 'metric' → route to default metrics site
3. Else → round-robin across healthy sites weighted by priority
"""
import logging
import threading
from dataclasses import dataclass, field
from typing import Optional

from services.mcp.models import McpServer, SiteInfo

logger = logging.getLogger(__name__)


# Round-robin state per priority tier
_rr_state: dict[int, int] = {}
_rr_lock = threading.Lock()


class SiteSelector:
    """
    多站点 MCP 路由选择器
    
    选择策略：
    1. datasource_luid provided → route to site owning that datasource
    2. query_type == 'metric' → route to default metrics site  
    3. Otherwise → round-robin across healthy sites weighted by priority
    """

    def select_site(
        self,
        datasource_luid: Optional[str],
        query_type: str,  # 'metric' | 'asset' | 'ad-hoc'
        user_role: str,
    ) -> Optional[SiteInfo]:
        """
        Select the best site for a query.
        
        Args:
            datasource_luid: If provided, route to the site owning this datasource
            query_type: 'metric', 'asset', or 'ad-hoc'
            user_role: User's role (for permission checks)
            
        Returns:
            SiteInfo for the selected site, or None if no healthy site available
        """
        from services.tableau.models import TableauConnection, TableauAsset
        from app.core.database import SessionLocal
        
        # Strategy 1: If datasource_luid provided, find owning site
        if datasource_luid:
            return self._select_by_datasource_luid(datasource_luid)
        
        # Strategy 2: Metric queries → default metrics site
        if query_type == "metric":
            return self._select_default_metrics_site()
        
        # Strategy 3: Round-robin across healthy sites weighted by priority
        return self._select_by_round_robin()

    def _select_by_datasource_luid(self, datasource_luid: str) -> Optional[SiteInfo]:
        """Find the site that owns the given datasource."""
        from services.tableau.models import TableauAsset, TableauConnection
        from app.core.database import SessionLocal
        
        session = SessionLocal()
        try:
            # Find the asset to get its connection_id
            asset = session.query(TableauAsset).filter(
                TableauAsset.tableau_id == datasource_luid,
                TableauAsset.is_deleted == False,
            ).first()
            
            if not asset:
                logger.warning("SiteSelector: datasource_luid=%s not found", datasource_luid)
                return None
            
            # Get the connection
            conn = session.query(TableauConnection).filter(
                TableauConnection.id == asset.connection_id,
                TableauConnection.is_active == True,
            ).first()
            
            if not conn:
                logger.warning("SiteSelector: connection_id=%d for datasource_luid=%s not found or inactive",
                             asset.connection_id, datasource_luid)
                return None
            
            return self._build_site_info_from_connection(conn)
        finally:
            session.close()

    def _select_default_metrics_site(self) -> Optional[SiteInfo]:
        """Select the default metrics site (is_default=True, healthy)."""
        from services.tableau.models import TableauConnection
        from app.core.database import SessionLocal
        
        session = SessionLocal()
        try:
            # First check McpServer for is_default
            mcp_server = session.query(McpServer).filter(
                McpServer.is_default == True,
                McpServer.is_active == True,
            ).first()
            
            if mcp_server:
                return SiteInfo(
                    site_id=f"mcp_{mcp_server.id}",
                    site_name=mcp_server.site_name or mcp_server.name,
                    site_url=mcp_server.server_url,
                    is_default=True,
                    priority=mcp_server.priority,
                    health_status=mcp_server.health_status,
                    consecutive_failures=mcp_server.consecutive_failures,
                )
            
            # Fallback: Check TableauConnection for is_default (if schema has it)
            # Note: TableauConnection doesn't have is_default by default
            conn = session.query(TableauConnection).filter(
                TableauConnection.is_active == True,
            ).order_by(TableauConnection.id.asc()).first()
            
            if conn:
                return self._build_site_info_from_connection(conn)
            
            return None
        finally:
            session.close()

    def _select_by_round_robin(self) -> Optional[SiteInfo]:
        """
        Round-robin across healthy sites weighted by priority.
        
        Implementation:
        - Group sites by priority tier
        - Within each tier, round-robin
        - Skip unhealthy sites (health_status != 'healthy')
        """
        global _rr_state
        
        from services.tableau.models import TableauConnection
        from app.core.database import SessionLocal
        
        session = SessionLocal()
        try:
            # Get all active, healthy connections
            connections = session.query(TableauConnection).filter(
                TableauConnection.is_active == True,
            ).all()
            
            # Also get healthy McpServers
            mcp_servers = session.query(McpServer).filter(
                McpServer.is_active == True,
                McpServer.health_status == "healthy",
            ).all()
            
            # Build site list
            sites: list[SiteInfo] = []
            
            # Build from TableauConnections
            for conn in connections:
                site_info = self._build_site_info_from_connection(conn)
                if site_info and site_info.is_healthy:
                    sites.append(site_info)
            
            # Build from McpServers
            for mcp in mcp_servers:
                sites.append(SiteInfo(
                    site_id=f"mcp_{mcp.id}",
                    site_name=mcp.site_name or mcp.name,
                    site_url=mcp.server_url,
                    is_default=mcp.is_default,
                    priority=mcp.priority,
                    health_status=mcp.health_status,
                    consecutive_failures=mcp.consecutive_failures,
                ))
            
            if not sites:
                logger.warning("SiteSelector: no healthy sites available for round-robin")
                return None
            
            # Group by priority
            priority_groups: dict[int, list[SiteInfo]] = {}
            for site in sites:
                priority_groups.setdefault(site.priority, []).append(site)
            
            # Get highest priority tier that has healthy sites
            max_priority = max(priority_groups.keys()) if priority_groups else 0
            
            # Within the highest priority tier, round-robin
            tier_sites = priority_groups.get(max_priority, [])
            if not tier_sites:
                return None
            
            with _rr_lock:
                rr_index = _rr_state.get(max_priority, 0)
                selected = tier_sites[rr_index % len(tier_sites)]
                _rr_state[max_priority] = (rr_index + 1) % len(tier_sites)
            
            logger.debug("SiteSelector: round-robin selected site_id=%s (priority=%d, index=%d)",
                        selected.site_id, max_priority, rr_index)
            return selected
        finally:
            session.close()

    def _build_site_info_from_connection(self, conn) -> Optional[SiteInfo]:
        """Build SiteInfo from a TableauConnection model."""
        # Determine health status based on connection's last_test_success
        health_status = "healthy"
        if conn.last_test_success is False:
            health_status = "unhealthy"
        elif conn.last_test_success is None:
            health_status = "unknown"
        
        # site_key format matches _get_site_key in mcp_client.py
        site_id = f"{conn.server_url}|{conn.site}"
        
        return SiteInfo(
            site_id=site_id,
            site_name=conn.site or conn.name,
            site_url=conn.mcp_server_url or conn.server_url,  # Use mcp_server_url if available
            is_default=False,
            priority=0,
            health_status=health_status,
            consecutive_failures=0,
            connection_id=conn.id,
            tableau_site_name=conn.site,
        )

    def get_all_healthy_sites(self) -> list[SiteInfo]:
        """Get all healthy sites for concurrent query."""
        from services.tableau.models import TableauConnection
        from app.core.database import SessionLocal
        
        session = SessionLocal()
        try:
            connections = session.query(TableauConnection).filter(
                TableauConnection.is_active == True,
            ).all()
            
            sites = []
            for conn in connections:
                site_info = self._build_site_info_from_connection(conn)
                if site_info and site_info.is_healthy:
                    sites.append(site_info)
            return sites
        finally:
            session.close()


# Module-level singleton
site_selector = SiteSelector()

"""
Tableau Connection Health — Spec 13 §3.4 MCP Offline Degradation

提供连接级别的 MCP 健康状态管理：
- mcp_health 状态：healthy / degraded / unhealthy
- data_freshness：基于 last_sync_at 计算数据新鲜度
- 写入拦截：degraded 状态拒绝 publish/sync 等写操作
- 读缓存放行：degraded 状态下已缓存数据仍可读
"""
import logging
import time
from datetime import datetime, timedelta
from enum import Enum
from typing import Optional

logger = logging.getLogger(__name__)


class MCPHealthStatus(str, Enum):
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNHEALTHY = "unhealthy"


# 全局 MCP 健康状态（进程内共享，key = server_url）
# 结构: {server_url: {"status": str, "consecutive_failures": int, "last_check": float}}
_mcp_health_state: dict = {}
_mcp_health_lock = __import__("threading").Lock()


def get_mcp_health(server_url: str) -> MCPHealthStatus:
    """
    获取指定 server_url 的 MCP 健康状态。
    
    Returns:
        MCPHealthStatus enum value
    """
    with _mcp_health_lock:
        entry = _mcp_health_state.get(server_url, {})
        return MCPHealthStatus(entry.get("status", "healthy"))


def set_mcp_health(server_url: str, status: MCPHealthStatus, consecutive_failures: int = 0) -> None:
    """
    更新指定 server_url 的 MCP 健康状态。
    """
    with _mcp_health_lock:
        _mcp_health_state[server_url] = {
            "status": status.value,
            "consecutive_failures": consecutive_failures,
            "last_check": time.time(),
        }


def reset_mcp_health(server_url: str) -> None:
    """
    重置指定 server_url 的 MCP 健康状态为 healthy（自动恢复时调用）。
    """
    with _mcp_health_lock:
        _mcp_health_state.pop(server_url, None)


def is_mcp_healthy(server_url: str) -> bool:
    """返回 True 如果 MCP 状态为 healthy。"""
    return get_mcp_health(server_url) == MCPHealthStatus.HEALTHY


def is_mcp_degraded(server_url: str) -> bool:
    """返回 True 如果 MCP 处于 degraded 或 unhealthy 状态。"""
    return get_mcp_health(server_url) in (MCPHealthStatus.DEGRADED, MCPHealthStatus.UNHEALTHY)


def get_data_freshness(last_sync_at: Optional[datetime], sync_interval_hours: int = 24) -> dict:
    """
    计算数据新鲜度。
    
    Args:
        last_sync_at: 上次同步时间
        sync_interval_hours: 同步间隔小时数
    
    Returns:
        dict with keys:
            - status: 'fresh' | 'stale' | 'unknown'
            - hours_since_sync: float or None
            - description: str
    """
    if last_sync_at is None:
        return {
            "status": "unknown",
            "hours_since_sync": None,
            "description": "从未同步",
        }
    
    now = datetime.now(last_sync_at.tzinfo) if last_sync_at.tzinfo else datetime.now()
    delta = now - last_sync_at
    hours = delta.total_seconds() / 3600
    
    if hours <= sync_interval_hours * 1.5:  # 1.5x interval 内视为 fresh
        return {
            "status": "fresh",
            "hours_since_sync": round(hours, 1),
            "description": f"{round(hours, 1)} 小时前同步",
        }
    elif hours <= sync_interval_hours * 3:
        return {
            "status": "stale",
            "hours_since_sync": round(hours, 1),
            "description": f"数据较旧：{round(hours, 1)} 小时前同步",
        }
    else:
        return {
            "status": "stale",
            "hours_since_sync": round(hours, 1),
            "description": f"数据严重过期：{round(hours, 1)} 小时前同步",
        }


class ConnectionHealthMixin:
    """
    Tableau 连接健康状态混入类（供 TableauConnection 模型扩展使用）。
    
    在 degraded 状态下，写操作（publish/sync）返回 503，
    读操作（缓存数据）仍可用。
    """

    @property
    def mcp_health(self) -> MCPHealthStatus:
        """返回该连接的 MCP 健康状态。"""
        mcp_url = getattr(self, 'mcp_server_url', None) or getattr(self, 'server_url', None)
        if not mcp_url:
            return MCPHealthStatus.HEALTHY
        return get_mcp_health(mcp_url)

    @property
    def is_mcp_available(self) -> bool:
        """返回 True 如果 MCP 可用（健康状态）。"""
        return is_mcp_healthy(getattr(self, 'mcp_server_url', None) or getattr(self, 'server_url', None))

    @property
    def data_freshness(self) -> dict:
        """返回该连接的数据新鲜度。"""
        return get_data_freshness(
            last_sync_at=getattr(self, 'last_sync_at', None),
            sync_interval_hours=getattr(self, 'sync_interval_hours', 24) or 24,
        )

    def check_write_allowed(self) -> tuple:
        """
        检查写操作是否允许。
        
        Returns:
            (allowed: bool, error_response: dict or None)
            - allowed=True, error_response=None 表示允许
            - allowed=False, error_response={...} 表示拒绝（返回 503）
        """
        if is_mcp_degraded(getattr(self, 'mcp_server_url', None) or getattr(self, 'server_url', None)):
            return False, {
                "error_code": "MCP_003",
                "message": "MCP 服务不可用（degraded 状态），写操作暂停。请等待服务恢复。",
                "mcp_health": get_mcp_health(
                    getattr(self, 'mcp_server_url', None) or getattr(self, 'server_url', None)
                ).value,
            }
        return True, None

    def check_read_allowed(self) -> tuple:
        """
        检查读操作是否允许（即使 MCP degraded，缓存数据仍可读）。
        
        Returns:
            (allowed: bool, warning: str or None)
        """
        mcp_url = getattr(self, 'mcp_server_url', None) or getattr(self, 'server_url', None)
        health = get_mcp_health(mcp_url)
        if health != MCPHealthStatus.HEALTHY:
            warning = f"MCP 当前处于 {health.value} 状态，返回缓存数据。"
            return True, warning
        return True, None


def build_connection_status_response(conn) -> dict:
    """
    构建连接状态响应（用于 GET /api/tableau/connections/{id}/status）。
    
    Args:
        conn: TableauConnection 实例
    
    Returns:
        dict with mcp_health, data_freshness, and connection metadata
    """
    mcp_url = getattr(conn, 'mcp_server_url', None) or getattr(conn, 'server_url', None)
    health = get_mcp_health(mcp_url) if mcp_url else MCPHealthStatus.HEALTHY
    freshness = get_data_freshness(
        last_sync_at=getattr(conn, 'last_sync_at', None),
        sync_interval_hours=getattr(conn, 'sync_interval_hours', 24) or 24,
    )
    
    return {
        "connection_id": conn.id,
        "connection_name": conn.name,
        "mcp_health": health.value,
        "data_freshness": freshness,
        "last_sync_at": conn.last_sync_at.strftime("%Y-%m-%d %H:%M:%S") if conn.last_sync_at else None,
        "last_test_at": conn.last_test_at.strftime("%Y-%m-%d %H:%M:%S") if conn.last_test_at else None,
        "last_test_success": conn.last_test_success,
        "sync_status": getattr(conn, 'sync_status', 'idle') or 'idle',
    }

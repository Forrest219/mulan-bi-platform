"""Connection Hub（Spec 24 P2 完成）

子模块：
- unified_view: 三类连接的读模型聚合
- connection_manager: 写操作与连接池管理
"""
from .unified_view import (
    ConnectionType,
    HealthStatus,
    UnifiedConnection,
    get_unified_connections,
)
from .connection_manager import (
    ConnectionManager,
    ConnectionPoolManager,
    get_pool_manager,
    get_builder,
    BUILDER_REGISTRY,
)

__all__ = [
    # unified_view
    "ConnectionType",
    "HealthStatus",
    "UnifiedConnection",
    "get_unified_connections",
    # connection_manager
    "ConnectionManager",
    "ConnectionPoolManager",
    "get_pool_manager",
    "get_builder",
    "BUILDER_REGISTRY",
]

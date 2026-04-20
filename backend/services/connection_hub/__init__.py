"""Connection Hub（Spec 24 P0）

子模块：
- unified_view: 三类连接的读模型聚合
"""
from .unified_view import (
    ConnectionType,
    HealthStatus,
    UnifiedConnection,
    get_unified_connections,
)

__all__ = [
    "ConnectionType",
    "HealthStatus",
    "UnifiedConnection",
    "get_unified_connections",
]

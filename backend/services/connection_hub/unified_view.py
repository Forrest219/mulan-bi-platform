"""Connection Hub - unified connection view（Spec 24 P0 读模型聚合）

将 tableau_connections + bi_data_sources + ai_llm_configs 聚合为统一 Connection DTO。
不调用外部 API，直接查 DB。

Spec 24 P0 策略：
- 只做读模型聚合（不改旧表）
- P2 阶段在 bi_connections 表回填数据
- P4 阶段 bi_connections 成为唯一写入口
"""
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Optional

from sqlalchemy.orm import Session

# Import existing models directly (services 层可引用其他 service 的 model)
from services.tableau.models import TableauConnection as _TableauConnection
from services.datasources.models import DataSource as _DataSource
from services.llm.models import LLMConfig as _LLMConfig


class ConnectionType(str, Enum):
    """统一连接类型枚举"""
    TABLEAU_SITE = "tableau_site"    # Tableau 站点
    SQL_DATABASE = "sql_database"    # SQL 数据库
    LLM_PROVIDER = "llm_provider"     # LLM Provider


class HealthStatus(str, Enum):
    """健康状态枚举"""
    HEALTHY = "healthy"
    UNHEALTHY = "unhealthy"
    UNKNOWN = "unknown"


@dataclass
class UnifiedConnection:
    """统一连接 DTO

    Attributes:
        id: 统一域 ID（格式：tableau-{n}, sql-{n}, llm-{n}）
        type: 连接类型
        name: 连接名称（展示用）
        health_status: 健康状态
        last_check_at: 最后检查时间
        last_error: 最后错误信息（可选）
        legacy_ref: 旧系统引用 {"type": "...", "id": n}
        is_active: 是否活跃
        meta: 额外元数据（type-specific）
    """
    id: str
    type: ConnectionType
    name: str
    health_status: HealthStatus = HealthStatus.UNKNOWN
    last_check_at: Optional[datetime] = None
    last_error: Optional[str] = None
    legacy_ref: Optional[dict] = None
    is_active: bool = True
    meta: Optional[dict] = None

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "type": self.type.value,
            "name": self.name,
            "health_status": self.health_status.value,
            "last_check_at": self.last_check_at.isoformat() if self.last_check_at else None,
            "last_error": self.last_error,
            "legacy_ref": self.legacy_ref,
            "is_active": self.is_active,
            "meta": self.meta or {},
        }


def _parse_tableau_health(conn: _TableauConnection) -> tuple[HealthStatus, Optional[str]]:
    """从 TableauConnection 提取健康状态"""
    if conn.last_test_at is None:
        return HealthStatus.UNKNOWN, None
    if conn.last_test_success:
        return HealthStatus.HEALTHY, None
    return HealthStatus.UNHEALTHY, conn.last_test_message


def _parse_sql_health(conn: _DataSource) -> tuple[HealthStatus, Optional[str]]:
    """从 DataSource 提取健康状态（目前无健康检查字段，降级为 UNKNOWN）"""
    return HealthStatus.UNKNOWN, None


def _parse_llm_health(conn: _LLMConfig) -> tuple[HealthStatus, Optional[str]]:
    """从 LLMConfig 提取健康状态（目前无健康检查字段，降级为 UNKNOWN）"""
    return HealthStatus.UNKNOWN, None


def get_unified_connections(db: Session) -> list[UnifiedConnection]:
    """聚合三类连接为统一视图。

    查询逻辑：
    - Tableau: id, name, site as meta, is_active, last_test_at, last_test_success, last_test_message
    - SQL DB: id, name, db_type+host+port as meta, is_active
    - LLM: id, display_name or model as name, provider+model as meta, is_active

    Returns:
        按 type 分组的 UnifiedConnection 列表
    """
    connections: list[UnifiedConnection] = []

    # ── Tableau Sites ──────────────────────────────────────────
    try:
        tableau_conns = db.query(_TableauConnection).all()
        for conn in tableau_conns:
            health, error = _parse_tableau_health(conn)
            connections.append(UnifiedConnection(
                id=f"tableau-{conn.id}",
                type=ConnectionType.TABLEAU_SITE,
                name=conn.name,
                health_status=health,
                last_check_at=conn.last_test_at,
                last_error=error,
                legacy_ref={"type": "tableau_connections", "id": conn.id},
                is_active=conn.is_active,
                meta={
                    "site": conn.site,
                    "server_url": conn.server_url,
                },
            ))
    except Exception:
        pass  # P0 阶段容错，不阻塞其他类型

    # ── SQL Databases ───────────────────────────────────────────
    try:
        sql_conns = db.query(_DataSource).all()
        for conn in sql_conns:
            health, error = _parse_sql_health(conn)
            connections.append(UnifiedConnection(
                id=f"sql-{conn.id}",
                type=ConnectionType.SQL_DATABASE,
                name=conn.name,
                health_status=health,
                last_check_at=None,
                last_error=None,
                legacy_ref={"type": "bi_data_sources", "id": conn.id},
                is_active=conn.is_active,
                meta={
                    "db_type": conn.db_type,
                    "host": conn.host,
                    "port": conn.port,
                    "database_name": conn.database_name,
                },
            ))
    except Exception:
        pass

    # ── LLM Providers ─────────────────────────────────────────
    try:
        llm_conns = db.query(_LLMConfig).all()
        for conn in llm_conns:
            health, error = _parse_llm_health(conn)
            connections.append(UnifiedConnection(
                id=f"llm-{conn.id}",
                type=ConnectionType.LLM_PROVIDER,
                name=conn.display_name or f"{conn.provider}/{conn.model}",
                health_status=health,
                last_check_at=None,
                last_error=None,
                legacy_ref={"type": "ai_llm_configs", "id": conn.id},
                is_active=conn.is_active,
                meta={
                    "provider": conn.provider,
                    "model": conn.model,
                    "purpose": conn.purpose,
                },
            ))
    except Exception:
        pass

    return connections

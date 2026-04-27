"""
MCP Server Models — Multi-Site MCP 站点信息模型

Spec 22 P0: 扩展 McpServer 模型支持多站点健康状态
"""
from sqlalchemy import Column, Integer, String, Boolean, DateTime, Text, Float
from sqlalchemy.dialects.postgresql import JSONB
from app.core.database import Base, sa_func, sa_text


class McpServer(Base):
    """
    MCP Server 注册表（支持多 Tableau Site）
    
    扩展字段（Spec 22 P0）:
    - site_name: Tableau Site 名称
    - is_default: 是否为默认指标站点
    - priority: 优先级（数值越高越优先）
    - health_status: 健康状态 'healthy' | 'unhealthy' | 'unknown'
    - consecutive_failures: 连续失败次数
    """
    __tablename__ = "mcp_servers"

    id          = Column(Integer, primary_key=True)
    name        = Column(String(128), nullable=False, unique=True)
    type        = Column(String(32), nullable=False, server_default=sa_text("'tableau'"))
    server_url  = Column(String(512), nullable=False)
    description = Column(Text, nullable=True)
    is_active   = Column(Boolean, nullable=False, default=False, server_default=sa_text("false"))
    credentials = Column(JSONB, nullable=True)
    created_at  = Column(DateTime, nullable=False, server_default=sa_func.now())
    updated_at  = Column(DateTime, nullable=False, server_default=sa_func.now(),
                         onupdate=sa_func.now())
    
    # Spec 22 P0: 多站点 MCP 扩展字段
    site_name = Column(String(128), nullable=True)  # Tableau Site 名称
    is_default = Column(Boolean, default=False, server_default=sa_text("false"))
    priority = Column(Integer, default=0, server_default=sa_func.cast(0, Integer()))
    health_status = Column(String(32), default="unknown", server_default=sa_text("'unknown'"))
    consecutive_failures = Column(Integer, default=0, server_default=sa_func.cast(0, Integer()))

    def to_dict(self):
        return {
            "id":          self.id,
            "name":        self.name,
            "type":        self.type,
            "server_url":  self.server_url,
            "description": self.description,
            "is_active":   self.is_active,
            "credentials": self.credentials,
            "created_at":  self.created_at.isoformat() if self.created_at else None,
            "updated_at":  self.updated_at.isoformat() if self.updated_at else None,
            # Spec 22 P0 扩展字段
            "site_name": self.site_name,
            "is_default": self.is_default,
            "priority": self.priority,
            "health_status": self.health_status,
            "consecutive_failures": self.consecutive_failures,
        }


# SiteInfo dataclass for in-memory representation (used by SiteSelector)
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class SiteInfo:
    """
    内存中的站点信息（从 McpServer 或 TableauConnection 构建）
    
    Spec 22 P0: 支持多站点 MCP 并发调度
    """
    site_id: str
    site_name: str
    site_url: str  # MCP server URL
    is_default: bool = False
    priority: int = 0
    health_status: str = "unknown"  # 'healthy' | 'unhealthy' | 'unknown'
    consecutive_failures: int = 0
    connection_id: Optional[int] = None  # 对应的 TableauConnection.id
    tableau_site_name: Optional[str] = None  # Tableau 原生 Site 名称
    
    @property
    def is_healthy(self) -> bool:
        return self.health_status == "healthy"
    
    def to_dict(self) -> dict:
        return {
            "site_id": self.site_id,
            "site_name": self.site_name,
            "site_url": self.site_url,
            "is_default": self.is_default,
            "priority": self.priority,
            "health_status": self.health_status,
            "consecutive_failures": self.consecutive_failures,
            "connection_id": self.connection_id,
            "tableau_site_name": self.tableau_site_name,
        }

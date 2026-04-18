from sqlalchemy import Column, Integer, String, Boolean, DateTime, Text
from sqlalchemy.dialects.postgresql import JSONB
from app.core.database import Base, sa_func, sa_text


class McpServer(Base):
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
        }

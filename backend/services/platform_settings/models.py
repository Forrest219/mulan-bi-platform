"""平台设置数据模型"""
from datetime import datetime
from typing import Dict, Any

from sqlalchemy import Column, Integer, String, DateTime, CheckConstraint, JSON
from sqlalchemy.orm import relationship

from app.core.database import Base, JSONB, sa_func, sa_text


class PlatformSettings(Base):
    """平台设置表（单行记录，id=1）"""
    __tablename__ = "platform_settings"

    id = Column(Integer, primary_key=True, autoincrement=True)
    platform_name = Column(String(128), nullable=False, default="木兰 BI 平台")
    platform_subtitle = Column(String(256), nullable=True, default="数据建模与治理平台")
    logo_url = Column(String(512), nullable=False)
    favicon_url = Column(String(512), nullable=True)
    extra_settings = Column(JSON, nullable=True, default=dict)  # Spec 36 §15: KV 扩展字段
    created_at = Column(DateTime, nullable=False, server_default=sa_func.now())
    updated_at = Column(DateTime, nullable=False, server_default=sa_func.now(), onupdate=sa_func.now())

    __table_args__ = (
        CheckConstraint("id = 1", name="ck_platform_settings_single_row"),
    )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "platform_name": self.platform_name,
            "platform_subtitle": self.platform_subtitle,
            "logo_url": self.logo_url,
            "favicon_url": self.favicon_url,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }

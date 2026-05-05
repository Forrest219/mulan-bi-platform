"""Metrics Agent — 维护窗口（Maintenance Window）Model

Spec 30 §4.2.1：admin 配置 [start, end] 时间区间，检测器在此区间跳过检测，
不写 anomaly，不发事件。
"""

from datetime import datetime

from sqlalchemy import Boolean, Column, DateTime, BigInteger, String, func

from app.core.database import Base


class BiMaintenanceWindow(Base):
    """
    维护窗口配置表

    检测器在 start_at ~ end_at 区间内跳过异常检测，不写 anomaly，不发事件。
    """
    __tablename__ = "bi_maintenance_windows"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    name = Column(String(128), nullable=False, comment="窗口名称")
    start_at = Column(DateTime, nullable=False, comment="窗口开始时间")
    end_at = Column(DateTime, nullable=False, comment="窗口结束时间")
    timezone = Column(String(32), default="Asia/Shanghai", comment="时区")
    reason = Column(String(512), nullable=True, comment="维护原因")
    created_by = Column(BigInteger, nullable=True, comment="创建人 user_id")
    is_active = Column(Boolean, server_default="true", nullable=False, comment="是否启用")
    created_at = Column(DateTime, server_default=func.now(), nullable=False, comment="创建时间")
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now(), nullable=False, comment="更新时间")

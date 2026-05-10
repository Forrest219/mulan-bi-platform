"""Metrics Agent — Maintenance Window Service

Spec 30 §4.2.1：admin配置 [start, end] 时间区间，检测器在此区间跳过检测，
不写 anomaly，不发事件。

Service 层不得 import FastAPI。
"""
from __future__ import annotations

import logging
from datetime import datetime

from sqlalchemy.orm import Session

from models.metrics_maintenance_window import BiMaintenanceWindow

logger = logging.getLogger(__name__)


class MaintenanceWindowService:
    """维护窗口服务"""

    def is_in_window(self, db: Session) -> bool:
        """
        判断当前时刻是否处于任意 active 维护窗口内。

        Returns:
            True — 当前在某个 active 窗口内，检测器应跳过
            False — 无 active 窗口，检测器正常执行
        """
        now = datetime.utcnow()
        window = db.query(BiMaintenanceWindow).filter(
            BiMaintenanceWindow.is_active == True,  # noqa: E712
            BiMaintenanceWindow.start_at <= now,
            BiMaintenanceWindow.end_at >= now,
        ).first()

        if window:
            logger.info(
                "当前处于维护窗口：id=%s, name=%s, start_at=%s, end_at=%s",
                window.id,
                window.name,
                window.start_at,
                window.end_at,
            )
            return True
        return False

    def get_active_window(self, db: Session) -> BiMaintenanceWindow | None:
        """
        获取当前处于 active 的维护窗口（仅供展示用）。

        Returns:
            当前 active 的窗口对象，或 None
        """
        now = datetime.utcnow()
        return db.query(BiMaintenanceWindow).filter(
            BiMaintenanceWindow.is_active == True,  # noqa: E712
            BiMaintenanceWindow.start_at <= now,
            BiMaintenanceWindow.end_at >= now,
        ).first()

    def list_windows(
        self,
        db: Session,
        page: int = 1,
        page_size: int = 20,
        is_active: bool | None = None,
    ) -> tuple[list[BiMaintenanceWindow], int]:
        """
        列出维护窗口，支持分页和状态过滤。

        Args:
            db: 数据库 session
            page: 页码（从 1 开始）
            page_size: 每页条数
            is_active: 按激活状态过滤，None 表示不过滤

        Returns:
            (items, total) 元组
        """
        q = db.query(BiMaintenanceWindow)

        if is_active is not None:
            q = q.filter(BiMaintenanceWindow.is_active == is_active)

        total = q.count()
        offset = (page - 1) * page_size
        items = (
            q.order_by(BiMaintenanceWindow.created_at.desc())
            .offset(offset)
            .limit(page_size)
            .all()
        )
        return items, total

    def create_window(
        self,
        db: Session,
        name: str,
        start_at: datetime,
        end_at: datetime,
        timezone: str = "Asia/Shanghai",
        reason: str | None = None,
        created_by: int | None = None,
    ) -> BiMaintenanceWindow:
        """
        创建新的维护窗口。

        Args:
            db: 数据库 session
            name: 窗口名称
            start_at: 开始时间
            end_at: 结束时间
            timezone: 时区，默认 Asia/Shanghai
            reason: 维护原因
            created_by: 创建人 user_id

        Returns:
            新创建的窗口对象
        """
        if end_at <= start_at:
            raise ValueError("结束时间必须大于开始时间")

        window = BiMaintenanceWindow(
            name=name,
            start_at=start_at,
            end_at=end_at,
            timezone=timezone,
            reason=reason,
            created_by=created_by,
            is_active=True,
        )
        db.add(window)
        db.commit()
        db.refresh(window)
        logger.info(
            "创建维护窗口：id=%s, name=%s, start_at=%s, end_at=%s",
            window.id,
            window.name,
            window.start_at,
            window.end_at,
        )
        return window

    def update_window(
        self,
        db: Session,
        window_id: int,
        name: str | None = None,
        start_at: datetime | None = None,
        end_at: datetime | None = None,
        timezone: str | None = None,
        reason: str | None = None,
        is_active: bool | None = None,
    ) -> BiMaintenanceWindow:
        """
        更新维护窗口。

        Args:
            db: 数据库 session
            window_id: 窗口 ID
            name: 窗口名称
            start_at: 开始时间
            end_at: 结束时间
            timezone: 时区
            reason: 维护原因
            is_active: 是否激活

        Returns:
            更新后的窗口对象

        Raises:
            ValueError: 窗口不存在或参数校验失败
        """
        window = db.query(BiMaintenanceWindow).filter(
            BiMaintenanceWindow.id == window_id
        ).first()

        if not window:
            raise ValueError(f"维护窗口不存在：id={window_id}")

        if name is not None:
            window.name = name
        if start_at is not None:
            window.start_at = start_at
        if end_at is not None:
            window.end_at = end_at
        if timezone is not None:
            window.timezone = timezone
        if reason is not None:
            window.reason = reason
        if is_active is not None:
            window.is_active = is_active

        if start_at and end_at and end_at <= start_at:
            raise ValueError("结束时间必须大于开始时间")

        db.commit()
        db.refresh(window)
        logger.info("更新维护窗口：id=%s", window_id)
        return window

    def delete_window(self, db: Session, window_id: int) -> None:
        """
        删除维护窗口。

        Args:
            db: 数据库 session
            window_id: 窗口 ID

        Raises:
            ValueError: 窗口不存在
        """
        window = db.query(BiMaintenanceWindow).filter(
            BiMaintenanceWindow.id == window_id
        ).first()

        if not window:
            raise ValueError(f"维护窗口不存在：id={window_id}")

        db.delete(window)
        db.commit()
        logger.info("删除维护窗口：id=%s", window_id)

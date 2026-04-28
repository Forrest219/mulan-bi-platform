"""事件与通知数据模型"""
from typing import Optional, List, Dict, Any

from sqlalchemy import (
    Column, BigInteger, String, DateTime,
    Boolean, Text, ForeignKey, Index
)
from sqlalchemy.orm import Session

from app.core.database import Base, JSONB, sa_func, sa_text


class BiEvent(Base):
    """事件存储表 bi_events"""
    __tablename__ = "bi_events"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    event_type = Column(String(64), nullable=False, index=True)
    source_module = Column(String(32), nullable=False)
    source_id = Column(String(128), nullable=True)
    severity = Column(String(16), nullable=False, server_default=sa_text("'info'"))
    actor_id = Column(BigInteger, ForeignKey("auth_users.id", ondelete="SET NULL"), nullable=True)
    payload_json = Column(JSONB, nullable=False, server_default=sa_text("'{}'::jsonb"))
    # extra_data: 携带 semantic_table_id / table_name 等扩展信息（Spec 9 → Spec 16）
    extra_data = Column(JSONB, nullable=True, server_default=sa_text("'{}'::jsonb"))
    created_at = Column(DateTime, nullable=False, server_default=sa_func.now())

    __table_args__ = (
        Index("ix_events_type_created", "event_type", "created_at"),
        Index("ix_events_source", "source_module", "source_id"),
        Index("ix_events_created", "created_at"),
    )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "event_type": self.event_type,
            "source_module": self.source_module,
            "source_id": self.source_id,
            "severity": self.severity,
            "actor_id": self.actor_id,
            "payload_json": self.payload_json,
            "extra_data": self.extra_data,
            "created_at": self.created_at.strftime("%Y-%m-%dT%H:%M:%SZ") if self.created_at else None,
        }


class BiNotification(Base):
    """用户通知表 bi_notifications"""
    __tablename__ = "bi_notifications"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    event_id = Column(BigInteger, ForeignKey("bi_events.id", ondelete="CASCADE"), nullable=False)
    user_id = Column(BigInteger, ForeignKey("auth_users.id", ondelete="CASCADE"), nullable=False, index=True)
    title = Column(String(256), nullable=False)
    content = Column(Text, nullable=False)
    level = Column(String(16), nullable=False, server_default=sa_text("'info'"))
    is_read = Column(Boolean, nullable=False, server_default=sa_text("false"))
    read_at = Column(DateTime, nullable=True)
    link = Column(String(512), nullable=True)
    created_at = Column(DateTime, nullable=False, server_default=sa_func.now())

    __table_args__ = (
        Index("ix_notif_user_read_created", "user_id", "is_read", "created_at"),
        Index("ix_notif_event", "event_id"),
    )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "event_id": self.event_id,
            "user_id": self.user_id,
            "title": self.title,
            "content": self.content,
            "level": self.level,
            "is_read": self.is_read,
            "read_at": self.read_at.strftime("%Y-%m-%dT%H:%M:%SZ") if self.read_at else None,
            "link": self.link,
            "created_at": self.created_at.strftime("%Y-%m-%dT%H:%M:%SZ") if self.created_at else None,
        }


class BiEventSubscription(Base):
    """用户事件订阅表 bi_event_subscriptions（支持按 metric 维度订阅异常告警，Spec 30）"""
    __tablename__ = "bi_event_subscriptions"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    user_id = Column(BigInteger, ForeignKey("auth_users.id", ondelete="CASCADE"), nullable=False, index=True)
    event_type = Column(String(64), nullable=False, index=True)
    # target_id 对应不同事件类型的关联对象 ID，如 anomaly.detected 时为 metric_id
    target_id = Column(String(128), nullable=True, index=True)
    is_active = Column(Boolean, nullable=False, server_default=sa_text("true"))
    created_at = Column(DateTime, nullable=False, server_default=sa_func.now())
    updated_at = Column(DateTime, nullable=True)

    __table_args__ = (
        Index("ix_event_sub_user_event_target", "user_id", "event_type", "target_id"),
        Index("ix_event_sub_event_active", "event_type", "is_active"),
    )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "user_id": self.user_id,
            "event_type": self.event_type,
            "target_id": self.target_id,
            "is_active": self.is_active,
            "created_at": self.created_at.strftime("%Y-%m-%dT%H:%M:%SZ") if self.created_at else None,
            "updated_at": self.updated_at.strftime("%Y-%m-%dT%H:%M:%SZ") if self.updated_at else None,
        }


class EventDatabase:
    """事件与通知数据库管理"""

    def __init__(self):
        pass

    def create_event(
        self,
        db: Session,
        event_type: str,
        source_module: str,
        payload_json: dict,
        source_id: Optional[str] = None,
        severity: str = "info",
        actor_id: Optional[int] = None,
        extra_data: Optional[dict] = None,
    ) -> BiEvent:
        """创建事件记录"""
        event = BiEvent(
            event_type=event_type,
            source_module=source_module,
            source_id=source_id,
            severity=severity,
            actor_id=actor_id,
            payload_json=payload_json,
            extra_data=extra_data or {},
        )
        db.add(event)
        db.commit()
        db.refresh(event)
        return event

    def get_event(self, db: Session, event_id: int) -> Optional[BiEvent]:
        """获取单个事件"""
        return db.query(BiEvent).filter(BiEvent.id == event_id).first()

    def list_events(
        self,
        db: Session,
        page: int = 1,
        page_size: int = 20,
        event_type: Optional[str] = None,
        source_module: Optional[str] = None,
        severity: Optional[str] = None,
        start_time=None,
        end_time=None,
    ) -> Dict[str, Any]:
        """查询事件列表"""
        q = db.query(BiEvent)
        if event_type:
            q = q.filter(BiEvent.event_type == event_type)
        if source_module:
            q = q.filter(BiEvent.source_module == source_module)
        if severity:
            q = q.filter(BiEvent.severity == severity)
        if start_time:
            q = q.filter(BiEvent.created_at >= start_time)
        if end_time:
            q = q.filter(BiEvent.created_at <= end_time)

        total = q.count()
        items = q.order_by(BiEvent.id.desc()).offset((page - 1) * page_size).limit(page_size).all()
        return {
            "items": [e.to_dict() for e in items],
            "total": total,
            "page": page,
            "page_size": page_size,
        }

    def create_notification(
        self,
        db: Session,
        event_id: int,
        user_id: int,
        title: str,
        content: str,
        level: str = "info",
        link: Optional[str] = None,
    ) -> BiNotification:
        """创建通知记录"""
        notification = BiNotification(
            event_id=event_id,
            user_id=user_id,
            title=title,
            content=content,
            level=level,
            link=link,
        )
        db.add(notification)
        db.commit()
        db.refresh(notification)
        return notification

    def batch_create_notifications(
        self,
        db: Session,
        event_id: int,
        user_ids: List[int],
        title: str,
        content: str,
        level: str = "info",
        link: Optional[str] = None,
    ) -> int:
        """批量创建通知"""
        notifications = [
            BiNotification(
                event_id=event_id,
                user_id=uid,
                title=title,
                content=content,
                level=level,
                link=link,
            )
            for uid in user_ids
        ]
        db.bulk_save_objects(notifications)
        db.commit()
        return len(notifications)

    def list_notifications(
        self,
        db: Session,
        user_id: int,
        page: int = 1,
        page_size: int = 20,
        is_read: Optional[bool] = None,
        level: Optional[str] = None,
    ) -> Dict[str, Any]:
        """查询用户通知列表"""
        q = db.query(BiNotification).filter(BiNotification.user_id == user_id)
        if is_read is not None:
            q = q.filter(BiNotification.is_read == is_read)
        if level:
            q = q.filter(BiNotification.level == level)

        total = q.count()
        items = q.order_by(BiNotification.id.desc()).offset((page - 1) * page_size).limit(page_size).all()
        return {
            "items": [n.to_dict() for n in items],
            "total": total,
            "page": page,
            "page_size": page_size,
        }

    def get_notification(self, db: Session, notification_id: int) -> Optional[BiNotification]:
        """获取单个通知"""
        return db.query(BiNotification).filter(BiNotification.id == notification_id).first()

    def mark_read(self, db: Session, notification_id: int) -> Optional[BiNotification]:
        """标记通知已读"""
        notification = self.get_notification(db, notification_id)
        if notification:
            notification.is_read = True
            notification.read_at = sa_func.now()
            db.commit()
            db.refresh(notification)
        return notification

    def mark_batch_read(self, db: Session, notification_ids: List[int], user_id: int) -> int:
        """批量标记通知已读"""
        count = db.query(BiNotification).filter(
            BiNotification.id.in_(notification_ids),
            BiNotification.user_id == user_id,
        ).update({"is_read": True, "read_at": sa_func.now()}, synchronize_session=False)
        db.commit()
        return count

    def mark_all_read(self, db: Session, user_id: int) -> int:
        """标记用户所有通知已读"""
        count = db.query(BiNotification).filter(
            BiNotification.user_id == user_id,
            BiNotification.is_read == False,
        ).update({"is_read": True, "read_at": sa_func.now()}, synchronize_session=False)
        db.commit()
        return count

    def get_unread_count(self, db: Session, user_id: int) -> int:
        """获取未读通知数量"""
        return db.query(BiNotification).filter(
            BiNotification.user_id == user_id,
            BiNotification.is_read == False,
        ).count()

    def get_users_by_role(self, db: Session, role: str) -> List[int]:
        """获取指定角色的所有用户ID"""
        from services.auth.models import User
        users = db.query(User).filter(User.role == role).all()
        return [u.id for u in users]

    def get_connection_owner(self, db: Session, connection_id: int) -> Optional[int]:
        """获取 Tableau 连接所有者ID"""
        from services.tableau.models import TableauConnection
        conn = db.query(TableauConnection).filter(TableauConnection.id == connection_id).first()
        return conn.owner_id if conn else None

    # -------------------------------------------------------------------------
    # 异常告警订阅管理（Spec 30）
    # -------------------------------------------------------------------------

    def create_subscription(
        self,
        db: Session,
        user_id: int,
        event_type: str,
        target_id: Optional[str] = None,
    ) -> BiEventSubscription:
        """创建事件订阅"""
        sub = BiEventSubscription(
            user_id=user_id,
            event_type=event_type,
            target_id=target_id,
            is_active=True,
        )
        db.add(sub)
        db.commit()
        db.refresh(sub)
        return sub

    def get_subscription(self, db: Session, subscription_id: int) -> Optional[BiEventSubscription]:
        """获取单个订阅"""
        return db.query(BiEventSubscription).filter(BiEventSubscription.id == subscription_id).first()

    def list_subscriptions(
        self,
        db: Session,
        user_id: int,
        event_type: Optional[str] = None,
        target_id: Optional[str] = None,
        page: int = 1,
        page_size: int = 20,
    ) -> Dict[str, Any]:
        """查询用户订阅列表"""
        q = db.query(BiEventSubscription).filter(BiEventSubscription.user_id == user_id)
        if event_type:
            q = q.filter(BiEventSubscription.event_type == event_type)
        if target_id is not None:
            q = q.filter(BiEventSubscription.target_id == target_id)

        total = q.count()
        items = (
            q.order_by(BiEventSubscription.id.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
            .all()
        )
        return {
            "items": [s.to_dict() for s in items],
            "total": total,
            "page": page,
            "page_size": page_size,
        }

    def delete_subscription(self, db: Session, subscription_id: int, user_id: int) -> bool:
        """删除订阅（仅所有者可删除）"""
        sub = db.query(BiEventSubscription).filter(
            BiEventSubscription.id == subscription_id,
            BiEventSubscription.user_id == user_id,
        ).first()
        if not sub:
            return False
        db.delete(sub)
        db.commit()
        return True

    def upsert_subscription(
        self,
        db: Session,
        user_id: int,
        event_type: str,
        target_id: Optional[str],
    ) -> BiEventSubscription:
        """
        幂等 upsert：若同 user_id + event_type + target_id 的订阅已存在则返回已有记录，
        否则创建新订阅。
        """
        existing = (
            db.query(BiEventSubscription)
            .filter(
                BiEventSubscription.user_id == user_id,
                BiEventSubscription.event_type == event_type,
                BiEventSubscription.target_id == target_id,
            )
            .first()
        )
        if existing:
            return existing
        return self.create_subscription(db, user_id, event_type, target_id)

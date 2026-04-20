"""SQL Agent 数据模型 — sql_agent_query_log 表定义"""

import hashlib
from typing import Optional

# 惰性导入，避免未配置 DATABASE_URL 时无法导入
_Base = None
_sa_func = None

def _get_base():
    global _Base, _sa_func
    if _Base is None:
        from app.core.database import Base, sa_func
        _Base = Base
        _sa_func = sa_func
    return _Base, _sa_func


class SQLAgentQueryLog:
    """SQL 执行日志表（SQLAlchemy Model）"""

    __tablename__ = "sql_agent_query_log"
    __table_args__ = (
        {"extend_existing": True},
    )

    id: int
    datasource_id: int
    db_type: str
    sql_text: str
    sql_hash: str
    action_type: str
    rejected_reason: Optional[str]
    row_count: Optional[int]
    duration_ms: int
    limit_applied: Optional[int]
    user_id: int
    created_at: None

    @staticmethod
    def compute_sql_hash(sql: str) -> str:
        """计算 SQL 的 SHA256 哈希（校验后、含 LIMIT 注入的 SQL）"""
        return hashlib.sha256(sql.encode("utf-8")).hexdigest()

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "datasource_id": self.datasource_id,
            "db_type": self.db_type,
            "sql_text": self.sql_text,
            "sql_hash": self.sql_hash,
            "action_type": self.action_type,
            "rejected_reason": self.rejected_reason,
            "row_count": self.row_count,
            "duration_ms": self.duration_ms,
            "limit_applied": self.limit_applied,
            "user_id": self.user_id,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }

    @classmethod
    def sqlalchemy_model(cls):
        """动态构造 SQLAlchemy Model，延迟到需要时才创建"""
        from sqlalchemy import Column, Integer, String, DateTime, Text, Index
        Base, sa_func = _get_base()

        class _SQLAgentQueryLog(Base):
            __tablename__ = "sql_agent_query_log"

            id = Column(Integer, primary_key=True, autoincrement=True)
            datasource_id = Column(Integer, nullable=False, index=True)
            db_type = Column(String(32), nullable=False)
            sql_text = Column(Text, nullable=False)
            sql_hash = Column(String(64), nullable=False, index=True)
            action_type = Column(String(16), nullable=False)
            rejected_reason = Column(String(128), nullable=True)
            row_count = Column(Integer, nullable=True)
            duration_ms = Column(Integer, nullable=False)
            limit_applied = Column(Integer, nullable=True)
            user_id = Column(Integer, nullable=False, index=True)
            created_at = Column(DateTime, server_default=sa_func.now(), nullable=False)

            __table_args__ = (
                Index("idx_datasource_created", "datasource_id", "created_at"),
                Index("idx_sql_hash_created", "sql_hash", "created_at"),
            )

        return _SQLAgentQueryLog

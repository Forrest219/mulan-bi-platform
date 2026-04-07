"""数据源数据模型"""
from typing import Optional, List, Dict, Any

from sqlalchemy import Column, Integer, String, DateTime, Boolean
from app.core.database import Base, JSONB, sa_func, sa_text  # 导入中央配置的 Base, JSONB, func, text
from sqlalchemy.orm import Session


class DataSource(Base):
    """数据源表"""
    __tablename__ = "bi_data_sources"  # 表名前缀规范化

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(128), nullable=False)
    db_type = Column(String(32), nullable=False)  # mysql / sqlserver / postgresql / hive / starrocks / doris
    host = Column(String(256), nullable=False)
    port = Column(Integer, nullable=False)
    database_name = Column(String(128), nullable=False)
    username = Column(String(128), nullable=False)
    password_encrypted = Column(String(512), nullable=False)  # 密码加密后长度可能变长，使用 String(512)
    extra_config = Column(JSONB, nullable=True, server_default=sa_text("'{}'::jsonb"))  # P2 修复: 统一 JSONB 默认值
    owner_id = Column(Integer, nullable=False)  # 创建者用户 ID
    is_active = Column(Boolean, default=True, server_default=sa_text('true'))  # Boolean 默认值
    created_at = Column(DateTime, nullable=False, server_default=sa_func.now())  # DateTime 默认值
    updated_at = Column(DateTime, server_default=sa_func.now(), onupdate=sa_func.now())  # DateTime 默认值和更新

    def to_dict(self, include_password: bool = False) -> Dict[str, Any]:
        result = {
            "id": self.id,
            "name": self.name,
            "db_type": self.db_type,
            "host": self.host,
            "port": self.port,
            "database_name": self.database_name,
            "username": self.username,
            "owner_id": self.owner_id,
            "is_active": self.is_active,
            "extra_config": self.extra_config,  # JSONB 字段直接是 Python 对象
            "created_at": self.created_at.strftime("%Y-%m-%d %H:%M:%S") if self.created_at else None,
            "updated_at": self.updated_at.strftime("%Y-%m-%d %H:%M:%S") if self.updated_at else None,
        }
        if include_password:
            result["password_encrypted"] = self.password_encrypted
        return result


class DataSourceDatabase:
    """
    数据源数据库管理 - P0 修复版。

    修复内容：
    - Fix 1 (P0)：移除 @property session，彻底消除连接池泄漏。
      所有方法强制接受 `db: Session` 参数，由调用方控制事务边界。
    - Fix 2 (P1)：delete() 改为软删除（is_active=False），保护下游级联数据。
    - Fix 3 (P2)：extra_config 增加 server_default='{}'::jsonb。
    """

    def create(
        self,
        db: Session,
        name: str,
        db_type: str,
        host: str,
        port: int,
        database_name: str,
        username: str,
        password_encrypted: str,
        owner_id: int,
        extra_config: dict = None,
    ) -> DataSource:
        """创建数据源"""
        ds = DataSource(
            name=name,
            db_type=db_type,
            host=host,
            port=port,
            database_name=database_name,
            username=username,
            password_encrypted=password_encrypted,
            owner_id=owner_id,
            extra_config=extra_config,
        )
        db.add(ds)
        db.commit()
        return ds

    def get(self, db: Session, ds_id: int) -> Optional[DataSource]:
        """根据 ID 获取数据源"""
        return db.query(DataSource).filter(DataSource.id == ds_id).first()

    def get_all(
        self,
        db: Session,
        owner_id: int = None,
        include_inactive: bool = False,
    ) -> List[DataSource]:
        """
        获取数据源列表。

        - owner_id 为 None 时返回所有（管理员用）
        - 默认过滤 is_active=True（软删除保护）
        """
        query = db.query(DataSource)
        if owner_id is not None:
            query = query.filter(DataSource.owner_id == owner_id)
        if not include_inactive:
            query = query.filter(DataSource.is_active == True)  # noqa: E712
        return query.order_by(DataSource.created_at.desc()).all()

    def update(self, db: Session, ds_id: int, **kwargs) -> bool:
        """更新数据源字段，返回是否成功"""
        ds = db.query(DataSource).filter(DataSource.id == ds_id).first()
        if not ds:
            return False
        for key, value in kwargs.items():
            if hasattr(ds, key) and value is not None:
                setattr(ds, key, value)
        # updated_at 会由 onupdate 自动更新，无需手动设置
        db.commit()
        return True

    def delete(self, db: Session, ds_id: int) -> bool:
        """
        软删除数据源（P1 修复：将 is_active 设为 False）。

        之所以不执行硬删除，是因为数据源下游存在大量级联关联
        （语义模型、Tableau 连接、体检记录等），硬删除会引发
        外键约束报错或产生幽灵数据。
        """
        ds = db.query(DataSource).filter(DataSource.id == ds_id).first()
        if not ds:
            return False
        ds.is_active = False
        db.commit()
        return True

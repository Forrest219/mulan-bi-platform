"""数据源数据模型"""
from typing import Optional, List, Dict, Any

from sqlalchemy import Column, Integer, String, DateTime, Boolean
from app.core.database import Base, JSONB, sa_func, sa_text # 导入中央配置的 Base, JSONB, func, text

class DataSource(Base):
    """数据源表"""
    __tablename__ = "bi_data_sources" # 表名前缀规范化

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(128), nullable=False)
    db_type = Column(String(32), nullable=False)  # mysql / sqlserver / postgresql / hive / starrocks / doris
    host = Column(String(256), nullable=False)
    port = Column(Integer, nullable=False)
    database_name = Column(String(128), nullable=False)
    username = Column(String(128), nullable=False)
    password_encrypted = Column(String(512), nullable=False) # 密码加密后长度可能变长，使用 String(512)
    extra_config = Column(JSONB, nullable=True)  # JSON: SSL、编码等, 改为 JSONB
    owner_id = Column(Integer, nullable=False)  # 创建者用户 ID
    is_active = Column(Boolean, default=True, server_default=sa_text('true')) # Boolean 默认值
    created_at = Column(DateTime, nullable=False, server_default=sa_func.now()) # DateTime 默认值
    updated_at = Column(DateTime, server_default=sa_func.now(), onupdate=sa_func.now()) # DateTime 默认值和更新

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
            "extra_config": self.extra_config, # JSONB 字段直接是 Python 对象
            "created_at": self.created_at.strftime("%Y-%m-%d %H:%M:%S") if self.created_at else None,
            "updated_at": self.updated_at.strftime("%Y-%m-%d %H:%M:%S") if self.updated_at else None,
        }
        if include_password:
            result["password_encrypted"] = self.password_encrypted
        return result


# 从中央配置导入 SessionLocal
from app.core.database import SessionLocal
from sqlalchemy.orm import Session

class DataSourceDatabase:
    """数据源数据库管理 - 不再是单例，直接使用中央 SessionLocal"""

    def __init__(self, db_path: str = None):
        """db_path 参数不再使用，保留签名以兼容旧代码"""
        pass

    @property
    def session(self) -> Session:
        """每次访问获取当前线程的 session，并刷新缓存避免脏读"""
        s = SessionLocal()
        s.expire_all()
        return s

    # close 方法不再需要
    # def close(self):
    #     self.session.remove()

    def create(self, name: str, db_type: str, host: str, port: int,
               database_name: str, username: str, password_encrypted: str,
               owner_id: int, extra_config: dict = None) -> DataSource: # extra_config 现在是 dict
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
            extra_config=extra_config
        )
        self.session.add(ds)
        self.session.commit()
        return ds

    def get(self, ds_id: int) -> Optional[DataSource]:
        return self.session.query(DataSource).filter(DataSource.id == ds_id).first()

    def get_all(self, owner_id: int = None, include_inactive: bool = False) -> List[DataSource]:
        """获取数据源列表，owner_id 为 None 时返回所有（管理员用）"""
        query = self.session.query(DataSource)
        if owner_id is not None:
            query = query.filter(DataSource.owner_id == owner_id)
        if not include_inactive:
            query = query.filter(DataSource.is_active == True)
        return query.order_by(DataSource.created_at.desc()).all()

    def update(self, ds_id: int, **kwargs) -> bool:
        ds = self.get(ds_id)
        if not ds:
            return False
        for key, value in kwargs.items():
            if hasattr(ds, key) and value is not None:
                setattr(ds, key, value)
        # updated_at 会由 onupdate 自动更新，无需手动设置
        self.session.commit()
        return True

    def delete(self, ds_id: int) -> bool:
        ds = self.get(ds_id)
        if not ds:
            return False
        self.session.delete(ds)
        self.session.commit()
        return True


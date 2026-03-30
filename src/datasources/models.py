"""数据源数据模型"""
import threading
from datetime import datetime
from typing import Optional, List, Dict, Any

from sqlalchemy import create_engine, Column, Integer, String, DateTime, Boolean, Text
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker

Base = declarative_base()


class DataSource(Base):
    """数据源表"""
    __tablename__ = "data_sources"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(128), nullable=False)
    db_type = Column(String(32), nullable=False)  # mysql / sqlserver / postgresql / hive / starrocks / doris
    host = Column(String(256), nullable=False)
    port = Column(Integer, nullable=False)
    database_name = Column(String(128), nullable=False)
    username = Column(String(128), nullable=False)
    password_encrypted = Column(Text, nullable=False)
    extra_config = Column(Text, nullable=True)  # JSON: SSL、编码等
    owner_id = Column(Integer, nullable=False)  # 创建者用户 ID
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.now, nullable=False)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)

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
            "extra_config": self.extra_config,
            "created_at": self.created_at.strftime("%Y-%m-%d %H:%M:%S") if self.created_at else None,
            "updated_at": self.updated_at.strftime("%Y-%m-%d %H:%M:%S") if self.updated_at else None,
        }
        if include_password:
            result["password_encrypted"] = self.password_encrypted
        return result


class DataSourceDatabase:
    """数据源数据库管理 - 单例模式（线程安全）"""

    _instance = None
    _lock = threading.Lock()

    def __new__(cls, db_path: str = None):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:  # 二次检查
                    cls._instance = super().__new__(cls)
                    if db_path is None:
                        db_path = "/Users/zhangxingchen/Documents/Claude code projects/mulan-bi-platform/data/datasources.db"
                    cls._instance._init_db(db_path)
        return cls._instance

    def _init_db(self, db_path: str):
        """初始化数据库"""
        import os
        os.makedirs(os.path.dirname(db_path), exist_ok=True)
        self.engine = create_engine(f"sqlite:///{db_path}", echo=False, pool_pre_ping=True)
        Base.metadata.create_all(self.engine)
        Session = sessionmaker(bind=self.engine, expire_on_commit=False)
        from sqlalchemy.orm import scoped_session
        self._scoped_session = scoped_session(Session)

    @property
    def session(self):
        """线程本地的 session，每次调用返回当前线程的 session"""
        return self._scoped_session()

    def close(self):
        self._scoped_session.remove()

    def create(self, name: str, db_type: str, host: str, port: int,
               database_name: str, username: str, password_encrypted: str,
               owner_id: int, extra_config: str = None) -> DataSource:
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
        ds.updated_at = datetime.now()
        self.session.commit()
        return True

    def delete(self, ds_id: int) -> bool:
        ds = self.get(ds_id)
        if not ds:
            return False
        self.session.delete(ds)
        self.session.commit()
        return True

    def close(self):
        self.session.close()

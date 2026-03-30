"""Tableau Connection & Asset 数据模型"""
from datetime import datetime
from typing import Optional, List, Dict, Any

from sqlalchemy import create_engine, Column, Integer, String, DateTime, Boolean, Text, ForeignKey
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, relationship

Base = declarative_base()


class TableauConnection(Base):
    """Tableau 连接表"""
    __tablename__ = "tableau_connections"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(128), nullable=False)
    server_url = Column(String(512), nullable=False)
    site = Column(String(128), nullable=False)
    api_version = Column(String(16), default="3.21")
    token_name = Column(String(256), nullable=False)
    token_encrypted = Column(Text, nullable=False)
    owner_id = Column(Integer, nullable=False)
    is_active = Column(Boolean, default=True)
    last_sync_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.now, nullable=False)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)

    assets = relationship("TableauAsset", back_populates="connection", cascade="all, delete-orphan")

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "server_url": self.server_url,
            "site": self.site,
            "api_version": self.api_version,
            "token_name": self.token_name,
            "owner_id": self.owner_id,
            "is_active": self.is_active,
            "last_sync_at": self.last_sync_at.strftime("%Y-%m-%d %H:%M:%S") if self.last_sync_at else None,
            "created_at": self.created_at.strftime("%Y-%m-%d %H:%M:%S") if self.created_at else None,
            "updated_at": self.updated_at.strftime("%Y-%m-%d %H:%M:%S") if self.updated_at else None,
        }


class TableauAsset(Base):
    """Tableau 资产表（Workbooks, Views, Dashboards, DataSources）"""
    __tablename__ = "tableau_assets"

    id = Column(Integer, primary_key=True, autoincrement=True)
    connection_id = Column(Integer, ForeignKey("tableau_connections.id", ondelete="CASCADE"), nullable=False)
    asset_type = Column(String(32), nullable=False)
    tableau_id = Column(String(256), nullable=False)
    name = Column(String(256), nullable=False)
    project_name = Column(String(256), nullable=True)
    description = Column(Text, nullable=True)
    owner_name = Column(String(128), nullable=True)
    thumbnail_url = Column(String(512), nullable=True)
    content_url = Column(String(512), nullable=True)
    raw_metadata = Column(Text, nullable=True)
    is_deleted = Column(Boolean, default=False)
    synced_at = Column(DateTime, default=datetime.now, nullable=False)

    connection = relationship("TableauConnection", back_populates="assets")
    datasources = relationship("TableauAssetDatasource", back_populates="asset", cascade="all, delete-orphan")

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "connection_id": self.connection_id,
            "asset_type": self.asset_type,
            "tableau_id": self.tableau_id,
            "name": self.name,
            "project_name": self.project_name,
            "description": self.description,
            "owner_name": self.owner_name,
            "thumbnail_url": self.thumbnail_url,
            "content_url": self.content_url,
            "is_deleted": self.is_deleted,
            "synced_at": self.synced_at.strftime("%Y-%m-%d %H:%M:%S") if self.synced_at else None,
        }


class TableauAssetDatasource(Base):
    """Tableau 资产的数据源关联表"""
    __tablename__ = "tableau_asset_datasources"

    id = Column(Integer, primary_key=True, autoincrement=True)
    asset_id = Column(Integer, ForeignKey("tableau_assets.id", ondelete="CASCADE"), nullable=False)
    datasource_name = Column(String(256), nullable=False)
    datasource_type = Column(String(64), nullable=True)

    asset = relationship("TableauAsset", back_populates="datasources")

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "asset_id": self.asset_id,
            "datasource_name": self.datasource_name,
            "datasource_type": self.datasource_type,
        }


class TableauDatabase:
    """Tableau 数据库管理 - 单例模式"""

    _instance = None

    def __new__(cls, db_path: str = None):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            if db_path is None:
                db_path = "/Users/zhangxingchen/Documents/Claude code projects/mulan-bi-platform/data/tableau.db"
            cls._instance._init_db(db_path)
        return cls._instance

    def _init_db(self, db_path: str):
        """初始化数据库"""
        import os
        os.makedirs(os.path.dirname(db_path), exist_ok=True)
        self.engine = create_engine(f"sqlite:///{db_path}", echo=False)
        Base.metadata.create_all(self.engine)
        Session = sessionmaker(bind=self.engine)
        self.session = Session()

    # --- Connection CRUD ---

    def create_connection(self, name: str, server_url: str, site: str,
                          token_name: str, token_encrypted: str,
                          owner_id: int, api_version: str = "3.21") -> TableauConnection:
        conn = TableauConnection(
            name=name,
            server_url=server_url,
            site=site,
            api_version=api_version,
            token_name=token_name,
            token_encrypted=token_encrypted,
            owner_id=owner_id,
        )
        self.session.add(conn)
        self.session.commit()
        return conn

    def get_connection(self, conn_id: int) -> Optional[TableauConnection]:
        return self.session.query(TableauConnection).filter(TableauConnection.id == conn_id).first()

    def get_all_connections(self, owner_id: int = None, include_inactive: bool = False) -> List[TableauConnection]:
        query = self.session.query(TableauConnection)
        if owner_id is not None:
            query = query.filter(TableauConnection.owner_id == owner_id)
        if not include_inactive:
            query = query.filter(TableauConnection.is_active == True)
        return query.order_by(TableauConnection.created_at.desc()).all()

    def update_connection(self, conn_id: int, **kwargs) -> bool:
        conn = self.get_connection(conn_id)
        if not conn:
            return False
        for key, value in kwargs.items():
            if hasattr(conn, key) and value is not None:
                setattr(conn, key, value)
        conn.updated_at = datetime.now()
        self.session.commit()
        return True

    def delete_connection(self, conn_id: int) -> bool:
        conn = self.get_connection(conn_id)
        if not conn:
            return False
        self.session.delete(conn)
        self.session.commit()
        return True

    def update_last_sync(self, conn_id: int) -> bool:
        conn = self.get_connection(conn_id)
        if not conn:
            return False
        conn.last_sync_at = datetime.now()
        self.session.commit()
        return True

    # --- Asset CRUD ---

    def upsert_asset(self, connection_id: int, asset_type: str, tableau_id: str,
                     name: str, **kwargs) -> TableauAsset:
        """Upsert 资产，基于 connection_id + tableau_id 唯一键"""
        existing = self.session.query(TableauAsset).filter(
            TableauAsset.connection_id == connection_id,
            TableauAsset.tableau_id == tableau_id
        ).first()

        if existing:
            existing.name = name
            for key, value in kwargs.items():
                if hasattr(existing, key) and value is not None:
                    setattr(existing, key, value)
            existing.synced_at = datetime.now()
            existing.is_deleted = False
            self.session.commit()
            return existing
        else:
            asset = TableauAsset(
                connection_id=connection_id,
                asset_type=asset_type,
                tableau_id=tableau_id,
                name=name,
                **kwargs
            )
            self.session.add(asset)
            self.session.commit()
            return asset

    def mark_assets_deleted(self, connection_id: int, valid_tableau_ids: List[str]) -> int:
        """将不在 valid_tableau_ids 中的资产标记为已删除（软删除）"""
        if not valid_tableau_ids:
            return 0
        from sqlalchemy import not_
        query = self.session.query(TableauAsset).filter(
            TableauAsset.connection_id == connection_id,
            TableauAsset.is_deleted == False,
            not_(TableauAsset.tableau_id.in_(valid_tableau_ids))
        )
        count = query.update({TableauAsset.is_deleted: True})
        self.session.commit()
        return count

    def get_assets(self, connection_id: int, asset_type: str = None,
                   include_deleted: bool = False, page: int = 1, page_size: int = 50) -> tuple:
        """分页获取资产"""
        query = self.session.query(TableauAsset).filter(TableauAsset.connection_id == connection_id)
        if not include_deleted:
            query = query.filter(TableauAsset.is_deleted == False)
        if asset_type:
            query = query.filter(TableauAsset.asset_type == asset_type)

        total = query.count()
        assets = query.order_by(TableauAsset.synced_at.desc()).offset((page - 1) * page_size).limit(page_size).all()
        return assets, total

    def get_asset(self, asset_id: int) -> Optional[TableauAsset]:
        return self.session.query(TableauAsset).filter(TableauAsset.id == asset_id).first()

    def search_assets(self, connection_id: int = None, query: str = None,
                      asset_type: str = None, page: int = 1, page_size: int = 50) -> tuple:
        """搜索资产"""
        from sqlalchemy import or_
        q = self.session.query(TableauAsset).filter(TableauAsset.is_deleted == False)
        if connection_id:
            q = q.filter(TableauAsset.connection_id == connection_id)
        if asset_type:
            q = q.filter(TableauAsset.asset_type == asset_type)
        if query:
            q = q.filter(or_(
                TableauAsset.name.ilike(f"%{query}%"),
                TableauAsset.project_name.ilike(f"%{query}%"),
                TableauAsset.owner_name.ilike(f"%{query}%"),
            ))
        total = q.count()
        assets = q.order_by(TableauAsset.synced_at.desc()).offset((page - 1) * page_size).limit(page_size).all()
        return assets, total

    def get_project_tree(self, connection_id: int) -> List[Dict[str, Any]]:
        """获取项目树结构"""
        from sqlalchemy import func
        results = self.session.query(
            TableauAsset.project_name,
            TableauAsset.asset_type,
            func.count(TableauAsset.id).label("count")
        ).filter(
            TableauAsset.connection_id == connection_id,
            TableauAsset.is_deleted == False,
            TableauAsset.project_name != None
        ).group_by(TableauAsset.project_name, TableauAsset.asset_type).all()

        project_map = {}
        for project_name, asset_type, count in results:
            if project_name not in project_map:
                project_map[project_name] = {"name": project_name, "children": {}}
            if asset_type not in project_map[project_name]["children"]:
                project_map[project_name]["children"][asset_type] = {"type": asset_type, "count": 0}
            project_map[project_name]["children"][asset_type]["count"] += count

        return list(project_map.values())

    def add_asset_datasource(self, asset_id: int, datasource_name: str, datasource_type: str = None) -> TableauAssetDatasource:
        ds = TableauAssetDatasource(
            asset_id=asset_id,
            datasource_name=datasource_name,
            datasource_type=datasource_type
        )
        self.session.add(ds)
        self.session.commit()
        return ds

    def get_asset_datasources(self, asset_id: int) -> List[TableauAssetDatasource]:
        return self.session.query(TableauAssetDatasource).filter(TableauAssetDatasource.asset_id == asset_id).all()

    def close(self):
        self.session.close()

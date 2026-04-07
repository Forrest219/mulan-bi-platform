"""Tableau Connection & Asset 数据模型"""
from typing import Optional, List, Dict, Any

from sqlalchemy import Column, Integer, String, DateTime, Boolean, Text, Float, ForeignKey, UniqueConstraint, Index
from sqlalchemy.orm import relationship
from app.core.database import Base, JSONB, sa_func, sa_text # 导入中央配置的 Base, JSONB, func, text

class TableauConnection(Base):
    """Tableau 连接表"""
    __tablename__ = "tableau_connections" # 保持现有前缀

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(128), nullable=False)
    server_url = Column(String(512), nullable=False)
    site = Column(String(128), nullable=False)
    api_version = Column(String(16), default="3.21", server_default=sa_text("'3.21'"))
    connection_type = Column(String(16), default="mcp", nullable=False, server_default=sa_text("'mcp'"))  # 'mcp' or 'tsc'
    token_name = Column(String(256), nullable=False)
    token_encrypted = Column(String(512), nullable=False) # 密码加密后长度可能变长，使用 String(512)
    owner_id = Column(Integer, nullable=False)
    is_active = Column(Boolean, default=True, server_default=sa_text('true')) # Boolean 默认值
    # 自动同步设置
    auto_sync_enabled = Column(Boolean, default=False, server_default=sa_text('false')) # Boolean 默认值
    sync_interval_hours = Column(Integer, default=24, server_default=sa_func.cast(24, Integer()))
    # 连接健康状态
    last_test_at = Column(DateTime, nullable=True)
    last_test_success = Column(Boolean, nullable=True)
    last_test_message = Column(Text, nullable=True)
    # 同步状态
    last_sync_at = Column(DateTime, nullable=True)
    last_sync_duration_sec = Column(Integer, nullable=True)
    sync_status = Column(String(16), default="idle", server_default=sa_text("'idle'"))  # idle / running / failed
    # MCP V2 直连配置（Spec 13 §9.1）
    mcp_direct_enabled = Column(Boolean, default=False, server_default=sa_text('false'))
    mcp_server_url = Column(String(512), nullable=True)
    created_at = Column(DateTime, nullable=False, server_default=sa_func.now()) # DateTime 默认值
    updated_at = Column(DateTime, server_default=sa_func.now(), onupdate=sa_func.now()) # DateTime 默认值和更新

    assets = relationship("TableauAsset", back_populates="connection", cascade="all, delete-orphan")

    def to_dict(self) -> Dict[str, Any]:
        next_sync_at = None
        if self.auto_sync_enabled:
            from datetime import timedelta # 局部导入，避免循环依赖
            if self.last_sync_at:
                next_dt = self.last_sync_at + timedelta(hours=self.sync_interval_hours or 24)
                next_sync_at = next_dt.strftime("%Y-%m-%d %H:%M:%S")
            else:
                next_sync_at = "即将执行"

        return {
            "id": self.id,
            "name": self.name,
            "server_url": self.server_url,
            "site": self.site,
            "api_version": self.api_version,
            "connection_type": self.connection_type,
            "token_name": self.token_name,
            "owner_id": self.owner_id,
            "is_active": self.is_active,
            "auto_sync_enabled": self.auto_sync_enabled,
            "sync_interval_hours": self.sync_interval_hours,
            "last_test_at": self.last_test_at.strftime("%Y-%m-%d %H:%M:%S") if self.last_test_at else None,
            "last_test_success": self.last_test_success,
            "last_test_message": self.last_test_message,
            "last_sync_at": self.last_sync_at.strftime("%Y-%m-%d %H:%M:%S") if self.last_sync_at else None,
            "last_sync_duration_sec": self.last_sync_duration_sec,
            "sync_status": self.sync_status or "idle",
            "mcp_direct_enabled": self.mcp_direct_enabled or False,
            "mcp_server_url": self.mcp_server_url,
            "next_sync_at": next_sync_at,
            "created_at": self.created_at.strftime("%Y-%m-%d %H:%M:%S") if self.created_at else None,
            "updated_at": self.updated_at.strftime("%Y-%m-%d %H:%M:%S") if self.updated_at else None,
        }


class TableauAsset(Base):
    """Tableau 资产表（Workbooks, Views, Dashboards, DataSources）"""
    __tablename__ = "tableau_assets" # 保持现有前缀
    __table_args__ = (
        UniqueConstraint("connection_id", "tableau_id", name="uq_asset_conn_tid"),
        Index("ix_asset_conn_deleted_type", "connection_id", "is_deleted", "asset_type"),
        Index("ix_asset_conn_parent", "connection_id", "parent_workbook_id"),
    )

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
    raw_metadata = Column(JSONB, nullable=True) # 改为 JSONB
    is_deleted = Column(Boolean, default=False, server_default=sa_text('false')) # Boolean 默认值
    synced_at = Column(DateTime, nullable=False, server_default=sa_func.now()) # DateTime 默认值
    # Phase 1 AI 摘要
    ai_summary = Column(Text, nullable=True)
    ai_summary_generated_at = Column(DateTime, nullable=True)
    ai_summary_error = Column(Text, nullable=True)
    # Phase 2a: 资产层级
    parent_workbook_id = Column(String(256), nullable=True)
    parent_workbook_name = Column(String(256), nullable=True)
    # Phase 2a: 扩展元数据
    tags = Column(JSONB, nullable=True)  # JSON 数组, 改为 JSONB
    sheet_type = Column(String(32), nullable=True)
    created_on_server = Column(DateTime, nullable=True)
    updated_on_server = Column(DateTime, nullable=True)
    view_count = Column(Integer, nullable=True)
    # Phase 2a: 深度 AI 解读
    ai_explain = Column(Text, nullable=True)
    ai_explain_at = Column(DateTime, nullable=True)
    # Phase 2b: 健康度
    health_score = Column(Float, nullable=True)
    health_details = Column(JSONB, nullable=True)  # JSON, 改为 JSONB
    # Phase 2b: 数据源扩展
    field_count = Column(Integer, nullable=True)
    is_certified = Column(Boolean, nullable=True)

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
            "ai_summary": self.ai_summary,
            "ai_summary_generated_at": self.ai_summary_generated_at.strftime("%Y-%m-%d %H:%M:%S") if self.ai_summary_generated_at else None,
            "parent_workbook_id": self.parent_workbook_id,
            "parent_workbook_name": self.parent_workbook_name,
            "tags": self.tags, # JSONB 字段直接是 Python 对象
            "sheet_type": self.sheet_type,
            "created_on_server": self.created_on_server.strftime("%Y-%m-%d %H:%M:%S") if self.created_on_server else None,
            "updated_on_server": self.updated_on_server.strftime("%Y-%m-%d %H:%M:%S") if self.updated_on_server else None,
            "view_count": self.view_count,
            "ai_explain": self.ai_explain,
            "ai_explain_at": self.ai_explain_at.strftime("%Y-%m-%d %H:%M:%S") if self.ai_explain_at else None,
            "health_score": self.health_score,
            "field_count": self.field_count,
            "is_certified": self.is_certified,
        }


class TableauAssetDatasource(Base):
    """Tableau 资产的数据源关联表"""
    __tablename__ = "tableau_asset_datasources" # 保持现有前缀
    __table_args__ = (
        UniqueConstraint("asset_id", "datasource_name", name="uq_asset_ds_name"),
    )

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


class TableauSyncLog(Base):
    """同步日志表"""
    __tablename__ = "tableau_sync_logs" # 保持现有前缀
    __table_args__ = (
        Index("ix_synclog_conn_started", "connection_id", "started_at"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    connection_id = Column(Integer, ForeignKey("tableau_connections.id", ondelete="CASCADE"), nullable=False)
    trigger_type = Column(String(16), nullable=False)  # 'manual' | 'scheduled'
    started_at = Column(DateTime, nullable=False, server_default=sa_func.now()) # DateTime 默认值
    finished_at = Column(DateTime, nullable=True)
    status = Column(String(16), nullable=False, default="running", server_default=sa_text("'running'"))  # running / success / partial / failed
    workbooks_synced = Column(Integer, default=0, server_default=sa_func.cast(0, Integer()))
    views_synced = Column(Integer, default=0, server_default=sa_func.cast(0, Integer()))
    dashboards_synced = Column(Integer, default=0, server_default=sa_func.cast(0, Integer()))
    datasources_synced = Column(Integer, default=0, server_default=sa_func.cast(0, Integer()))
    assets_deleted = Column(Integer, default=0, server_default=sa_func.cast(0, Integer()))
    error_message = Column(Text, nullable=True)
    details = Column(JSONB, nullable=True)  # JSON, 改为 JSONB

    connection = relationship("TableauConnection")

    def to_dict(self) -> Dict[str, Any]:
        duration = None
        if self.started_at and self.finished_at:
            duration = int((self.finished_at - self.started_at).total_seconds())
        return {
            "id": self.id,
            "connection_id": self.connection_id,
            "trigger_type": self.trigger_type,
            "started_at": self.started_at.strftime("%Y-%m-%d %H:%M:%S") if self.started_at else None,
            "finished_at": self.finished_at.strftime("%Y-%m-%d %H:%M:%S") if self.finished_at else None,
            "status": self.status,
            "workbooks_synced": self.workbooks_synced,
            "views_synced": self.views_synced,
            "dashboards_synced": self.dashboards_synced,
            "datasources_synced": self.datasources_synced,
            "assets_deleted": self.assets_deleted,
            "error_message": self.error_message,
            "duration_sec": duration,
        }


class TableauDatasourceField(Base):
    """数据源字段缓存表"""
    __tablename__ = "tableau_datasource_fields" # 保持现有前缀
    __table_args__ = (
        Index("ix_dsfield_asset_luid", "asset_id", "datasource_luid"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    asset_id = Column(Integer, ForeignKey("tableau_assets.id", ondelete="CASCADE"), nullable=False)
    datasource_luid = Column(String(256), nullable=False)
    field_name = Column(String(256), nullable=False)
    field_caption = Column(String(256), nullable=True)
    data_type = Column(String(64), nullable=True)
    role = Column(String(32), nullable=True)  # dimension / measure
    description = Column(Text, nullable=True)
    formula = Column(Text, nullable=True)
    aggregation = Column(String(32), nullable=True)
    is_calculated = Column(Boolean, default=False, server_default=sa_text('false')) # Boolean 默认值
    metadata_json = Column(JSONB, nullable=True) # 改为 JSONB
    fetched_at = Column(DateTime, nullable=False, server_default=sa_func.now()) # DateTime 默认值
    # AI 标注
    ai_caption = Column(String(256), nullable=True)
    ai_description = Column(Text, nullable=True)
    ai_role = Column(String(32), nullable=True)
    ai_confidence = Column(Float, nullable=True)
    ai_annotated_at = Column(DateTime, nullable=True)

    asset = relationship("TableauAsset")

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "asset_id": self.asset_id,
            "datasource_luid": self.datasource_luid,
            "field_name": self.field_name,
            "field_caption": self.field_caption,
            "data_type": self.data_type,
            "role": self.role,
            "description": self.description,
            "formula": self.formula,
            "aggregation": self.aggregation,
            "is_calculated": self.is_calculated,
            "fetched_at": self.fetched_at.strftime("%Y-%m-%d %H:%M:%S") if self.fetched_at else None,
            "ai_caption": self.ai_caption,
            "ai_description": self.ai_description,
            "ai_role": self.ai_role,
            "ai_confidence": self.ai_confidence,
            "ai_annotated_at": self.ai_annotated_at.strftime("%Y-%m-%d %H:%M:%S") if self.ai_annotated_at else None,
        }


# 从中央配置导入 SessionLocal
from app.core.database import SessionLocal
from sqlalchemy.orm import Session

class TableauDatabase:
    """
    Tableau 数据库管理类。

    Session 管理规范（Spec 07 §7.3 P1）：
    - API 层：传入外部注入的 db session（由 FastAPI Depends(get_db) 管理），
      以确保同一请求内所有操作共享同一事务上下文。
    - Celery 任务层：使用 get_db_context() 上下文管理器创建 session，
      禁止自行 new Session 或调用 expire_all()。
    - 兼容模式（向后兼容）：不传 session 时，使用 SessionLocal()（每次创建新 session）。
    """

    def __init__(self, db_path: str = None, session: Session = None):
        """
        Args:
            db_path: 已废弃，仅保留签名兼容性。
            session: 可选。外部注入的 SQLAlchemy Session。
                     若传入，则所有 DB 操作使用此 session（不创建新 session）。
                     若为 None，则创建新的 SessionLocal()（向后兼容模式）。
        """
        self._external_session: Optional[Session] = session

    @property
    def session(self) -> Session:
        """
        返回当前 DB session。
        - 若外部注入了 session，直接返回（不复用、不 expire_all）。
        - 若无注入，每次创建新的 SessionLocal()（向后兼容模式）。
        """
        if self._external_session is not None:
            return self._external_session
        # 向后兼容：每次创建新 session（不建议在新代码中使用）
        s = SessionLocal()
        return s

    # close 方法不再需要
    # def close(self):
    #     self.session.remove()

    # --- Connection CRUD ---

    def create_connection(self, name: str, server_url: str, site: str,
                          token_name: str, token_encrypted: str,
                          owner_id: int, api_version: str = "3.21",
                          connection_type: str = "mcp") -> TableauConnection:
        conn = TableauConnection(
            name=name,
            server_url=server_url,
            site=site,
            api_version=api_version,
            connection_type=connection_type,
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
        # updated_at 会由 onupdate 自动更新
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
        conn.last_sync_at = sa_func.now() # 使用 server_default
        self.session.commit()
        return True

    def update_connection_health(self, conn_id: int, success: bool, message: str) -> bool:
        """更新连接健康状态（测试结果）"""
        conn = self.get_connection(conn_id)
        if not conn:
            return False
        conn.last_test_at = sa_func.now() # 使用 server_default
        conn.last_test_success = success
        conn.last_test_message = message
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
            existing.synced_at = sa_func.now() # 使用 server_default
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
        count = query.update({TableauAsset.is_deleted: True}, synchronize_session=False) # synchronize_session=False 避免加载所有对象
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
                      asset_type: str = None, page: int = 1, page_size: int = 50,
                      owner_id: int = None) -> tuple:
        """
        搜索资产。

        安全约束（Spec 07 §3.3.2 P0 IDOR 修复）：
        - 若传入 owner_id（非 None），自动限定为该用户创建的连接下的资产。
        - 此过滤与 connection_id 过滤为 AND 关系，共同生效。
        """
        from sqlalchemy import or_
        q = self.session.query(TableauAsset).filter(TableauAsset.is_deleted == False)
        if connection_id:
            q = q.filter(TableauAsset.connection_id == connection_id)
        if owner_id is not None:
            # 强制多租户隔离：仅查询该 owner 创建的连接下的资产
            q = q.filter(
                TableauAsset.connection_id.in_(
                    self.session.query(TableauConnection.id).filter(
                        TableauConnection.owner_id == owner_id
                    )
                )
            )
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
        """Upsert 资产数据源关联，避免重复插入"""
        existing = self.session.query(TableauAssetDatasource).filter(
            TableauAssetDatasource.asset_id == asset_id,
            TableauAssetDatasource.datasource_name == datasource_name
        ).first()
        if existing:
            if datasource_type is not None:
                existing.datasource_type = datasource_type
            self.session.commit()
            return existing
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

    def update_asset_summary(self, asset_id: int, summary: str) -> bool:
        """更新资产 AI 摘要"""
        asset = self.get_asset(asset_id)
        if not asset:
            return False
        asset.ai_summary = summary
        asset.ai_summary_generated_at = sa_func.now() # 使用 server_default
        asset.ai_summary_error = None
        self.session.commit()
        return True

    def update_asset_error(self, asset_id: int, error: str) -> bool:
        """记录资产 AI 生成错误"""
        asset = self.get_asset(asset_id)
        if not asset:
            return False
        asset.ai_summary_error = error
        self.session.commit()
        return True

    def update_asset_explain(self, asset_id: int, explain: str) -> bool:
        """更新资产深度 AI 解读"""
        asset = self.get_asset(asset_id)
        if not asset:
            return False
        asset.ai_explain = explain
        asset.ai_explain_at = sa_func.now() # 使用 server_default
        self.session.commit()
        return True

    def update_asset_health(self, asset_id: int, score: float, details_json: Dict[str, Any]) -> bool: # details_json 现在是 dict
        """更新资产健康评分"""
        asset = self.get_asset(asset_id)
        if not asset:
            return False
        asset.health_score = score
        asset.health_details = details_json
        self.session.commit()
        return True

    def get_children_assets(self, parent_tableau_id: str, connection_id: int) -> List[TableauAsset]:
        """获取 workbook 下属的 view/dashboard"""
        return self.session.query(TableauAsset).filter(
            TableauAsset.connection_id == connection_id,
            TableauAsset.parent_workbook_id == parent_tableau_id,
            TableauAsset.is_deleted == False,
        ).all()

    def get_parent_asset(self, asset_id: int) -> Optional[TableauAsset]:
        """获取 view/dashboard 的父 workbook"""
        asset = self.get_asset(asset_id)
        if not asset or not asset.parent_workbook_id:
            return None
        return self.session.query(TableauAsset).filter(
            TableauAsset.connection_id == asset.connection_id,
            TableauAsset.tableau_id == asset.parent_workbook_id,
            TableauAsset.is_deleted == False,
        ).first()

    # --- Sync Log ---

    def create_sync_log(self, connection_id: int, trigger_type: str = "manual") -> TableauSyncLog:
        """创建同步日志（同步开始时调用）"""
        log = TableauSyncLog(
            connection_id=connection_id,
            trigger_type=trigger_type,
            started_at=sa_func.now(), # 使用 server_default
            status="running",
        )
        self.session.add(log)
        self.session.commit()
        return log

    def finish_sync_log(self, log_id: int, status: str, **counts) -> bool:
        """完成同步日志（同步结束时调用）"""
        log = self.session.query(TableauSyncLog).filter(TableauSyncLog.id == log_id).first()
        if not log:
            return False
        log.finished_at = sa_func.now() # 使用 server_default
        log.status = status
        for key, value in counts.items():
            if hasattr(log, key) and value is not None:
                setattr(log, key, value)
        self.session.commit()
        return True

    def get_sync_logs(self, connection_id: int, page: int = 1, page_size: int = 20) -> tuple:
        """分页获取同步日志"""
        query = self.session.query(TableauSyncLog).filter(
            TableauSyncLog.connection_id == connection_id
        )
        total = query.count()
        logs = query.order_by(TableauSyncLog.started_at.desc()).offset(
            (page - 1) * page_size
        ).limit(page_size).all()
        return logs, total

    def get_sync_log(self, log_id: int) -> Optional[TableauSyncLog]:
        return self.session.query(TableauSyncLog).filter(TableauSyncLog.id == log_id).first()

    # --- Datasource Fields ---

    def upsert_datasource_fields(self, asset_id: int, datasource_luid: str,
                                  fields: List[Dict[str, Any]]) -> int:
        """批量 upsert 数据源字段（先清除旧数据再插入）"""
        self.session.query(TableauDatasourceField).filter(
            TableauDatasourceField.asset_id == asset_id,
            TableauDatasourceField.datasource_luid == datasource_luid,
        ).delete(synchronize_session=False) # synchronize_session=False 避免加载所有对象

        now = sa_func.now() # 使用 server_default
        for f in fields:
            field = TableauDatasourceField(
                asset_id=asset_id,
                datasource_luid=datasource_luid,
                field_name=f.get("field_name", ""),
                field_caption=f.get("field_caption"),
                data_type=f.get("data_type"),
                role=f.get("role"),
                description=f.get("description"),
                formula=f.get("formula"),
                aggregation=f.get("aggregation"),
                is_calculated=f.get("is_calculated", False),
                metadata_json=f.get("metadata_json"),
                fetched_at=now,
            )
            self.session.add(field)
        self.session.commit()
        return len(fields)

    def get_datasource_fields(self, asset_id: int) -> List[TableauDatasourceField]:
        """获取数据源字段列表"""
        return self.session.query(TableauDatasourceField).filter(
            TableauDatasourceField.asset_id == asset_id
        ).order_by(TableauDatasourceField.role, TableauDatasourceField.field_name).all()

    def update_field_annotation(self, field_id: int, ai_caption: str = None,
                                 ai_description: str = None, ai_role: str = None,
                                 ai_confidence: float = None) -> bool:
        """更新字段 AI 标注"""
        field = self.session.query(TableauDatasourceField).filter(
            TableauDatasourceField.id == field_id
        ).first()
        if not field:
            return False
        if ai_caption is not None:
            field.ai_caption = ai_caption
        if ai_description is not None:
            field.ai_description = ai_description
        if ai_role is not None:
            field.ai_role = ai_role
        if ai_confidence is not None:
            field.ai_confidence = ai_confidence
        field.ai_annotated_at = sa_func.now() # 使用 server_default
        self.session.commit()
        return True

    # --- Connection sync status ---

    def set_sync_status(self, conn_id: int, status: str, duration_sec: int = None) -> bool:
        """更新连接同步状态"""
        conn = self.get_connection(conn_id)
        if not conn:
            return False
        conn.sync_status = status
        if duration_sec is not None:
            conn.last_sync_duration_sec = duration_sec
        self.session.commit()
        return True


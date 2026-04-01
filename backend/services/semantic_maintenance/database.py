"""语义维护模块 - 数据库管理层"""
import json
import logging
import sqlite3
import threading
from datetime import datetime
from typing import Optional, List, Dict, Any

from sqlalchemy import create_engine
from sqlalchemy.orm import scoped_session

from .models import (
    Base,
    TableauDatasourceSemantics,
    TableauDatasourceSemanticVersion,
    TableauFieldSemantics,
    TableauFieldSemanticVersion,
    TableauPublishLog,
    SemanticStatus,
)

logger = logging.getLogger(__name__)


class SemanticMaintenanceDatabase:
    """语义维护数据库管理 - 单例模式（线程安全）"""

    _instance = None
    _lock = threading.Lock()

    def __new__(cls, db_path: str = None):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    if db_path is None:
                        import os as _os
                        db_path = _os.path.join(
                            _os.path.dirname(_os.path.abspath(__file__)),
                            "..", "..", "data", "semantic_maintenance.db"
                        )
                    cls._instance._init_db(db_path)
        return cls._instance

    def _init_db(self, db_path: str):
        """初始化数据库"""
        import os as _os
        _os.makedirs(_os.path.dirname(db_path), exist_ok=True)
        self.engine = create_engine(f"sqlite:///{db_path}", echo=False, pool_pre_ping=True)
        Base.metadata.create_all(self.engine)
        self._ensure_columns()
        Session = sessionmaker(bind=self.engine, expire_on_commit=False)
        self._scoped_session = scoped_session(Session)

    def _ensure_columns(self):
        """SQLite 迁移：兼容已有库，忽略新增列/表的错误"""
        raw_path = str(self.engine.url).replace("sqlite:///", "")
        conn = sqlite3.connect(raw_path)
        cursor = conn.cursor()

        # 新增索引（IF NOT EXISTS 兼容已有库）
        index_stmts = [
            "CREATE UNIQUE INDEX IF NOT EXISTS uq_ds_semantic_conn_ds ON tableau_datasource_semantics(connection_id, tableau_datasource_id)",
            "CREATE INDEX IF NOT EXISTS ix_ds_semantic_status ON tableau_datasource_semantics(status)",
            "CREATE INDEX IF NOT EXISTS ix_ds_semantic_conn_id ON tableau_datasource_semantics(connection_id)",
            "CREATE INDEX IF NOT EXISTS ix_ds_ver_sem_id ON tableau_datasource_semantic_versions(datasource_semantic_id)",
            "CREATE UNIQUE INDEX IF NOT EXISTS uq_field_semantic_conn_fid ON tableau_field_semantics(connection_id, tableau_field_id)",
            "CREATE INDEX IF NOT EXISTS ix_field_semantic_status ON tableau_field_semantics(status)",
            "CREATE INDEX IF NOT EXISTS ix_field_semantic_conn_id ON tableau_field_semantics(connection_id)",
            "CREATE INDEX IF NOT EXISTS ix_field_semantic_reg_id ON tableau_field_semantics(field_registry_id)",
            "CREATE INDEX IF NOT EXISTS ix_field_ver_sem_id ON tableau_field_semantic_versions(field_semantic_id)",
            "CREATE INDEX IF NOT EXISTS ix_publish_log_conn_status ON tableau_publish_log(connection_id, status)",
            "CREATE INDEX IF NOT EXISTS ix_publish_log_object ON tableau_publish_log(object_type, object_id)",
        ]
        for stmt in index_stmts:
            try:
                cursor.execute(stmt)
            except Exception:
                pass

        conn.commit()
        conn.close()

    @property
    def session(self):
        return self._scoped_session()

    def close(self):
        self._scoped_session.remove()

    # ============================================================
    # 数据源语义 CRUD
    # ============================================================

    def upsert_datasource_semantics(
        self,
        connection_id: int,
        tableau_datasource_id: str,
        user_id: int = None,
        **fields
    ) -> TableauDatasourceSemantics:
        """Upsert 数据源语义，基于 connection_id + tableau_datasource_id"""
        existing = self.session.query(TableauDatasourceSemantics).filter(
            TableauDatasourceSemantics.connection_id == connection_id,
            TableauDatasourceSemantics.tableau_datasource_id == tableau_datasource_id,
        ).first()

        if existing:
            for key, value in fields.items():
                if hasattr(existing, key) and value is not None:
                    setattr(existing, key, value)
            existing.updated_at = datetime.now()
            if user_id:
                existing.updated_by = user_id
            self.session.commit()
            return existing
        else:
            obj = TableauDatasourceSemantics(
                connection_id=connection_id,
                tableau_datasource_id=tableau_datasource_id,
                created_by=user_id,
                updated_by=user_id,
                **fields
            )
            self.session.add(obj)
            self.session.commit()
            return obj

    def get_datasource_semantics(
        self, connection_id: int, tableau_datasource_id: str
    ) -> Optional[TableauDatasourceSemantics]:
        return self.session.query(TableauDatasourceSemantics).filter(
            TableauDatasourceSemantics.connection_id == connection_id,
            TableauDatasourceSemantics.tableau_datasource_id == tableau_datasource_id,
        ).first()

    def get_datasource_semantics_by_id(self, ds_id: int) -> Optional[TableauDatasourceSemantics]:
        return self.session.query(TableauDatasourceSemantics).filter(
            TableauDatasourceSemantics.id == ds_id
        ).first()

    def list_datasource_semantics(
        self,
        connection_id: int,
        status: str = None,
        page: int = 1,
        page_size: int = 50,
    ) -> tuple:
        query = self.session.query(TableauDatasourceSemantics).filter(
            TableauDatasourceSemantics.connection_id == connection_id
        )
        if status:
            query = query.filter(TableauDatasourceSemantics.status == status)
        total = query.count()
        items = query.order_by(
            TableauDatasourceSemantics.updated_at.desc()
        ).offset((page - 1) * page_size).limit(page_size).all()
        return items, total

    def update_datasource_semantics(
        self, ds_id: int, user_id: int = None,
        change_reason: str = None, **fields
    ) -> bool:
        """更新数据源语义，自动创建版本快照"""
        obj = self.get_datasource_semantics_by_id(ds_id)
        if not obj:
            return False
        self._create_datasource_version_snapshot(obj, user_id, change_reason or "manual_update")
        for key, value in fields.items():
            if hasattr(obj, key) and value is not None:
                setattr(obj, key, value)
        obj.updated_at = datetime.now()
        if user_id:
            obj.updated_by = user_id
        self.session.commit()
        return True

    def _create_datasource_version_snapshot(
        self, ds: TableauDatasourceSemantics,
        user_id: int = None, change_reason: str = None
    ):
        """创建数据源语义历史版本快照"""
        snapshot_data = {
            "semantic_name": ds.semantic_name,
            "semantic_name_zh": ds.semantic_name_zh,
            "semantic_description": ds.semantic_description,
            "business_definition": ds.business_definition,
            "usage_scenarios": ds.usage_scenarios,
            "owner": ds.owner,
            "steward": ds.steward,
            "sensitivity_level": ds.sensitivity_level,
            "tags_json": ds.tags_json,
            "status": ds.status,
            "source": ds.source,
        }
        version = TableauDatasourceSemanticVersion(
            datasource_semantic_id=ds.id,
            version=ds.current_version or 1,
            snapshot_json=json.dumps(snapshot_data, ensure_ascii=False),
            changed_by=user_id,
            change_reason=change_reason,
        )
        self.session.add(version)
        ds.current_version = (ds.current_version or 1) + 1

    def get_datasource_semantic_history(self, ds_id: int) -> List[TableauDatasourceSemanticVersion]:
        """获取数据源语义版本历史"""
        return self.session.query(TableauDatasourceSemanticVersion).filter(
            TableauDatasourceSemanticVersion.datasource_semantic_id == ds_id
        ).order_by(TableauDatasourceSemanticVersion.version.desc()).all()

    def rollback_datasource_semantic(
        self, ds_id: int, version_id: int, user_id: int = None
    ) -> tuple:
        """回滚数据源语义到指定版本"""
        target = self.session.query(TableauDatasourceSemanticVersion).filter(
            TableauDatasourceSemanticVersion.id == version_id,
            TableauDatasourceSemanticVersion.datasource_semantic_id == ds_id,
        ).first()
        if not target:
            return False, "版本记录不存在"

        ds = self.get_datasource_semantics_by_id(ds_id)
        if not ds:
            return False, "数据源语义记录不存在"

        # 保存当前版本快照
        self._create_datasource_version_snapshot(ds, user_id, f"rollback_to_v{version_id}")

        try:
            snapshot = json.loads(target.snapshot_json)
        except (json.JSONDecodeError, TypeError):
            return False, "版本快照数据损坏"

        for key, value in snapshot.items():
            if hasattr(ds, key):
                setattr(ds, key, value)

        ds.current_version = (ds.current_version or 1) + 1
        ds.updated_at = datetime.now()
        if user_id:
            ds.updated_by = user_id
        self.session.commit()
        return True, None

    def transition_datasource_status(
        self, ds_id: int, new_status: str, user_id: int = None
    ) -> tuple:
        """状态流转，返回 (success, error_message)"""
        obj = self.get_datasource_semantics_by_id(ds_id)
        if not obj:
            return False, "记录不存在"

        current = obj.status
        allowed = SemanticStatus.TRANSITIONS.get(current, [])
        if new_status not in allowed:
            return False, f"不允许从 {current} 流转到 {new_status}，允许的目标状态：{allowed}"

        obj.status = new_status
        obj.updated_at = datetime.now()
        if user_id:
            obj.updated_by = user_id
        self.session.commit()
        return True, None

    # ============================================================
    # 字段语义 CRUD
    # ============================================================

    def upsert_field_semantics(
        self,
        connection_id: int,
        tableau_field_id: str,
        user_id: int = None,
        create_version: bool = False,
        **fields
    ) -> TableauFieldSemantics:
        """Upsert 字段语义，基于 connection_id + tableau_field_id

        Args:
            create_version: 是否创建历史版本快照（每次 update 时应传 True）
        """
        existing = self.session.query(TableauFieldSemantics).filter(
            TableauFieldSemantics.connection_id == connection_id,
            TableauFieldSemantics.tableau_field_id == tableau_field_id,
        ).first()

        if existing:
            if create_version:
                self._create_field_version_snapshot(existing, user_id, "manual_update")
            for key, value in fields.items():
                if hasattr(existing, key) and value is not None:
                    setattr(existing, key, value)
            existing.updated_at = datetime.now()
            if user_id:
                existing.updated_by = user_id
            self.session.commit()
            return existing
        else:
            obj = TableauFieldSemantics(
                connection_id=connection_id,
                tableau_field_id=tableau_field_id,
                created_by=user_id,
                updated_by=user_id,
                **fields
            )
            self.session.add(obj)
            self.session.commit()
            return obj

    def upsert_field_semantics_by_reg_id(
        self,
        field_registry_id: int,
        connection_id: int,
        tableau_field_id: str,
        user_id: int = None,
        create_version: bool = False,
        **fields
    ) -> TableauFieldSemantics:
        """Upsert 字段语义（按 field_registry_id）"""
        existing = self.session.query(TableauFieldSemantics).filter(
            TableauFieldSemantics.field_registry_id == field_registry_id,
            TableauFieldSemantics.connection_id == connection_id,
        ).first()

        if existing:
            if create_version:
                self._create_field_version_snapshot(existing, user_id, "manual_update")
            for key, value in fields.items():
                if hasattr(existing, key) and value is not None:
                    setattr(existing, key, value)
            existing.tableau_field_id = tableau_field_id  # 同步更新
            existing.updated_at = datetime.now()
            if user_id:
                existing.updated_by = user_id
            self.session.commit()
            return existing
        else:
            obj = TableauFieldSemantics(
                field_registry_id=field_registry_id,
                connection_id=connection_id,
                tableau_field_id=tableau_field_id,
                created_by=user_id,
                updated_by=user_id,
                **fields
            )
            self.session.add(obj)
            self.session.commit()
            return obj

    def get_field_semantics_by_id(self, field_id: int) -> Optional[TableauFieldSemantics]:
        return self.session.query(TableauFieldSemantics).filter(
            TableauFieldSemantics.id == field_id
        ).first()

    def get_field_semantics_by_reg_id(self, field_registry_id: int) -> Optional[TableauFieldSemantics]:
        return self.session.query(TableauFieldSemantics).filter(
            TableauFieldSemantics.field_registry_id == field_registry_id
        ).first()

    def list_field_semantics(
        self,
        connection_id: int,
        ds_id: int = None,
        status: str = None,
        page: int = 1,
        page_size: int = 50,
    ) -> tuple:
        """ds_id: tableau_datasource_fields.id（即 field_registry_id）"""
        query = self.session.query(TableauFieldSemantics).filter(
            TableauFieldSemantics.connection_id == connection_id
        )
        if ds_id is not None:
            query = query.filter(TableauFieldSemantics.field_registry_id == ds_id)
        if status:
            query = query.filter(TableauFieldSemantics.status == status)
        total = query.count()
        items = query.order_by(
            TableauFieldSemantics.updated_at.desc()
        ).offset((page - 1) * page_size).limit(page_size).all()
        return items, total

    def update_field_semantics(self, field_id: int, user_id: int = None, change_reason: str = None, **fields) -> bool:
        obj = self.get_field_semantics_by_id(field_id)
        if not obj:
            return False
        self._create_field_version_snapshot(obj, user_id, change_reason or "manual_update")
        for key, value in fields.items():
            if hasattr(obj, key) and value is not None:
                setattr(obj, key, value)
        obj.updated_at = datetime.now()
        if user_id:
            obj.updated_by = user_id
        self.session.commit()
        return True

    def transition_field_status(
        self, field_id: int, new_status: str, user_id: int = None
    ) -> tuple:
        """状态流转，返回 (success, error_message)"""
        obj = self.get_field_semantics_by_id(field_id)
        if not obj:
            return False, "记录不存在"

        current = obj.status
        allowed = SemanticStatus.TRANSITIONS.get(current, [])
        if new_status not in allowed:
            return False, f"不允许从 {current} 流转到 {new_status}，允许的目标状态：{allowed}"

        obj.status = new_status
        obj.updated_at = datetime.now()
        if user_id:
            obj.updated_by = user_id
        self.session.commit()
        return True, None

    def _create_field_version_snapshot(
        self, field_semantic: TableauFieldSemantics,
        user_id: int = None,
        change_reason: str = None
    ):
        """创建字段语义历史版本快照"""
        # 序列化当前所有语义字段
        snapshot_data = {
            "semantic_name": field_semantic.semantic_name,
            "semantic_name_zh": field_semantic.semantic_name_zh,
            "semantic_definition": field_semantic.semantic_definition,
            "metric_definition": field_semantic.metric_definition,
            "dimension_definition": field_semantic.dimension_definition,
            "unit": field_semantic.unit,
            "enum_desc_json": field_semantic.enum_desc_json,
            "tags_json": field_semantic.tags_json,
            "synonyms_json": field_semantic.synonyms_json,
            "sensitivity_level": field_semantic.sensitivity_level,
            "is_core_field": field_semantic.is_core_field,
            "ai_confidence": field_semantic.ai_confidence,
            "status": field_semantic.status,
            "source": field_semantic.source,
        }
        version = TableauFieldSemanticVersion(
            field_semantic_id=field_semantic.id,
            version=field_semantic.version,
            snapshot_json=json.dumps(snapshot_data, ensure_ascii=False),
            changed_by=user_id,
            change_reason=change_reason,
        )
        self.session.add(version)
        # 递增版本号
        field_semantic.version = (field_semantic.version or 1) + 1

    def get_field_semantic_history(self, field_semantic_id: int) -> List[TableauFieldSemanticVersion]:
        return self.session.query(TableauFieldSemanticVersion).filter(
            TableauFieldSemanticVersion.field_semantic_id == field_semantic_id
        ).order_by(TableauFieldSemanticVersion.version.desc()).all()

    def rollback_field_semantic(
        self, field_semantic_id: int, version_id: int, user_id: int = None
    ) -> tuple:
        """回滚字段语义到指定版本，返回 (success, error_message)"""
        target_version = self.session.query(TableauFieldSemanticVersion).filter(
            TableauFieldSemanticVersion.id == version_id,
            TableauFieldSemanticVersion.field_semantic_id == field_semantic_id,
        ).first()
        if not target_version:
            return False, "版本记录不存在"

        field = self.get_field_semantics_by_id(field_semantic_id)
        if not field:
            return False, "字段语义记录不存在"

        # 保存当前版本快照
        self._create_field_version_snapshot(field, user_id, f"rollback_to_v{version_id}")

        # 恢复快照
        try:
            snapshot = json.loads(target_version.snapshot_json)
        except (json.JSONDecodeError, TypeError):
            return False, "版本快照数据损坏"

        for key, value in snapshot.items():
            if hasattr(field, key):
                setattr(field, key, value)

        field.version = (field.version or 1) + 1
        field.updated_at = datetime.now()
        if user_id:
            field.updated_by = user_id
        self.session.commit()
        return True, None

    # ============================================================
    # 发布日志 CRUD
    # ============================================================

    def create_publish_log(
        self,
        connection_id: int,
        object_type: str,
        object_id: int,
        operator: int = None,
        tableau_object_id: str = None,
        diff_json: str = None,
        payload_json: str = None,
    ) -> TableauPublishLog:
        """创建发布日志"""
        log = TableauPublishLog(
            connection_id=connection_id,
            object_type=object_type,
            object_id=object_id,
            tableau_object_id=tableau_object_id,
            diff_json=diff_json,
            publish_payload_json=payload_json,
            operator=operator,
        )
        self.session.add(log)
        self.session.commit()
        return log

    def update_publish_log_status(
        self,
        log_id: int,
        status: str,
        response_summary: str = None
    ) -> bool:
        log = self.session.query(TableauPublishLog).filter(
            TableauPublishLog.id == log_id
        ).first()
        if not log:
            return False
        log.status = status
        if response_summary is not None:
            log.response_summary = response_summary
        self.session.commit()
        return True

    def list_publish_logs(
        self,
        connection_id: int,
        object_type: str = None,
        status: str = None,
        page: int = 1,
        page_size: int = 50,
    ) -> tuple:
        query = self.session.query(TableauPublishLog).filter(
            TableauPublishLog.connection_id == connection_id
        )
        if object_type:
            query = query.filter(TableauPublishLog.object_type == object_type)
        if status:
            query = query.filter(TableauPublishLog.status == status)
        total = query.count()
        items = query.order_by(
            TableauPublishLog.created_at.desc()
        ).offset((page - 1) * page_size).limit(page_size).all()
        return items, total

    def get_publish_log(self, log_id: int) -> Optional[TableauPublishLog]:
        return self.session.query(TableauPublishLog).filter(
            TableauPublishLog.id == log_id
        ).first()

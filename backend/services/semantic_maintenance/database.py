"""语义维护模块 - 数据库管理层"""
import logging
from typing import Optional, List, Dict, Any

from app.core.database import SessionLocal
from sqlalchemy.orm import Session

from .models import (
    TableauDatasourceSemantics,
    TableauDatasourceSemanticVersion,
    TableauFieldSemantics,
    TableauFieldSemanticVersion,
    TableauPublishLog,
    SemanticStatus,
)

logger = logging.getLogger(__name__)


class SemanticMaintenanceDatabase:
    """语义维护数据库管理 - 不再是单例，直接使用中央 SessionLocal"""

    def __init__(self, db_path: str = None):
        """db_path 参数不再使用，保留签名以兼容旧代码"""
        pass

    # _ensure_columns 方法是针对 SQLite 迁移的，在 PostgreSQL 环境中由 Alembic 管理，因此移除
    # def _ensure_columns(self):
    #     pass

    @property
    def session(self) -> Session:
        """每次访问获取当前线程的 session，并刷新缓存避免脏读"""
        s = SessionLocal()
        s.expire_all()
        return s

    # close 方法不再需要
    # def close(self):
    #     self.session.remove()

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
        s = self.session
        try:
            existing = s.query(TableauDatasourceSemantics).filter(
                TableauDatasourceSemantics.connection_id == connection_id,
                TableauDatasourceSemantics.tableau_datasource_id == tableau_datasource_id,
            ).first()

            if existing:
                for key, value in fields.items():
                    if hasattr(existing, key) and value is not None:
                        setattr(existing, key, value)
                # updated_at 会由 onupdate 自动更新
                if user_id:
                    existing.updated_by = user_id
                s.commit()
                return existing
            else:
                obj = TableauDatasourceSemantics(
                    connection_id=connection_id,
                    tableau_datasource_id=tableau_datasource_id,
                    created_by=user_id,
                    updated_by=user_id,
                    **fields
                )
                s.add(obj)
                s.commit()
                return obj
        finally:
            s.remove()

    def get_datasource_semantics(
        self, connection_id: int, tableau_datasource_id: str
    ) -> Optional[TableauDatasourceSemantics]:
        s = self.session
        try:
            return s.query(TableauDatasourceSemantics).filter(
                TableauDatasourceSemantics.connection_id == connection_id,
                TableauDatasourceSemantics.tableau_datasource_id == tableau_datasource_id,
            ).first()
        finally:
            s.remove()

    def get_datasource_semantics_by_id(self, ds_id: int) -> Optional[TableauDatasourceSemantics]:
        s = self.session
        try:
            return s.query(TableauDatasourceSemantics).filter(
                TableauDatasourceSemantics.id == ds_id
            ).first()
        finally:
            s.remove()

    def list_datasource_semantics(
        self,
        connection_id: int,
        status: str = None,
        page: int = 1,
        page_size: int = 50,
    ) -> tuple:
        s = self.session
        try:
            query = s.query(TableauDatasourceSemantics).filter(
                TableauDatasourceSemantics.connection_id == connection_id
            )
            if status:
                query = query.filter(TableauDatasourceSemantics.status == status)
            total = query.count()
            items = query.order_by(
                TableauDatasourceSemantics.updated_at.desc()
            ).offset((page - 1) * page_size).limit(page_size).all()
            return items, total
        finally:
            s.remove()

    def update_datasource_semantics(
        self, ds_id: int, user_id: int = None,
        change_reason: str = None, **fields
    ) -> bool:
        """更新数据源语义，自动创建版本快照"""
        s = self.session
        try:
            obj = s.query(TableauDatasourceSemantics).filter(TableauDatasourceSemantics.id == ds_id).first()
            if not obj:
                return False
            self._create_datasource_version_snapshot(obj, user_id, change_reason or "manual_update")
            for key, value in fields.items():
                if hasattr(obj, key) and value is not None:
                    setattr(obj, key, value)
            # updated_at 会由 onupdate 自动更新
            if user_id:
                obj.updated_by = user_id
            s.commit()
            return True
        except Exception:
            s.rollback()
            raise
        finally:
            s.remove()

    def _create_datasource_version_snapshot(
        self, ds: TableauDatasourceSemantics,
        user_id: int = None, change_reason: str = None
    ):
        """创建数据源语义历史版本快照"""
        # JSONB 字段直接是 Python 对象，无需 json.dumps
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
            snapshot_json=snapshot_data, # JSONB 字段直接传入 Python 对象
            changed_by=user_id,
            change_reason=change_reason,
        )
        self.session.add(version)
        ds.current_version = (ds.current_version or 1) + 1

    def get_datasource_semantic_history(self, ds_id: int) -> List[TableauDatasourceSemanticVersion]:
        """获取数据源语义版本历史"""
        s = self.session
        try:
            return s.query(TableauDatasourceSemanticVersion).filter(
                TableauDatasourceSemanticVersion.datasource_semantic_id == ds_id
            ).order_by(TableauDatasourceSemanticVersion.version.desc()).all()
        finally:
            s.remove()

    def rollback_datasource_semantic(
        self, ds_id: int, version_id: int, user_id: int = None
    ) -> tuple:
        """回滚数据源语义到指定版本"""
        s = self.session
        try:
            target = s.query(TableauDatasourceSemanticVersion).filter(
                TableauDatasourceSemanticVersion.id == version_id,
                TableauDatasourceSemanticVersion.datasource_semantic_id == ds_id,
            ).first()
            if not target:
                return False, "版本记录不存在"

            ds = s.query(TableauDatasourceSemantics).filter(TableauDatasourceSemantics.id == ds_id).first()
            if not ds:
                return False, "数据源语义记录不存在"

            # 保存当前版本快照
            self._create_datasource_version_snapshot(ds, user_id, f"rollback_to_v{version_id}")

            # JSONB 字段直接是 Python 对象，无需 json.loads
            snapshot = target.snapshot_json

            for key, value in snapshot.items():
                if hasattr(ds, key):
                    setattr(ds, key, value)

            ds.current_version = (ds.current_version or 1) + 1
            # updated_at 会由 onupdate 自动更新
            if user_id:
                ds.updated_by = user_id
            s.commit()
            return True, None
        except Exception as e:
            s.rollback()
            logger.error(f"Error rolling back datasource semantic {ds_id} to version {version_id}: {e}", exc_info=True)
            return False, f"回滚失败: {e}"
        finally:
            s.remove()

    def transition_datasource_status(
        self, ds_id: int, new_status: str, user_id: int = None
    ) -> tuple:
        """状态流转，返回 (success, error_message)"""
        s = self.session
        try:
            obj = s.query(TableauDatasourceSemantics).filter(TableauDatasourceSemantics.id == ds_id).first()
            if not obj:
                return False, "记录不存在"

            current = obj.status
            allowed = SemanticStatus.TRANSITIONS.get(current, [])
            if new_status not in allowed:
                return False, f"不允许从 {current} 流转到 {new_status}，允许的目标状态：{allowed}"

            obj.status = new_status
            # updated_at 会由 onupdate 自动更新
            if user_id:
                obj.updated_by = user_id
            s.commit()
            return True, None
        except Exception:
            s.rollback()
            raise
        finally:
            s.remove()

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
        """Upsert 字段语义，基于 connection_id + tableau_field_id"""
        s = self.session
        try:
            existing = s.query(TableauFieldSemantics).filter(
                TableauFieldSemantics.connection_id == connection_id,
                TableauFieldSemantics.tableau_field_id == tableau_field_id,
            ).first()

            if existing:
                if create_version:
                    self._create_field_version_snapshot(existing, user_id, "manual_update")
                for key, value in fields.items():
                    if hasattr(existing, key) and value is not None:
                        setattr(existing, key, value)
                # updated_at 会由 onupdate 自动更新
                if user_id:
                    existing.updated_by = user_id
                s.commit()
                return existing
            else:
                obj = TableauFieldSemantics(
                    connection_id=connection_id,
                    tableau_field_id=tableau_field_id,
                    created_by=user_id,
                    updated_by=user_id,
                    **fields
                )
                s.add(obj)
                s.commit()
                return obj
        finally:
            s.remove()

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
        s = self.session
        try:
            existing = s.query(TableauFieldSemantics).filter(
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
                # updated_at 会由 onupdate 自动更新
                if user_id:
                    existing.updated_by = user_id
                s.commit()
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
                s.add(obj)
                s.commit()
                return obj
        finally:
            s.remove()

    def get_field_semantics_by_id(self, field_id: int) -> Optional[TableauFieldSemantics]:
        s = self.session
        try:
            return s.query(TableauFieldSemantics).filter(
                TableauFieldSemantics.id == field_id
            ).first()
        finally:
            s.remove()

    def get_field_semantics_by_reg_id(self, field_registry_id: int) -> Optional[TableauFieldSemantics]:
        s = self.session
        try:
            return s.query(TableauFieldSemantics).filter(
                TableauFieldSemantics.field_registry_id == field_registry_id
            ).first()
        finally:
            s.remove()

    def list_field_semantics(
        self,
        connection_id: int,
        ds_id: int = None,
        status: str = None,
        page: int = 1,
        page_size: int = 50,
    ) -> tuple:
        """ds_id: tableau_datasource_fields.id（即 field_registry_id）"""
        s = self.session
        try:
            query = s.query(TableauFieldSemantics).filter(
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
        finally:
            s.remove()

    def update_field_semantics(self, field_id: int, user_id: int = None, change_reason: str = None, **fields) -> bool:
        s = self.session
        try:
            obj = s.query(TableauFieldSemantics).filter(TableauFieldSemantics.id == field_id).first()
            if not obj:
                return False
            self._create_field_version_snapshot(obj, user_id, change_reason or "manual_update")
            for key, value in fields.items():
                if hasattr(obj, key) and value is not None:
                    setattr(obj, key, value)
            # updated_at 会由 onupdate 自动更新
            if user_id:
                obj.updated_by = user_id
            s.commit()
            return True
        except Exception:
            s.rollback()
            raise
        finally:
            s.remove()

    def transition_field_status(
        self, field_id: int, new_status: str, user_id: int = None
    ) -> tuple:
        """状态流转，返回 (success, error_message)"""
        s = self.session
        try:
            obj = s.query(TableauFieldSemantics).filter(TableauFieldSemantics.id == field_id).first()
            if not obj:
                return False, "记录不存在"

            current = obj.status
            allowed = SemanticStatus.TRANSITIONS.get(current, [])
            if new_status not in allowed:
                return False, f"不允许从 {current} 流转到 {new_status}，允许的目标状态：{allowed}"

            obj.status = new_status
            # updated_at 会由 onupdate 自动更新
            if user_id:
                obj.updated_by = user_id
            s.commit()
            return True, None
        except Exception:
            s.rollback()
            raise
        finally:
            s.remove()

    def _create_field_version_snapshot(
        self, field_semantic: TableauFieldSemantics,
        user_id: int = None,
        change_reason: str = None
    ):
        """创建字段语义历史版本快照"""
        # 序列化当前所有语义字段
        # JSONB 字段直接是 Python 对象，无需 json.dumps
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
            snapshot_json=snapshot_data, # JSONB 字段直接传入 Python 对象
            changed_by=user_id,
            change_reason=change_reason,
        )
        self.session.add(version)
        # 递增版本号
        field_semantic.version = (field_semantic.version or 1) + 1

    def get_field_semantic_history(self, field_semantic_id: int) -> List[TableauFieldSemanticVersion]:
        s = self.session
        try:
            return s.query(TableauFieldSemanticVersion).filter(
                TableauFieldSemanticVersion.field_semantic_id == field_semantic_id
            ).order_by(TableauFieldSemanticVersion.version.desc()).all()
        finally:
            s.remove()

    def rollback_field_semantic(
        self, field_semantic_id: int, version_id: int, user_id: int = None
    ) -> tuple:
        """回滚字段语义到指定版本，返回 (success, error_message)"""
        s = self.session
        try:
            target_version = s.query(TableauFieldSemanticVersion).filter(
                TableauFieldSemanticVersion.id == version_id,
                TableauFieldSemanticVersion.field_semantic_id == field_semantic_id,
            ).first()
            if not target_version:
                return False, "版本记录不存在"

            field = s.query(TableauFieldSemantics).filter(TableauFieldSemantics.id == field_semantic_id).first()
            if not field:
                return False, "字段语义记录不存在"

            # 保存当前版本快照
            self._create_field_version_snapshot(field, user_id, f"rollback_to_v{version_id}")

            # 恢复快照
            # JSONB 字段直接是 Python 对象，无需 json.loads
            snapshot = target_version.snapshot_json

            for key, value in snapshot.items():
                if hasattr(field, key):
                    setattr(field, key, value)

            field.version = (field.version or 1) + 1
            # updated_at 会由 onupdate 自动更新
            if user_id:
                field.updated_by = user_id
            s.commit()
            return True, None
        except Exception as e:
            s.rollback()
            logger.error(f"Error rolling back field semantic {field_semantic_id} to version {version_id}: {e}", exc_info=True)
            return False, f"回滚失败: {e}"
        finally:
            s.remove()

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
        diff_json: Dict[str, Any] = None, # diff_json 现在是 dict
        payload_json: Dict[str, Any] = None, # payload_json 现在是 dict
    ) -> TableauPublishLog:
        """创建发布日志"""
        s = self.session
        try:
            log = TableauPublishLog(
                connection_id=connection_id,
                object_type=object_type,
                object_id=object_id,
                tableau_object_id=tableau_object_id,
                diff_json=diff_json,
                publish_payload_json=payload_json,
                operator=operator,
            )
            s.add(log)
            s.commit()
            return log
        finally:
            s.remove()

    def update_publish_log_status(
        self,
        log_id: int,
        status: str,
        response_summary: str = None
    ) -> bool:
        s = self.session
        try:
            log = s.query(TableauPublishLog).filter(
                TableauPublishLog.id == log_id
            ).first()
            if not log:
                return False
            log.status = status
            if response_summary is not None:
                log.response_summary = response_summary
            s.commit()
            return True
        finally:
            s.remove()

    def list_publish_logs(
        self,
        connection_id: int,
        object_type: str = None,
        status: str = None,
        page: int = 1,
        page_size: int = 50,
    ) -> tuple:
        s = self.session
        try:
            query = s.query(TableauPublishLog).filter(
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
        finally:
            s.remove()

    def get_publish_log(self, log_id: int, connection_id: Optional[int] = None) -> Optional[TableauPublishLog]:
        s = self.session
        try:
            query = s.query(TableauPublishLog).filter(TableauPublishLog.id == log_id)
            if connection_id is not None:
                query = query.filter(TableauPublishLog.connection_id == connection_id)
            return query.first()
        finally:
            s.remove()

    def list_publish_logs_with_filters(
        self,
        connection_id: Optional[int] = None,
        object_type: Optional[str] = None,
        status: Optional[str] = None,
        operator_id: Optional[int] = None,
        start_date=None,
        end_date=None,
        page: int = 1,
        page_size: int = 20,
        sort_by: str = "created_at",
        sort_order: str = "desc",
    ) -> tuple:
        """
        带多条件过滤的发布日志列表查询，支持 JOIN 获取连接名、对象名、操作人信息。
        返回 (list of dicts, total_count)
        """
        from services.tableau.models import TableauConnection
        from app.core.database import SessionLocal as AppSessionLocal

        s = self.session
        app_session = AppSessionLocal()
        try:
            # Base query with joins
            query = s.query(TableauPublishLog).outerjoin(
                TableauConnection,
                TableauPublishLog.connection_id == TableauConnection.id
            )

            # Apply filters
            if connection_id is not None:
                query = query.filter(TableauPublishLog.connection_id == connection_id)
            if object_type:
                query = query.filter(TableauPublishLog.object_type == object_type)
            if status:
                query = query.filter(TableauPublishLog.status == status)
            if operator_id is not None:
                query = query.filter(TableauPublishLog.operator == operator_id)
            if start_date:
                query = query.filter(TableauPublishLog.created_at >= start_date)
            if end_date:
                query = query.filter(TableauPublishLog.created_at <= end_date)

            # Sorting
            sort_column = getattr(TableauPublishLog, sort_by, TableauPublishLog.created_at)
            if sort_order == "asc":
                query = query.order_by(sort_column.asc())
            else:
                query = query.order_by(sort_column.desc())

            # Total count before pagination
            total = query.count()

            # Pagination
            items = query.offset((page - 1) * page_size).limit(page_size).all()

            # Build result with joined data
            results = []
            for log in items:
                # Get connection name
                connection_name = None
                if log.connection_id:
                    try:
                        conn = app_session.query(TableauConnection).filter(
                            TableauConnection.id == log.connection_id
                        ).first()
                        if conn:
                            connection_name = conn.name
                    except Exception:
                        connection_name = f"连接 {log.connection_id}"

                # Get object name from semantics tables
                object_name = None
                if log.object_type == "datasource":
                    try:
                        from .models import TableauDatasourceSemantics
                        ds = app_session.query(TableauDatasourceSemantics).filter(
                            TableauDatasourceSemantics.id == log.object_id
                        ).first()
                        if ds:
                            object_name = ds.semantic_name_zh or ds.semantic_name
                    except Exception:
                        object_name = f"数据源 {log.object_id}"
                elif log.object_type == "field":
                    try:
                        from .models import TableauFieldSemantics
                        field = app_session.query(TableauFieldSemantics).filter(
                            TableauFieldSemantics.id == log.object_id
                        ).first()
                        if field:
                            object_name = field.semantic_name_zh or field.semantic_name
                    except Exception:
                        object_name = f"字段 {log.object_id}"

                # Get operator info
                operator_info = None
                if log.operator:
                    try:
                        from services.auth.models import User
                        user = app_session.query(User).filter(User.id == log.operator).first()
                        if user:
                            operator_info = {
                                "id": user.id,
                                "username": user.username,
                                "display_name": getattr(user, "display_name", None) or user.username,
                            }
                    except Exception:
                        operator_info = {"id": log.operator, "username": str(log.operator), "display_name": str(log.operator)}

                # Build diff_summary from diff_json
                diff_summary = {"changed_fields": [], "total_changes": 0}
                if log.diff_json and isinstance(log.diff_json, dict):
                    # Check if it's a rollback diff
                    if "rollback" in log.diff_json:
                        diff_summary["changed_fields"] = list(log.diff_json.get("rollback", {}).keys())
                        diff_summary["total_changes"] = len(diff_summary["changed_fields"])
                        diff_summary["is_rollback"] = True
                    else:
                        diff_summary["changed_fields"] = list(log.diff_json.keys())
                        diff_summary["total_changes"] = len(diff_summary["changed_fields"])

                results.append({
                    "id": log.id,
                    "connection_id": log.connection_id,
                    "connection_name": connection_name,
                    "object_type": log.object_type,
                    "object_id": log.object_id,
                    "object_name": object_name,
                    "tableau_object_id": log.tableau_object_id,
                    "status": log.status,
                    "response_summary": log.response_summary,
                    "operator": operator_info,
                    "diff_summary": diff_summary,
                    "created_at": log.created_at.strftime("%Y-%m-%dT%H:%M:%SZ") if log.created_at else None,
                })

            return results, total
        finally:
            s.remove()
            app_session.close()

    def get_publish_log_detail(self, log_id: int) -> Optional[dict]:
        """
        获取发布日志详情，JOIN 连接名、对象名、操作人信息、完整 diff、related_logs。
        """
        from services.tableau.models import TableauConnection
        from app.core.database import SessionLocal as AppSessionLocal

        s = self.session
        app_session = AppSessionLocal()
        try:
            log = s.query(TableauPublishLog).filter(TableauPublishLog.id == log_id).first()
            if not log:
                return None

            # Get connection name
            connection_name = None
            if log.connection_id:
                try:
                    conn = app_session.query(TableauConnection).filter(
                        TableauConnection.id == log.connection_id
                    ).first()
                    if conn:
                        connection_name = conn.name
                except Exception:
                    connection_name = f"连接 {log.connection_id}"

            # Get object name
            object_name = None
            if log.object_type == "datasource":
                try:
                    from .models import TableauDatasourceSemantics
                    ds = app_session.query(TableauDatasourceSemantics).filter(
                        TableauDatasourceSemantics.id == log.object_id
                    ).first()
                    if ds:
                        object_name = ds.semantic_name_zh or ds.semantic_name
                except Exception:
                    object_name = f"数据源 {log.object_id}"
            elif log.object_type == "field":
                try:
                    from .models import TableauFieldSemantics
                    field = app_session.query(TableauFieldSemantics).filter(
                        TableauFieldSemantics.id == log.object_id
                    ).first()
                    if field:
                        object_name = field.semantic_name_zh or field.semantic_name
                except Exception:
                    object_name = f"字段 {log.object_id}"

            # Get operator info
            operator_info = None
            if log.operator:
                try:
                    from services.auth.models import User
                    user = app_session.query(User).filter(User.id == log.operator).first()
                    if user:
                        operator_info = {
                            "id": user.id,
                            "username": user.username,
                            "display_name": getattr(user, "display_name", None) or user.username,
                        }
                except Exception:
                    operator_info = {"id": log.operator, "username": str(log.operator), "display_name": str(log.operator)}

            # Get related logs (same object_type + object_id)
            related_logs = []
            try:
                related = s.query(TableauPublishLog).filter(
                    TableauPublishLog.object_type == log.object_type,
                    TableauPublishLog.object_id == log.object_id,
                    TableauPublishLog.id != log.id,
                ).order_by(TableauPublishLog.created_at.desc()).limit(5).all()
                related_logs = [
                    {
                        "id": r.id,
                        "status": r.status,
                        "created_at": r.created_at.strftime("%Y-%m-%dT%H:%M:%SZ") if r.created_at else None,
                    }
                    for r in related
                ]
            except Exception:
                pass

            # Determine if rollback diff
            is_rollback = log.diff_json and isinstance(log.diff_json, dict) and "rollback" in log.diff_json

            # Build diff_summary (same logic as list endpoint)
            diff_summary = {"changed_fields": [], "total_changes": 0}
            if log.diff_json and isinstance(log.diff_json, dict):
                if "rollback" in log.diff_json:
                    diff_summary["changed_fields"] = list(log.diff_json.get("rollback", {}).keys())
                    diff_summary["total_changes"] = len(diff_summary["changed_fields"])
                    diff_summary["is_rollback"] = True
                else:
                    diff_summary["changed_fields"] = list(log.diff_json.keys())
                    diff_summary["total_changes"] = len(diff_summary["changed_fields"])

            return {
                "id": log.id,
                "connection_id": log.connection_id,
                "connection_name": connection_name,
                "object_type": log.object_type,
                "object_id": log.object_id,
                "object_name": object_name,
                "tableau_object_id": log.tableau_object_id,
                "target_system": log.target_system,
                "status": log.status,
                "response_summary": log.response_summary,
                "operator": operator_info,
                "diff_summary": diff_summary,
                "publish_payload": log.publish_payload_json,
                "diff": log.diff_json if not is_rollback else None,
                "rollback_diff": log.diff_json.get("rollback") if is_rollback else None,
                "created_at": log.created_at.strftime("%Y-%m-%dT%H:%M:%SZ") if log.created_at else None,
                "can_rollback": log.status == "success",
                "related_logs": related_logs,
            }
        finally:
            s.remove()
            app_session.close()

    # ============================================================
    # 字段向量 Embedding（HNSW — 复用 kb_embeddings 表）
    # ============================================================

    def upsert_field_embedding(
        self,
        field_semantic_id: int,
        chunk_text: str,
        embedding: list,
        model_name: str = "text-embedding-3-small",
        token_count: int = None,
    ) -> None:
        """将字段语义 embedding 写入 tableau_field_semantics.embedding 列（HNSW 索引）。"""
        s = self.session
        try:
            field = s.query(TableauFieldSemantics).filter(
                TableauFieldSemantics.id == field_semantic_id
            ).first()
            if not field:
                logger.warning("upsert_field_embedding: field_semantic_id=%d 不存在，跳过", field_semantic_id)
                return
            field.embedding = embedding  # Vector(1024) 列，SQLAlchemy 自动转为 pgvector
            field.embedding_model = model_name
            from datetime import datetime
            field.embedding_generated_at = datetime.utcnow()
            field.chunk_text = chunk_text  # 记录 embedding 对应的原始文本
            s.commit()
        finally:
            s.remove()

    def search_field_embeddings(
        self,
        query_embedding: list,
        connection_id: int,
        top_k: int = 5,
        threshold: float = 0.5,
    ) -> List[Dict]:
        """
        向量相似度搜索字段语义（HNSW 索引）。

        直接在 tableau_field_semantics.embedding 列上做 cosine similarity 搜索，
        通过 field_registry_id join tableau_datasource_fields 补全 role / data_type。
        """
        from sqlalchemy import text
        # 边界校验
        if not query_embedding or not isinstance(query_embedding, (list, tuple)):
            logger.warning("search_field_embeddings: query_embedding 无效，跳过")
            return []
        if len(query_embedding) != 1024:
            logger.warning("search_field_embeddings: query_embedding 维度=%d，需为 1024，跳过", len(query_embedding))
            return []
        top_k = max(1, min(top_k, 100))
        threshold = max(-1.0, min(float(threshold), 1.0))

        s = self.session
        try:
            sql = text("""
                SELECT
                    tfs.id             AS field_semantic_id,
                    tfs.tableau_field_id,
                    tfs.semantic_name,
                    tfs.semantic_name_zh,
                    tfs.semantic_definition,
                    tfs.field_registry_id,
                    tfs.connection_id,
                    tfs.chunk_text,
                    tdsf.role,
                    tdsf.data_type,
                    1 - (tfs.embedding <=> :qe::vector) AS cosine_similarity
                FROM tableau_field_semantics tfs
                LEFT JOIN tableau_datasource_fields tdsf
                    ON tdsf.id = tfs.field_registry_id
                WHERE tfs.connection_id = :conn_id
                  AND tfs.embedding IS NOT NULL
                  AND 1 - (tfs.embedding <=> :qe::vector) > :threshold
                ORDER BY tfs.embedding <=> :qe::vector
                LIMIT :top_k
            """)
            rows = s.execute(sql, {
                "qe": str(query_embedding),
                "conn_id": connection_id,
                "threshold": threshold,
                "top_k": top_k,
            }).fetchall()
            return [dict(row._mapping) for row in rows]
        finally:
            s.remove()

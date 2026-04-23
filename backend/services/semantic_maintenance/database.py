"""语义维护模块 - 数据库管理层"""
import json
import logging
from typing import Optional, List, Dict, Any

from app.core.database import Base, SessionLocal, JSONB, sa_func # 导入中央配置的 Base, SessionLocal, JSONB, func
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
            s.close()

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
            s.close()

    def get_datasource_semantics_by_id(self, ds_id: int) -> Optional[TableauDatasourceSemantics]:
        s = self.session
        try:
            return s.query(TableauDatasourceSemantics).filter(
                TableauDatasourceSemantics.id == ds_id
            ).first()
        finally:
            s.close()

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
            s.close()

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
            s.close()

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
            s.close()

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
            s.close()

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
            s.close()

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
            s.close()

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
            s.close()

    def get_field_semantics_by_id(self, field_id: int) -> Optional[TableauFieldSemantics]:
        s = self.session
        try:
            return s.query(TableauFieldSemantics).filter(
                TableauFieldSemantics.id == field_id
            ).first()
        finally:
            s.close()

    def get_field_semantics_by_reg_id(self, field_registry_id: int) -> Optional[TableauFieldSemantics]:
        s = self.session
        try:
            return s.query(TableauFieldSemantics).filter(
                TableauFieldSemantics.field_registry_id == field_registry_id
            ).first()
        finally:
            s.close()

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
            s.close()

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
            s.close()

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
            s.close()

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
            s.close()

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
            s.close()

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
            s.close()

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
            s.close()

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
            s.close()

    def get_publish_log(self, log_id: int, connection_id: Optional[int] = None) -> Optional[TableauPublishLog]:
        s = self.session
        try:
            query = s.query(TableauPublishLog).filter(TableauPublishLog.id == log_id)
            if connection_id is not None:
                query = query.filter(TableauPublishLog.connection_id == connection_id)
            return query.first()
        finally:
            s.close()

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
            s.close()

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
        threshold = max(0.0, min(float(threshold), 1.0))

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
                    tfs.embedding,
                    tfs.chunk_text,
                    tdsf.role,
                    tdsf.data_type,
                    1 - (tfs.embedding <=> :qe::vector) AS similarity
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
            s.close()

"""语义维护模块 - SQLAlchemy 数据模型"""
from typing import Optional, List, Dict, Any

from sqlalchemy import (
    Column, Integer, String, DateTime, Boolean,
    Text, Float, ForeignKey, UniqueConstraint, Index
)
from sqlalchemy.orm import relationship
from app.core.database import Base, JSONB, sa_func, sa_text
from pgvector.sqlalchemy import Vector

# --- 枚举常量 ---
class SemanticStatus:
    DRAFT = "draft"
    AI_GENERATED = "ai_generated"
    REVIEWED = "reviewed"
    APPROVED = "approved"
    PUBLISHED = "published"
    REJECTED = "rejected"

    ALL = [DRAFT, AI_GENERATED, REVIEWED, APPROVED, PUBLISHED, REJECTED]

    # 允许的状态流转
    TRANSITIONS = {
        DRAFT: [AI_GENERATED, REVIEWED],
        AI_GENERATED: [DRAFT, REVIEWED],
        REVIEWED: [APPROVED, REJECTED, DRAFT],
        APPROVED: [PUBLISHED, REVIEWED],
        PUBLISHED: [DRAFT],  # 回滚后降级
        REJECTED: [DRAFT],
    }


class SemanticSource:
    SYNC = "sync"
    MANUAL = "manual"
    AI = "ai"
    IMPORTED = "imported"


class SensitivityLevel:
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CONFIDENTIAL = "confidential"

    ALL = [LOW, MEDIUM, HIGH, CONFIDENTIAL]


class PublishStatus:
    PENDING = "pending"
    SUCCESS = "success"
    FAILED = "failed"
    ROLLED_BACK = "rolled_back"
    NOT_SUPPORTED = "not_supported"


# --- 数据模型 ---

class TableauDatasourceSemantics(Base):
    """数据源级语义主信息表"""
    __tablename__ = "tableau_datasource_semantics" # 保持现有前缀
    __table_args__ = (
        UniqueConstraint("connection_id", "tableau_datasource_id", name="uq_ds_semantic_conn_ds"),
        Index("ix_ds_semantic_status", "status"),
        Index("ix_ds_semantic_conn_id", "connection_id"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    connection_id = Column(Integer, nullable=False)  # FK → tableau_connections.id
    tableau_datasource_id = Column(String(256), nullable=False)
    semantic_name = Column(String(256), nullable=True)
    semantic_name_zh = Column(String(256), nullable=True)
    semantic_description = Column(Text, nullable=True)
    business_definition = Column(Text, nullable=True)
    usage_scenarios = Column(Text, nullable=True)
    owner = Column(String(128), nullable=True)
    steward = Column(String(128), nullable=True)
    sensitivity_level = Column(String(16), default=SensitivityLevel.LOW, server_default=sa_text(f"'{SensitivityLevel.LOW}'"))
    tags_json = Column(JSONB, nullable=True, server_default=sa_text("'[]'::jsonb"))  # JSON array, P0 修复: 统一 server_default
    status = Column(String(32), default=SemanticStatus.DRAFT, server_default=sa_text(f"'{SemanticStatus.DRAFT}'"))
    source = Column(String(16), default=SemanticSource.MANUAL, server_default=sa_text(f"'{SemanticSource.MANUAL}'"))
    current_version = Column(Integer, default=1, server_default=sa_func.cast(1, Integer()))
    published_to_tableau = Column(Boolean, default=False, server_default=sa_text('false')) # Boolean 默认值
    published_at = Column(DateTime, nullable=True)
    created_by = Column(Integer, nullable=True)
    updated_by = Column(Integer, nullable=True)
    created_at = Column(DateTime, nullable=False, server_default=sa_func.now()) # DateTime 默认值
    updated_at = Column(DateTime, server_default=sa_func.now(), onupdate=sa_func.now()) # DateTime 默认值和更新

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "connection_id": self.connection_id,
            "tableau_datasource_id": self.tableau_datasource_id,
            "semantic_name": self.semantic_name,
            "semantic_name_zh": self.semantic_name_zh,
            "semantic_description": self.semantic_description,
            "business_definition": self.business_definition,
            "usage_scenarios": self.usage_scenarios,
            "owner": self.owner,
            "steward": self.steward,
            "sensitivity_level": self.sensitivity_level,
            "tags_json": self.tags_json, # JSONB 字段直接是 Python 对象
            "status": self.status,
            "source": self.source,
            "current_version": self.current_version,
            "published_to_tableau": self.published_to_tableau,
            "published_at": self.published_at.strftime("%Y-%m-%d %H:%M:%S") if self.published_at else None,
            "created_by": self.created_by,
            "updated_by": self.updated_by,
            "created_at": self.created_at.strftime("%Y-%m-%d %H:%M:%S") if self.created_at else None,
            "updated_at": self.updated_at.strftime("%Y-%m-%d %H:%M:%S") if self.updated_at else None,
        }


class TableauDatasourceSemanticVersion(Base):
    """数据源语义历史版本快照"""
    __tablename__ = "tableau_datasource_semantic_versions" # 保持现有前缀
    __table_args__ = (
        Index("ix_ds_ver_sem_id", "datasource_semantic_id"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    datasource_semantic_id = Column(Integer, ForeignKey("tableau_datasource_semantics.id", ondelete="CASCADE"), nullable=False)
    version = Column(Integer, nullable=False)
    snapshot_json = Column(JSONB, nullable=False, server_default=sa_text("'{}'::jsonb"))  # P1 修复: 统一 JSONB 默认值（对象字典）
    changed_by = Column(Integer, nullable=True)
    change_reason = Column(Text, nullable=True)
    created_at = Column(DateTime, nullable=False, server_default=sa_func.now()) # DateTime 默认值

    datasource_semantic = relationship("TableauDatasourceSemantics", back_populates="versions")

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "datasource_semantic_id": self.datasource_semantic_id,
            "version": self.version,
            "snapshot_json": self.snapshot_json, # JSONB 字段直接是 Python 对象
            "changed_by": self.changed_by,
            "change_reason": self.change_reason,
            "created_at": self.created_at.strftime("%Y-%m-%d %H:%M:%S") if self.created_at else None,
        }


class TableauFieldSemantics(Base):
    """字段语义版本表"""
    __tablename__ = "tableau_field_semantics" # 保持现有前缀
    __table_args__ = (
        UniqueConstraint("connection_id", "tableau_field_id", name="uq_field_semantic_conn_fid"),
        Index("ix_field_semantic_status", "status"),
        Index("ix_field_semantic_conn_id", "connection_id"),
        Index("ix_field_semantic_reg_id", "field_registry_id"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    field_registry_id = Column(Integer, nullable=True)  # FK → tableau_datasource_fields.id
    connection_id = Column(Integer, nullable=False)
    tableau_field_id = Column(String(256), nullable=False)
    semantic_name = Column(String(256), nullable=True)
    semantic_name_zh = Column(String(256), nullable=True)
    semantic_definition = Column(Text, nullable=True)
    metric_definition = Column(Text, nullable=True)
    dimension_definition = Column(Text, nullable=True)
    unit = Column(String(64), nullable=True)
    enum_desc_json = Column(JSONB, nullable=True, server_default=sa_text("'[]'::jsonb"))   # P1 修复: 统一 JSONB 默认值（数组）
    tags_json = Column(JSONB, nullable=True, server_default=sa_text("'[]'::jsonb"))          # P1 修复: 统一 JSONB 默认值（数组）
    synonyms_json = Column(JSONB, nullable=True, server_default=sa_text("'[]'::jsonb"))    # P1 修复: 统一 JSONB 默认值（数组）
    sensitivity_level = Column(String(16), default=SensitivityLevel.LOW, server_default=sa_text(f"'{SensitivityLevel.LOW}'"))
    is_core_field = Column(Boolean, default=False, server_default=sa_text('false')) # Boolean 默认值
    ai_confidence = Column(Float, nullable=True)
    status = Column(String(32), default=SemanticStatus.DRAFT, server_default=sa_text(f"'{SemanticStatus.DRAFT}'"))
    source = Column(String(16), default=SemanticSource.MANUAL, server_default=sa_text(f"'{SemanticSource.MANUAL}'"))
    version = Column(Integer, default=1, server_default=sa_func.cast(1, Integer()))
    published_to_tableau = Column(Boolean, default=False, server_default=sa_text('false')) # Boolean 默认值
    published_at = Column(DateTime, nullable=True)
    # 向量 embedding（HNSW 索引，migration 已建列）
    embedding = Column(Vector(1024), nullable=True)
    embedding_model = Column(String(64), nullable=True)
    embedding_generated_at = Column(DateTime, nullable=True)
    chunk_text = Column(Text, nullable=True)  # embedding 对应的原始文本，方便 trace/debug
    created_by = Column(Integer, nullable=True)
    updated_by = Column(Integer, nullable=True)
    created_at = Column(DateTime, nullable=False, server_default=sa_func.now()) # DateTime 默认值
    updated_at = Column(DateTime, server_default=sa_func.now(), onupdate=sa_func.now()) # DateTime 默认值和更新


    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "field_registry_id": self.field_registry_id,
            "connection_id": self.connection_id,
            "tableau_field_id": self.tableau_field_id,
            "semantic_name": self.semantic_name,
            "semantic_name_zh": self.semantic_name_zh,
            "semantic_definition": self.semantic_definition,
            "metric_definition": self.metric_definition,
            "dimension_definition": self.dimension_definition,
            "unit": self.unit,
            "enum_desc_json": self.enum_desc_json, # JSONB 字段直接是 Python 对象
            "tags_json": self.tags_json, # JSONB 字段直接是 Python 对象
            "synonyms_json": self.synonyms_json, # JSONB 字段直接是 Python 对象
            "sensitivity_level": self.sensitivity_level,
            "is_core_field": self.is_core_field,
            "ai_confidence": self.ai_confidence,
            "status": self.status,
            "source": self.source,
            "version": self.version,
            "published_to_tableau": self.published_to_tableau,
            "published_at": self.published_at.strftime("%Y-%m-%d %H:%M:%S") if self.published_at else None,
            "has_embedding": self.embedding is not None,
            "embedding_model": self.embedding_model,
            "embedding_generated_at": self.embedding_generated_at.strftime("%Y-%m-%d %H:%M:%S") if self.embedding_generated_at else None,
            "chunk_text": self.chunk_text,
            "created_by": self.created_by,
            "updated_by": self.updated_by,
            "created_at": self.created_at.strftime("%Y-%m-%d %H:%M:%S") if self.created_at else None,
            "updated_at": self.updated_at.strftime("%Y-%m-%d %H:%M:%S") if self.updated_at else None,
        }


class TableauFieldSemanticVersion(Base):
    """字段语义历史版本快照"""
    __tablename__ = "tableau_field_semantic_versions" # 保持现有前缀
    __table_args__ = (
        Index("ix_field_ver_sem_id", "field_semantic_id"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    field_semantic_id = Column(Integer, ForeignKey("tableau_field_semantics.id", ondelete="CASCADE"), nullable=False)
    version = Column(Integer, nullable=False)
    snapshot_json = Column(JSONB, nullable=False, server_default=sa_text("'{}'::jsonb"))  # P1 修复: 统一 JSONB 默认值（对象字典）
    changed_by = Column(Integer, nullable=True)
    change_reason = Column(Text, nullable=True)
    created_at = Column(DateTime, nullable=False, server_default=sa_func.now()) # DateTime 默认值

    field_semantic = relationship("TableauFieldSemantics", back_populates="versions")

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "field_semantic_id": self.field_semantic_id,
            "version": self.version,
            "snapshot_json": self.snapshot_json, # JSONB 字段直接是 Python 对象
            "changed_by": self.changed_by,
            "change_reason": self.change_reason,
            "created_at": self.created_at.strftime("%Y-%m-%d %H:%M:%S") if self.created_at else None,
        }


class TableauPublishLog(Base):
    """发布回写日志表"""
    __tablename__ = "tableau_publish_logs" # tableau_publish_log → tableau_publish_logs
    __table_args__ = (
        Index("ix_publish_log_conn_status", "connection_id", "status"),
        Index("ix_publish_log_object", "object_type", "object_id"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    connection_id = Column(Integer, nullable=False)
    object_type = Column(String(32), nullable=False)  # 'datasource' / 'field'
    object_id = Column(Integer, nullable=False)
    tableau_object_id = Column(String(256), nullable=True)
    target_system = Column(String(32), default="tableau", server_default=sa_text("'tableau'"))
    publish_payload_json = Column(JSONB, nullable=True, server_default=sa_text("'{}'::jsonb"))  # P1 修复: 统一 JSONB 默认值（对象字典）
    diff_json = Column(JSONB, nullable=True, server_default=sa_text("'{}'::jsonb"))            # P1 修复: 统一 JSONB 默认值（对象字典）
    status = Column(String(16), default=PublishStatus.PENDING, server_default=sa_text(f"'{PublishStatus.PENDING}'"))
    response_summary = Column(Text, nullable=True)
    operator = Column(Integer, nullable=True)
    created_at = Column(DateTime, nullable=False, server_default=sa_func.now()) # DateTime 默认值

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "connection_id": self.connection_id,
            "object_type": self.object_type,
            "object_id": self.object_id,
            "tableau_object_id": self.tableau_object_id,
            "target_system": self.target_system,
            "publish_payload_json": self.publish_payload_json, # JSONB 字段直接是 Python 对象
            "diff_json": self.diff_json, # JSONB 字段直接是 Python 对象
            "status": self.status,
            "response_summary": self.response_summary,
            "operator": self.operator,
            "created_at": self.created_at.strftime("%Y-%m-%d %H:%M:%S") if self.created_at else None,
        }


# 修复 relationship 的 back_populates 引用（类体定义时 Table 尚未创建）
TableauDatasourceSemantics.versions = relationship(
    "TableauDatasourceSemanticVersion",
    back_populates="datasource_semantic",
    cascade="all, delete-orphan",
    order_by="desc(TableauDatasourceSemanticVersion.version)"
)

TableauFieldSemantics.versions = relationship(
    "TableauFieldSemanticVersion",
    back_populates="field_semantic",
    cascade="all, delete-orphan",
    order_by="desc(TableauFieldSemanticVersion.version)"
)


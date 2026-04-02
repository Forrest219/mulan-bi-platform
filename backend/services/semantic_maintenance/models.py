"""语义维护模块 - SQLAlchemy 数据模型"""
from datetime import datetime
from typing import Optional, List, Dict, Any

from sqlalchemy import (
    create_engine, Column, Integer, String, DateTime, Boolean,
    Text, Float, ForeignKey, UniqueConstraint, Index
)
from sqlalchemy.orm import declarative_base, sessionmaker, relationship

Base = declarative_base()

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
        DRAFT: [AI_GENERATED],
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


# --- 数据模型 ---

class TableauDatasourceSemantics(Base):
    """数据源级语义主信息表"""
    __tablename__ = "tableau_datasource_semantics"
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
    sensitivity_level = Column(String(16), default=SensitivityLevel.LOW)
    tags_json = Column(Text, nullable=True)  # JSON array
    status = Column(String(32), default=SemanticStatus.DRAFT)
    source = Column(String(16), default=SemanticSource.MANUAL)
    current_version = Column(Integer, default=1)
    published_to_tableau = Column(Boolean, default=False)
    published_at = Column(DateTime, nullable=True)
    created_by = Column(Integer, nullable=True)
    updated_by = Column(Integer, nullable=True)
    created_at = Column(DateTime, default=datetime.now, nullable=False)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)

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
            "tags_json": self.tags_json,
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
    __tablename__ = "tableau_datasource_semantic_versions"
    __table_args__ = (
        Index("ix_ds_ver_sem_id", "datasource_semantic_id"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    datasource_semantic_id = Column(Integer, ForeignKey("tableau_datasource_semantics.id", ondelete="CASCADE"), nullable=False)
    version = Column(Integer, nullable=False)
    snapshot_json = Column(Text, nullable=False)
    changed_by = Column(Integer, nullable=True)
    change_reason = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.now, nullable=False)

    datasource_semantic = relationship("TableauDatasourceSemantics", back_populates="versions")

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "datasource_semantic_id": self.datasource_semantic_id,
            "version": self.version,
            "snapshot_json": self.snapshot_json,
            "changed_by": self.changed_by,
            "change_reason": self.change_reason,
            "created_at": self.created_at.strftime("%Y-%m-%d %H:%M:%S") if self.created_at else None,
        }


class TableauFieldSemantics(Base):
    """字段语义版本表"""
    __tablename__ = "tableau_field_semantics"
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
    enum_desc_json = Column(Text, nullable=True)
    tags_json = Column(Text, nullable=True)
    synonyms_json = Column(Text, nullable=True)
    sensitivity_level = Column(String(16), default=SensitivityLevel.LOW)
    is_core_field = Column(Boolean, default=False)
    ai_confidence = Column(Float, nullable=True)
    status = Column(String(32), default=SemanticStatus.DRAFT)
    source = Column(String(16), default=SemanticSource.MANUAL)
    version = Column(Integer, default=1)
    published_to_tableau = Column(Boolean, default=False)
    published_at = Column(DateTime, nullable=True)
    created_by = Column(Integer, nullable=True)
    updated_by = Column(Integer, nullable=True)
    created_at = Column(DateTime, default=datetime.now, nullable=False)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)


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
            "enum_desc_json": self.enum_desc_json,
            "tags_json": self.tags_json,
            "synonyms_json": self.synonyms_json,
            "sensitivity_level": self.sensitivity_level,
            "is_core_field": self.is_core_field,
            "ai_confidence": self.ai_confidence,
            "status": self.status,
            "source": self.source,
            "version": self.version,
            "published_to_tableau": self.published_to_tableau,
            "published_at": self.published_at.strftime("%Y-%m-%d %H:%M:%S") if self.published_at else None,
            "created_by": self.created_by,
            "updated_by": self.updated_by,
            "created_at": self.created_at.strftime("%Y-%m-%d %H:%M:%S") if self.created_at else None,
            "updated_at": self.updated_at.strftime("%Y-%m-%d %H:%M:%S") if self.updated_at else None,
        }


class TableauFieldSemanticVersion(Base):
    """字段语义历史版本快照"""
    __tablename__ = "tableau_field_semantic_versions"
    __table_args__ = (
        Index("ix_field_ver_sem_id", "field_semantic_id"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    field_semantic_id = Column(Integer, ForeignKey("tableau_field_semantics.id", ondelete="CASCADE"), nullable=False)
    version = Column(Integer, nullable=False)
    snapshot_json = Column(Text, nullable=False)  # 完整快照 JSON
    changed_by = Column(Integer, nullable=True)
    change_reason = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.now, nullable=False)

    field_semantic = relationship("TableauFieldSemantics", back_populates="versions")

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "field_semantic_id": self.field_semantic_id,
            "version": self.version,
            "snapshot_json": self.snapshot_json,
            "changed_by": self.changed_by,
            "change_reason": self.change_reason,
            "created_at": self.created_at.strftime("%Y-%m-%d %H:%M:%S") if self.created_at else None,
        }


class TableauPublishLog(Base):
    """发布回写日志表"""
    __tablename__ = "tableau_publish_log"
    __table_args__ = (
        Index("ix_publish_log_conn_status", "connection_id", "status"),
        Index("ix_publish_log_object", "object_type", "object_id"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    connection_id = Column(Integer, nullable=False)
    object_type = Column(String(32), nullable=False)  # 'datasource' / 'field'
    object_id = Column(Integer, nullable=False)
    tableau_object_id = Column(String(256), nullable=True)
    target_system = Column(String(32), default="tableau")
    publish_payload_json = Column(Text, nullable=True)
    diff_json = Column(Text, nullable=True)
    status = Column(String(16), default=PublishStatus.PENDING)
    response_summary = Column(Text, nullable=True)
    operator = Column(Integer, nullable=True)
    created_at = Column(DateTime, default=datetime.now, nullable=False)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "connection_id": self.connection_id,
            "object_type": self.object_type,
            "object_id": self.object_id,
            "tableau_object_id": self.tableau_object_id,
            "target_system": self.target_system,
            "publish_payload_json": self.publish_payload_json,
            "diff_json": self.diff_json,
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

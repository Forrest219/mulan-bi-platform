"""数仓资产数据模型"""
from typing import Dict, Any

from sqlalchemy import (
    Column, Integer, String, DateTime, Boolean, Text, Float,
    BigInteger, ForeignKey, CheckConstraint, UniqueConstraint, Index,
)
from app.core.database import Base, JSONB, sa_func, sa_text


class DwAssetTable(Base):
    """数仓资产表级主表"""
    __tablename__ = "dw_asset_tables"

    id = Column(Integer, primary_key=True, autoincrement=True)
    asset_uid = Column(String(192), unique=True, nullable=False)
    datasource_id = Column(Integer, ForeignKey("bi_data_sources.id"), nullable=False)
    database_name = Column(String(128), nullable=False)
    schema_name = Column(String(128), nullable=False, server_default=sa_text("''"))
    table_name = Column(String(256), nullable=False)
    table_type = Column(String(32), nullable=False)
    business_name = Column(String(256), nullable=True)
    description = Column(Text, nullable=True)
    table_comment = Column(Text, nullable=True)
    domain = Column(String(64), nullable=True)
    layer = Column(String(32), nullable=True)
    tags_json = Column(JSONB, nullable=False, server_default=sa_text("'[]'::jsonb"))
    owner_name = Column(String(128), nullable=True)
    row_count_estimate = Column(BigInteger, nullable=True)
    storage_bytes = Column(BigInteger, nullable=True)
    partition_type = Column(String(64), nullable=True)
    partition_key = Column(String(256), nullable=True)
    partition_count = Column(Integer, nullable=True)
    last_partition_name = Column(String(256), nullable=True)
    last_partition_at = Column(DateTime, nullable=True)
    heat_score = Column(Float, nullable=False, server_default=sa_text("0"))
    query_count_7d = Column(Integer, nullable=False, server_default=sa_text("0"))
    query_count_30d = Column(Integer, nullable=False, server_default=sa_text("0"))
    last_queried_at = Column(DateTime, nullable=True)
    is_deleted = Column(Boolean, nullable=False, server_default=sa_text("false"))
    raw_metadata_json = Column(JSONB, nullable=False, server_default=sa_text("'{}'::jsonb"))
    synced_at = Column(DateTime, nullable=False, server_default=sa_func.now())
    created_at = Column(DateTime, nullable=False, server_default=sa_func.now())
    updated_at = Column(DateTime, nullable=False, server_default=sa_func.now(), onupdate=sa_func.now())
    updated_by = Column(Integer, ForeignKey("auth_users.id"), nullable=True)

    __table_args__ = (
        UniqueConstraint("datasource_id", "database_name", "schema_name", "table_name", name="uq_dw_table_identity"),
        Index("ix_dw_table_ds_deleted", "datasource_id", "is_deleted"),
        Index("ix_dw_table_search", "table_name", "business_name"),
        Index("ix_dw_table_domain_layer", "domain", "layer"),
        Index("ix_dw_table_heat", heat_score.desc()),
    )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "asset_uid": self.asset_uid,
            "datasource_id": self.datasource_id,
            "database_name": self.database_name,
            "schema_name": self.schema_name,
            "table_name": self.table_name,
            "table_type": self.table_type,
            "business_name": self.business_name,
            "description": self.description,
            "table_comment": self.table_comment,
            "domain": self.domain,
            "layer": self.layer,
            "tags": self.tags_json or [],
            "owner_name": self.owner_name,
            "row_count_estimate": self.row_count_estimate,
            "storage_bytes": self.storage_bytes,
            "partition_type": self.partition_type,
            "partition_key": self.partition_key,
            "partition_count": self.partition_count,
            "last_partition_name": self.last_partition_name,
            "last_partition_at": self.last_partition_at.strftime("%Y-%m-%d %H:%M:%S") if self.last_partition_at else None,
            "heat_score": self.heat_score,
            "query_count_7d": self.query_count_7d,
            "query_count_30d": self.query_count_30d,
            "last_queried_at": self.last_queried_at.strftime("%Y-%m-%d %H:%M:%S") if self.last_queried_at else None,
            "is_deleted": self.is_deleted,
            "synced_at": self.synced_at.strftime("%Y-%m-%d %H:%M:%S") if self.synced_at else None,
            "created_at": self.created_at.strftime("%Y-%m-%d %H:%M:%S") if self.created_at else None,
            "updated_at": self.updated_at.strftime("%Y-%m-%d %H:%M:%S") if self.updated_at else None,
            "updated_by": self.updated_by,
        }

    def to_list_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "asset_uid": self.asset_uid,
            "datasource_id": self.datasource_id,
            "database_name": self.database_name,
            "schema_name": self.schema_name,
            "table_name": self.table_name,
            "business_name": self.business_name,
            "description": self.description,
            "table_type": self.table_type,
            "domain": self.domain,
            "layer": self.layer,
            "row_count_estimate": self.row_count_estimate,
            "storage_bytes": self.storage_bytes,
            "partition_key": self.partition_key,
            "partition_count": self.partition_count,
            "heat_score": self.heat_score,
            "query_count_7d": self.query_count_7d,
            "tags": self.tags_json or [],
            "synced_at": self.synced_at.strftime("%Y-%m-%d %H:%M:%S") if self.synced_at else None,
        }


class DwAssetColumn(Base):
    """数仓资产字段级元数据"""
    __tablename__ = "dw_asset_columns"

    id = Column(Integer, primary_key=True, autoincrement=True)
    table_id = Column(Integer, ForeignKey("dw_asset_tables.id"), nullable=False)
    column_name = Column(String(256), nullable=False)
    ordinal_position = Column(Integer, nullable=False)
    data_type = Column(String(128), nullable=False)
    normalized_type = Column(String(64), nullable=True)
    is_nullable = Column(Boolean, nullable=True)
    is_primary_key = Column(Boolean, nullable=False, server_default=sa_text("false"))
    is_partition_key = Column(Boolean, nullable=False, server_default=sa_text("false"))
    is_business_key = Column(Boolean, nullable=False, server_default=sa_text("false"))
    default_value = Column(Text, nullable=True)
    column_comment = Column(Text, nullable=True)
    business_name = Column(String(256), nullable=True)
    description = Column(Text, nullable=True)
    sensitivity_level = Column(String(32), nullable=False, server_default=sa_text("'internal'"))
    sample_values_json = Column(JSONB, nullable=False, server_default=sa_text("'[]'::jsonb"))
    stats_json = Column(JSONB, nullable=False, server_default=sa_text("'{}'::jsonb"))
    raw_metadata_json = Column(JSONB, nullable=False, server_default=sa_text("'{}'::jsonb"))
    created_at = Column(DateTime, nullable=False, server_default=sa_func.now())
    updated_at = Column(DateTime, nullable=False, server_default=sa_func.now(), onupdate=sa_func.now())

    __table_args__ = (
        UniqueConstraint("table_id", "column_name", name="uq_dw_col_identity"),
        Index("ix_dw_col_table", "table_id", "ordinal_position"),
        Index("ix_dw_col_name", "column_name"),
    )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "table_id": self.table_id,
            "column_name": self.column_name,
            "ordinal_position": self.ordinal_position,
            "data_type": self.data_type or "unknown",
            "normalized_type": self.normalized_type,
            "is_nullable": self.is_nullable,
            "is_primary_key": self.is_primary_key,
            "is_partition_key": self.is_partition_key,
            "is_business_key": self.is_business_key,
            "default_value": self.default_value,
            "column_comment": self.column_comment,
            "business_name": self.business_name,
            "description": self.description,
            "sensitivity_level": self.sensitivity_level,
            "sample_values": self.sample_values_json or [],
            "stats": self.stats_json or {},
            "created_at": self.created_at.strftime("%Y-%m-%d %H:%M:%S") if self.created_at else None,
            "updated_at": self.updated_at.strftime("%Y-%m-%d %H:%M:%S") if self.updated_at else None,
        }


class DwAssetPartition(Base):
    """数仓资产分区快照"""
    __tablename__ = "dw_asset_partitions"

    id = Column(Integer, primary_key=True, autoincrement=True)
    table_id = Column(Integer, ForeignKey("dw_asset_tables.id"), nullable=False)
    partition_name = Column(String(256), nullable=False)
    partition_value = Column(Text, nullable=True)
    row_count_estimate = Column(BigInteger, nullable=True)
    storage_bytes = Column(BigInteger, nullable=True)
    visible_version = Column(String(64), nullable=True)
    raw_metadata_json = Column(JSONB, nullable=False, server_default=sa_text("'{}'::jsonb"))
    updated_at = Column(DateTime, nullable=False, server_default=sa_func.now(), onupdate=sa_func.now())

    __table_args__ = (
        UniqueConstraint("table_id", "partition_name", name="uq_dw_partition_identity"),
        Index("ix_dw_partition_table", "table_id", "partition_name"),
    )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "table_id": self.table_id,
            "partition_name": self.partition_name,
            "partition_value": self.partition_value,
            "row_count_estimate": self.row_count_estimate,
            "storage_bytes": self.storage_bytes,
            "visible_version": self.visible_version,
            "updated_at": self.updated_at.strftime("%Y-%m-%d %H:%M:%S") if self.updated_at else None,
        }


class DwAssetLineageEdge(Base):
    """数仓资产血缘边"""
    __tablename__ = "dw_asset_lineage_edges"

    id = Column(Integer, primary_key=True, autoincrement=True)
    lineage_type = Column(String(32), nullable=False)
    source_table_id = Column(Integer, ForeignKey("dw_asset_tables.id"), nullable=True)
    source_column_id = Column(Integer, ForeignKey("dw_asset_columns.id"), nullable=True)
    target_table_id = Column(Integer, ForeignKey("dw_asset_tables.id"), nullable=False)
    target_column_id = Column(Integer, ForeignKey("dw_asset_columns.id"), nullable=True)
    relation_type = Column(String(32), nullable=False)
    confidence = Column(Float, nullable=False, server_default=sa_text("1.0"))
    source_system = Column(String(64), nullable=False)
    transformation_logic = Column(Text, nullable=True)
    raw_metadata_json = Column(JSONB, nullable=False, server_default=sa_text("'{}'::jsonb"))
    created_at = Column(DateTime, nullable=False, server_default=sa_func.now())
    updated_at = Column(DateTime, nullable=False, server_default=sa_func.now(), onupdate=sa_func.now())

    __table_args__ = (
        CheckConstraint("lineage_type IN ('table', 'column')", name="ck_lineage_type_valid"),
        CheckConstraint("lineage_type != 'table' OR source_table_id IS NOT NULL", name="ck_lineage_table_has_source"),
        CheckConstraint(
            "lineage_type != 'column' OR (source_table_id IS NOT NULL AND source_column_id IS NOT NULL AND target_column_id IS NOT NULL)",
            name="ck_lineage_column_complete",
        ),
        CheckConstraint("source_table_id IS NULL OR source_table_id != target_table_id", name="ck_lineage_no_self_loop"),
        Index("ix_dw_lineage_source", "source_table_id"),
        Index("ix_dw_lineage_target", "target_table_id"),
    )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "lineage_type": self.lineage_type,
            "source_table_id": self.source_table_id,
            "source_column_id": self.source_column_id,
            "target_table_id": self.target_table_id,
            "target_column_id": self.target_column_id,
            "relation_type": self.relation_type,
            "confidence": self.confidence,
            "source_system": self.source_system,
            "transformation_logic": self.transformation_logic,
            "created_at": self.created_at.strftime("%Y-%m-%d %H:%M:%S") if self.created_at else None,
            "updated_at": self.updated_at.strftime("%Y-%m-%d %H:%M:%S") if self.updated_at else None,
        }


class DwAssetSyncRun(Base):
    """数仓资产元数据同步运行记录"""
    __tablename__ = "dw_asset_sync_runs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    datasource_id = Column(Integer, ForeignKey("bi_data_sources.id"), nullable=False)
    trigger_type = Column(String(32), nullable=False)
    status = Column(String(32), nullable=False)
    started_at = Column(DateTime, nullable=False, server_default=sa_func.now())
    finished_at = Column(DateTime, nullable=True)
    tables_found = Column(Integer, nullable=False, server_default=sa_text("0"))
    tables_upserted = Column(Integer, nullable=False, server_default=sa_text("0"))
    columns_upserted = Column(Integer, nullable=False, server_default=sa_text("0"))
    partitions_upserted = Column(Integer, nullable=False, server_default=sa_text("0"))
    error_message = Column(Text, nullable=True)
    details_json = Column(JSONB, nullable=False, server_default=sa_text("'{}'::jsonb"))
    operator_id = Column(Integer, nullable=True)

    __table_args__ = (
        Index("ix_dw_sync_ds_started", "datasource_id", started_at.desc()),
    )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "datasource_id": self.datasource_id,
            "trigger_type": self.trigger_type,
            "status": self.status,
            "started_at": self.started_at.strftime("%Y-%m-%d %H:%M:%S") if self.started_at else None,
            "finished_at": self.finished_at.strftime("%Y-%m-%d %H:%M:%S") if self.finished_at else None,
            "tables_found": self.tables_found,
            "tables_upserted": self.tables_upserted,
            "columns_upserted": self.columns_upserted,
            "partitions_upserted": self.partitions_upserted,
            "error_message": self.error_message,
            "details_json": self.details_json or {},
            "operator_id": self.operator_id,
        }


class DwDomainTaxonomy(Base):
    """
    主题域层级架构配置表（由 admin/data_admin 维护）。

    结构为 L1 → [L2, L2, ...]。
    例：L1=营销域，L2=[交易分析, 用户画像, 活动效果]
    """
    __tablename__ = "dw_domain_taxonomy"

    id = Column(Integer, primary_key=True, autoincrement=True)
    l1 = Column(String(64), nullable=False)
    l2 = Column(String(64), nullable=True)       # NULL 表示仅 L1 无 L2
    description = Column(String(200), nullable=True)  # L1 建设重点描述
    display_order = Column(Integer, default=0, server_default=sa_func.cast(0, Integer()))
    created_at = Column(DateTime, server_default=sa_func.now())

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "l1": self.l1,
            "l2": self.l2,
            "description": self.description,
            "display_order": self.display_order,
        }


class DwDomainTaxonomyDatabase:
    """主题域层级配置 CRUD"""

    def list_all(self) -> list[DwDomainTaxonomy]:
        from app.core.database import SessionLocal
        session = SessionLocal()
        try:
            rows = (
                session.query(DwDomainTaxonomy)
                .order_by(DwDomainTaxonomy.l1, DwDomainTaxonomy.display_order)
                .all()
            )
            return rows
        finally:
            session.close()

    def upsert(self, l1: str, l2: str | None, display_order: int = 0) -> DwDomainTaxonomy:
        from app.core.database import SessionLocal
        session = SessionLocal()
        try:
            existing = (
                session.query(DwDomainTaxonomy)
                .filter(DwDomainTaxonomy.l1 == l1, DwDomainTaxonomy.l2 == l2)
                .first()
            )
            if existing:
                existing.display_order = display_order
            else:
                existing = DwDomainTaxonomy(l1=l1, l2=l2, display_order=display_order)
                session.add(existing)
            session.commit()
            session.refresh(existing)
            return existing
        finally:
            session.close()

    def delete(self, taxonomy_id: int) -> bool:
        from app.core.database import SessionLocal
        session = SessionLocal()
        try:
            row = session.query(DwDomainTaxonomy).filter(DwDomainTaxonomy.id == taxonomy_id).first()
            if not row:
                return False
            session.delete(row)
            session.commit()
            return True
        finally:
            session.close()

    def get_l1_l2_tree(self) -> list[dict]:
        """返回 [{l1, l2_list, description}]"""
        rows = self.list_all()
        tree: dict = {}
        descs: dict = {}
        for r in rows:
            if r.l1 not in tree:
                tree[r.l1] = []
            if r.l2 and r.l2 not in tree[r.l1]:
                tree[r.l1].append(r.l2)
            if not r.l2 and r.description:
                descs[r.l1] = r.description
        items = [
            {"l1": l1, "l2_list": sorted(l2s), "description": descs.get(l1)}
            for l1, l2s in sorted(tree.items())
        ]
        return items

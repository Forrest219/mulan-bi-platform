"""API Contract Governance - 数据访问对象

命名规范：create/get/list/insert/bulk_insert
"""
from datetime import datetime
from typing import Optional
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .models import ApiContractAsset, ApiFieldChangeEvent, ApiFieldLineage, ApiFieldSnapshot


class ApiContractAssetDao:
    """API 契约资产 DAO"""

    def __init__(self, db: Session):
        self.db = db

    def create(self, asset: ApiContractAsset) -> ApiContractAsset:
        self.db.add(asset)
        self.db.flush()
        return asset

    def get(self, asset_id: UUID) -> Optional[ApiContractAsset]:
        return self.db.get(ApiContractAsset, asset_id)

    def get_by_endpoint(self, endpoint_url: str, method: str) -> Optional[ApiContractAsset]:
        return self.db.execute(
            select(ApiContractAsset).where(
                ApiContractAsset.endpoint_url == endpoint_url,
                ApiContractAsset.method == method,
            )
        ).scalar_one_or_none()

    def list(
        self,
        is_active: Optional[bool] = None,
        upstream_system: Optional[str] = None,
        owner_id: Optional[int] = None,
        page: int = 1,
        page_size: int = 20,
    ) -> dict:
        query = select(ApiContractAsset)

        if is_active is not None:
            query = query.where(ApiContractAsset.is_active == is_active)
        if upstream_system:
            query = query.where(ApiContractAsset.upstream_system == upstream_system)
        if owner_id is not None:
            query = query.where(ApiContractAsset.owner_id == owner_id)

        query = query.order_by(ApiContractAsset.created_at.desc())

        total = self.db.execute(select(func.count()).select_from(query.subquery())).scalar_one()

        query = query.offset((page - 1) * page_size).limit(page_size)
        items = list(self.db.execute(query).scalars().all())

        return {
            "items": items,
            "total": total,
            "page": page,
            "page_size": page_size,
            "pages": (total + page_size - 1) // page_size if total > 0 else 0,
        }

    def update(self, asset: ApiContractAsset) -> ApiContractAsset:
        self.db.flush()
        return asset

    def delete(self, asset_id: UUID) -> bool:
        asset = self.get(asset_id)
        if asset:
            asset.is_active = False
            self.db.flush()
            return True
        return False

    def count(self, is_active: Optional[bool] = None) -> int:
        query = select(func.count(ApiContractAsset.id))
        if is_active is not None:
            query = query.where(ApiContractAsset.is_active == is_active)
        return self.db.execute(query).scalar_one()


class ApiFieldSnapshotDao:
    """字段快照 DAO"""

    def __init__(self, db: Session):
        self.db = db

    def create(self, snapshot: ApiFieldSnapshot) -> ApiFieldSnapshot:
        self.db.add(snapshot)
        self.db.flush()
        return snapshot

    def bulk_insert(self, snapshots: list[ApiFieldSnapshot]) -> list[ApiFieldSnapshot]:
        self.db.add_all(snapshots)
        self.db.flush()
        return snapshots

    def get(self, snapshot_id: UUID) -> Optional[ApiFieldSnapshot]:
        return self.db.get(ApiFieldSnapshot, snapshot_id)

    def list_by_asset(
        self,
        asset_id: UUID,
        limit: int = 100,
        offset: int = 0,
    ) -> list[ApiFieldSnapshot]:
        return list(self.db.execute(
            select(ApiFieldSnapshot)
            .where(ApiFieldSnapshot.asset_id == asset_id)
            .order_by(ApiFieldSnapshot.snapshot_time.desc())
            .offset(offset)
            .limit(limit)
        ).scalars().all())

    def get_latest(self, asset_id: UUID) -> Optional[ApiFieldSnapshot]:
        return self.db.execute(
            select(ApiFieldSnapshot)
            .where(ApiFieldSnapshot.asset_id == asset_id)
            .order_by(ApiFieldSnapshot.snapshot_time.desc())
            .limit(1)
        ).scalar_one_or_none()

    def get_previous(
        self,
        asset_id: UUID,
        before_snapshot_id: UUID,
    ) -> Optional[ApiFieldSnapshot]:
        current = self.get(before_snapshot_id)
        if not current:
            return None

        return self.db.execute(
            select(ApiFieldSnapshot)
            .where(
                ApiFieldSnapshot.asset_id == asset_id,
                ApiFieldSnapshot.snapshot_time < current.snapshot_time,
            )
            .order_by(ApiFieldSnapshot.snapshot_time.desc())
            .limit(1)
        ).scalar_one_or_none()

    def count_by_asset(self, asset_id: UUID) -> int:
        return self.db.execute(
            select(func.count(ApiFieldSnapshot.id)).where(
                ApiFieldSnapshot.asset_id == asset_id
            )
        ).scalar_one()


class ApiFieldChangeEventDao:
    """变更事件 DAO"""

    def __init__(self, db: Session):
        self.db = db

    def create(self, event: ApiFieldChangeEvent) -> ApiFieldChangeEvent:
        self.db.add(event)
        self.db.flush()
        return event

    def bulk_insert(self, events: list[ApiFieldChangeEvent]) -> list[ApiFieldChangeEvent]:
        self.db.add_all(events)
        self.db.flush()
        return events

    def get(self, event_id: UUID) -> Optional[ApiFieldChangeEvent]:
        return self.db.get(ApiFieldChangeEvent, event_id)

    def list_by_asset(
        self,
        asset_id: UUID,
        is_resolved: Optional[bool] = None,
        severity: Optional[str] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[ApiFieldChangeEvent]:
        query = select(ApiFieldChangeEvent).where(ApiFieldChangeEvent.asset_id == asset_id)

        if is_resolved is not None:
            query = query.where(ApiFieldChangeEvent.is_resolved == is_resolved)
        if severity:
            query = query.where(ApiFieldChangeEvent.severity == severity)

        query = query.order_by(ApiFieldChangeEvent.detected_at.desc()).offset(offset).limit(limit)

        return list(self.db.execute(query).scalars().all())

    def resolve(
        self,
        event_id: UUID,
        resolved_by: str,
        resolution: str,
        resolution_note: Optional[str] = None,
    ) -> Optional[ApiFieldChangeEvent]:
        event = self.get(event_id)
        if event:
            event.is_resolved = True
            event.resolved_at = datetime.utcnow()
            event.resolved_by = resolved_by
            event.resolution = resolution
            event.resolution_note = resolution_note
            self.db.flush()
        return event

    def count_by_severity(self, asset_id: UUID) -> dict:
        """按严重级别统计"""
        result = self.db.execute(
            select(
                ApiFieldChangeEvent.severity,
                func.count(ApiFieldChangeEvent.id)
            )
            .where(ApiFieldChangeEvent.asset_id == asset_id)
            .group_by(ApiFieldChangeEvent.severity)
        ).all()
        return {row[0]: row[1] for row in result}

    def get_unresolved_count(self, asset_id: UUID) -> int:
        return self.db.execute(
            select(func.count(ApiFieldChangeEvent.id)).where(
                ApiFieldChangeEvent.asset_id == asset_id,
                ApiFieldChangeEvent.is_resolved == False,
            )
        ).scalar_one()


class ApiFieldLineageDao:
    """字段血缘 DAO"""

    def __init__(self, db: Session):
        self.db = db

    def create(self, lineage: ApiFieldLineage) -> ApiFieldLineage:
        self.db.add(lineage)
        self.db.flush()
        return lineage

    def upsert(self, lineage: ApiFieldLineage) -> ApiFieldLineage:
        existing = self.get_by_asset_and_field(lineage.asset_id, lineage.field_path)
        if existing:
            existing.source_system = lineage.source_system
            existing.source_field = lineage.source_field
            existing.transformation_rule = lineage.transformation_rule
            existing.business_description = lineage.business_description
            existing.data_steward = lineage.data_steward
            self.db.flush()
            return existing
        else:
            self.db.add(lineage)
            self.db.flush()
            return lineage

    def get(self, lineage_id: UUID) -> Optional[ApiFieldLineage]:
        return self.db.get(ApiFieldLineage, lineage_id)

    def get_by_asset_and_field(
        self,
        asset_id: UUID,
        field_path: str,
    ) -> Optional[ApiFieldLineage]:
        return self.db.execute(
            select(ApiFieldLineage).where(
                ApiFieldLineage.asset_id == asset_id,
                ApiFieldLineage.field_path == field_path,
            )
        ).scalar_one_or_none()

    def list_by_asset(
        self,
        asset_id: UUID,
        limit: int = 100,
        offset: int = 0,
    ) -> list[ApiFieldLineage]:
        return list(self.db.execute(
            select(ApiFieldLineage)
            .where(ApiFieldLineage.asset_id == asset_id)
            .order_by(ApiFieldLineage.field_path)
            .offset(offset)
            .limit(limit)
        ).scalars().all())

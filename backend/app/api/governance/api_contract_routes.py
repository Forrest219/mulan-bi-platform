"""API Contract Governance - API 路由

路由前缀: /api/governance/api-contract
"""
import logging
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.dependencies import get_current_user, require_roles
from app.api.governance.api_contract import (
    AssetListResponse,
    AssetResponse,
    ChangeEventListResponse,
    ChangeEventResponse,
    CreateAssetRequest,
    FieldDiffResponse,
    FieldDiffItem,
    FieldHistoryItem,
    FieldHistoryResponse,
    FieldLineageCreate,
    FieldLineageListResponse,
    FieldLineageResponse,
    PromoteBaselineRequest,
    ResolveChangeEventRequest,
    SamplingResponse,
    SnapshotListResponse,
    SnapshotResponse,
    UpdateAssetRequest,
)

logger = logging.getLogger(__name__)
router = APIRouter()


# ==================== Asset CRUD ====================


@router.post("/assets", response_model=AssetResponse, status_code=201)
async def create_asset(
    body: CreateAssetRequest,
    db: Session = Depends(get_db),
    current_user: dict = Depends(require_roles(["admin", "data_admin"])),
):
    """创建 API 契约资产"""
    from services.api_contract_governance.models import ApiContractAsset
    from services.api_contract_governance.dao import ApiContractAssetDao

    asset = ApiContractAsset(
        **body.model_dump(),
        created_by=current_user["id"],
    )
    dao = ApiContractAssetDao(db)
    created = dao.create(asset)
    db.commit()
    return AssetResponse.model_validate(created)


@router.get("/assets", response_model=AssetListResponse)
async def list_assets(
    is_active: Optional[bool] = None,
    upstream_system: Optional[str] = None,
    owner_id: Optional[int] = None,
    page: int = 1,
    page_size: int = 20,
    db: Session = Depends(get_db),
):
    """列出 API 契约资产"""
    from services.api_contract_governance.dao import ApiContractAssetDao

    dao = ApiContractAssetDao(db)
    result = dao.list(
        is_active=is_active,
        upstream_system=upstream_system,
        owner_id=owner_id,
        page=page,
        page_size=page_size,
    )
    return AssetListResponse(
        items=[AssetResponse.model_validate(a) for a in result["items"]],
        total=result["total"],
        page=result["page"],
        page_size=result["page_size"],
        pages=result["pages"],
    )


@router.get("/assets/{asset_id}", response_model=AssetResponse)
async def get_asset(
    asset_id: UUID,
    db: Session = Depends(get_db),
):
    """获取单个 API 契约资产"""
    from services.api_contract_governance.dao import ApiContractAssetDao

    dao = ApiContractAssetDao(db)
    asset = dao.get(asset_id)
    if not asset:
        raise HTTPException(status_code=404, detail="Asset not found")
    return AssetResponse.model_validate(asset)


@router.patch("/assets/{asset_id}", response_model=AssetResponse)
async def update_asset(
    asset_id: UUID,
    body: UpdateAssetRequest,
    db: Session = Depends(get_db),
    current_user: dict = Depends(require_roles(["admin", "data_admin"])),
):
    """更新 API 契约资产"""
    from services.api_contract_governance.dao import ApiContractAssetDao

    dao = ApiContractAssetDao(db)
    asset = dao.get(asset_id)
    if not asset:
        raise HTTPException(status_code=404, detail="Asset not found")

    updates = body.model_dump(exclude_unset=True)
    for key, value in updates.items():
        setattr(asset, key, value)

    dao.update(asset)
    db.commit()
    return AssetResponse.model_validate(asset)


@router.delete("/assets/{asset_id}")
async def delete_asset(
    asset_id: UUID,
    db: Session = Depends(get_db),
    current_user: dict = Depends(require_roles(["admin", "data_admin"])),
):
    """删除 API 契约资产（软删除）"""
    from services.api_contract_governance.dao import ApiContractAssetDao

    dao = ApiContractAssetDao(db)
    deleted = dao.delete(asset_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Asset not found")
    db.commit()
    return {"message": "Asset deleted"}


# ==================== Sampling ====================


@router.post("/assets/{asset_id}/sample", response_model=SamplingResponse)
async def trigger_sampling(
    asset_id: UUID,
    db: Session = Depends(get_db),
    current_user: dict = Depends(require_roles(["admin", "data_admin"])),
):
    """手动触发采样"""
    from services.api_contract_governance.orchestrator import ApiContractGovernanceOrchestrator

    orch = ApiContractGovernanceOrchestrator(db)
    result = orch.sample_only(asset_id)

    if not result.success:
        raise HTTPException(status_code=400, detail=result.error_message)

    return SamplingResponse(
        success=result.success,
        snapshot_id=result.snapshot_id,
        fields_count=result.fields_count,
        message=result.error_message if not result.success else None,
    )


@router.post("/assets/{asset_id}/promote-baseline")
async def promote_to_baseline(
    asset_id: UUID,
    body: PromoteBaselineRequest,
    db: Session = Depends(get_db),
    current_user: dict = Depends(require_roles(["admin", "data_admin"])),
):
    """将指定快照提升为基线"""
    from services.api_contract_governance.orchestrator import ApiContractGovernanceOrchestrator

    orch = ApiContractGovernanceOrchestrator(db)
    success = orch.promote_to_baseline(asset_id, body.snapshot_id)

    if not success:
        raise HTTPException(status_code=404, detail="Asset or snapshot not found")

    db.commit()
    return {"message": "Baseline promoted"}


# ==================== Snapshots ====================


@router.get("/assets/{asset_id}/snapshots", response_model=SnapshotListResponse)
async def list_snapshots(
    asset_id: UUID,
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
):
    """列出资产的快照历史"""
    from services.api_contract_governance.dao import ApiFieldSnapshotDao

    dao = ApiFieldSnapshotDao(db)
    snapshots = dao.list_by_asset(asset_id, limit=limit, offset=offset)
    total = dao.count_by_asset(asset_id)

    return SnapshotListResponse(
        items=[SnapshotResponse.model_validate(s) for s in snapshots],
        total=total,
    )


# ==================== Field History ====================


@router.get("/assets/{asset_id}/field-history", response_model=list[FieldHistoryResponse])
async def get_field_history(
    asset_id: UUID,
    field_path: Optional[str] = None,
    limit: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
):
    """获取字段历史"""
    from services.api_contract_governance.dao import ApiFieldSnapshotDao

    dao = ApiFieldSnapshotDao(db)
    snapshots = dao.list_by_asset(asset_id, limit=limit)

    # 按 field_path 分组
    field_histories: dict[str, list] = {}

    for snapshot in snapshots:
        fields_schema = snapshot.fields_schema
        for path, field_data in fields_schema.items():
            if field_path and path != field_path:
                continue

            if path not in field_histories:
                field_histories[path] = []

            field_histories[path].append(FieldHistoryItem(
                field_path=path,
                field_type=field_data.get("type"),
                value_samples=field_data.get("value_samples", []),
                enum_values=field_data.get("enum_values"),
                snapshot_time=snapshot.snapshot_time.strftime("%Y-%m-%d %H:%M:%S"),
            ))

    return [
        FieldHistoryResponse(asset_id=asset_id, field_path=path, history=items)
        for path, items in field_histories.items()
    ]


# ==================== Field Diff ====================


@router.get("/assets/{asset_id}/field-diff", response_model=Optional[FieldDiffResponse])
async def get_field_diff(
    asset_id: UUID,
    from_snapshot_id: UUID = Query(...),
    to_snapshot_id: UUID = Query(...),
    db: Session = Depends(get_db),
):
    """获取字段差异"""
    from services.api_contract_governance.orchestrator import ApiContractGovernanceOrchestrator

    orch = ApiContractGovernanceOrchestrator(db)
    comparison = orch.compare_snapshots(asset_id, from_snapshot_id, to_snapshot_id)

    if not comparison.result:
        return None

    result = comparison.result
    return FieldDiffResponse(
        asset_id=asset_id,
        from_snapshot_id=from_snapshot_id,
        to_snapshot_id=to_snapshot_id,
        changes=[
            FieldDiffItem(
                change_type=c.change_type.value,
                field_path=c.field_path,
                from_value=c.from_value,
                to_value=c.to_value,
                severity=c.severity.value,
                description=c.description,
            )
            for c in result.changes
        ],
        breaking_changes_count=len(result.breaking_changes),
        non_breaking_changes_count=len(result.non_breaking_changes),
        compatibility_score=result.compatibility_score,
    )


# ==================== Change Events ====================


@router.get("/assets/{asset_id}/change-events", response_model=ChangeEventListResponse)
async def list_change_events(
    asset_id: UUID,
    is_resolved: Optional[bool] = None,
    severity: Optional[str] = None,
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
):
    """列出变更事件"""
    from services.api_contract_governance.dao import ApiFieldChangeEventDao

    dao = ApiFieldChangeEventDao(db)
    events = dao.list_by_asset(
        asset_id,
        is_resolved=is_resolved,
        severity=severity,
        limit=limit,
        offset=offset,
    )
    total = dao.get_unresolved_count(asset_id) if is_resolved is False else len(events)

    return ChangeEventListResponse(
        items=[ChangeEventResponse.model_validate(e) for e in events],
        total=total,
    )


@router.post("/change-events/{event_id}/resolve", response_model=ChangeEventResponse)
async def resolve_change_event(
    event_id: UUID,
    body: ResolveChangeEventRequest,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """标记事件为已处理"""
    from services.api_contract_governance.dao import ApiFieldChangeEventDao

    dao = ApiFieldChangeEventDao(db)
    event = dao.resolve(
        event_id,
        resolved_by=current_user.get("username", str(current_user["id"])),
        resolution=body.resolution,
        resolution_note=body.resolution_note,
    )

    if not event:
        raise HTTPException(status_code=404, detail="Event not found")

    db.commit()
    return ChangeEventResponse.model_validate(event)


# ==================== Field Lineage ====================


@router.post("/assets/{asset_id}/field-lineage", response_model=FieldLineageResponse, status_code=201)
async def create_field_lineage(
    asset_id: UUID,
    body: FieldLineageCreate,
    db: Session = Depends(get_db),
    current_user: dict = Depends(require_roles(["admin", "data_admin"])),
):
    """创建字段血缘记录"""
    from services.api_contract_governance.models import ApiFieldLineage
    from services.api_contract_governance.dao import ApiFieldLineageDao

    lineage = ApiFieldLineage(
        asset_id=asset_id,
        **body.model_dump(),
        created_by=current_user["id"],
    )
    dao = ApiFieldLineageDao(db)
    created = dao.create(lineage)
    db.commit()
    return FieldLineageResponse.model_validate(created)


@router.get("/assets/{asset_id}/field-lineage", response_model=FieldLineageListResponse)
async def list_field_lineage(
    asset_id: UUID,
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
):
    """列出字段血缘记录"""
    from services.api_contract_governance.dao import ApiFieldLineageDao

    dao = ApiFieldLineageDao(db)
    lineages = dao.list_by_asset(asset_id, limit=limit, offset=offset)

    return FieldLineageListResponse(
        items=[FieldLineageResponse.model_validate(l) for l in lineages],
        total=len(lineages),
    )

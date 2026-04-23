"""API Contract Governance 异步任务

Celery 任务入口
"""
import logging
from uuid import UUID

from celery import shared_task

logger = logging.getLogger(__name__)


@shared_task(
    bind=True,
    name="services.tasks.api_contract_tasks.sample_asset",
    soft_time_limit=300,
    time_limit=360,
    acks_late=True,
    max_retries=3,
)
def sample_asset(self, asset_id: str):
    """
    对指定资产执行采样

    Args:
        asset_id: 资产 ID (str UUID)
    """
    from app.core.database import SessionLocal
    from services.api_contract_governance.orchestrator import ApiContractGovernanceOrchestrator

    with SessionLocal() as db:
        orch = ApiContractGovernanceOrchestrator(db)
        result = orch.sample_only(UUID(asset_id))
        db.commit()
        return {
            "asset_id": asset_id,
            "success": result.success,
            "snapshot_id": str(result.snapshot_id) if result.snapshot_id else None,
            "fields_count": result.fields_count,
            "error": result.error_message,
        }


@shared_task(
    bind=True,
    name="services.tasks.api_contract_tasks.run_cycle",
    soft_time_limit=300,
    time_limit=360,
    acks_late=True,
    max_retries=3,
)
def run_cycle(self, asset_id: str):
    """
    执行完整的采样-比对-事件发射周期

    Args:
        asset_id: 资产 ID (str UUID)
    """
    from app.core.database import SessionLocal
    from services.api_contract_governance.orchestrator import ApiContractGovernanceOrchestrator

    with SessionLocal() as db:
        orch = ApiContractGovernanceOrchestrator(db)
        result = orch.run_cycle(UUID(asset_id))
        db.commit()
        return {
            "asset_id": asset_id,
            "success": result.success,
            "snapshot_id": str(result.snapshot_id) if result.snapshot_id else None,
            "fields_count": result.fields_count,
            "error": result.error_message,
        }


@shared_task(
    bind=True,
    name="services.tasks.api_contract_tasks.compare_snapshots",
    soft_time_limit=120,
    time_limit=180,
    acks_late=True,
    max_retries=2,
)
def compare_snapshots(self, asset_id: str, from_snapshot_id: str, to_snapshot_id: str):
    """
    比对两个快照

    Args:
        asset_id: 资产 ID
        from_snapshot_id: 旧快照 ID
        to_snapshot_id: 新快照 ID
    """
    from app.core.database import SessionLocal
    from services.api_contract_governance.orchestrator import ApiContractGovernanceOrchestrator

    with SessionLocal() as db:
        orch = ApiContractGovernanceOrchestrator(db)
        result = orch.compare_snapshots(
            UUID(asset_id),
            UUID(from_snapshot_id),
            UUID(to_snapshot_id),
        )
        db.commit()
        return {
            "asset_id": asset_id,
            "has_changes": result.has_changes,
            "compatibility_score": result.result.compatibility_score if result.result else None,
        }


@shared_task(
    bind=True,
    name="services.tasks.api_contract_tasks.run_cycle_batch",
    soft_time_limit=1800,
    time_limit=2000,
    acks_late=True,
    max_retries=1,
)
def run_cycle_batch(self, asset_ids: list[str]):
    """
    批量执行采样-比对周期

    Args:
        asset_ids: 资产 ID 列表
    """
    from app.core.database import SessionLocal
    from services.api_contract_governance.orchestrator import ApiContractGovernanceOrchestrator

    results = []
    with SessionLocal() as db:
        orch = ApiContractGovernanceOrchestrator(db)
        for asset_id in asset_ids:
            try:
                result = orch.run_cycle(UUID(asset_id))
                db.commit()
                results.append({
                    "asset_id": asset_id,
                    "success": result.success,
                    "fields_count": result.fields_count,
                })
            except Exception as e:
                logger.exception("Failed to run cycle for asset %s", asset_id)
                results.append({
                    "asset_id": asset_id,
                    "success": False,
                    "error": str(e),
                })
    return {"results": results, "total": len(asset_ids)}

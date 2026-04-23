"""DQC 数据质量核心流水线 API

路由前缀：/api/dqc
认证：统一 get_current_user；写操作 admin/data_admin
"""
import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.dependencies import get_current_admin, get_current_user, require_roles
from app.core.errors import DQCError
from services.datasources.models import DataSourceDatabase
from services.dqc.constants import (
    ALL_DIMENSIONS,
    ALL_RULE_TYPES,
    DEFAULT_DIMENSION_WEIGHTS,
    DEFAULT_SIGNAL_THRESHOLDS,
    DIMENSION_RULE_COMPATIBILITY,
    RuleType,
    WEIGHT_SUM_TOLERANCE,
)
from services.dqc.database import DqcDatabase
from services.dqc.models import DqcMonitoredAsset
from services.tasks.dqc_tasks import (
    profile_and_suggest_task,
    run_for_asset_task,
)
from services.dqc.orchestrator import is_cycle_locked

logger = logging.getLogger(__name__)
router = APIRouter()


# ==================== 请求/响应模型 ====================


class CreateAssetRequest(BaseModel):
    datasource_id: int
    schema_name: str = Field(..., max_length=128)
    table_name: str = Field(..., max_length=128)
    display_name: Optional[str] = Field(None, max_length=256)
    description: Optional[str] = None
    dimension_weights: Optional[Dict[str, float]] = None
    signal_thresholds: Optional[Dict[str, float]] = None
    auto_suggest_rules: bool = True


class UpdateAssetRequest(BaseModel):
    display_name: Optional[str] = Field(None, max_length=256)
    description: Optional[str] = None
    dimension_weights: Optional[Dict[str, float]] = None
    signal_thresholds: Optional[Dict[str, float]] = None
    status: Optional[str] = None


class CreateRuleRequest(BaseModel):
    name: str = Field(..., max_length=256)
    description: Optional[str] = None
    dimension: str = Field(..., max_length=32)
    rule_type: str = Field(..., max_length=32)
    rule_config: Dict[str, Any] = Field(default_factory=dict)
    is_active: bool = True


class UpdateRuleRequest(BaseModel):
    name: Optional[str] = Field(None, max_length=256)
    description: Optional[str] = None
    rule_config: Optional[Dict[str, Any]] = None
    is_active: Optional[bool] = None


class SuggestRulesRequest(BaseModel):
    dimensions: Optional[List[str]] = None
    max_rules: int = 5


class RunCycleRequest(BaseModel):
    scope: str = "full"
    asset_ids: Optional[List[int]] = None


# ==================== 工具函数 ====================


def _validate_weights(weights: Optional[Dict[str, float]]) -> None:
    if not weights:
        return
    for dim in weights:
        if dim not in ALL_DIMENSIONS:
            raise DQCError.invalid_dimension_weights(
                {"reason": "unknown_dimension", "dimension": dim}
            )
    for dim, value in weights.items():
        if value is None or float(value) < 0:
            raise DQCError.invalid_dimension_weights(
                {"reason": "negative_or_null", "dimension": dim, "value": value}
            )
    total = sum(float(v) for v in weights.values())
    if abs(total - 1.0) > WEIGHT_SUM_TOLERANCE:
        raise DQCError.invalid_dimension_weights(
            {
                "reason": "sum_mismatch",
                "submitted_weights": weights,
                "sum": round(total, 4),
                "expected": 1.0,
                "tolerance": WEIGHT_SUM_TOLERANCE,
            }
        )


def _validate_thresholds(thresholds: Optional[Dict[str, float]]) -> None:
    if not thresholds:
        return
    p0 = float(thresholds.get("p0_score", DEFAULT_SIGNAL_THRESHOLDS["p0_score"]))
    p1 = float(thresholds.get("p1_score", DEFAULT_SIGNAL_THRESHOLDS["p1_score"]))
    if p0 >= p1:
        raise DQCError.invalid_signal_thresholds(
            {"reason": "p0_score_must_be_less_than_p1_score", "p0_score": p0, "p1_score": p1}
        )
    for key in ("p0_score", "p1_score", "confidence_p0", "confidence_p1"):
        v = thresholds.get(key)
        if v is None:
            continue
        v = float(v)
        if v < 0 or v > 100:
            raise DQCError.invalid_signal_thresholds(
                {"reason": "out_of_range", "key": key, "value": v}
            )


def _validate_rule_type_and_dim(dimension: str, rule_type: str) -> None:
    if rule_type not in ALL_RULE_TYPES:
        raise DQCError.unsupported_rule_type(
            {"rule_type": rule_type, "supported": ALL_RULE_TYPES}
        )
    if dimension not in ALL_DIMENSIONS:
        raise DQCError.dimension_rule_incompatible(
            {"reason": "unknown_dimension", "dimension": dimension}
        )
    allowed = DIMENSION_RULE_COMPATIBILITY.get(dimension, set())
    if rule_type not in allowed:
        raise DQCError.dimension_rule_incompatible(
            {
                "dimension": dimension,
                "rule_type": rule_type,
                "allowed_rule_types": sorted(allowed),
            }
        )


def _validate_rule_config(rule_type: str, config: Dict[str, Any]) -> None:
    """MVP 仅校验已实现的 4 类规则"""
    if rule_type == "null_rate":
        if not config.get("column"):
            raise DQCError.invalid_rule_config({"reason": "require_column"})
        if config.get("max_rate") is None:
            raise DQCError.invalid_rule_config({"reason": "require_max_rate"})
        rate = float(config["max_rate"])
        if rate < 0 or rate > 1:
            raise DQCError.invalid_rule_config({"reason": "max_rate_out_of_range", "value": rate})
    elif rule_type == "uniqueness":
        cols = config.get("columns")
        if not isinstance(cols, list) or not cols:
            raise DQCError.invalid_rule_config({"reason": "require_columns_list"})
    elif rule_type == "range_check":
        if not config.get("column"):
            raise DQCError.invalid_rule_config({"reason": "require_column"})
        check_mode = (config.get("check_mode") or "min_max_all").lower()
        if check_mode not in ("avg", "min_max_all"):
            raise DQCError.invalid_rule_config({"reason": "invalid_check_mode", "value": check_mode})
        if config.get("min") is None and config.get("max") is None:
            raise DQCError.invalid_rule_config({"reason": "require_min_or_max"})
    elif rule_type == "freshness":
        if not config.get("column"):
            raise DQCError.invalid_rule_config({"reason": "require_column"})
        if config.get("max_age_hours") is None:
            raise DQCError.invalid_rule_config({"reason": "require_max_age_hours"})
    elif rule_type == "regex":
        if not config.get("column") or not config.get("pattern"):
            raise DQCError.invalid_rule_config({"reason": "require_column_and_pattern"})
    elif rule_type == "custom_sql":
        if not config.get("sql"):
            raise DQCError.invalid_rule_config({"reason": "require_sql"})
    elif rule_type == RuleType.VOLUME_ANOMALY.value:
        direction = config.get("direction", "drop").lower()
        if direction not in ("drop", "rise", "both"):
            raise DQCError.invalid_rule_config({"reason": "invalid_direction", "value": direction})
        threshold = config.get("threshold_pct", 0.80)
        if not (0 < threshold <= 1):
            raise DQCError.invalid_rule_config({"reason": "threshold_pct_out_of_range", "value": threshold})
        window = config.get("comparison_window", "1d")
        if window not in ("1d", "7d", "30d"):
            raise DQCError.invalid_rule_config({"reason": "invalid_comparison_window", "value": window})
    elif rule_type == RuleType.TABLE_COUNT_COMPARE.value:
        if not config.get("target_schema"):
            raise DQCError.invalid_rule_config({"reason": "require_target_schema"})
        if not config.get("target_table"):
            raise DQCError.invalid_rule_config({"reason": "require_target_table"})
        tolerance = config.get("tolerance_pct", 0.0)
        if not (0.0 <= tolerance <= 1.0):
            raise DQCError.invalid_rule_config({"reason": "tolerance_pct_out_of_range", "value": tolerance})


def _check_asset_ownership(asset: DqcMonitoredAsset, current_user: dict) -> None:
    if current_user["role"] == "admin":
        return
    if asset.owner_id != current_user["id"]:
        raise DQCError.not_asset_owner()


def _serialize_asset_with_snapshot(dao: DqcDatabase, db: Session, asset: DqcMonitoredAsset) -> Dict[str, Any]:
    snapshot = dao.get_latest_snapshot(db, asset.id)
    counts = dao.count_rules_by_asset(db, asset.id)
    ds_db = DataSourceDatabase()
    ds = ds_db.get(db, asset.datasource_id)

    snap_info = None
    if snapshot:
        snap_info = {
            "cycle_id": str(snapshot.cycle_id) if snapshot.cycle_id else None,
            "confidence_score": snapshot.confidence_score,
            "signal": snapshot.signal,
            "dimension_scores": snapshot.dimension_scores,
            "dimension_signals": snapshot.dimension_signals,
            "computed_at": snapshot.computed_at.strftime("%Y-%m-%d %H:%M:%S")
            if snapshot.computed_at
            else None,
        }

    dim_snapshot = None
    if snapshot and snapshot.dimension_scores and snapshot.dimension_signals:
        dim_snapshot = {
            dim: {
                "score": snapshot.dimension_scores.get(dim),
                "signal": snapshot.dimension_signals.get(dim),
            }
            for dim in ALL_DIMENSIONS
        }

    return {
        **asset.to_dict(),
        "datasource_name": ds.name if ds else None,
        "current_signal": snapshot.signal if snapshot else None,
        "current_confidence_score": snapshot.confidence_score if snapshot else None,
        "dimension_snapshot": dim_snapshot,
        "current_snapshot": snap_info,
        "last_computed_at": snap_info["computed_at"] if snap_info else None,
        "rules_count": counts["total"],
        "active_rules_count": counts["active"],
    }


# ==================== Assets ====================


@router.get("/assets")
async def list_assets(
    request: Request,
    datasource_id: Optional[int] = None,
    status: Optional[str] = None,
    signal: Optional[str] = None,
    page: int = 1,
    page_size: int = 20,
    db: Session = Depends(get_db),
):
    get_current_user(request, db)
    page_size = min(max(1, page_size), 100)
    dao = DqcDatabase()
    result = dao.list_assets(
        db,
        datasource_id=datasource_id,
        status=status,
        page=page,
        page_size=page_size,
    )
    items = [_serialize_asset_with_snapshot(dao, db, asset) for asset in result["items"]]
    if signal:
        items = [i for i in items if i.get("current_signal") == signal]
    return {
        "items": items,
        "total": result["total"],
        "page": result["page"],
        "page_size": result["page_size"],
        "pages": result["pages"],
    }


@router.post("/assets")
async def create_asset(
    body: CreateAssetRequest,
    current_user: dict = Depends(require_roles(["admin", "data_admin"])),
    db: Session = Depends(get_db),
):
    dao = DqcDatabase()
    ds_db = DataSourceDatabase()

    ds = ds_db.get(db, body.datasource_id)
    if not ds or not ds.is_active:
        raise DQCError.datasource_not_found_or_inactive({"datasource_id": body.datasource_id})

    if current_user["role"] != "admin" and ds.owner_id != current_user["id"]:
        raise DQCError.not_asset_owner()

    _validate_weights(body.dimension_weights)
    _validate_thresholds(body.signal_thresholds)

    existing = dao.get_asset_by_natural_key(db, body.datasource_id, body.schema_name, body.table_name)
    if existing:
        raise DQCError.asset_already_exists(
            {
                "datasource_id": body.datasource_id,
                "schema_name": body.schema_name,
                "table_name": body.table_name,
                "existing_id": existing.id,
            }
        )

    weights = body.dimension_weights or DEFAULT_DIMENSION_WEIGHTS
    thresholds = body.signal_thresholds or DEFAULT_SIGNAL_THRESHOLDS

    asset = dao.create_asset(
        db,
        datasource_id=body.datasource_id,
        schema_name=body.schema_name,
        table_name=body.table_name,
        display_name=body.display_name,
        description=body.description,
        dimension_weights=weights,
        signal_thresholds=thresholds,
        owner_id=current_user["id"],
        created_by=current_user["id"],
        status="enabled",
    )
    db.commit()
    db.refresh(asset)

    profiling_task_id: Optional[str] = None
    if body.auto_suggest_rules:
        try:
            task = profile_and_suggest_task.delay(asset.id)
            profiling_task_id = task.id
        except Exception:
            logger.exception("failed to enqueue profile_and_suggest_task for asset %s", asset.id)

    return {
        "asset": asset.to_dict(),
        "profiling_task_id": profiling_task_id,
        "message": "监控已开启，正在对表进行 Profiling" if profiling_task_id else "监控已开启",
    }


@router.get("/assets/{asset_id}")
async def get_asset(asset_id: int, request: Request, db: Session = Depends(get_db)):
    get_current_user(request, db)
    dao = DqcDatabase()
    asset = dao.get_asset(db, asset_id)
    if not asset:
        raise DQCError.asset_not_found()
    data = _serialize_asset_with_snapshot(dao, db, asset)

    profile = asset.profile_json
    data["profile"] = (
        {
            "row_count": profile.get("row_count"),
            "columns_count": len(profile.get("columns") or []),
            "profiled_at": profile.get("profiled_at"),
        }
        if isinstance(profile, dict)
        else None
    )

    snapshots = dao.list_snapshots(db, asset.id, limit=14)
    data["recent_trend"] = [
        {
            "date": snap.computed_at.strftime("%Y-%m-%d") if snap.computed_at else None,
            "confidence_score": snap.confidence_score,
        }
        for snap in reversed(snapshots)
    ]
    counts = dao.count_rules_by_asset(db, asset.id)
    data["rules_total"] = counts["total"]
    data["rules_active"] = counts["active"]
    return data


@router.patch("/assets/{asset_id}")
async def update_asset(
    asset_id: int,
    body: UpdateAssetRequest,
    current_user: dict = Depends(require_roles(["admin", "data_admin"])),
    db: Session = Depends(get_db),
):
    dao = DqcDatabase()
    asset = dao.get_asset(db, asset_id)
    if not asset:
        raise DQCError.asset_not_found()
    _check_asset_ownership(asset, current_user)

    if body.dimension_weights is not None:
        _validate_weights(body.dimension_weights)
    if body.signal_thresholds is not None:
        merged = dict(asset.signal_thresholds or DEFAULT_SIGNAL_THRESHOLDS)
        merged.update(body.signal_thresholds)
        _validate_thresholds(merged)
        body = body.model_copy(update={"signal_thresholds": merged})

    updates = body.model_dump(exclude_unset=True, exclude_none=True)
    if updates:
        dao.update_asset(db, asset_id, **updates)
        db.commit()

    asset = dao.get_asset(db, asset_id)
    return _serialize_asset_with_snapshot(dao, db, asset)


@router.delete("/assets/{asset_id}")
async def delete_asset(
    asset_id: int,
    current_user: dict = Depends(require_roles(["admin", "data_admin"])),
    db: Session = Depends(get_db),
):
    dao = DqcDatabase()
    asset = dao.get_asset(db, asset_id)
    if not asset:
        raise DQCError.asset_not_found()
    _check_asset_ownership(asset, current_user)
    dao.disable_asset(db, asset_id)
    db.commit()
    return {"message": "监控已停止", "asset_id": asset_id}


# ==================== Rules ====================


@router.get("/assets/{asset_id}/rules")
async def list_rules(
    asset_id: int,
    request: Request,
    dimension: Optional[str] = None,
    is_active: Optional[bool] = None,
    is_system_suggested: Optional[bool] = None,
    db: Session = Depends(get_db),
):
    get_current_user(request, db)
    dao = DqcDatabase()
    asset = dao.get_asset(db, asset_id)
    if not asset:
        raise DQCError.asset_not_found()
    rules = dao.list_rules_by_asset(
        db,
        asset_id,
        dimension=dimension,
        is_active=is_active,
        is_system_suggested=is_system_suggested,
    )
    return {"items": [r.to_dict() for r in rules], "total": len(rules)}


@router.post("/assets/{asset_id}/rules")
async def create_rule(
    asset_id: int,
    body: CreateRuleRequest,
    current_user: dict = Depends(require_roles(["admin", "data_admin"])),
    db: Session = Depends(get_db),
):
    dao = DqcDatabase()
    asset = dao.get_asset(db, asset_id)
    if not asset:
        raise DQCError.asset_not_found()
    _check_asset_ownership(asset, current_user)

    _validate_rule_type_and_dim(body.dimension, body.rule_type)
    _validate_rule_config(body.rule_type, body.rule_config or {})

    if dao.rule_name_exists(db, asset_id, body.name):
        raise DQCError.rule_already_exists({"asset_id": asset_id, "name": body.name})

    rule = dao.create_rule(
        db,
        asset_id=asset_id,
        name=body.name,
        description=body.description,
        dimension=body.dimension,
        rule_type=body.rule_type,
        rule_config=body.rule_config or {},
        is_active=body.is_active,
        is_system_suggested=False,
        created_by=current_user["id"],
    )
    db.commit()
    db.refresh(rule)
    return rule.to_dict()


@router.patch("/assets/{asset_id}/rules/{rule_id}")
async def update_rule(
    asset_id: int,
    rule_id: int,
    body: UpdateRuleRequest,
    current_user: dict = Depends(require_roles(["admin", "data_admin"])),
    db: Session = Depends(get_db),
):
    dao = DqcDatabase()
    asset = dao.get_asset(db, asset_id)
    if not asset:
        raise DQCError.asset_not_found()
    _check_asset_ownership(asset, current_user)

    rule = dao.get_rule(db, rule_id)
    if not rule or rule.asset_id != asset_id:
        raise DQCError.rule_not_found()

    updates = body.model_dump(exclude_unset=True, exclude_none=True)
    if "rule_config" in updates:
        _validate_rule_config(rule.rule_type, updates["rule_config"])
    if "name" in updates and dao.rule_name_exists(db, asset_id, updates["name"], exclude_id=rule_id):
        raise DQCError.rule_already_exists({"asset_id": asset_id, "name": updates["name"]})

    updates["updated_by"] = current_user["id"]
    dao.update_rule(db, rule_id, **updates)
    db.commit()

    rule = dao.get_rule(db, rule_id)
    return rule.to_dict()


@router.delete("/assets/{asset_id}/rules/{rule_id}")
async def delete_rule(
    asset_id: int,
    rule_id: int,
    current_user: dict = Depends(require_roles(["admin", "data_admin"])),
    db: Session = Depends(get_db),
):
    dao = DqcDatabase()
    asset = dao.get_asset(db, asset_id)
    if not asset:
        raise DQCError.asset_not_found()
    _check_asset_ownership(asset, current_user)

    rule = dao.get_rule(db, rule_id)
    if not rule or rule.asset_id != asset_id:
        raise DQCError.rule_not_found()

    dao.delete_rule(db, rule_id)
    db.commit()
    return {"message": "规则已删除", "rule_id": rule_id}


@router.post("/assets/{asset_id}/rules/suggest")
async def suggest_rules(
    asset_id: int,
    body: Optional[SuggestRulesRequest] = None,
    current_user: dict = Depends(require_roles(["admin", "data_admin"])),
    db: Session = Depends(get_db),
):
    dao = DqcDatabase()
    asset = dao.get_asset(db, asset_id)
    if not asset:
        raise DQCError.asset_not_found()
    _check_asset_ownership(asset, current_user)

    # V1 开放，MVP 返回空数组
    return {
        "analysis_id": None,
        "suggested_rules": [],
        "message": "V1 开放",
    }


# ==================== Scores / Snapshots / Analyses ====================


@router.get("/assets/{asset_id}/scores")
async def list_scores(
    asset_id: int,
    request: Request,
    dimension: Optional[str] = None,
    start: Optional[str] = None,
    end: Optional[str] = None,
    limit: int = 100,
    db: Session = Depends(get_db),
):
    get_current_user(request, db)
    dao = DqcDatabase()
    asset = dao.get_asset(db, asset_id)
    if not asset:
        raise DQCError.asset_not_found()
    start_dt = datetime.fromisoformat(start) if start else None
    end_dt = datetime.fromisoformat(end) if end else None
    limit = min(max(1, limit), 500)
    rows = dao.list_dimension_scores(
        db, asset_id, dimension=dimension, start=start_dt, end=end_dt, limit=limit
    )
    return {"items": [r.to_dict() for r in rows], "total": len(rows)}


@router.get("/assets/{asset_id}/snapshots")
async def list_snapshots(
    asset_id: int,
    request: Request,
    start: Optional[str] = None,
    end: Optional[str] = None,
    limit: int = 30,
    db: Session = Depends(get_db),
):
    get_current_user(request, db)
    dao = DqcDatabase()
    asset = dao.get_asset(db, asset_id)
    if not asset:
        raise DQCError.asset_not_found()
    start_dt = datetime.fromisoformat(start) if start else None
    end_dt = datetime.fromisoformat(end) if end else None
    limit = min(max(1, limit), 500)
    rows = dao.list_snapshots(db, asset_id, start=start_dt, end=end_dt, limit=limit)
    return {"items": [r.to_dict() for r in rows], "total": len(rows)}


@router.get("/assets/{asset_id}/analyses")
async def list_analyses(
    asset_id: int,
    request: Request,
    trigger: Optional[str] = None,
    limit: int = 20,
    db: Session = Depends(get_db),
):
    get_current_user(request, db)
    dao = DqcDatabase()
    asset = dao.get_asset(db, asset_id)
    if not asset:
        raise DQCError.asset_not_found()
    limit = min(max(1, limit), 100)
    rows = dao.list_llm_analyses_for_asset(db, asset_id, trigger=trigger, limit=limit)
    return {"items": [r.to_dict() for r in rows], "total": len(rows)}


# ==================== Cycles ====================


@router.post("/cycles/run")
async def run_cycle(
    body: RunCycleRequest,
    current_user: dict = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    dao = DqcDatabase()
    if body.asset_ids:
        if body.scope in ("hourly_light", "incremental"):
            raise DQCError.invalid_parameter("asset_ids 和 scope 不可同时指定")
    if is_cycle_locked(body.scope):
        raise DQCError.cycle_in_progress()

    if body.asset_ids:
        task_ids = []
        for aid in body.asset_ids:
            t = run_for_asset_task.delay(aid, "manual", current_user["id"])
            task_ids.append(t.id)
        return {
            "task_ids": task_ids,
            "message": "DQC cycle 已启动",
        }

    from services.tasks.dqc_tasks import run_daily_full_cycle, run_hourly_light_cycle

    if body.scope == "hourly_light":
        task = run_hourly_light_cycle.delay()
    else:
        task = run_daily_full_cycle.delay()
    return {"task_id": task.id, "message": "DQC cycle 已启动"}


@router.get("/cycles")
async def list_cycles(
    request: Request,
    status: Optional[str] = None,
    scope: Optional[str] = None,
    start: Optional[str] = None,
    end: Optional[str] = None,
    page: int = 1,
    page_size: int = 20,
    db: Session = Depends(get_db),
):
    get_current_user(request, db)
    dao = DqcDatabase()
    page_size = min(max(1, page_size), 100)
    start_dt = datetime.fromisoformat(start) if start else None
    end_dt = datetime.fromisoformat(end) if end else None
    result = dao.list_cycles(
        db,
        status=status,
        scope=scope,
        start=start_dt,
        end=end_dt,
        page=page,
        page_size=page_size,
    )
    return {
        "items": [c.to_dict() for c in result["items"]],
        "total": result["total"],
        "page": result["page"],
        "page_size": result["page_size"],
        "pages": result["pages"],
    }


@router.get("/cycles/{cycle_id}")
async def get_cycle(cycle_id: str, request: Request, db: Session = Depends(get_db)):
    from uuid import UUID

    get_current_user(request, db)
    dao = DqcDatabase()
    try:
        uuid_obj = UUID(cycle_id)
    except ValueError:
        raise DQCError.cycle_not_found()
    cycle = dao.get_cycle(db, uuid_obj)
    if not cycle:
        raise DQCError.cycle_not_found()
    snapshots = dao.get_snapshots_for_cycle(db, uuid_obj)
    asset_summaries = [
        {
            "asset_id": snap.asset_id,
            "signal": snap.signal,
            "confidence_score": snap.confidence_score,
        }
        for snap in snapshots
    ]
    data = cycle.to_dict()
    data["asset_summaries"] = asset_summaries
    return data


# ==================== Dashboard ====================


@router.get("/dashboard")
async def dashboard(request: Request, db: Session = Depends(get_db)):
    get_current_user(request, db)
    dao = DqcDatabase()
    summary = dao.get_dashboard_summary(db)
    top_failing = dao.get_top_failing_assets(db, limit=10)
    dim_avg = dao.get_dimension_avg(db)
    recent_changes = dao.get_recent_signal_changes(db, hours=24, limit=20)
    return {
        "summary": {k: v for k, v in summary.items() if k != "signal_distribution"},
        "signal_distribution": summary.get("signal_distribution", {}),
        "dimension_avg": dim_avg,
        "top_failing_assets": top_failing,
        "recent_signal_changes": recent_changes,
    }

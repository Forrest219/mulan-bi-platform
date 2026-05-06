"""DQC 数据质量核心流水线 API

路由前缀：/api/dqc
认证：统一 get_current_user；写操作 admin/data_admin
"""
import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
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
    RULE_TYPE_TO_DIMENSION,
    RuleType,
    WEIGHT_SUM_TOLERANCE,
)
from services.dqc.database import DqcDatabase
from services.dqc.models import DqcMonitoredAsset, DqcQualityRule, DqcRuleResult
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
    use_llm: bool = False


class CreateTemplateRequest(BaseModel):
    name: str = Field(..., max_length=256)
    description: Optional[str] = None
    dimension: str = Field(..., max_length=32)
    rule_type: str = Field(..., max_length=32)
    default_config: Dict[str, Any] = Field(default_factory=dict)
    match_condition: Dict[str, Any] = Field(default_factory=dict)
    severity: str = "MEDIUM"
    rule_package: Optional[str] = Field(None, max_length=8)
    enabled: bool = True


class UpdateTemplateRequest(BaseModel):
    name: Optional[str] = Field(None, max_length=256)
    description: Optional[str] = None
    default_config: Optional[Dict[str, Any]] = None
    match_condition: Optional[Dict[str, Any]] = None
    severity: Optional[str] = None
    rule_package: Optional[str] = Field(None, max_length=8)
    enabled: Optional[bool] = None


class RunCycleRequest(BaseModel):
    scope: str = "full"
    asset_ids: Optional[List[int]] = None


class QuickCreateRuleRequest(BaseModel):
    table_name: str = Field(..., max_length=128)
    schema_name: str = Field(..., max_length=128)
    rule_type: str = Field(..., max_length=64)
    rule_config: Dict[str, Any] = Field(default_factory=dict)
    severity: str = "HIGH"
    name: str = Field(..., max_length=256)


class BatchImportRequest(BaseModel):
    datasource_id: int
    tables: List[Dict[str, str]]  # [{schema_name, table_name, display_name?}]
    auto_suggest_rules: bool = False


class BatchDeleteRequest(BaseModel):
    asset_ids: List[int]


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
        direction = config.get("direction", "both").lower()
        if direction not in ("drop", "rise", "both"):
            raise DQCError.invalid_rule_config({"reason": "invalid_direction", "value": direction})
        threshold = config.get("threshold_pct", 0.10)
        if not (0 < threshold <= 1):
            raise DQCError.invalid_rule_config({"reason": "threshold_pct_out_of_range", "value": threshold})
        min_row = config.get("min_row_count", 10)
        if not isinstance(min_row, (int, float)) or min_row < 0:
            raise DQCError.invalid_rule_config({"reason": "min_row_count_invalid", "value": min_row})
        time_col = config.get("time_column")
        if time_col is not None and not isinstance(time_col, str):
            raise DQCError.invalid_rule_config({"reason": "time_column_must_be_string"})
        window = config.get("comparison_window")
        if window and window not in ("1d", "7d", "30d"):
            raise DQCError.invalid_rule_config({"reason": "invalid_comparison_window", "value": window})
    elif rule_type == RuleType.TABLE_COUNT_COMPARE.value:
        if not config.get("target_schema"):
            raise DQCError.invalid_rule_config({"reason": "require_target_schema"})
        if not config.get("target_table"):
            raise DQCError.invalid_rule_config({"reason": "require_target_table"})
        tolerance = config.get("tolerance_pct", 0.0)
        if not (0.0 <= tolerance <= 1.0):
            raise DQCError.invalid_rule_config({"reason": "tolerance_pct_out_of_range", "value": tolerance})
    elif rule_type == RuleType.ENUM_CHECK.value:
        if not config.get("column"):
            raise DQCError.invalid_rule_config({"reason": "require_column"})
        allowed = config.get("allowed_values")
        if not isinstance(allowed, list) or not allowed:
            raise DQCError.invalid_rule_config({"reason": "require_allowed_values_list"})
    elif rule_type == RuleType.AI_TABLE_DESCRIPTION.value:
        min_len = config.get("min_length", 20)
        if not isinstance(min_len, (int, float)) or int(min_len) < 1:
            raise DQCError.invalid_rule_config({"reason": "min_length_must_be_positive"})
    elif rule_type == RuleType.AI_FIELD_COMMENT.value:
        min_cov = config.get("min_coverage", 0.8)
        if not (0.0 < float(min_cov) <= 1.0):
            raise DQCError.invalid_rule_config({"reason": "min_coverage_out_of_range", "value": min_cov})


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


@router.get("/assets/schemas")
async def list_asset_schemas(
    request: Request,
    datasource_ids: List[int] = Query(default=[]),
    db: Session = Depends(get_db),
):
    """返回资产表中所有不重复的 schema_name，用于前端筛选器。"""
    get_current_user(request, db)
    q = db.query(DqcMonitoredAsset.schema_name).distinct()
    if datasource_ids:
        q = q.filter(DqcMonitoredAsset.datasource_id.in_(datasource_ids))
    schemas = sorted(r[0] for r in q.all() if r[0])
    return {"schemas": schemas}


@router.get("/assets")
async def list_assets(
    request: Request,
    datasource_id: Optional[int] = None,
    datasource_ids: List[int] = Query(default=[]),
    schema_names: List[str] = Query(default=[]),
    status: Optional[str] = None,
    signal: Optional[str] = None,
    page: int = 1,
    page_size: int = 20,
    db: Session = Depends(get_db),
):
    get_current_user(request, db)
    page_size = min(max(1, page_size), 100)
    dao = DqcDatabase()
    effective_ds_ids = list(datasource_ids)
    if datasource_id is not None and datasource_id not in effective_ds_ids:
        effective_ds_ids.append(datasource_id)
    result = dao.list_assets(
        db,
        datasource_ids=effective_ds_ids or None,
        schema_names=schema_names or None,
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
        # 同步匹配 table-scope 规则（无需 profiling，立即可用）
        from services.dqc.template_matcher import TemplateMatcher
        matcher = TemplateMatcher(dao)
        try:
            matcher.match_and_instantiate(db, asset, created_by=current_user["id"])
            db.commit()
        except Exception:
            logger.exception("sync template match failed for asset %s", asset.id)

        # 异步 profiling + 列级规则（需要 Celery worker 在线）
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


@router.post("/assets/batch-import")
async def batch_import_assets(
    body: BatchImportRequest,
    current_user: dict = Depends(require_roles(["admin", "data_admin"])),
    db: Session = Depends(get_db),
):
    """批量注册监控资产，已存在的跳过（不报错）。"""
    dao = DqcDatabase()
    ds_db = DataSourceDatabase()

    ds = ds_db.get(db, body.datasource_id)
    if not ds or not ds.is_active:
        raise DQCError.datasource_not_found_or_inactive({"datasource_id": body.datasource_id})

    if current_user["role"] != "admin" and ds.owner_id != current_user["id"]:
        raise DQCError.not_asset_owner()

    # 一次查出该数据源下所有资产（含已停用）
    all_existing = (
        db.query(DqcMonitoredAsset)
        .filter(DqcMonitoredAsset.datasource_id == body.datasource_id)
        .all()
    )
    existing_map: dict = {(a.schema_name, a.table_name): a for a in all_existing}

    created = 0
    skipped = 0
    new_asset_ids: List[int] = []

    for entry in body.tables:
        schema = entry.get("schema_name", "").strip()
        table = entry.get("table_name", "").strip()
        if not schema or not table:
            continue
        existing_asset = existing_map.get((schema, table))
        if existing_asset:
            if existing_asset.status == "enabled":
                skipped += 1
                continue
            # 已停用 → 重新启用
            existing_asset.status = "enabled"
            db.flush()
            new_asset_ids.append(existing_asset.id)
            created += 1
        else:
            asset = dao.create_asset(
                db,
                datasource_id=body.datasource_id,
                schema_name=schema,
                table_name=table,
                display_name=entry.get("display_name") or None,
                description=None,
                dimension_weights=DEFAULT_DIMENSION_WEIGHTS,
                signal_thresholds=DEFAULT_SIGNAL_THRESHOLDS,
                owner_id=current_user["id"],
                created_by=current_user["id"],
                status="enabled",
            )
            db.flush()
            existing_map[(schema, table)] = asset
            new_asset_ids.append(asset.id)
            created += 1

    db.commit()

    if body.auto_suggest_rules and new_asset_ids:
        # 同步匹配模板：table-scope 规则不依赖 profiling，立即生效
        from services.dqc.template_matcher import TemplateMatcher
        matcher = TemplateMatcher(dao)
        for aid in new_asset_ids:
            asset = dao.get_asset(db, aid)
            if asset:
                try:
                    matcher.match_and_instantiate(db, asset, created_by=current_user["id"])
                except Exception:
                    logger.exception("sync template match failed for asset %s", aid)
        db.commit()

        # 异步 profiling + 列级规则（需要 Celery worker 在线）
        for aid in new_asset_ids:
            try:
                profile_and_suggest_task.delay(aid)
            except Exception:
                logger.exception("failed to enqueue profile_and_suggest_task for asset %s", aid)

    return {"created": created, "skipped": skipped, "total": created + skipped}


@router.get("/datasources/{datasource_id}/tables")
async def list_datasource_tables(
    datasource_id: int,
    current_user: dict = Depends(require_roles(["admin", "data_admin"])),
    db: Session = Depends(get_db),
):
    """连接目标 DB，枚举所有非系统库的表，用于批量导入监控资产。"""
    from sqlalchemy import create_engine, text as sa_text
    from sqlalchemy.engine import URL

    ds_db = DataSourceDatabase()
    ds = ds_db.get(db, datasource_id)
    if not ds or not ds.is_active:
        raise DQCError.datasource_not_found_or_inactive({"datasource_id": datasource_id})

    from app.core.crypto import get_datasource_crypto
    try:
        crypto = get_datasource_crypto()
        password = crypto.decrypt(ds.password_encrypted)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"解密密码失败：{e}")

    db_type = ds.db_type
    try:
        if db_type == "postgresql":
            url = URL.create(
                drivername="postgresql+psycopg2",
                username=ds.username,
                password=password,
                host=ds.host,
                port=ds.port,
                database=ds.database_name,
            )
            connect_args: dict = {"options": "-c default_transaction_read_only=on"}
            sys_schemas = {"information_schema", "pg_catalog", "pg_toast"}
        elif db_type in ("mysql", "starrocks", "doris"):
            url = URL.create(
                drivername="mysql+pymysql",
                username=ds.username,
                password=password,
                host=ds.host,
                port=ds.port,
                database=ds.database_name,
            )
            connect_args = {}
            sys_schemas = {"information_schema", "_statistics_", "mysql", "performance_schema", "sys"}
        else:
            url = URL.create(
                drivername="postgresql+psycopg2",
                username=ds.username,
                password=password,
                host=ds.host,
                port=ds.port,
                database=ds.database_name,
            )
            connect_args = {}
            sys_schemas = {"information_schema", "pg_catalog"}

        engine = create_engine(url, connect_args=connect_args, pool_pre_ping=True, pool_size=1)
        stmt = sa_text(
            "SELECT table_schema, table_name FROM information_schema.tables "
            "WHERE table_type = 'BASE TABLE' "
            "ORDER BY table_schema, table_name"
        )
        with engine.connect() as conn:
            rows = conn.execute(stmt).fetchall()
        engine.dispose()

        tables = [
            {"schema_name": r[0], "table_name": r[1]}
            for r in rows
            if r[0].lower() not in sys_schemas
        ]
        return {"items": tables, "total": len(tables)}
    except Exception as e:
        logger.exception("list_datasource_tables failed for datasource %s", datasource_id)
        raise HTTPException(status_code=502, detail=f"连接数据源失败：{str(e)}")


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


@router.delete("/assets/batch")
async def batch_delete_assets(
    body: BatchDeleteRequest,
    current_user: dict = Depends(require_roles(["admin", "data_admin"])),
    db: Session = Depends(get_db),
):
    """批量停用监控资产。无权操作的资产跳过（不中断整批）。"""
    dao = DqcDatabase()
    deleted = 0
    unauthorized = 0
    for aid in body.asset_ids:
        asset = dao.get_asset(db, aid)
        if not asset:
            continue
        if current_user["role"] != "admin" and asset.owner_id != current_user["id"]:
            unauthorized += 1
            continue
        dao.disable_asset(db, aid)
        deleted += 1
    db.commit()
    return {"deleted": deleted, "unauthorized": unauthorized}


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
    items = []
    template_cache: dict = {}
    for r in rules:
        d = r.to_dict()
        if r.template_id:
            if r.template_id not in template_cache:
                tmpl = dao.get_template(db, r.template_id)
                template_cache[r.template_id] = tmpl.default_config if tmpl else {}
            d["template_default_config"] = template_cache[r.template_id]
        items.append(d)
    return {"items": items, "total": len(rules)}


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
    if rule.template_id:
        updates["is_modified_by_user"] = True
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

    from services.dqc.rule_suggester import suggest_and_create_rules

    rules = suggest_and_create_rules(
        db, asset_id,
        created_by=current_user["id"],
        use_llm=body.use_llm if body else False,
        max_rules=body.max_rules if body else 5,
    )
    return {
        "analysis_id": None,
        "suggested_rules": [r.to_dict() for r in rules] if rules else [],
        "message": f"生成 {len(rules)} 条建议规则" if rules else "无可建议规则（请先完成 Profiling）",
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


# ==================== Templates ====================


@router.get("/templates")
async def list_templates(
    request: Request,
    enabled: Optional[bool] = None,
    dimension: Optional[str] = None,
    db: Session = Depends(get_db),
):
    get_current_user(request, db)
    dao = DqcDatabase()
    templates = dao.list_templates(db, enabled=enabled, dimension=dimension)
    items = []
    for t in templates:
        d = t.to_dict()
        d["derived_rules_count"] = dao.count_derived_rules(db, t.id)
        d["unmodified_rules_count"] = dao.count_derived_rules(db, t.id, only_unmodified=True)
        items.append(d)
    return {"items": items, "total": len(items)}


@router.post("/templates")
async def create_template(
    body: CreateTemplateRequest,
    current_user: dict = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    _validate_rule_type_and_dim(body.dimension, body.rule_type)
    dao = DqcDatabase()
    tmpl = dao.create_template(
        db,
        name=body.name,
        description=body.description,
        dimension=body.dimension,
        rule_type=body.rule_type,
        default_config=body.default_config,
        match_condition=body.match_condition,
        severity=body.severity,
        rule_package=body.rule_package,
        enabled=body.enabled,
        is_builtin=False,
        created_by=current_user["id"],
    )
    db.commit()
    db.refresh(tmpl)
    return tmpl.to_dict()


@router.get("/templates/{template_id}")
async def get_template(template_id: int, request: Request, db: Session = Depends(get_db)):
    get_current_user(request, db)
    dao = DqcDatabase()
    tmpl = dao.get_template(db, template_id)
    if not tmpl:
        raise DQCError.template_not_found()
    d = tmpl.to_dict()
    d["derived_rules_count"] = dao.count_derived_rules(db, template_id)
    d["unmodified_rules_count"] = dao.count_derived_rules(db, template_id, only_unmodified=True)
    return d


@router.patch("/templates/{template_id}")
async def update_template(
    template_id: int,
    body: UpdateTemplateRequest,
    current_user: dict = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    dao = DqcDatabase()
    tmpl = dao.get_template(db, template_id)
    if not tmpl:
        raise DQCError.template_not_found()

    updates = body.model_dump(exclude_unset=True, exclude_none=True)
    updates["updated_by"] = current_user["id"]
    dao.update_template(db, template_id, **updates)

    propagated = 0
    if "default_config" in updates:
        propagated = dao.propagate_template(db, template_id)

    db.commit()
    tmpl = dao.get_template(db, template_id)
    d = tmpl.to_dict()
    d["propagated_rules_count"] = propagated
    return d


@router.delete("/templates/{template_id}")
async def delete_template(
    template_id: int,
    current_user: dict = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    dao = DqcDatabase()
    tmpl = dao.get_template(db, template_id)
    if not tmpl:
        raise DQCError.template_not_found()
    dao.delete_template(db, template_id)
    db.commit()
    return {"message": "模板已删除", "template_id": template_id}


class TemplateCoverageToggleRequest(BaseModel):
    asset_id: int
    enabled: bool


class TemplateCoverageBatchRequest(BaseModel):
    add: List[int] = Field(default_factory=list)
    remove: List[int] = Field(default_factory=list)


@router.get("/templates/{template_id}/coverage")
async def get_template_coverage(
    template_id: int,
    request: Request,
    db: Session = Depends(get_db),
):
    """返回所有已监控资产及其是否已应用该模板。"""
    get_current_user(request, db)
    dao = DqcDatabase()
    tmpl = dao.get_template(db, template_id)
    if not tmpl:
        raise DQCError.template_not_found()

    result = dao.list_assets(db, page=1, page_size=500)
    assets = result["items"]

    # 查出已有该模板派生规则的 asset_id 集合
    covered = {
        r.asset_id
        for r in db.query(DqcQualityRule.asset_id)
        .filter(DqcQualityRule.template_id == template_id)
        .all()
    }

    ds_db = DataSourceDatabase()
    items = []
    for asset in assets:
        ds = ds_db.get(db, asset.datasource_id)
        items.append({
            "asset_id": asset.id,
            "schema_name": asset.schema_name,
            "table_name": asset.table_name,
            "display_name": asset.display_name or f"{asset.schema_name}.{asset.table_name}",
            "datasource_name": ds.name if ds else None,
            "status": asset.status,
            "enabled": asset.id in covered,
        })

    return {"items": items, "total": len(items)}


@router.post("/templates/{template_id}/coverage")
async def toggle_template_coverage(
    template_id: int,
    body: TemplateCoverageToggleRequest,
    current_user: dict = Depends(require_roles(["admin", "data_admin"])),
    db: Session = Depends(get_db),
):
    """为单个资产开启或关闭该模板的派生规则。"""
    dao = DqcDatabase()
    tmpl = dao.get_template(db, template_id)
    if not tmpl:
        raise DQCError.template_not_found()

    asset = dao.get_asset(db, body.asset_id)
    if not asset:
        raise DQCError.asset_not_found()

    existing = (
        db.query(DqcQualityRule)
        .filter(
            DqcQualityRule.template_id == template_id,
            DqcQualityRule.asset_id == body.asset_id,
        )
        .first()
    )

    if body.enabled:
        if existing:
            return {"message": "已存在，无需重复创建", "rule_id": existing.id}
        dimension = RULE_TYPE_TO_DIMENSION.get(tmpl.rule_type, "validity")
        rule = dao.create_rule(
            db,
            asset_id=body.asset_id,
            name=f"{asset.schema_name}.{asset.table_name} — {tmpl.name}",
            description=tmpl.description,
            dimension=dimension,
            rule_type=tmpl.rule_type,
            rule_config=tmpl.default_config or {},
            is_active=True,
            is_system_suggested=False,
            template_id=template_id,
            created_by=current_user["id"],
        )
        db.commit()
        db.refresh(rule)
        return {"message": "规则已创建", "rule_id": rule.id}
    else:
        if not existing:
            return {"message": "不存在，无需删除"}
        dao.delete_rule(db, existing.id)
        db.commit()
        return {"message": "规则已删除"}


@router.post("/templates/{template_id}/coverage/batch")
async def batch_toggle_template_coverage(
    template_id: int,
    body: TemplateCoverageBatchRequest,
    current_user: dict = Depends(require_roles(["admin", "data_admin"])),
    db: Session = Depends(get_db),
):
    """批量开启/关闭该模板在多个资产上的派生规则。"""
    dao = DqcDatabase()
    tmpl = dao.get_template(db, template_id)
    if not tmpl:
        raise DQCError.template_not_found()

    dimension = RULE_TYPE_TO_DIMENSION.get(tmpl.rule_type, "validity")

    covered_ids = {
        r.asset_id
        for r in db.query(DqcQualityRule.asset_id)
        .filter(DqcQualityRule.template_id == template_id)
        .all()
    }

    added, removed = 0, 0

    for asset_id in body.add:
        if asset_id in covered_ids:
            continue
        asset = dao.get_asset(db, asset_id)
        if not asset:
            continue
        dao.create_rule(
            db,
            asset_id=asset_id,
            name=f"{asset.schema_name}.{asset.table_name} — {tmpl.name}",
            description=tmpl.description,
            dimension=dimension,
            rule_type=tmpl.rule_type,
            rule_config=tmpl.default_config or {},
            is_active=True,
            is_system_suggested=False,
            template_id=template_id,
            created_by=current_user["id"],
        )
        added += 1

    for asset_id in body.remove:
        rule = (
            db.query(DqcQualityRule)
            .filter(
                DqcQualityRule.template_id == template_id,
                DqcQualityRule.asset_id == asset_id,
            )
            .first()
        )
        if rule:
            dao.delete_rule(db, rule.id)
            removed += 1

    db.commit()
    return {"added": added, "removed": removed}



async def apply_template_to_assets(
    template_id: int,
    current_user: dict = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    """对已有资产补刷模板。"""
    dao = DqcDatabase()
    tmpl = dao.get_template(db, template_id)
    if not tmpl:
        raise DQCError.template_not_found()
    if not tmpl.enabled:
        raise DQCError.invalid_parameter("模板未启用")

    from services.dqc.template_matcher import TemplateMatcher

    matcher = TemplateMatcher(dao)
    assets = dao.list_enabled_assets(db)
    total_created = 0
    for asset in assets:
        rules = matcher.match_and_instantiate(db, asset, created_by=current_user["id"])
        total_created += len(rules)
    db.commit()
    return {
        "message": f"已对 {len(assets)} 个资产补刷模板，创建 {total_created} 条规则",
        "assets_count": len(assets),
        "rules_created": total_created,
    }


# ── AI 智能填充 ──────────────────────────────────────────────────────

class AiParseTemplateInput(BaseModel):
    description: str = Field(..., min_length=2, max_length=500)
    rule_type: Optional[str] = None

AI_PARSE_TEMPLATE_PROMPT = """你是数据质量平台的配置助手。用户用自然语言描述了一条监控规则的意图，请解析为结构化配置。

## 规则类型和对应参数

- null_rate: max_rate(0~1)
- uniqueness: max_duplicate_rate(0~1)
- freshness: max_age_hours(整数，小时)
- range_check: check_mode(min_max_all | sample)
- regex: pattern(正则表达式)
- volume_anomaly: time_column(时间列名，可选), observation_date(默认today), threshold_pct(0~1), direction(both|drop|rise), min_row_count(整数)
- table_count_compare: tolerance_pct(0~1)
- custom_sql: sql(SELECT语句)

## 匹配范围

- 表级: {{"scope": "table"}}
- 列级: {{"scope": "column", "column_filter": {{...}}}}
  column_filter 支持: has_nulls(bool), is_candidate_id(bool), has_numeric_range(bool), data_type_contains(字符串数组)

## 用户描述

规则类型: {rule_type}
用户描述: {description}

## 要求

返回 JSON，格式如下（只返回 JSON，不要其他内容）：
{{
  "name": "模板名称（简洁中文）",
  "default_config": {{...按规则类型填充}},
  "match_condition": {{...}},
  "severity": "LOW|MEDIUM|HIGH|CRITICAL",
  "reasoning": "一句话解释你的理解"
}}"""


@router.post("/templates/ai-parse")
async def ai_parse_template_config(
    body: AiParseTemplateInput,
    current_user: dict = Depends(get_current_user),
):
    """用 LLM 解析自然语言描述为模板配置。"""
    import json as _json
    import re

    from services.common.async_compat import run_async_safely
    from services.llm.service import LLMService

    rule_type = body.rule_type or "未指定"
    prompt = AI_PARSE_TEMPLATE_PROMPT.format(
        rule_type=rule_type,
        description=body.description,
    )

    service = LLMService()

    async def _call():
        return await service.complete_for_semantic(
            prompt=prompt,
            system="你是数据质量监控配置助手，擅长将自然语言转为结构化参数。只返回 JSON。",
            timeout=20,
            purpose="default",
        )

    result = run_async_safely(_call())

    if "error" in result:
        raise DQCError.invalid_parameter(f"AI 解析失败: {result['error']}")

    content = result.get("content", "")
    json_match = re.search(r"\{[\s\S]*\}", content)
    if not json_match:
        raise DQCError.invalid_parameter("AI 返回格式异常，请重试或手动配置")

    try:
        parsed = _json.loads(json_match.group())
    except _json.JSONDecodeError:
        raise DQCError.invalid_parameter("AI 返回 JSON 解析失败，请重试")

    return {
        "name": parsed.get("name", ""),
        "default_config": parsed.get("default_config", {}),
        "match_condition": parsed.get("match_condition", {"scope": "table"}),
        "severity": parsed.get("severity", "MEDIUM"),
        "reasoning": parsed.get("reasoning", ""),
    }


# ==================== AI 规则生成 ====================


class AiGenerateRuleInput(BaseModel):
    description: str = Field(..., min_length=2, max_length=500)


AI_GENERATE_RULE_PROMPT = """你是数据质量平台的智能助手。用户用自然语言描述了一个数据质量问题，请：
1. 识别最合适的检查能力（rule_type）
2. 从描述中提取目标表名（target_table）和字段名（target_column，如有）
3. 根据规则类型建议参数配置

## 可用检查能力

### L1 基础质量
- table_not_null: 表必填字段非空
- null_rate: 字段空值率监控 — 检查某字段空值比例，需 column(字段名)、max_rate(0~1)
- uniqueness: 唯一性监控 — 检查字段组合是否重复，需 columns(字段名数组)
- enum_check: 值域合法性 — 检查枚举类字段，需 column、allowed_values(字符串数组)
- range_check: 数值范围 — 检查数值字段范围，需 column、min、max

### L2 时效稳定性
- freshness: 数据新鲜度 — 检查数据是否及时更新，需 column(时间字段)、max_age_hours(整数)
- arrival_check: 数据到达检查
- volume_anomaly: 行数异常检测，需 threshold_pct(0~1)、direction(both|drop|rise)
- schema_drift: 结构漂移检测
- partition_completeness: 分区完整性

### L3 业务勾稽
- table_count_compare: 跨表行数对比
- fk_coverage: 外键覆盖率
- amount_reconciliation: 金额对账
- detail_summary_consistency: 明细汇总一致性
- metric_drift: 指标波动检测

### L4 AI Ready
- ai_table_description: 表业务说明完整性
- ai_field_comment: 字段注释覆盖率
- ai_metric_definition: 指标语义定义

## 用户描述

{description}

## 要求

只返回如下 JSON，不要有任何其他内容：
{{
  "rule_type": "识别到的规则类型",
  "target_table": "目标表名（从描述提取，未提及则为null）",
  "target_column": "目标字段名（未提及则为null）",
  "suggested_name": "规则名称（简洁中文，如 '订单表 order_id 唯一性检查'）",
  "suggested_description": "规则描述（一句话说明检查目的）",
  "config": {{}},
  "severity": "HIGH|MEDIUM|LOW",
  "reasoning": "一句话说明识别理由"
}}"""

RULE_TYPE_TO_PACKAGE = {
    "table_not_null": "L1", "null_rate": "L1", "uniqueness": "L1",
    "enum_check": "L1", "range_check": "L1",
    "freshness": "L2", "arrival_check": "L2", "volume_anomaly": "L2",
    "schema_drift": "L2", "partition_completeness": "L2",
    "table_count_compare": "L3", "fk_coverage": "L3",
    "amount_reconciliation": "L3", "detail_summary_consistency": "L3",
    "metric_drift": "L3",
    "ai_table_description": "L4", "ai_field_comment": "L4",
    "ai_metric_definition": "L4", "default_time_field": "L4",
    "default_amount_field": "L4", "default_filter_condition": "L4",
    "sensitive_field": "L4", "deprecated_field": "L4", "sample_questions": "L4",
}

RULE_TYPE_LABELS_ZH = {
    "table_not_null": "表必填字段非空",
    "null_rate": "字段空值率监控",
    "uniqueness": "唯一性监控",
    "enum_check": "值域合法性监控",
    "range_check": "数值范围监控",
    "freshness": "数据新鲜度监控",
    "arrival_check": "数据到达检查",
    "volume_anomaly": "行数异常检测",
    "schema_drift": "结构漂移检测",
    "partition_completeness": "分区完整性检查",
    "table_count_compare": "跨表行数对比",
    "fk_coverage": "外键覆盖率",
    "amount_reconciliation": "金额对账",
    "detail_summary_consistency": "明细汇总一致性",
    "metric_drift": "指标波动检测",
    "ai_table_description": "表业务说明完整性",
    "ai_field_comment": "字段注释覆盖率",
    "ai_metric_definition": "指标语义定义",
}


@router.post("/rules/ai-generate")
async def ai_generate_rule(
    body: AiGenerateRuleInput,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """自然语言描述 → LLM 识别检查能力 → 返回规则草案"""
    import json as _json
    import re

    from services.common.async_compat import run_async_safely
    from services.llm.service import LLMService

    prompt = AI_GENERATE_RULE_PROMPT.format(description=body.description)
    service = LLMService()

    async def _call():
        return await service.complete_for_semantic(
            prompt=prompt,
            system="你是数据质量平台的智能助手，擅长将自然语言转换为结构化检查规则。只返回 JSON。",
            timeout=30,
            purpose="default",
        )

    result = run_async_safely(_call())

    if "error" in result:
        raise DQCError.invalid_parameter(f"AI 分析失败: {result['error']}")

    content = result.get("content", "")
    json_match = re.search(r"\{[\s\S]*\}", content)
    if not json_match:
        raise DQCError.invalid_parameter("AI 返回格式异常，请重试")

    try:
        parsed = _json.loads(json_match.group())
    except _json.JSONDecodeError:
        raise DQCError.invalid_parameter("AI 返回 JSON 解析失败，请重试")

    rule_type = parsed.get("rule_type", "")
    rule_package = RULE_TYPE_TO_PACKAGE.get(rule_type, "")
    capability_name = RULE_TYPE_LABELS_ZH.get(rule_type, rule_type)

    # 查找匹配的检查能力模板
    dao = DqcDatabase()
    templates = dao.list_templates(db, enabled=None)
    template_id = 0
    for t in templates:
        if t.rule_type == rule_type:
            template_id = t.id
            capability_name = t.name
            break

    return {
        "template_id": template_id,
        "capability_name": capability_name,
        "rule_package": rule_package,
        "dimension": parsed.get("dimension", ""),
        "suggested_name": parsed.get("suggested_name", ""),
        "suggested_description": parsed.get("suggested_description", ""),
        "target_table": parsed.get("target_table") or "",
        "target_column": parsed.get("target_column") or None,
        "severity": parsed.get("severity", "MEDIUM"),
        "default_config": parsed.get("config", {}),
    }


# ==================== Quick Create Rule ====================


@router.post("/rules/quick-create")
async def quick_create_rule(
    body: QuickCreateRuleRequest,
    current_user: dict = Depends(require_roles(["admin", "data_admin"])),
    db: Session = Depends(get_db),
):
    """从能力库表单直接创建规则，自动匹配已监控资产"""
    # 规范化 rule_type
    rule_type = body.rule_type
    if rule_type not in ALL_RULE_TYPES:
        from fastapi import HTTPException
        raise HTTPException(status_code=422, detail=f"不支持的规则类型: {rule_type}")

    # 查找监控资产（跨 datasource，取第一个匹配）
    asset = (
        db.query(DqcMonitoredAsset)
        .filter(
            DqcMonitoredAsset.schema_name == body.schema_name,
            DqcMonitoredAsset.table_name == body.table_name,
        )
        .first()
    )
    if not asset:
        from fastapi import HTTPException
        raise HTTPException(
            status_code=422,
            detail=f"表 {body.schema_name}.{body.table_name} 尚未纳入监控，请先在「监控资产」中添加该表",
        )

    # 推导 dimension
    dimension = RULE_TYPE_TO_DIMENSION.get(rule_type, "validity")

    # 转换 table_count_compare 的 compare_table → target_schema/target_table
    config = dict(body.rule_config)
    if rule_type == RuleType.TABLE_COUNT_COMPARE.value:
        compare_table = config.pop("compare_table", "")
        if "." in compare_table:
            tgt_schema, tgt_table = compare_table.split(".", 1)
        else:
            tgt_schema, tgt_table = "public", compare_table
        config.setdefault("target_schema", tgt_schema)
        config.setdefault("target_table", tgt_table)

    # 对已有验证逻辑的类型做校验
    _validate_rule_config(rule_type, config)

    dao = DqcDatabase()
    if dao.rule_name_exists(db, asset.id, body.name):
        from fastapi import HTTPException
        raise HTTPException(status_code=409, detail=f"该资产下已存在同名规则「{body.name}」")

    rule = dao.create_rule(
        db,
        asset_id=asset.id,
        name=body.name,
        description=None,
        dimension=dimension,
        rule_type=rule_type,
        rule_config=config,
        is_active=True,
        is_system_suggested=False,
        created_by=current_user["id"],
    )
    db.commit()
    db.refresh(rule)
    return rule.to_dict()


# ==================== 模板 Seed ====================


@router.post("/templates/seed")
async def seed_templates(
    current_user: dict = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    dao = DqcDatabase()
    created = dao.seed_default_templates(db)
    db.commit()
    return {"message": f"已创建/更新 {len(created)} 条内置模板", "count": len(created)}


# ==================== 派生规则（Layer 2） ====================


class UpdateDerivedRuleRequest(BaseModel):
    enabled: Optional[bool] = None


def _serialize_derived_rule(rule: DqcQualityRule, tmpl, asset) -> Dict[str, Any]:
    column_name = (rule.rule_config or {}).get("column")
    return {
        "id": rule.id,
        "template_id": rule.template_id,
        "template_name": tmpl.name if tmpl else None,
        "rule_name": rule.name,
        "table_name": asset.table_name if asset else None,
        "column_name": column_name,
        "object_type": "column" if column_name else "table",
        "rule_config": rule.rule_config,
        "severity": tmpl.severity if tmpl else "MEDIUM",
        "action": "alert",
        "ai_ready_enabled": False,
        "enabled": rule.is_active,
        "owner": None,
        "generated_by": "system" if rule.is_system_suggested else "user",
        "created_at": rule.created_at.strftime("%Y-%m-%d %H:%M:%S") if rule.created_at else None,
        "updated_at": rule.updated_at.strftime("%Y-%m-%d %H:%M:%S") if rule.updated_at else None,
    }


@router.get("/derived-rules")
async def list_derived_rules(
    request: Request,
    template_id: Optional[int] = None,
    enabled: Optional[bool] = None,
    page: int = 1,
    page_size: int = 50,
    db: Session = Depends(get_db),
):
    get_current_user(request, db)
    page_size = min(max(1, page_size), 100)
    dao = DqcDatabase()

    q = db.query(DqcQualityRule)
    if template_id is not None:
        q = q.filter(DqcQualityRule.template_id == template_id)
    if enabled is not None:
        q = q.filter(DqcQualityRule.is_active == enabled)

    total = q.count()
    rules = q.order_by(DqcQualityRule.created_at.desc()).offset((page - 1) * page_size).limit(page_size).all()

    template_cache: Dict[int, Any] = {}
    asset_cache: Dict[int, Any] = {}

    items = []
    for rule in rules:
        tmpl = None
        if rule.template_id is not None:
            if rule.template_id not in template_cache:
                template_cache[rule.template_id] = dao.get_template(db, rule.template_id)
            tmpl = template_cache[rule.template_id]
        if rule.asset_id not in asset_cache:
            asset_cache[rule.asset_id] = dao.get_asset(db, rule.asset_id)
        asset = asset_cache[rule.asset_id]
        items.append(_serialize_derived_rule(rule, tmpl, asset))

    return {"items": items, "total": total, "page": page, "page_size": page_size}


@router.patch("/derived-rules/{rule_id}")
async def update_derived_rule(
    rule_id: int,
    body: UpdateDerivedRuleRequest,
    current_user: dict = Depends(require_roles(["admin", "data_admin"])),
    db: Session = Depends(get_db),
):
    dao = DqcDatabase()
    rule = dao.get_rule(db, rule_id)
    if not rule:
        raise DQCError.rule_not_found()

    if body.enabled is not None:
        dao.update_rule(db, rule_id, is_active=body.enabled)
        db.commit()

    rule = dao.get_rule(db, rule_id)
    tmpl = dao.get_template(db, rule.template_id) if rule.template_id else None
    asset = dao.get_asset(db, rule.asset_id)
    return _serialize_derived_rule(rule, tmpl, asset)


# ==================== 检查记录（Layer 3） ====================


@router.get("/check-results")
async def list_check_results(
    request: Request,
    status: Optional[str] = None,
    affect_ai_ready: Optional[bool] = None,
    rule_id: Optional[int] = None,
    page: int = 1,
    page_size: int = 50,
    db: Session = Depends(get_db),
):
    get_current_user(request, db)
    page_size = min(max(1, page_size), 100)

    q = db.query(DqcRuleResult)
    if status == "PASS":
        q = q.filter(DqcRuleResult.passed == True)
    elif status in ("FAIL", "WARNING"):
        q = q.filter(DqcRuleResult.passed == False)
    if rule_id is not None:
        q = q.filter(DqcRuleResult.rule_id == rule_id)

    total = q.count()
    results = (
        q.order_by(DqcRuleResult.executed_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )

    dao = DqcDatabase()
    rule_cache: Dict[int, Any] = {}
    asset_cache: Dict[int, Any] = {}
    template_cache: Dict[int, Any] = {}

    items = []
    for res in results:
        if res.rule_id not in rule_cache:
            rule_cache[res.rule_id] = dao.get_rule(db, res.rule_id)
        rule = rule_cache[res.rule_id]

        tmpl = None
        if rule and rule.template_id is not None:
            if rule.template_id not in template_cache:
                template_cache[rule.template_id] = dao.get_template(db, rule.template_id)
            tmpl = template_cache[rule.template_id]

        if res.asset_id not in asset_cache:
            asset_cache[res.asset_id] = dao.get_asset(db, res.asset_id)
        asset = asset_cache[res.asset_id]

        status_val = "PASS" if res.passed else "FAIL"
        column_name = (rule.rule_config or {}).get("column") if rule else None
        expected = res.expected_config or {}
        threshold_value = (
            expected.get("max_rate")
            or expected.get("max_duplicate_rate")
            or expected.get("max_age_hours")
        )

        items.append({
            "id": res.id,
            "rule_id": res.rule_id,
            "rule_name": rule.name if rule else f"rule_{res.rule_id}",
            "template_id": rule.template_id if rule else None,
            "template_name": tmpl.name if tmpl else None,
            "rule_package": tmpl.rule_package if tmpl else None,
            "table_name": asset.table_name if asset else None,
            "column_name": column_name,
            "check_time": res.executed_at.strftime("%Y-%m-%d %H:%M:%S") if res.executed_at else None,
            "status": status_val,
            "actual_value": res.actual_value,
            "threshold_value": threshold_value,
            "total_count": None,
            "error_count": None,
            "message": res.error_message,
            "suggestion": None,
            "affect_ai_ready": False,
        })

    return {"items": items, "total": total, "page": page, "page_size": page_size}

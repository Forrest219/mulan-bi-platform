"""Governance Runtime API（Spec 24 P0 — 基于 DQC 基础设施实现）

API 前缀: /api/governance
职责: 规则 CRUD、扫描触发、结果查询、漂移检测、信号灯判定

技术实现:
- 规则管理委托给 DqcDatabase (bi_dqc_quality_rules)
- 扫描触发使用 Celery tasks (dqc_tasks)
- 漂移检测委托给 DriftDetector
- 信号灯判定委托给 DqcScorer.judge_dimension_signal / judge_asset_signal
- LLM 修复建议通过 LlmAnalyzer 生成
"""
import logging
from datetime import datetime
from typing import Any, Dict, List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.dependencies import get_current_admin, get_current_user, require_roles
from app.core.errors import DQCError
from services.dqc.constants import (
    ALL_DIMENSIONS,
    ALL_RULE_TYPES,
    DEFAULT_DIMENSION_WEIGHTS,
    DEFAULT_SIGNAL_THRESHOLDS,
    DIMENSION_RULE_COMPATIBILITY,
    SIGNAL_PRIORITY,
    SignalLevel,
)
from services.dqc.database import DqcDatabase
from services.dqc.drift_detector import DriftDetector
from services.dqc.models import (
    DqcDimensionScore,
    DqcMonitoredAsset,
    DqcQualityRule,
)
from services.dqc.scorer import DqcScorer
from services.tasks.dqc_tasks import (
    profile_and_suggest_task,
    run_daily_full_cycle,
    run_for_asset_task,
    run_hourly_light_cycle,
)
from services.dqc.orchestrator import is_cycle_locked

logger = logging.getLogger(__name__)
router = APIRouter()


# ==================== 请求/响应模型 ====================


class GovernanceRuleCreate(BaseModel):
    """创建规则请求"""
    asset_id: int
    name: str = Field(..., max_length=256)
    description: Optional[str] = None
    dimension: str = Field(..., max_length=32)
    rule_type: str = Field(..., max_length=32)
    rule_config: Dict[str, Any] = Field(default_factory=dict)
    is_active: bool = True


class GovernanceRuleUpdate(BaseModel):
    """更新规则请求"""
    name: Optional[str] = Field(None, max_length=256)
    description: Optional[str] = None
    rule_config: Optional[Dict[str, Any]] = None
    is_active: Optional[bool] = None


class GovernanceScanRequest(BaseModel):
    """触发扫描请求"""
    scope: str = Field("full", pattern="^(full|hourly_light)$")
    asset_ids: Optional[List[int]] = None


class GovernanceRuleResponse(BaseModel):
    id: int
    asset_id: int
    name: str
    description: Optional[str]
    dimension: str
    rule_type: str
    rule_config: Dict[str, Any]
    is_active: bool
    is_system_suggested: bool
    suggested_by_llm_analysis_id: Optional[int]
    created_by: int
    updated_by: Optional[int]
    created_at: Optional[str]
    updated_at: Optional[str]

    class Config:
        from_attributes = True


class GovernanceScanResponse(BaseModel):
    """扫描触发响应"""
    cycle_id: Optional[str]
    task_ids: List[str]
    message: str


class GovernanceResultItem(BaseModel):
    """扫描结果项"""
    cycle_id: str
    asset_id: int
    asset_name: str
    confidence_score: float
    signal: str
    dimension_scores: Dict[str, float]
    dimension_signals: Dict[str, str]
    drift_24h: Optional[Dict[str, float]]
    drift_vs_7d_avg: Optional[Dict[str, float]]
    rules_total: int
    rules_passed: int
    rules_failed: int
    computed_at: Optional[str]


class GovernanceResultsResponse(BaseModel):
    scan_id: str
    status: str
    scope: str
    started_at: Optional[str]
    completed_at: Optional[str]
    assets_total: int
    assets_processed: int
    assets_failed: int
    rules_executed: int
    p0_count: int
    p1_count: int
    results: List[GovernanceResultItem]


# ==================== 辅助函数 ====================


def _validate_rule_type_and_dim(dimension: str, rule_type: str) -> None:
    """校验 dimension 与 rule_type 兼容性"""
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
    """校验 rule_config 参数"""
    if rule_type == "null_rate":
        if not config.get("column"):
            raise DQCError.invalid_rule_config({"reason": "require_column"})
        rate = config.get("max_rate")
        if rate is None:
            raise DQCError.invalid_rule_config({"reason": "require_max_rate"})
        if not (0 <= float(rate) <= 1):
            raise DQCError.invalid_rule_config({"reason": "max_rate_out_of_range"})
    elif rule_type == "uniqueness":
        cols = config.get("columns")
        if not isinstance(cols, list) or not cols:
            raise DQCError.invalid_rule_config({"reason": "require_columns_list"})
    elif rule_type == "range_check":
        if not config.get("column"):
            raise DQCError.invalid_rule_config({"reason": "require_column"})
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
        sql = config["sql"].upper()
        for kw in ("INSERT", "UPDATE", "DELETE", "DROP", "ALTER", "TRUNCATE", "GRANT", "REVOKE", "COPY"):
            if kw in sql:
                raise DQCError.custom_sql_not_readonly({"keyword": kw})


def _serialize_rule(rule: DqcQualityRule) -> Dict[str, Any]:
    """规则对象序列化"""
    return {
        "id": rule.id,
        "asset_id": rule.asset_id,
        "name": rule.name,
        "description": rule.description,
        "dimension": rule.dimension,
        "rule_type": rule.rule_type,
        "rule_config": rule.rule_config,
        "is_active": rule.is_active,
        "is_system_suggested": rule.is_system_suggested,
        "suggested_by_llm_analysis_id": rule.suggested_by_llm_analysis_id,
        "created_by": rule.created_by,
        "updated_by": rule.updated_by,
        "created_at": rule.created_at.strftime("%Y-%m-%d %H:%M:%S") if rule.created_at else None,
        "updated_at": rule.updated_at.strftime("%Y-%m-%d %H:%M:%S") if rule.updated_at else None,
    }


def _build_result_items(
    dao: DqcDatabase,
    db: Session,
    cycle_id: UUID,
    thresholds: Dict[str, float],
) -> List[Dict[str, Any]]:
    """从 cycle 汇总结果构建 GovernanceResultItem 列表"""
    snapshots = dao.get_snapshots_for_cycle(db, cycle_id)
    items = []
    for snap in snapshots:
        asset = dao.get_asset(db, snap.asset_id)
        asset_name = f"{asset.schema_name}.{asset.table_name}" if asset else str(snap.asset_id)

        # 获取维度分
        dim_rows = dao.get_latest_dimension_scores(db, snap.asset_id)

        # 计算漂移
        prev_scores = dao.get_prev_dimension_scores(db, snap.asset_id, snap.computed_at)
        d7_avg = dao.get_7d_avg_dimension_scores(db, snap.asset_id, snap.computed_at)

        drift_24h = {}
        drift_vs_7d = {}
        rules_total = 0
        rules_passed = 0

        for dim in ALL_DIMENSIONS:
            row = dim_rows.get(dim)
            score = row.score if row else 100.0
            prev = prev_scores.get(dim)
            d7 = d7_avg.get(dim)

            drift_24h[dim] = round(score - prev, 2) if prev is not None else None
            drift_vs_7d[dim] = round(score - d7, 2) if d7 is not None else None

            if row:
                rules_total += row.rules_total
                rules_passed += row.rules_passed

        items.append({
            "cycle_id": str(cycle_id),
            "asset_id": snap.asset_id,
            "asset_name": asset_name,
            "confidence_score": snap.confidence_score,
            "signal": snap.signal,
            "dimension_scores": snap.dimension_scores or {d: 100.0 for d in ALL_DIMENSIONS},
            "dimension_signals": snap.dimension_signals or {d: "GREEN" for d in ALL_DIMENSIONS},
            "drift_24h": drift_24h,
            "drift_vs_7d_avg": drift_vs_7d,
            "rules_total": rules_total,
            "rules_passed": rules_passed,
            "rules_failed": rules_total - rules_passed,
            "computed_at": snap.computed_at.strftime("%Y-%m-%d %H:%M:%S") if snap.computed_at else None,
        })
    return items


# ==================== API 端点 ====================


@router.post("/rules", response_model=GovernanceRuleResponse, status_code=201)
async def create_governance_rule(
    body: GovernanceRuleCreate,
    current_user: dict = Depends(require_roles(["admin", "data_admin"])),
    db: Session = Depends(get_db),
):
    """POST /governance/rules — 创建质量规则"""
    dao = DqcDatabase()

    asset = dao.get_asset(db, body.asset_id)
    if not asset:
        raise DQCError.asset_not_found()

    if current_user["role"] != "admin" and asset.owner_id != current_user["id"]:
        raise DQCError.not_asset_owner()

    _validate_rule_type_and_dim(body.dimension, body.rule_type)
    _validate_rule_config(body.rule_type, body.rule_config or {})

    if dao.rule_name_exists(db, body.asset_id, body.name):
        raise DQCError.rule_already_exists({"asset_id": body.asset_id, "name": body.name})

    rule = dao.create_rule(
        db,
        asset_id=body.asset_id,
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
    return GovernanceRuleResponse(**_serialize_rule(rule))


@router.get("/rules/{rule_id}", response_model=GovernanceRuleResponse)
async def get_governance_rule(
    rule_id: int,
    request: Request,
    db: Session = Depends(get_db),
):
    """GET /governance/rules/{rule_id} — 获取指定规则"""
    get_current_user(request, db)
    dao = DqcDatabase()
    rule = dao.get_rule(db, rule_id)
    if not rule:
        raise DQCError.rule_not_found()
    return GovernanceRuleResponse(**_serialize_rule(rule))


@router.put("/rules/{rule_id}", response_model=GovernanceRuleResponse)
async def update_governance_rule(
    rule_id: int,
    body: GovernanceRuleUpdate,
    current_user: dict = Depends(require_roles(["admin", "data_admin"])),
    db: Session = Depends(get_db),
):
    """PUT /governance/rules/{rule_id} — 更新规则"""
    dao = DqcDatabase()
    rule = dao.get_rule(db, rule_id)
    if not rule:
        raise DQCError.rule_not_found()

    asset = dao.get_asset(db, rule.asset_id)
    if current_user["role"] != "admin" and asset and asset.owner_id != current_user["id"]:
        raise DQCError.not_asset_owner()

    if body.rule_config is not None:
        _validate_rule_config(rule.rule_type, body.rule_config)

    if body.name is not None and body.name != rule.name:
        if dao.rule_name_exists(db, rule.asset_id, body.name, exclude_id=rule_id):
            raise DQCError.rule_already_exists({"asset_id": rule.asset_id, "name": body.name})

    updates = body.model_dump(exclude_unset=True, exclude_none=True)
    if updates:
        updates["updated_by"] = current_user["id"]
        dao.update_rule(db, rule_id, **updates)
        db.commit()

    rule = dao.get_rule(db, rule_id)
    return GovernanceRuleResponse(**_serialize_rule(rule))


@router.delete("/rules/{rule_id}", status_code=200)
async def delete_governance_rule(
    rule_id: int,
    current_user: dict = Depends(require_roles(["admin", "data_admin"])),
    db: Session = Depends(get_db),
):
    """DELETE /governance/rules/{rule_id} — 删除规则（硬删）"""
    dao = DqcDatabase()
    rule = dao.get_rule(db, rule_id)
    if not rule:
        raise DQCError.rule_not_found()

    asset = dao.get_asset(db, rule.asset_id)
    if current_user["role"] != "admin" and asset and asset.owner_id != current_user["id"]:
        raise DQCError.not_asset_owner()

    dao.delete_rule(db, rule_id)
    db.commit()
    return {"message": "规则已删除", "rule_id": rule_id}


@router.post("/scan", response_model=GovernanceScanResponse)
async def trigger_governance_scan(
    body: GovernanceScanRequest,
    current_user: dict = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    """POST /governance/scan — 触发 DQC 扫描"""
    if body.asset_ids and body.scope == "hourly_light":
        raise DQCError.invalid_parameter("asset_ids 和 hourly_light 不可同时指定")

    if is_cycle_locked(body.scope):
        raise DQCError.cycle_in_progress()

    task_ids: List[str] = []

    if body.asset_ids:
        for asset_id in body.asset_ids:
            dao = DqcDatabase()
            asset = dao.get_asset(db, asset_id)
            if not asset or asset.status != "enabled":
                logger.warning("skipping invalid or disabled asset_id=%s", asset_id)
                continue
            task = run_for_asset_task.delay(asset_id, "manual", current_user["id"])
            task_ids.append(task.id)
        return GovernanceScanResponse(
            cycle_id=None,
            task_ids=task_ids,
            message=f"已触发 {len(task_ids)} 个资产的 DQC 扫描",
        )

    if body.scope == "hourly_light":
        task = run_hourly_light_cycle.delay()
    else:
        task = run_daily_full_cycle.delay()
    task_ids.append(task.id)

    return GovernanceScanResponse(
        cycle_id=None,
        task_ids=task_ids,
        message=f"已触发 DQC {body.scope} 周期扫描",
    )


@router.get("/results/{scan_id}", response_model=GovernanceResultsResponse)
async def get_governance_scan_results(
    scan_id: str,
    request: Request,
    db: Session = Depends(get_db),
):
    """GET /governance/results/{scan_id} — 查询扫描结果"""
    get_current_user(request, db)
    dao = DqcDatabase()

    # 优先尝试解析为 cycle_id
    try:
        cycle_uuid = UUID(scan_id)
        cycle = dao.get_cycle(db, cycle_uuid)
        if cycle:
            thresholds = DEFAULT_SIGNAL_THRESHOLDS
            results = _build_result_items(dao, db, cycle_uuid, thresholds)
            return GovernanceResultsResponse(
                scan_id=scan_id,
                status=cycle.status,
                scope=cycle.scope,
                started_at=cycle.started_at.strftime("%Y-%m-%d %H:%M:%S") if cycle.started_at else None,
                completed_at=cycle.completed_at.strftime("%Y-%m-%d %H:%M:%S") if cycle.completed_at else None,
                assets_total=cycle.assets_total,
                assets_processed=cycle.assets_processed,
                assets_failed=cycle.assets_failed,
                rules_executed=cycle.rules_executed,
                p0_count=cycle.p0_count,
                p1_count=cycle.p1_count,
                results=results,
            )
    except ValueError:
        pass

    # 遍历 cycle 列表查找
    cycles = dao.list_cycles(db, page=1, page_size=100)
    for c in cycles["items"]:
        if str(c.id) == scan_id:
            cycle_uuid = c.id
            thresholds = DEFAULT_SIGNAL_THRESHOLDS
            results = _build_result_items(dao, db, cycle_uuid, thresholds)
            return GovernanceResultsResponse(
                scan_id=scan_id,
                status=c.status,
                scope=c.scope,
                started_at=c.started_at.strftime("%Y-%m-%d %H:%M:%S") if c.started_at else None,
                completed_at=c.completed_at.strftime("%Y-%m-%d %H:%M:%S") if c.completed_at else None,
                assets_total=c.assets_total,
                assets_processed=c.assets_processed,
                assets_failed=c.assets_failed,
                rules_executed=c.rules_executed,
                p0_count=c.p0_count,
                p1_count=c.p1_count,
                results=results,
            )

    raise DQCError.cycle_not_found()


@router.get("/drift/{asset_id}")
async def get_asset_drift(
    asset_id: int,
    request: Request,
    db: Session = Depends(get_db),
):
    """GET /governance/drift/{asset_id} — 获取资产漂移数据"""
    get_current_user(request, db)
    dao = DqcDatabase()

    asset = dao.get_asset(db, asset_id)
    if not asset:
        raise DQCError.asset_not_found()

    detector = DriftDetector(dao)
    now = datetime.utcnow()

    prev_scores = detector.compute_prev_scores(db, asset_id)
    d7_avg = detector.compute_7d_avg(db, asset_id, now)
    latest_dims = dao.get_latest_dimension_scores(db, asset_id)

    drift_24h = {}
    drift_vs_7d = {}
    current_scores = {}

    for dim in ALL_DIMENSIONS:
        row = latest_dims.get(dim)
        score = row.score if row else 100.0
        current_scores[dim] = score
        prev = prev_scores.get(dim)
        avg7 = d7_avg.get(dim)
        drift_24h[dim] = round(score - prev, 2) if prev is not None else None
        drift_vs_7d[dim] = round(score - avg7, 2) if avg7 is not None else None

    return {
        "asset_id": asset_id,
        "current_scores": current_scores,
        "drift_24h": drift_24h,
        "drift_vs_7d_avg": drift_vs_7d,
    }


@router.get("/signal/{asset_id}")
async def get_asset_signal(
    asset_id: int,
    request: Request,
    db: Session = Depends(get_db),
):
    """GET /governance/signal/{asset_id} — 获取资产信号灯判定"""
    get_current_user(request, db)
    dao = DqcDatabase()

    asset = dao.get_asset(db, asset_id)
    if not asset:
        raise DQCError.asset_not_found()

    snapshot = dao.get_latest_snapshot(db, asset_id)
    if not snapshot:
        return {
            "asset_id": asset_id,
            "signal": None,
            "confidence_score": None,
            "dimension_signals": {},
            "message": "暂无扫描结果",
        }

    thresholds = asset.signal_thresholds or DEFAULT_SIGNAL_THRESHOLDS

    dim_signals_raw = snapshot.dimension_signals or {}
    dim_signals = {dim: dim_signals_raw.get(dim, "GREEN") for dim in ALL_DIMENSIONS}

    cs_signal = "GREEN"
    if snapshot.confidence_score < thresholds["confidence_p0"]:
        cs_signal = "P0"
    elif snapshot.confidence_score < thresholds["confidence_p1"]:
        cs_signal = "P1"

    worst_dim = max(dim_signals.values(), key=lambda s: SIGNAL_PRIORITY.get(s, 0))
    final_signal = max([worst_dim, cs_signal], key=lambda s: SIGNAL_PRIORITY.get(s, 0))

    return {
        "asset_id": asset_id,
        "confidence_score": snapshot.confidence_score,
        "signal": final_signal,
        "dimension_signals": dim_signals,
        "worst_dimension": worst_dim,
        "confidence_score_signal": cs_signal,
        "thresholds": thresholds,
    }

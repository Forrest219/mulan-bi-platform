"""Metrics Agent — Service 层实现"""

import logging
import re
import uuid
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import func
from sqlalchemy.exc import IntegrityError

from app.core.errors import MulanError
from models.metrics import BiMetricDefinition, BiMetricLineage, BiMetricVersion
from .schemas import MetricCreate, MetricUpdate
from .events import emit_metric_published

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# 哨兵时间：用于标记 pending_review 状态
# reviewed_by 字段有 FK→auth_users 约束，无法写入非法整数。
# 改用 reviewed_at = PENDING_SENTINEL_DT 作为"已提交待审核"标记。
# ---------------------------------------------------------------------------
_PENDING_SENTINEL_DT = datetime(1970, 1, 1, 0, 0, 0)  # UTC epoch 哨兵时间


# ---------------------------------------------------------------------------
# 内部辅助
# ---------------------------------------------------------------------------

def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _is_pending(reviewed_at) -> bool:
    """检查 reviewed_at 是否为 pending_review 哨兵值。"""
    if reviewed_at is None:
        return False
    # 兼容 aware/naive datetime 比较
    ra = reviewed_at.replace(tzinfo=None) if hasattr(reviewed_at, 'tzinfo') and reviewed_at.tzinfo else reviewed_at
    return ra == _PENDING_SENTINEL_DT


def _get_metric_status(metric: BiMetricDefinition) -> str:
    """
    根据 ORM 对象字段推断语义状态。

    状态优先级（从高到低）：
    | 状态           | 条件                                                              |
    |---------------|-------------------------------------------------------------------|
    | archived      | is_active = False AND (published_at IS NOT NULL OR approved 过)   |
    | published     | is_active = True AND published_at IS NOT NULL                     |
    | approved      | reviewed_at IS NOT NULL AND NOT pending AND published_at IS NULL  |
    | pending_review| reviewed_at == SENTINEL_DT                                       |
    | draft         | 其他所有情况                                                       |

    注意：pending_review 用 reviewed_at = 1970-01-01 哨兵时间标记，
    avoided reviewed_by=-1（FK 约束违反）。
    """
    if metric.is_active and metric.published_at is not None:
        return "published"

    if _is_pending(metric.reviewed_at):
        return "pending_review"

    if (
        metric.reviewed_at is not None
        and not _is_pending(metric.reviewed_at)
        and metric.published_at is None
    ):
        # reviewed_at 有真实时间且不是哨兵 → approved
        # P1-5：原 pass 为死代码（published_at is None 时无法同时满足已发布下线条件）
        return "approved"

    if not metric.is_active and (metric.published_at is not None):
        # is_active=False 且曾经发布过（published_at is not None）→ archived
        return "archived"

    return "draft"


def _get_datasource_or_400(db, datasource_id: int):
    """校验 datasource_id 存在于 bi_data_sources，不存在则抛出 400 DS_004。"""
    from sqlalchemy import text
    result = db.execute(
        text("SELECT id FROM bi_data_sources WHERE id = :id"),
        {"id": datasource_id},
    ).first()
    if result is None:
        raise MulanError("DS_004", f"数据源不存在：id={datasource_id}", 400)


def _get_metric_or_404(db, metric_id: uuid.UUID, tenant_id: uuid.UUID) -> BiMetricDefinition:
    metric = (
        db.query(BiMetricDefinition)
        .filter(
            BiMetricDefinition.id == metric_id,
            BiMetricDefinition.tenant_id == tenant_id,
        )
        .first()
    )
    if metric is None:
        raise MulanError("MC_404", f"指标不存在：id={metric_id}", 404)
    return metric


def _next_version(db, metric_id: uuid.UUID) -> int:
    """获取该指标的下一个版本号。"""
    max_ver = (
        db.query(func.max(BiMetricVersion.version))
        .filter(BiMetricVersion.metric_id == metric_id)
        .scalar()
    )
    return (max_ver or 0) + 1


def _write_version(
    db,
    metric: BiMetricDefinition,
    change_type: str,
    changes: dict,
    changed_by: int,
    change_reason: Optional[str] = None,
):
    ver = BiMetricVersion(
        tenant_id=metric.tenant_id,
        metric_id=metric.id,
        version=_next_version(db, metric.id),
        change_type=change_type,
        changes=changes,
        changed_by=changed_by,
        change_reason=change_reason,
    )
    db.add(ver)


def _validate_formula_template(formula_template: Optional[str], filters: Optional[dict]):
    """
    校验 formula_template 中的 {{xxx}} 参数在 filters 中均有对应 key。
    不合法时抛出 400 MC_003。
    """
    if not formula_template:
        return
    params = re.findall(r"\{\{(\w+)\}\}", formula_template)
    if not params:
        return
    filter_keys = set((filters or {}).keys())
    missing = [p for p in params if p not in filter_keys]
    if missing:
        raise MulanError(
            "MC_003",
            f"formula_template 参数未在 filters 中定义：{missing}",
            400,
            {"missing_params": missing},
        )


# =============================================================================
# CRUD
# =============================================================================

def create_metric(db, data: MetricCreate, user_id: int, tenant_id: uuid.UUID):
    """
    创建新指标定义。

    Raises:
        MulanError(DS_004, 400): datasource_id 不存在
        MulanError(MC_001, 409): 同 tenant 下 name 重复
    """
    _get_datasource_or_400(db, data.datasource_id)

    metric = BiMetricDefinition(
        tenant_id=tenant_id,
        name=data.name,
        name_zh=data.name_zh,
        metric_type=data.metric_type.value if hasattr(data.metric_type, "value") else data.metric_type,
        business_domain=data.business_domain,
        description=data.description,
        formula=data.formula,
        formula_template=data.formula_template,
        aggregation_type=data.aggregation_type.value if data.aggregation_type and hasattr(data.aggregation_type, "value") else data.aggregation_type,
        result_type=data.result_type.value if data.result_type and hasattr(data.result_type, "value") else data.result_type,
        unit=data.unit,
        precision=data.precision,
        datasource_id=data.datasource_id,
        table_name=data.table_name,
        column_name=data.column_name,
        filters=data.filters,
        sensitivity_level=data.sensitivity_level.value if hasattr(data.sensitivity_level, "value") else data.sensitivity_level,
        is_active=False,
        lineage_status="unknown",
        created_by=user_id,
        reviewed_by=None,
        reviewed_at=None,
        published_at=None,
    )
    db.add(metric)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise MulanError("MC_001", f"指标名称已存在：{data.name}", 409)
    db.commit()
    db.refresh(metric)
    return metric


def list_metrics(
    db,
    tenant_id: uuid.UUID,
    page: int = 1,
    page_size: int = 20,
    business_domain: Optional[str] = None,
    metric_type: Optional[str] = None,
    datasource_id: Optional[int] = None,
    is_active: Optional[bool] = None,
    sensitivity_level: Optional[str] = None,
    search: Optional[str] = None,
) -> tuple[list, int]:
    """
    查询指标列表，支持多维过滤与分页。

    Returns:
        (items: list[BiMetricDefinition], total: int)
    """
    q = db.query(BiMetricDefinition).filter(BiMetricDefinition.tenant_id == tenant_id)

    if business_domain is not None:
        q = q.filter(BiMetricDefinition.business_domain == business_domain)
    if metric_type is not None:
        q = q.filter(BiMetricDefinition.metric_type == metric_type)
    if datasource_id is not None:
        q = q.filter(BiMetricDefinition.datasource_id == datasource_id)
    if is_active is not None:
        q = q.filter(BiMetricDefinition.is_active == is_active)
    if sensitivity_level is not None:
        q = q.filter(BiMetricDefinition.sensitivity_level == sensitivity_level)
    if search:
        pattern = f"%{search}%"
        q = q.filter(
            BiMetricDefinition.name.ilike(pattern)
            | BiMetricDefinition.name_zh.ilike(pattern)
            | BiMetricDefinition.description.ilike(pattern)
        )

    total = q.count()
    offset = (page - 1) * page_size
    items = q.order_by(BiMetricDefinition.created_at.desc()).offset(offset).limit(page_size).all()
    return items, total


def get_metric(db, metric_id: uuid.UUID, tenant_id: uuid.UUID) -> BiMetricDefinition:
    """按 ID 获取指标详情，不存在则 404 MC_404。"""
    return _get_metric_or_404(db, metric_id, tenant_id)


def update_metric(
    db, metric_id: uuid.UUID, data: MetricUpdate, user_id: int, tenant_id: uuid.UUID
) -> BiMetricDefinition:
    """
    PATCH 语义更新指标字段，写入版本记录。

    - formula / formula_template 变更 → lineage_status 重置为 unknown
    - 若当前 published → 任何变更使 is_active=False, published_at=None（需重新走流程）
    """
    metric = _get_metric_or_404(db, metric_id, tenant_id)
    current_status = _get_metric_status(metric)

    update_data = data.model_dump(exclude_none=True)
    if not update_data:
        return metric

    # 检查 datasource_id 是否合法
    if "datasource_id" in update_data:
        _get_datasource_or_400(db, update_data["datasource_id"])

    # 记录哪些字段实际发生了变化
    changes = {}
    formula_changed = False

    for field, new_val in update_data.items():
        old_val = getattr(metric, field, None)
        # 处理 Enum 值
        if hasattr(new_val, "value"):
            new_val = new_val.value
        if old_val != new_val:
            changes[field] = {"from": old_val, "to": new_val}
            setattr(metric, field, new_val)
            if field in ("formula", "formula_template"):
                formula_changed = True

    if not changes:
        return metric

    if formula_changed:
        metric.lineage_status = "unknown"

    if current_status == "published":
        # 已发布指标被修改 → 退回草稿
        metric.is_active = False
        metric.published_at = None

    metric.updated_at = _now()

    _write_version(
        db,
        metric,
        change_type="formula_updated" if formula_changed else "description_updated",
        changes=changes,
        changed_by=user_id,
    )

    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise MulanError("MC_001", f"指标名称已存在：{data.name}", 409)
    db.commit()
    db.refresh(metric)
    return metric


def archive_metric(db, metric_id: uuid.UUID, user_id: int, tenant_id: uuid.UUID) -> dict:
    """软删除/下线指标（is_active=False）。"""
    metric = _get_metric_or_404(db, metric_id, tenant_id)
    current_status = _get_metric_status(metric)
    if current_status == "archived":
        raise MulanError("MC_400", "指标已下线，无需重复操作", 400)

    metric.is_active = False
    metric.updated_at = _now()

    _write_version(
        db,
        metric,
        change_type="archived",
        changes={"is_active": {"from": True, "to": False}},
        changed_by=user_id,
    )

    # P1-6：写操作保护
    try:
        db.commit()
    except Exception:
        db.rollback()
        raise
    return {"metric_id": str(metric_id), "archived": True}


# =============================================================================
# 审核流
# =============================================================================

def submit_review(db, metric_id: uuid.UUID, user_id: int, tenant_id: uuid.UUID) -> BiMetricDefinition:
    """
    提交审核（draft → pending_review）。
    用 reviewed_at = PENDING_SENTINEL_DT (1970-01-01) 哨兵时间标记待审核。
    （不使用 reviewed_by=-1 以避免 FK 约束冲突）
    """
    # P1-1：悲观锁，防止并发重复提交
    metric = (
        db.query(BiMetricDefinition)
        .filter_by(id=metric_id, tenant_id=tenant_id)
        .with_for_update()
        .first()
    )
    if metric is None:
        raise MulanError("MC_404", f"指标不存在：id={metric_id}", 404)
    current_status = _get_metric_status(metric)
    if current_status != "draft":
        raise MulanError(
            "MC_400",
            f"只有草稿状态才能提交审核，当前状态：{current_status}",
            400,
            {"current_status": current_status},
        )

    metric.reviewed_at = _PENDING_SENTINEL_DT
    metric.updated_at = _now()
    # P1-6：写操作保护
    try:
        db.commit()
    except Exception:
        db.rollback()
        raise
    db.refresh(metric)
    return metric


def approve_metric(db, metric_id: uuid.UUID, reviewer_id: int, tenant_id: uuid.UUID) -> BiMetricDefinition:
    """
    批准指标（pending_review → approved）。
    审核人不能与创建人相同。
    """
    # P1-1：悲观锁，防止并发重复审批
    metric = (
        db.query(BiMetricDefinition)
        .filter_by(id=metric_id, tenant_id=tenant_id)
        .with_for_update()
        .first()
    )
    if metric is None:
        raise MulanError("MC_404", f"指标不存在：id={metric_id}", 404)
    current_status = _get_metric_status(metric)
    if current_status != "pending_review":
        raise MulanError(
            "MC_400",
            f"只有待审核状态才能批准，当前状态：{current_status}",
            400,
            {"current_status": current_status},
        )

    if reviewer_id == metric.created_by:
        raise MulanError("MC_400", "审核人不能与创建人相同", 400)

    now = _now()
    metric.reviewed_by = reviewer_id
    metric.reviewed_at = now   # 覆盖哨兵时间，写入真实审核时间
    metric.updated_at = now
    # P1-6：写操作保护
    try:
        db.commit()
    except Exception:
        db.rollback()
        raise
    db.refresh(metric)
    return metric


def reject_metric(
    db, metric_id: uuid.UUID, reason: str, reviewer_id: int, tenant_id: uuid.UUID
) -> BiMetricDefinition:
    """
    拒绝指标（pending_review → draft）。
    清空 reviewed_by / reviewed_at，写版本记录保存原因。
    """
    # P1-1：悲观锁，防止并发重复拒绝
    metric = (
        db.query(BiMetricDefinition)
        .filter_by(id=metric_id, tenant_id=tenant_id)
        .with_for_update()
        .first()
    )
    if metric is None:
        raise MulanError("MC_404", f"指标不存在：id={metric_id}", 404)
    current_status = _get_metric_status(metric)
    if current_status != "pending_review":
        raise MulanError(
            "MC_400",
            f"只有待审核状态才能拒绝，当前状态：{current_status}",
            400,
            {"current_status": current_status},
        )

    metric.reviewed_by = None
    metric.reviewed_at = None   # 清空哨兵时间，回到 draft
    metric.updated_at = _now()

    _write_version(
        db,
        metric,
        change_type="description_updated",
        changes={"reject_reason": reason, "rejected_by": reviewer_id},
        changed_by=reviewer_id,
        change_reason=reason,
    )

    # P1-6：写操作保护
    try:
        db.commit()
    except Exception:
        db.rollback()
        raise
    db.refresh(metric)
    return metric


def _sensitivity_rank(level: str) -> int:
    """
    返回敏感级别的排序权重（数值越高代表越高密级）。
    用于判断上游字段是否比指标标注级别更高。
    """
    ranking = {
        "public": 0,
        "internal": 1,
        "confidential": 2,
        "restricted": 3,
    }
    return ranking.get(level.lower(), 0)


def _check_sensitivity_level_upgrade(db, metric: BiMetricDefinition) -> tuple[str, Optional[str]]:
    """
    MC_004：检查上游血缘字段的 sensitivity_level 是否高于指标当前标注值。

    流程：
    1. 从 bi_metric_lineage 查出该指标的所有上游字段（同一 datasource_id）
    2. 字段的 sensitivity_level 存储在语义层（bi_field_semantics），通过 datasource_id+table_name+column_name 查找
    3. 取上游 max sensitivity_level 与指标的 sensitivity_level 比较
    4. 若指标级别 < 上游最高级别 → 自动升级到上游最高级别，返回警告信息

    Returns:
        (actual_sensitivity_level, warning_message or None)
    """
    from services.semantic_maintenance.models import FieldSemantics

    lineage_records = (
        db.query(BiMetricLineage)
        .filter(BiMetricLineage.metric_id == metric.id)
        .all()
    )
    if not lineage_records:
        return metric.sensitivity_level, None

    # 收集上游字段 sensitivity_level
    upstream_levels: list[str] = []
    for rec in lineage_records:
        # 通过 datasource_id + table_name + column_name 查语义层
        field_sem = (
            db.query(FieldSemantics)
            .filter(
                FieldSemantics.datasource_id == rec.datasource_id,
                FieldSemantics.table_name == rec.table_name,
                FieldSemantics.column_name == rec.column_name,
            )
            .first()
        )
        if field_sem and field_sem.sensitivity_level:
            upstream_levels.append(field_sem.sensitivity_level)

    if not upstream_levels:
        return metric.sensitivity_level, None

    upstream_max_rank = max(_sensitivity_rank(l) for l in upstream_levels)
    metric_rank = _sensitivity_rank(metric.sensitivity_level)

    if metric_rank < upstream_max_rank:
        # 反查上游最高级别对应的字符串
        rank_to_level = {v: k for k, v in {
            "public": 0, "internal": 1, "confidential": 2, "restricted": 3
        }.items()}
        upgraded_level = rank_to_level.get(upstream_max_rank, metric.sensitivity_level)

        warning = (
            f"MC_004：上游字段敏感级别（{upstream_max_rank} 级）高于指标当前标注（{metric_rank} 级），"
            f"自动升级指标 sensitivity_level 为 {upgraded_level}"
        )
        logger.warning(
            "MC_004 sensitivity_level upgrade: metric_id=%s, old=%s, new=%s, upstream_max=%s",
            metric.id,
            metric.sensitivity_level,
            upgraded_level,
            max(upstream_levels),
        )
        return upgraded_level, warning

    return metric.sensitivity_level, None


def publish_metric(db, metric_id: uuid.UUID, user_id: int, tenant_id: uuid.UUID) -> BiMetricDefinition:
    """
    发布指标（approved → published）。

    额外校验：
    - lineage_status in ("resolved", "manual")  → 否则 400 MC_002
    - formula_template 参数均有对应 filters key  → 否则 400 MC_003
    - MC_004：上游字段 sensitivity_level 高于指标标注值时自动升级
    """
    metric = _get_metric_or_404(db, metric_id, tenant_id)
    current_status = _get_metric_status(metric)
    if current_status != "approved":
        raise MulanError(
            "MC_400",
            f"只有已批准状态才能发布，当前状态：{current_status}",
            400,
            {"current_status": current_status},
        )

    if metric.lineage_status not in ("resolved", "manual"):
        raise MulanError(
            "MC_002",
            f"血缘状态必须为 resolved 或 manual 才能发布，当前：{metric.lineage_status}",
            400,
            {"lineage_status": metric.lineage_status},
        )

    _validate_formula_template(metric.formula_template, metric.filters)

    # MC_004：敏感级别自动升级检查
    actual_sensitivity, mc004_warning = _check_sensitivity_level_upgrade(db, metric)
    if mc004_warning:
        metric.sensitivity_level = actual_sensitivity

    now = _now()
    metric.is_active = True
    metric.published_at = now
    metric.updated_at = now

    changes = {"published_at": now.isoformat(), "is_active": True, "sensitivity_level": actual_sensitivity}
    _write_version(
        db,
        metric,
        change_type="created",
        changes=changes,
        changed_by=user_id,
    )

    # P1-6：写操作保护
    try:
        db.commit()
    except Exception:
        db.rollback()
        raise
    db.refresh(metric)

    # 发射 metric.published 事件（失败时仅记录日志，不阻断主流程）
    try:
        emit_metric_published(
            db=db,
            metric_id=metric.id,
            name=metric.name,
            tenant_id=metric.tenant_id,
            actor_id=user_id,
        )
    except Exception as _evt_exc:
        logger.warning(
            "publish_metric 事件发射失败（已忽略）：metric_id=%s, error=%s",
            metric.id,
            _evt_exc,
        )

    return metric


# =============================================================================
# 内部查询
# =============================================================================

def lookup_metrics(
    db,
    names: list[str],
    tenant_id: uuid.UUID,
    datasource_id: Optional[int] = None,
) -> dict:
    """
    批量按名称查找已发布指标（Data Agent 内部调用）。

    Returns:
        {"metrics": [...], "not_found": [...]}
    """
    q = db.query(BiMetricDefinition).filter(
        BiMetricDefinition.tenant_id == tenant_id,
        BiMetricDefinition.is_active == True,
        BiMetricDefinition.name.in_(names),
    )
    if datasource_id is not None:
        q = q.filter(BiMetricDefinition.datasource_id == datasource_id)

    found = q.all()
    found_names = {m.name for m in found}
    not_found = [n for n in names if n not in found_names]

    return {
        "metrics": found,
        "not_found": not_found,
    }


# =============================================================================
# 版本历史查询
# =============================================================================

def get_versions(
    db,
    metric_id: uuid.UUID,
    tenant_id: uuid.UUID,
    page: int = 1,
    page_size: int = 20,
) -> tuple[list["BiMetricVersion"], int]:
    """
    查询指标版本历史，分页返回。

    Returns:
        (items: list[BiMetricVersion], total: int)
    """
    # 先校验指标存在且属于该租户
    _get_metric_or_404(db, metric_id, tenant_id)

    q = db.query(BiMetricVersion).filter(
        BiMetricVersion.metric_id == metric_id,
        BiMetricVersion.tenant_id == tenant_id,
    )

    total = q.count()
    offset = (page - 1) * page_size
    items = (
        q.order_by(BiMetricVersion.version.desc())
        .offset(offset)
        .limit(page_size)
        .all()
    )
    return items, total

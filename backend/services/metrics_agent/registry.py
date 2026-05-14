"""Metrics Agent — Service 层实现"""

import json
import logging
import re
import uuid
from datetime import datetime, timezone
from types import SimpleNamespace
from typing import Any, Optional

from sqlalchemy import bindparam, delete, func, inspect, text
from sqlalchemy.exc import IntegrityError

from app.core.errors import MulanError
from models.metrics import (
    BiMetricBinding,
    BiMetricDefinition,
    BiMetricDependency,
    BiMetricLineage,
    BiMetricVersion,
)
from .schemas import MetricCreate, MetricUpdate
from .events import emit_metric_published

logger = logging.getLogger(__name__)

_METRIC_ALIASES_TABLE = "bi_metric_aliases"
_METRIC_BINDINGS_TABLE = "bi_metric_bindings"
_METRIC_DEPENDENCIES_TABLE = "bi_metric_dependencies"
_TABLEAU_SOURCE_TYPE = "tableau_published_datasource"
_RELATIONSHIP_FIELDS = {
    "tableau_connection_id",
    "tableau_asset_id",
    "tableau_datasource_luid",
    "field_mappings",
    "dependency_metric_ids",
    "numerator_metric_id",
    "denominator_metric_id",
    "formula_expression",
}

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


def _normalize_lookup_names(names: list[str]) -> list[str]:
    """Accept repeated query params and comma-separated names while preserving order."""
    normalized: list[str] = []
    seen: set[str] = set()
    for raw in names:
        for part in str(raw).split(","):
            name = part.strip()
            if not name:
                continue
            key = name.casefold()
            if key in seen:
                continue
            seen.add(key)
            normalized.append(name)
    return normalized


def _table_exists(db, table_name: str) -> bool:
    try:
        return inspect(db.get_bind()).has_table(table_name)
    except Exception:
        logger.warning("lookup table existence check failed: table=%s", table_name, exc_info=True)
        return False


def _json_or_default(value: Any, default: Any) -> Any:
    if value is None:
        return default
    if isinstance(value, str):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return default
    return value


def _binding_error(requested_name: str, metric: BiMetricDefinition, code: str, message: str) -> dict[str, Any]:
    return {
        "requested_name": requested_name,
        "metric_name": metric.name or metric.name_zh,
        "metric_code": metric.metric_code,
        "metric_id": str(metric.id),
        "error_code": code,
        "message": message,
    }


def _metric_label(metric: BiMetricDefinition) -> str:
    return metric.name_zh or metric.name or metric.metric_code


def _enum_value(value: Any) -> Any:
    return value.value if hasattr(value, "value") else value


def _generate_metric_code(db, tenant_id: uuid.UUID) -> str:
    row = db.execute(
        text(
            """
            SELECT metric_code
            FROM bi_metric_definitions
            WHERE tenant_id = :tenant_id
              AND metric_code LIKE 'MET-%'
            ORDER BY metric_code DESC
            LIMIT 1
            """
        ),
        {"tenant_id": tenant_id},
    ).first()
    if row is None or not row[0]:
        return "MET-000001"
    try:
        next_number = int(str(row[0]).rsplit("-", 1)[1]) + 1
    except (IndexError, ValueError):
        next_number = (
            db.query(func.count(BiMetricDefinition.id))
            .filter(BiMetricDefinition.tenant_id == tenant_id)
            .scalar()
            or 0
        ) + 1
    return f"MET-{next_number:06d}"


def _has_nonempty_mapping(value: Any) -> bool:
    parsed = _json_or_default(value, {})
    return isinstance(parsed, dict) and bool(parsed)


def _get_primary_tableau_binding(db, metric_id: uuid.UUID, tenant_id: uuid.UUID) -> Optional[BiMetricBinding]:
    return (
        db.query(BiMetricBinding)
        .filter(
            BiMetricBinding.tenant_id == tenant_id,
            BiMetricBinding.metric_id == metric_id,
            BiMetricBinding.source_type == _TABLEAU_SOURCE_TYPE,
            BiMetricBinding.is_primary == True,
            BiMetricBinding.is_active == True,
        )
        .order_by(BiMetricBinding.created_at.desc())
        .first()
    )


def _is_valid_tableau_binding(metric: BiMetricDefinition, binding: Optional[BiMetricBinding]) -> bool:
    if binding is None:
        return False
    if metric.metric_type == "atomic":
        return _has_nonempty_mapping(binding.field_mappings)
    if metric.metric_type in ("derived", "ratio"):
        return binding.formula_expression is not None
    return False


def _ensure_metric_has_valid_tableau_binding(db, metric: BiMetricDefinition):
    binding = _get_primary_tableau_binding(db, metric.id, metric.tenant_id)
    if not _is_valid_tableau_binding(metric, binding):
        raise MulanError(
            "MC_BINDING_REQUIRED",
            f"指标缺少有效 Tableau binding，不能发布或作为依赖：{_metric_label(metric)}",
            400,
            {"metric_id": str(metric.id), "metric_code": metric.metric_code},
        )
    return binding


def _dependency_rows_for_metric(db, metric_id: uuid.UUID, tenant_id: uuid.UUID) -> list[BiMetricDependency]:
    return (
        db.query(BiMetricDependency)
        .filter(
            BiMetricDependency.tenant_id == tenant_id,
            BiMetricDependency.metric_id == metric_id,
        )
        .order_by(BiMetricDependency.expression_order.asc())
        .all()
    )


def _would_create_cycle(
    db,
    metric_id: uuid.UUID,
    tenant_id: uuid.UUID,
    depends_on_ids: list[uuid.UUID],
) -> bool:
    stack = list(depends_on_ids)
    seen: set[uuid.UUID] = set()
    while stack:
        current_id = stack.pop()
        if current_id == metric_id:
            return True
        if current_id in seen:
            continue
        seen.add(current_id)
        rows = _dependency_rows_for_metric(db, current_id, tenant_id)
        stack.extend(row.depends_on_metric_id for row in rows)
    return False


def _validate_dependency_metrics(
    db,
    tenant_id: uuid.UUID,
    dependency_specs: list[dict[str, Any]],
) -> tuple[list[BiMetricDefinition], dict[str, Any]]:
    dependency_ids = [spec["depends_on_metric_id"] for spec in dependency_specs]
    if not dependency_ids:
        return [], {}

    dependencies = (
        db.query(BiMetricDefinition)
        .filter(
            BiMetricDefinition.tenant_id == tenant_id,
            BiMetricDefinition.id.in_(dependency_ids),
        )
        .all()
    )
    by_id = {metric.id: metric for metric in dependencies}
    missing = [str(dep_id) for dep_id in dependency_ids if dep_id not in by_id]
    if missing:
        raise MulanError("MC_DEPENDENCY_INVALID", "依赖指标不存在或不属于当前租户", 400, {"missing": missing})

    binding_source: Optional[dict[str, Any]] = None
    for metric in dependencies:
        if not metric.is_active or metric.published_at is None:
            raise MulanError(
                "MC_DEPENDENCY_INVALID",
                f"依赖指标未发布或已下线：{_metric_label(metric)}",
                400,
                {"metric_id": str(metric.id), "metric_code": metric.metric_code},
            )
        binding = _ensure_metric_has_valid_tableau_binding(db, metric)
        current_source = {
            "tableau_connection_id": binding.tableau_connection_id,
            "tableau_asset_id": binding.tableau_asset_id,
            "tableau_datasource_luid": binding.tableau_datasource_luid,
        }
        if binding_source is None:
            binding_source = current_source
        elif (
            binding_source["tableau_connection_id"] != current_source["tableau_connection_id"]
            or binding_source["tableau_datasource_luid"] != current_source["tableau_datasource_luid"]
        ):
            raise MulanError("MC_DEPENDENCY_INVALID", "派生/比率指标暂不支持跨 Tableau datasource 依赖", 400)

    ordered = [by_id[dep_id] for dep_id in dependency_ids]
    return ordered, binding_source or {}


def _prepare_relationships(db, data: MetricCreate | MetricUpdate, tenant_id: uuid.UUID, metric_type: str):
    dependency_specs: list[dict[str, Any]] = []
    binding_source: dict[str, Any] = {
        "tableau_connection_id": getattr(data, "tableau_connection_id", None),
        "tableau_asset_id": getattr(data, "tableau_asset_id", None),
        "tableau_datasource_luid": getattr(data, "tableau_datasource_luid", None),
    }

    if metric_type == "atomic":
        if (
            getattr(data, "dependency_metric_ids", None)
            or getattr(data, "numerator_metric_id", None)
            or getattr(data, "denominator_metric_id", None)
        ):
            raise MulanError("MC_DEPENDENCY_INVALID", "atomic 指标不允许声明指标依赖", 400)
        if not _has_nonempty_mapping(getattr(data, "field_mappings", None)):
            raise MulanError("MC_BINDING_REQUIRED", "atomic 指标必须提供 Tableau field_mappings", 400)
        if not binding_source["tableau_connection_id"] or not binding_source["tableau_datasource_luid"]:
            raise MulanError("MC_BINDING_REQUIRED", "atomic 指标必须提供 Tableau connection_id 和 datasource_luid", 400)
        return [], [], binding_source

    if metric_type == "derived":
        dependency_ids = list(getattr(data, "dependency_metric_ids", None) or [])
        if not dependency_ids:
            raise MulanError("MC_DEPENDENCY_INVALID", "derived 指标必须提供 dependency_metric_ids", 400)
        if getattr(data, "formula_expression", None) is None:
            raise MulanError("MC_DEPENDENCY_INVALID", "derived 指标必须提供 formula_expression", 400)
        for index, dependency_id in enumerate(dependency_ids):
            dependency_specs.append(
                {
                    "depends_on_metric_id": dependency_id,
                    "dependency_role": "base",
                    "expression_order": index,
                }
            )
    elif metric_type == "ratio":
        numerator_id = getattr(data, "numerator_metric_id", None)
        denominator_id = getattr(data, "denominator_metric_id", None)
        if numerator_id is None or denominator_id is None:
            raise MulanError("MC_DEPENDENCY_INVALID", "ratio 指标必须提供 numerator_metric_id 和 denominator_metric_id", 400)
        if numerator_id == denominator_id:
            raise MulanError("MC_DEPENDENCY_INVALID", "ratio 分子和分母不能引用同一个指标", 400)
        if getattr(data, "formula_expression", None) is None:
            raise MulanError("MC_DEPENDENCY_INVALID", "ratio 指标必须提供 formula_expression", 400)
        dependency_specs = [
            {"depends_on_metric_id": numerator_id, "dependency_role": "numerator", "expression_order": 0},
            {"depends_on_metric_id": denominator_id, "dependency_role": "denominator", "expression_order": 1},
        ]
    else:
        raise MulanError("MC_400", f"不支持的 metric_type：{metric_type}", 400)

    dependencies, dependency_source = _validate_dependency_metrics(db, tenant_id, dependency_specs)
    for key in ("tableau_connection_id", "tableau_datasource_luid"):
        explicit_value = binding_source.get(key)
        if explicit_value is not None and explicit_value != dependency_source.get(key):
            raise MulanError("MC_DEPENDENCY_INVALID", "指标 binding 与依赖指标 Tableau datasource 不一致", 400)
    binding_source = {**dependency_source, **{k: v for k, v in binding_source.items() if v is not None}}
    return dependency_specs, dependencies, binding_source


def _replace_dependencies(
    db,
    metric: BiMetricDefinition,
    dependency_specs: list[dict[str, Any]],
):
    db.execute(
        delete(BiMetricDependency).where(
            BiMetricDependency.tenant_id == metric.tenant_id,
            BiMetricDependency.metric_id == metric.id,
        )
    )
    for spec in dependency_specs:
        db.add(
            BiMetricDependency(
                tenant_id=metric.tenant_id,
                metric_id=metric.id,
                depends_on_metric_id=spec["depends_on_metric_id"],
                dependency_role=spec["dependency_role"],
                expression_order=spec["expression_order"],
                weight=spec.get("weight"),
            )
        )


def _replace_primary_tableau_binding(
    db,
    metric: BiMetricDefinition,
    data: MetricCreate | MetricUpdate,
    dependencies: list[BiMetricDefinition],
    binding_source: dict[str, Any],
):
    existing = _get_primary_tableau_binding(db, metric.id, metric.tenant_id)
    if existing is not None:
        existing.is_primary = False
        existing.is_active = False

    required_base_metrics = [_metric_label(dep) for dep in dependencies]
    db.add(
        BiMetricBinding(
            tenant_id=metric.tenant_id,
            metric_id=metric.id,
            source_type=_TABLEAU_SOURCE_TYPE,
            datasource_id=None,
            tableau_connection_id=binding_source.get("tableau_connection_id"),
            tableau_asset_id=binding_source.get("tableau_asset_id"),
            tableau_datasource_luid=binding_source.get("tableau_datasource_luid"),
            field_mappings=getattr(data, "field_mappings", None),
            required_base_metrics=required_base_metrics,
            formula_expression=getattr(data, "formula_expression", None),
            is_primary=True,
            is_active=True,
        )
    )


def _relationship_data_for_update(
    db,
    metric: BiMetricDefinition,
    data: MetricUpdate,
    target_metric_type: str,
) -> SimpleNamespace:
    current_binding = _get_primary_tableau_binding(db, metric.id, metric.tenant_id)
    rows = _dependency_rows_for_metric(db, metric.id, metric.tenant_id)
    by_role = {row.dependency_role: row.depends_on_metric_id for row in rows}

    dependency_metric_ids = data.dependency_metric_ids
    if dependency_metric_ids is None and target_metric_type == "derived":
        dependency_metric_ids = [row.depends_on_metric_id for row in rows if row.dependency_role == "base"]

    numerator_metric_id = data.numerator_metric_id
    denominator_metric_id = data.denominator_metric_id
    if target_metric_type == "ratio":
        numerator_metric_id = numerator_metric_id or by_role.get("numerator")
        denominator_metric_id = denominator_metric_id or by_role.get("denominator")

    return SimpleNamespace(
        tableau_connection_id=data.tableau_connection_id
        if data.tableau_connection_id is not None
        else getattr(current_binding, "tableau_connection_id", None),
        tableau_asset_id=data.tableau_asset_id
        if data.tableau_asset_id is not None
        else getattr(current_binding, "tableau_asset_id", None),
        tableau_datasource_luid=data.tableau_datasource_luid
        if data.tableau_datasource_luid is not None
        else getattr(current_binding, "tableau_datasource_luid", None),
        field_mappings=data.field_mappings
        if data.field_mappings is not None
        else getattr(current_binding, "field_mappings", None),
        dependency_metric_ids=dependency_metric_ids,
        numerator_metric_id=numerator_metric_id,
        denominator_metric_id=denominator_metric_id,
        formula_expression=data.formula_expression
        if data.formula_expression is not None
        else getattr(current_binding, "formula_expression", None),
    )


def _validate_existing_dependency_contract(db, metric: BiMetricDefinition):
    if metric.metric_type == "atomic":
        if _dependency_rows_for_metric(db, metric.id, metric.tenant_id):
            raise MulanError("MC_DEPENDENCY_INVALID", "atomic 指标不允许存在指标依赖", 400)
        return

    rows = _dependency_rows_for_metric(db, metric.id, metric.tenant_id)
    if metric.metric_type == "derived":
        if not rows or any(row.dependency_role != "base" for row in rows):
            raise MulanError("MC_DEPENDENCY_INVALID", "derived 指标必须至少有一个 base 依赖", 400)
    elif metric.metric_type == "ratio":
        roles = [row.dependency_role for row in rows]
        if roles.count("numerator") != 1 or roles.count("denominator") != 1 or len(rows) != 2:
            raise MulanError("MC_DEPENDENCY_INVALID", "ratio 指标必须且只能有 numerator/denominator 依赖", 400)

    dependency_ids = [row.depends_on_metric_id for row in rows]
    dependency_specs = [
        {
            "depends_on_metric_id": row.depends_on_metric_id,
            "dependency_role": row.dependency_role,
            "expression_order": row.expression_order,
        }
        for row in rows
    ]
    _validate_dependency_metrics(db, metric.tenant_id, dependency_specs)
    if _would_create_cycle(db, metric.id, metric.tenant_id, dependency_ids):
        raise MulanError("MC_DEPENDENCY_INVALID", "指标依赖存在环路", 400)


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
    if data.datasource_id is not None:
        _get_datasource_or_400(db, data.datasource_id)

    metric_type = _enum_value(data.metric_type)
    dependency_specs, dependencies, binding_source = _prepare_relationships(db, data, tenant_id, metric_type)

    metric = BiMetricDefinition(
        tenant_id=tenant_id,
        metric_code=_generate_metric_code(db, tenant_id),
        name=data.name,
        name_zh=data.name_zh,
        metric_type=metric_type,
        business_domain=data.business_domain,
        description=data.description,
        formula=data.formula,
        formula_template=data.formula_template,
        aggregation_type=_enum_value(data.aggregation_type) if data.aggregation_type else None,
        result_type=_enum_value(data.result_type) if data.result_type else None,
        unit=data.unit,
        precision=data.precision,
        datasource_id=data.datasource_id,
        table_name=data.table_name,
        column_name=data.column_name,
        filters=data.filters,
        sensitivity_level=_enum_value(data.sensitivity_level),
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
        if dependency_specs:
            if _would_create_cycle(
                db,
                metric_id=metric.id,
                tenant_id=tenant_id,
                depends_on_ids=[spec["depends_on_metric_id"] for spec in dependency_specs],
            ):
                raise MulanError("MC_DEPENDENCY_INVALID", "指标依赖存在环路", 400)
            _replace_dependencies(db, metric, dependency_specs)
        _replace_primary_tableau_binding(db, metric, data, dependencies, binding_source)
        db.flush()
    except IntegrityError:
        db.rollback()
        raise MulanError("MC_001", f"指标编号或技术别名已存在：{data.name or metric.metric_code}", 409)
    except MulanError:
        db.rollback()
        raise
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

    target_metric_type = _enum_value(update_data.get("metric_type", metric.metric_type))
    relationship_update = bool(_RELATIONSHIP_FIELDS.intersection(update_data.keys())) or (
        "metric_type" in update_data and target_metric_type != metric.metric_type
    )
    dependency_specs: list[dict[str, Any]] = []
    dependencies: list[BiMetricDefinition] = []
    binding_source: dict[str, Any] = {}
    if relationship_update:
        relationship_data = _relationship_data_for_update(db, metric, data, target_metric_type)
        dependency_specs, dependencies, binding_source = _prepare_relationships(
            db,
            relationship_data,  # type: ignore[arg-type]
            tenant_id,
            target_metric_type,
        )

    metric_update_data = {
        key: value
        for key, value in update_data.items()
        if key not in _RELATIONSHIP_FIELDS
    }

    # 记录哪些字段实际发生了变化
    changes = {}
    formula_changed = False

    for field, new_val in metric_update_data.items():
        old_val = getattr(metric, field, None)
        # 处理 Enum 值
        new_val = _enum_value(new_val)
        if old_val != new_val:
            changes[field] = {"from": old_val, "to": new_val}
            setattr(metric, field, new_val)
            if field in ("formula", "formula_template"):
                formula_changed = True

    if relationship_update:
        changes["relationships"] = {"updated": True}

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
        if relationship_update:
            db.flush()
            if dependency_specs and _would_create_cycle(
                db,
                metric_id=metric.id,
                tenant_id=tenant_id,
                depends_on_ids=[spec["depends_on_metric_id"] for spec in dependency_specs],
            ):
                raise MulanError("MC_DEPENDENCY_INVALID", "指标依赖存在环路", 400)
            _replace_dependencies(db, metric, dependency_specs)
            _replace_primary_tableau_binding(db, metric, relationship_data, dependencies, binding_source)
        db.flush()
    except IntegrityError:
        db.rollback()
        raise MulanError("MC_001", f"指标技术别名已存在：{data.name}", 409)
    except MulanError:
        db.rollback()
        raise
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
        "low": 0,
        "internal": 1,
        "medium": 1,
        "confidential": 2,
        "high": 2,
        "restricted": 3,
    }
    return ranking.get(level.lower(), 0)


def _check_sensitivity_level_upgrade(db, metric: BiMetricDefinition) -> tuple[str, Optional[str]]:
    """
    MC_004：检查上游血缘字段的 sensitivity_level 是否高于指标当前标注值。

    流程：
    1. 从 bi_metric_lineage 查出该指标的所有上游字段（同一 datasource_id）
    2. 字段的 sensitivity_level 存储在语义层，通过血缘字段查找
    3. 取上游 max sensitivity_level 与指标的 sensitivity_level 比较
    4. 若指标级别 < 上游最高级别 → 自动升级到上游最高级别，返回警告信息

    Returns:
        (actual_sensitivity_level, warning_message or None)
    """
    lineage_records = (
        db.query(BiMetricLineage)
        .filter(BiMetricLineage.metric_id == metric.id)
        .all()
    )
    if not lineage_records:
        return metric.sensitivity_level, None

    from services.semantic_maintenance.models import TableauFieldSemantics

    # 收集上游字段 sensitivity_level
    upstream_levels: list[str] = []
    for rec in lineage_records:
        # 当前语义层使用 TableauFieldSemantics；历史血缘中的 datasource_id
        # 对应语义 connection_id，字段名可能是裸 column 或 table.column。
        field_ids = [rec.column_name, f"{rec.table_name}.{rec.column_name}"]
        field_sem = (
            db.query(TableauFieldSemantics)
            .filter(
                TableauFieldSemantics.connection_id == rec.datasource_id,
                TableauFieldSemantics.tableau_field_id.in_(field_ids),
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
    _ensure_metric_has_valid_tableau_binding(db, metric)
    _validate_existing_dependency_contract(db, metric)

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
            name=metric.name or metric.name_zh,
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
    tableau_connection_id: Optional[int] = None,
    tableau_datasource_luid: Optional[str] = None,
) -> dict:
    """
    批量按名称、中文名、别名查找已发布指标（Data Agent 内部调用）。

    Returns:
        {"metrics": [...], "not_found": [...], "binding_errors": [...]}
    """
    requested_names = _normalize_lookup_names(names)
    if not requested_names:
        return {"metrics": [], "not_found": [], "binding_errors": []}

    lookup_keys = [n.casefold() for n in requested_names]
    candidates_by_request: dict[str, list[BiMetricDefinition]] = {n: [] for n in requested_names}
    metric_by_id: dict[uuid.UUID, BiMetricDefinition] = {}
    binding_table_exists = _table_exists(db, _METRIC_BINDINGS_TABLE)
    legacy_datasource_filter = (
        datasource_id is not None
        and tableau_connection_id is None
        and tableau_datasource_luid is None
        and not binding_table_exists
    )

    base_query = db.query(BiMetricDefinition).filter(
        BiMetricDefinition.tenant_id == tenant_id,
        BiMetricDefinition.is_active == True,
        BiMetricDefinition.published_at.isnot(None),
        (
            func.lower(BiMetricDefinition.metric_code).in_(lookup_keys)
            | func.lower(BiMetricDefinition.name).in_(lookup_keys)
            | func.lower(BiMetricDefinition.name_zh).in_(lookup_keys)
        ),
    )
    if legacy_datasource_filter:
        base_query = base_query.filter(BiMetricDefinition.datasource_id == datasource_id)

    base_matches = base_query.all()
    for metric in base_matches:
        metric_by_id[metric.id] = metric
        for requested_name in requested_names:
            key = requested_name.casefold()
            if (
                metric.metric_code.casefold() == key
                or (metric.name and metric.name.casefold() == key)
                or (metric.name_zh and metric.name_zh.casefold() == key)
            ):
                candidates_by_request[requested_name].append(metric)

    alias_table_exists = _table_exists(db, _METRIC_ALIASES_TABLE)
    if alias_table_exists:
        alias_match_stmt = text(
            f"""
            SELECT metric_id, alias
            FROM {_METRIC_ALIASES_TABLE}
            WHERE tenant_id = :tenant_id
              AND is_active = true
              AND lower(alias) IN :lookup_keys
            ORDER BY priority DESC
            """
        ).bindparams(bindparam("lookup_keys", expanding=True))
        alias_rows = db.execute(
            alias_match_stmt,
            {"tenant_id": tenant_id, "lookup_keys": lookup_keys},
        ).mappings().all()
        alias_metric_ids = {row["metric_id"] for row in alias_rows}
        if alias_metric_ids:
            alias_metrics_query = db.query(BiMetricDefinition).filter(
                BiMetricDefinition.tenant_id == tenant_id,
                BiMetricDefinition.is_active == True,
                BiMetricDefinition.published_at.isnot(None),
                BiMetricDefinition.id.in_(alias_metric_ids),
            )
            if legacy_datasource_filter:
                alias_metrics_query = alias_metrics_query.filter(
                    BiMetricDefinition.datasource_id == datasource_id
                )
            alias_metrics = alias_metrics_query.all()
            metric_by_id.update({m.id: m for m in alias_metrics})
            for row in alias_rows:
                metric = metric_by_id.get(row["metric_id"])
                if metric is None:
                    continue
                for requested_name in requested_names:
                    if str(row["alias"]).casefold() == requested_name.casefold():
                        candidates_by_request[requested_name].append(metric)

    binding_required = not legacy_datasource_filter
    all_candidate_ids = list(
        {
            candidate.id
            for candidates in candidates_by_request.values()
            for candidate in candidates
        }
    )
    preferred_bindings_by_metric = _load_lookup_bindings(
        db,
        tenant_id=tenant_id,
        metric_ids=all_candidate_ids,
        datasource_id=datasource_id,
        tableau_connection_id=tableau_connection_id,
        tableau_datasource_luid=tableau_datasource_luid,
    ) if binding_required else {}

    selected_by_request: dict[str, BiMetricDefinition] = {}
    not_found: list[str] = []
    for requested_name, candidates in candidates_by_request.items():
        deduped = list({candidate.id: candidate for candidate in candidates}.values())
        if not deduped:
            not_found.append(requested_name)
            continue
        selected_by_request[requested_name] = sorted(
            deduped,
            key=lambda candidate: (
                candidate.id not in preferred_bindings_by_metric,
                candidate.name or candidate.metric_code,
            ),
        )[0]

    selected_metrics = list({metric.id: metric for metric in selected_by_request.values()}.values())
    selected_metric_ids = [metric.id for metric in selected_metrics]

    aliases_by_metric = _load_lookup_aliases(db, tenant_id, selected_metric_ids, alias_table_exists)
    bindings_by_metric = _load_lookup_bindings(
        db,
        tenant_id=tenant_id,
        metric_ids=selected_metric_ids,
        datasource_id=datasource_id,
        tableau_connection_id=tableau_connection_id,
        tableau_datasource_luid=tableau_datasource_luid,
    )
    dependencies_by_metric = _load_lookup_dependencies(db, tenant_id, selected_metric_ids)

    response_metrics_by_id: dict[uuid.UUID, dict[str, Any]] = {}
    binding_errors: list[dict[str, Any]] = []
    for requested_name, metric in selected_by_request.items():
        binding = bindings_by_metric.get(metric.id)
        metric_errors: list[dict[str, Any]] = []

        if binding_required and binding is None:
            if binding_table_exists:
                message = "指标口径未绑定当前执行数据源"
                code = "MC_BINDING_UNAVAILABLE"
            else:
                message = "指标绑定表不存在，无法校验当前执行数据源绑定"
                code = "MC_BINDING_TABLE_MISSING"
            error = _binding_error(requested_name, metric, code, message)
            metric_errors.append(error)
            binding_errors.append(error)
        elif binding is not None and not _is_valid_lookup_binding(metric, binding):
            error = _binding_error(
                requested_name,
                metric,
                "MC_BINDING_INVALID",
                "指标缺少有效 Tableau field_mappings 或 formula_expression",
            )
            metric_errors.append(error)
            binding_errors.append(error)

        if metric.metric_type in ("derived", "ratio"):
            required_base_metrics = (
                _json_or_default(binding.get("required_base_metrics"), [])
                if binding is not None
                else []
            )
            formula_expression = (
                _json_or_default(binding.get("formula_expression"), None)
                if binding is not None
                else None
            )
            if (not required_base_metrics or formula_expression is None) and not metric_errors:
                error = _binding_error(
                    requested_name,
                    metric,
                    "MC_FORMULA_EXPRESSION_MISSING",
                    "派生或比率指标缺少 required_base_metrics 或 formula_expression",
                )
                metric_errors.append(error)
                binding_errors.append(error)

        existing = response_metrics_by_id.get(metric.id)
        if existing is None:
            response_metrics_by_id[metric.id] = _serialize_lookup_metric(
                metric,
                aliases=aliases_by_metric.get(metric.id, []),
                binding=binding,
                dependencies=dependencies_by_metric.get(metric.id, []),
                binding_errors=metric_errors,
            )
        elif metric_errors:
            existing["binding_errors"].extend(metric_errors)

    return {
        "metrics": list(response_metrics_by_id.values()),
        "not_found": not_found,
        "binding_errors": binding_errors,
    }


def _load_lookup_aliases(
    db,
    tenant_id: uuid.UUID,
    metric_ids: list[uuid.UUID],
    alias_table_exists: bool,
) -> dict[uuid.UUID, list[str]]:
    if not metric_ids or not alias_table_exists:
        return {}

    stmt = text(
        f"""
        SELECT metric_id, alias
        FROM {_METRIC_ALIASES_TABLE}
        WHERE tenant_id = :tenant_id
          AND metric_id IN :metric_ids
          AND is_active = true
        ORDER BY priority DESC, alias ASC
        """
    ).bindparams(bindparam("metric_ids", expanding=True))
    rows = db.execute(stmt, {"tenant_id": tenant_id, "metric_ids": metric_ids}).mappings().all()

    aliases_by_metric: dict[uuid.UUID, list[str]] = {}
    seen_by_metric: dict[uuid.UUID, set[str]] = {}
    for row in rows:
        metric_id = row["metric_id"]
        alias = row["alias"]
        seen = seen_by_metric.setdefault(metric_id, set())
        if alias.casefold() in seen:
            continue
        seen.add(alias.casefold())
        aliases_by_metric.setdefault(metric_id, []).append(alias)
    return aliases_by_metric


def _load_lookup_bindings(
    db,
    tenant_id: uuid.UUID,
    metric_ids: list[uuid.UUID],
    datasource_id: Optional[int],
    tableau_connection_id: Optional[int],
    tableau_datasource_luid: Optional[str],
) -> dict[uuid.UUID, dict[str, Any]]:
    if not metric_ids or not _table_exists(db, _METRIC_BINDINGS_TABLE):
        return {}

    clauses = [
        "tenant_id = :tenant_id",
        "metric_id IN :metric_ids",
        "is_active = true",
    ]
    params: dict[str, Any] = {"tenant_id": tenant_id, "metric_ids": metric_ids}

    if tableau_connection_id is not None or tableau_datasource_luid is not None:
        clauses.append("source_type = 'tableau_published_datasource'")
        if tableau_connection_id is not None:
            clauses.append("tableau_connection_id = :tableau_connection_id")
            params["tableau_connection_id"] = tableau_connection_id
        if tableau_datasource_luid is not None:
            clauses.append("tableau_datasource_luid = :tableau_datasource_luid")
            params["tableau_datasource_luid"] = tableau_datasource_luid
    elif datasource_id is not None:
        clauses.append("source_type = 'database_table'")
        clauses.append("datasource_id = :datasource_id")
        params["datasource_id"] = datasource_id
    else:
        clauses.append("source_type = 'tableau_published_datasource'")

    stmt = text(
        f"""
        SELECT
            metric_id,
            source_type,
            datasource_id,
            tableau_connection_id,
            tableau_datasource_luid,
            field_mappings,
            required_base_metrics,
            formula_expression,
            is_primary
        FROM {_METRIC_BINDINGS_TABLE}
        WHERE {" AND ".join(clauses)}
        ORDER BY is_primary DESC
        """
    ).bindparams(bindparam("metric_ids", expanding=True))
    rows = db.execute(stmt, params).mappings().all()

    bindings_by_metric: dict[uuid.UUID, dict[str, Any]] = {}
    for row in rows:
        metric_id = row["metric_id"]
        if metric_id not in bindings_by_metric:
            bindings_by_metric[metric_id] = dict(row)
    return bindings_by_metric


def _is_valid_lookup_binding(metric: BiMetricDefinition, binding: dict[str, Any]) -> bool:
    if binding.get("source_type") != _TABLEAU_SOURCE_TYPE:
        return False
    if metric.metric_type == "atomic":
        return _has_nonempty_mapping(binding.get("field_mappings"))
    if metric.metric_type in ("derived", "ratio"):
        return binding.get("formula_expression") is not None
    return False


def _load_lookup_dependencies(
    db,
    tenant_id: uuid.UUID,
    metric_ids: list[uuid.UUID],
) -> dict[uuid.UUID, list[dict[str, Any]]]:
    if not metric_ids or not _table_exists(db, _METRIC_DEPENDENCIES_TABLE):
        return {}

    stmt = text(
        f"""
        SELECT
            d.metric_id,
            d.depends_on_metric_id,
            d.dependency_role,
            d.expression_order,
            d.weight,
            m.metric_code,
            m.name,
            m.name_zh,
            m.metric_type
        FROM {_METRIC_DEPENDENCIES_TABLE} d
        JOIN bi_metric_definitions m
          ON m.id = d.depends_on_metric_id
        WHERE d.tenant_id = :tenant_id
          AND d.metric_id IN :metric_ids
        ORDER BY d.metric_id, d.expression_order ASC
        """
    ).bindparams(bindparam("metric_ids", expanding=True))
    rows = db.execute(stmt, {"tenant_id": tenant_id, "metric_ids": metric_ids}).mappings().all()

    dependencies_by_metric: dict[uuid.UUID, list[dict[str, Any]]] = {}
    for row in rows:
        dependencies_by_metric.setdefault(row["metric_id"], []).append(
            {
                "metric_id": str(row["depends_on_metric_id"]),
                "metric_code": row["metric_code"],
                "name": row["name"],
                "name_zh": row["name_zh"],
                "metric_type": row["metric_type"],
                "dependency_role": row["dependency_role"],
                "expression_order": row["expression_order"],
                "weight": row["weight"],
            }
        )
    return dependencies_by_metric


def _serialize_lookup_metric(
    metric: BiMetricDefinition,
    aliases: list[str],
    binding: Optional[dict[str, Any]],
    dependencies: list[dict[str, Any]],
    binding_errors: list[dict[str, Any]],
) -> dict[str, Any]:
    field_mappings: Any = {}
    required_base_metrics: list[str] = []
    formula_expression: Any = None
    tableau_connection_id: Optional[int] = None
    tableau_datasource_luid: Optional[str] = None
    datasource_id: Optional[int] = metric.datasource_id
    table_name: Optional[str] = metric.table_name
    column_name: Optional[str] = metric.column_name

    if binding is not None:
        source_type = binding.get("source_type")
        field_mappings = _json_or_default(binding.get("field_mappings"), {})
        required_base_metrics = _json_or_default(binding.get("required_base_metrics"), [])
        formula_expression = _json_or_default(binding.get("formula_expression"), None)
        tableau_connection_id = binding.get("tableau_connection_id")
        tableau_datasource_luid = binding.get("tableau_datasource_luid")
        datasource_id = binding.get("datasource_id")
        if source_type == "tableau_published_datasource":
            table_name = None
            column_name = None
        elif datasource_id is None:
            datasource_id = metric.datasource_id

    return {
        "metric_code": metric.metric_code,
        "name": metric.name,
        "name_zh": metric.name_zh,
        "aliases": aliases,
        "metric_type": metric.metric_type,
        "formula": metric.formula,
        "formula_template": metric.formula_template,
        "aggregation_type": metric.aggregation_type,
        "result_type": metric.result_type,
        "unit": metric.unit,
        "precision": metric.precision,
        "datasource_id": datasource_id,
        "tableau_connection_id": tableau_connection_id,
        "tableau_datasource_luid": tableau_datasource_luid,
        "table_name": table_name,
        "column_name": column_name,
        "field_mappings": field_mappings,
        "required_base_metrics": required_base_metrics,
        "formula_expression": formula_expression,
        "filters": metric.filters,
        "sensitivity_level": metric.sensitivity_level,
        "lineage_status": metric.lineage_status,
        "description": metric.description,
        "dependencies": dependencies,
        "queryable": not binding_errors and binding is not None and _is_valid_lookup_binding(metric, binding),
        "binding_errors": binding_errors,
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

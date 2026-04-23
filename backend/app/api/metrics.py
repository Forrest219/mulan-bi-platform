"""Metrics Agent — FastAPI 路由层"""

import math
import os
import uuid
from typing import Any, Optional

import jwt as pyjwt
from fastapi import APIRouter, Body, Depends, Header, HTTPException, Query, status

from app.core.database import get_db
from app.core.dependencies import require_roles
from models.metrics import BiMetricLineage
from services.metrics_agent.schemas import (
    MetricCreate,
    MetricCreatedResponse,
    MetricDetail,
    MetricLookupResponse,
    MetricUpdate,
    PaginatedMetrics,
    PublishResponse,
    RejectRequest,
)
from services.metrics_agent import registry
from services.metrics_agent.lineage import resolve_lineage as _resolve_lineage_service

router = APIRouter()

# ---------------------------------------------------------------------------
# Service JWT 验证（供 /lookup 接口使用）
# ---------------------------------------------------------------------------

# P0-2：fail-fast — 启动时若环境变量未设置或长度不足则拒绝启动
_SERVICE_JWT_SECRET = os.getenv("SERVICE_JWT_SECRET")
if not _SERVICE_JWT_SECRET or len(_SERVICE_JWT_SECRET) < 32:
    raise RuntimeError(
        "SERVICE_JWT_SECRET 环境变量未设置或长度不足 32 字符，服务拒绝启动。"
        "开发环境请在 .env 中设置，生产环境通过 Vault/K8s Secret 注入。"
    )


def verify_service_jwt(
    x_scan_service_jwt: str = Header(..., alias="X-Scan-Service-JWT"),
    tenant_id: uuid.UUID = Query(...),
) -> dict:
    # P0-2：JWT payload 中的 tenant_id 必须与请求参数一致
    try:
        payload = pyjwt.decode(x_scan_service_jwt, _SERVICE_JWT_SECRET, algorithms=["HS256"])
        if str(payload.get("tenant_id", "")) != str(tenant_id):
            raise HTTPException(
                status_code=403,
                detail={"error_code": "MC_403", "message": "JWT tenant_id 与请求参数不匹配"},
            )
        return payload
    except HTTPException:
        raise
    except pyjwt.InvalidTokenError:
        raise HTTPException(
            status_code=403,
            detail={"error_code": "MC_403", "message": "Invalid service JWT"},
        )


# =============================================================================
# 指标 CRUD
# =============================================================================

@router.post(
    "/",
    response_model=MetricCreatedResponse,
    status_code=status.HTTP_201_CREATED,
    summary="创建指标",
)
def create_metric(
    data: MetricCreate,
    current_user: dict = Depends(require_roles(["data_admin", "admin"])),
    db=Depends(get_db),
):
    """创建新指标定义（data_admin+）"""
    tenant_id = uuid.UUID(str(current_user.get("tenant_id", uuid.uuid4())))
    metric = registry.create_metric(db, data, user_id=current_user["id"], tenant_id=tenant_id)
    return metric


@router.get(
    "/",
    response_model=PaginatedMetrics,
    summary="指标列表",
)
def list_metrics(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=200),
    business_domain: Optional[str] = Query(default=None),
    metric_type: Optional[str] = Query(default=None),
    datasource_id: Optional[int] = Query(default=None),
    is_active: Optional[bool] = Query(default=None),
    sensitivity_level: Optional[str] = Query(default=None),
    search: Optional[str] = Query(default=None, description="按 name / name_zh 模糊搜索"),
    current_user: dict = Depends(require_roles(["analyst", "data_admin", "admin"])),
    db=Depends(get_db),
):
    """查询指标列表，支持多维过滤与分页（analyst+）"""
    tenant_id = uuid.UUID(str(current_user.get("tenant_id", uuid.uuid4())))
    items, total = registry.list_metrics(
        db,
        tenant_id=tenant_id,
        page=page,
        page_size=page_size,
        business_domain=business_domain,
        metric_type=metric_type,
        datasource_id=datasource_id,
        is_active=is_active,
        sensitivity_level=sensitivity_level,
        search=search,
    )
    pages = math.ceil(total / page_size) if page_size else 0
    return PaginatedMetrics(items=items, total=total, page=page, page_size=page_size, pages=pages)


@router.get(
    "/lookup",
    response_model=MetricLookupResponse,
    summary="批量指标查询（Service JWT）",
)
def lookup_metrics(
    names: list[str] = Query(..., description="指标英文名列表"),
    tenant_id: uuid.UUID = Query(...),
    datasource_id: Optional[int] = Query(default=None),
    _jwt_payload: dict = Depends(verify_service_jwt),
    db=Depends(get_db),
):
    """
    内部 Service 调用接口，使用 X-Scan-Service-JWT Header 鉴权（非用户 Session）。
    Data Agent 通过此接口批量获取指标元数据。
    """
    result = registry.lookup_metrics(db, names=names, tenant_id=tenant_id, datasource_id=datasource_id)
    return MetricLookupResponse(
        metrics=result["metrics"],
        not_found=result["not_found"],
    )


@router.get(
    "/{metric_id}",
    response_model=MetricDetail,
    summary="指标详情",
)
def get_metric(
    metric_id: uuid.UUID,
    current_user: dict = Depends(require_roles(["analyst", "data_admin", "admin"])),
    db=Depends(get_db),
):
    """获取指标完整详情（analyst+）"""
    tenant_id = uuid.UUID(str(current_user.get("tenant_id", uuid.uuid4())))
    return registry.get_metric(db, metric_id=metric_id, tenant_id=tenant_id)


@router.put(
    "/{metric_id}",
    response_model=MetricDetail,
    summary="更新指标",
)
def update_metric(
    metric_id: uuid.UUID,
    data: MetricUpdate,
    current_user: dict = Depends(require_roles(["data_admin", "admin"])),
    db=Depends(get_db),
):
    """更新指标字段（data_admin+）"""
    tenant_id = uuid.UUID(str(current_user.get("tenant_id", uuid.uuid4())))
    return registry.update_metric(db, metric_id=metric_id, data=data, user_id=current_user["id"], tenant_id=tenant_id)


@router.delete(
    "/{metric_id}",
    status_code=status.HTTP_200_OK,
    summary="软删除/下线指标",
)
def archive_metric(
    metric_id: uuid.UUID,
    current_user: dict = Depends(require_roles(["admin"])),
    db=Depends(get_db),
):
    """软删除（下线）指标，设置 is_active=False（admin）"""
    tenant_id = uuid.UUID(str(current_user.get("tenant_id", uuid.uuid4())))
    return registry.archive_metric(db, metric_id=metric_id, user_id=current_user["id"], tenant_id=tenant_id)


# =============================================================================
# 审核流
# =============================================================================

@router.post(
    "/{metric_id}/submit-review",
    response_model=MetricDetail,
    summary="提交审核",
)
def submit_review(
    metric_id: uuid.UUID,
    current_user: dict = Depends(require_roles(["data_admin", "admin"])),
    db=Depends(get_db),
):
    """将指标提交至审核队列（data_admin+）"""
    tenant_id = uuid.UUID(str(current_user.get("tenant_id", uuid.uuid4())))
    return registry.submit_review(db, metric_id=metric_id, user_id=current_user["id"], tenant_id=tenant_id)


@router.post(
    "/{metric_id}/approve",
    response_model=MetricDetail,
    summary="批准指标",
)
def approve_metric(
    metric_id: uuid.UUID,
    current_user: dict = Depends(require_roles(["data_admin", "admin"])),
    db=Depends(get_db),
):
    """批准审核中的指标（data_admin+）"""
    tenant_id = uuid.UUID(str(current_user.get("tenant_id", uuid.uuid4())))
    return registry.approve_metric(db, metric_id=metric_id, reviewer_id=current_user["id"], tenant_id=tenant_id)


@router.post(
    "/{metric_id}/reject",
    response_model=MetricDetail,
    summary="拒绝指标",
)
def reject_metric(
    metric_id: uuid.UUID,
    body: RejectRequest,
    current_user: dict = Depends(require_roles(["data_admin", "admin"])),
    db=Depends(get_db),
):
    """拒绝审核中的指标，附带原因（data_admin+）"""
    tenant_id = uuid.UUID(str(current_user.get("tenant_id", uuid.uuid4())))
    return registry.reject_metric(
        db,
        metric_id=metric_id,
        reason=body.reason,
        reviewer_id=current_user["id"],
        tenant_id=tenant_id,
    )


@router.post(
    "/{metric_id}/publish",
    response_model=PublishResponse,
    summary="发布指标",
)
def publish_metric(
    metric_id: uuid.UUID,
    current_user: dict = Depends(require_roles(["data_admin", "admin"])),
    db=Depends(get_db),
):
    """发布已批准的指标，激活生效（data_admin+）"""
    tenant_id = uuid.UUID(str(current_user.get("tenant_id", uuid.uuid4())))
    return registry.publish_metric(db, metric_id=metric_id, user_id=current_user["id"], tenant_id=tenant_id)


# =============================================================================
# 版本历史
# =============================================================================

@router.get(
    "/{metric_id}/versions",
    summary="版本历史列表",
)
def list_versions(
    metric_id: uuid.UUID,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    current_user: dict = Depends(require_roles(["analyst", "data_admin", "admin"])),
    db=Depends(get_db),
):
    """查询指标变更版本列表，分页（analyst+）"""
    # P2-2：改为标准 501 HTTP 响应，而非触发 500 的 NotImplementedError
    raise HTTPException(
        status_code=501,
        detail={"error_code": "NOT_IMPLEMENTED", "message": "版本历史接口待实现"},
    )


# =============================================================================
# 血缘（T3 实现，骨架占位）
# =============================================================================

@router.get(
    "/{metric_id}/lineage",
    summary="血缘查询",
)
def get_lineage(
    metric_id: uuid.UUID,
    current_user: dict = Depends(require_roles(["analyst", "data_admin", "admin"])),
    db=Depends(get_db),
):
    """查询指标血缘关系（analyst+）"""
    tenant_id = uuid.UUID(str(current_user.get("tenant_id", uuid.uuid4())))
    metric = registry.get_metric(db, metric_id=metric_id, tenant_id=tenant_id)
    records = db.query(BiMetricLineage).filter(
        BiMetricLineage.metric_id == metric_id
    ).all()
    return {
        "metric_id": str(metric_id),
        "lineage_status": metric.lineage_status,
        "records": [
            {
                "id": str(r.id),
                "datasource_id": r.datasource_id,
                "table_name": r.table_name,
                "column_name": r.column_name,
                "column_type": r.column_type,
                "relationship_type": r.relationship_type,
                "hop_number": r.hop_number,
                "transformation_logic": r.transformation_logic,
                "created_at": r.created_at.isoformat() if r.created_at else None,
            }
            for r in records
        ],
    }


@router.post(
    "/{metric_id}/lineage/resolve",
    summary="触发血缘解析",
    status_code=status.HTTP_202_ACCEPTED,
)
async def resolve_lineage(
    metric_id: uuid.UUID,
    manual_override: bool = Query(default=False, description="是否跳过 LLM，直接写入手动血缘"),
    manual_records: Optional[list[dict[str, Any]]] = Body(default=None, description="手动血缘记录列表（manual_override=True 时必填）"),
    current_user: dict = Depends(require_roles(["data_admin", "admin"])),
    db=Depends(get_db),
):
    """触发血缘解析（data_admin+）。

    - manual_override=False（默认）：调用 LLM 自动解析公式血缘
    - manual_override=True：跳过 LLM，直接写入 manual_records 手动血缘
    """
    tenant_id = uuid.UUID(str(current_user.get("tenant_id", uuid.uuid4())))
    result = await _resolve_lineage_service(
        db=db,
        metric_id=metric_id,
        tenant_id=tenant_id,
        manual_override=manual_override,
        manual_records=manual_records,
    )
    return result


# =============================================================================
# 异常检测（T4）
# =============================================================================

@router.post(
    "/detect-anomalies",
    summary="批量触发异常检测",
    status_code=status.HTTP_202_ACCEPTED,
)
async def detect_anomalies(
    body: dict = Body(
        ...,
        example={
            "metric_ids": None,
            "detection_method": "zscore",
            "window_days": 30,
            "threshold": 3.0,
        },
    ),
    current_user: dict = Depends(require_roles(["data_admin", "admin"])),
    db=Depends(get_db),
):
    """
    批量对指标执行异常检测（data_admin+）。

    请求体字段：
    - metric_ids: list[UUID] | null — 指定指标 ID 列表，null 表示全 tenant
    - detection_method: str — zscore / quantile / trend_deviation / threshold_breach
    - window_days: int — 历史窗口天数，默认 30
    - threshold: float — 算法阈值，默认 3.0
    """
    from services.metrics_agent.anomaly_service import run_anomaly_detection

    tenant_id = uuid.UUID(str(current_user.get("tenant_id", uuid.uuid4())))

    raw_metric_ids = body.get("metric_ids")
    metric_ids: Optional[list[uuid.UUID]] = None
    if raw_metric_ids is not None:
        try:
            metric_ids = [uuid.UUID(str(mid)) for mid in raw_metric_ids]
        except (ValueError, TypeError):
            raise HTTPException(status_code=400, detail={"error_code": "MC_400", "message": "metric_ids 格式非法，需为 UUID 列表"})

    detection_method = body.get("detection_method", "zscore")
    window_days = int(body.get("window_days", 30))
    threshold = float(body.get("threshold", 3.0))

    result = await run_anomaly_detection(
        db=db,
        tenant_id=tenant_id,
        metric_ids=metric_ids,
        detection_method=detection_method,
        window_days=window_days,
        threshold=threshold,
    )
    return result


@router.get(
    "/{metric_id}/anomalies",
    summary="查询指标异常记录列表",
)
def list_metric_anomalies(
    metric_id: uuid.UUID,
    status_filter: Optional[str] = Query(default=None, alias="status", description="按状态过滤：detected / investigating / resolved / false_positive"),
    detection_method: Optional[str] = Query(default=None, description="按检测方法过滤"),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=200),
    current_user: dict = Depends(require_roles(["analyst", "data_admin", "admin"])),
    db=Depends(get_db),
):
    """查询指定指标的异常记录，支持状态/方法过滤，分页（analyst+）。"""
    from models.metrics import BiMetricAnomaly

    tenant_id = uuid.UUID(str(current_user.get("tenant_id", uuid.uuid4())))

    q = db.query(BiMetricAnomaly).filter(
        BiMetricAnomaly.metric_id == metric_id,
        BiMetricAnomaly.tenant_id == tenant_id,
    )

    if status_filter is not None:
        q = q.filter(BiMetricAnomaly.status == status_filter)
    if detection_method is not None:
        q = q.filter(BiMetricAnomaly.detection_method == detection_method)

    total = q.count()
    offset = (page - 1) * page_size
    items = q.order_by(BiMetricAnomaly.detected_at.desc()).offset(offset).limit(page_size).all()

    return {
        "metric_id": str(metric_id),
        "total": total,
        "page": page,
        "page_size": page_size,
        "pages": math.ceil(total / page_size) if page_size else 0,
        "items": [
            {
                "id": str(a.id),
                "metric_id": str(a.metric_id),
                "datasource_id": a.datasource_id,
                "detection_method": a.detection_method,
                "metric_value": a.metric_value,
                "expected_value": a.expected_value,
                "deviation_score": a.deviation_score,
                "deviation_threshold": a.deviation_threshold,
                "detected_at": a.detected_at.isoformat() if a.detected_at else None,
                "status": a.status,
                "resolved_by": a.resolved_by,
                "resolved_at": a.resolved_at.isoformat() if a.resolved_at else None,
                "resolution_note": a.resolution_note,
                "created_at": a.created_at.isoformat() if a.created_at else None,
            }
            for a in items
        ],
    }


# =============================================================================
# 一致性校验（T5）
# =============================================================================

@router.post(
    "/consistency-check",
    summary="触发指标一致性校验",
    status_code=status.HTTP_202_ACCEPTED,
)
async def run_consistency_check(
    body: dict = Body(
        ...,
        example={
            "metric_id": "00000000-0000-0000-0000-000000000001",
            "datasource_id_a": 1,
            "datasource_id_b": 2,
            "tolerance_pct": 5.0,
        },
    ),
    current_user: dict = Depends(require_roles(["data_admin", "admin"])),
    db=Depends(get_db),
):
    """
    对同一指标在两个数据源上执行聚合查询，比对结果（data_admin+）。

    请求体字段：
    - metric_id: UUID（必填）
    - datasource_id_a: int（必填）
    - datasource_id_b: int（必填）
    - tolerance_pct: float — 容差百分比，默认 5.0
    """
    from services.metrics_agent.consistency import run_consistency_check as _run_check

    tenant_id = uuid.UUID(str(current_user.get("tenant_id", uuid.uuid4())))

    raw_metric_id = body.get("metric_id")
    if not raw_metric_id:
        raise HTTPException(status_code=400, detail={"error_code": "MC_400", "message": "metric_id 字段必填"})
    try:
        metric_id = uuid.UUID(str(raw_metric_id))
    except (ValueError, TypeError):
        raise HTTPException(status_code=400, detail={"error_code": "MC_400", "message": "metric_id 格式非法，需为 UUID"})

    datasource_id_a = body.get("datasource_id_a")
    datasource_id_b = body.get("datasource_id_b")
    if datasource_id_a is None or datasource_id_b is None:
        raise HTTPException(status_code=400, detail={"error_code": "MC_400", "message": "datasource_id_a 和 datasource_id_b 字段必填"})

    try:
        datasource_id_a = int(datasource_id_a)
        datasource_id_b = int(datasource_id_b)
    except (ValueError, TypeError):
        raise HTTPException(status_code=400, detail={"error_code": "MC_400", "message": "datasource_id_a / datasource_id_b 需为整数"})

    tolerance_pct = float(body.get("tolerance_pct", 5.0))

    result = await _run_check(
        db=db,
        metric_id=metric_id,
        tenant_id=tenant_id,
        datasource_id_a=datasource_id_a,
        datasource_id_b=datasource_id_b,
        tolerance_pct=tolerance_pct,
    )
    return result


@router.get(
    "/consistency-checks",
    summary="查询一致性校验记录列表",
)
def list_consistency_checks(
    metric_id: Optional[uuid.UUID] = Query(default=None, description="按指标 ID 过滤"),
    check_status: Optional[str] = Query(default=None, description="按校验状态过滤：pass / warning / fail"),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=200),
    current_user: dict = Depends(require_roles(["analyst", "data_admin", "admin"])),
    db=Depends(get_db),
):
    """
    查询一致性校验记录，支持 metric_id、check_status 过滤，分页（analyst+）。
    """
    from models.metrics import BiMetricConsistencyCheck

    tenant_id = uuid.UUID(str(current_user.get("tenant_id", uuid.uuid4())))

    q = db.query(BiMetricConsistencyCheck).filter(
        BiMetricConsistencyCheck.tenant_id == tenant_id,
    )

    if metric_id is not None:
        q = q.filter(BiMetricConsistencyCheck.metric_id == metric_id)
    if check_status is not None:
        q = q.filter(BiMetricConsistencyCheck.check_status == check_status)

    total = q.count()
    offset = (page - 1) * page_size
    items = q.order_by(BiMetricConsistencyCheck.checked_at.desc()).offset(offset).limit(page_size).all()

    return {
        "total": total,
        "page": page,
        "page_size": page_size,
        "pages": math.ceil(total / page_size) if page_size else 0,
        "items": [
            {
                "id": str(c.id),
                "tenant_id": str(c.tenant_id),
                "metric_id": str(c.metric_id),
                "metric_name": c.metric_name,
                "datasource_id_a": c.datasource_id_a,
                "datasource_id_b": c.datasource_id_b,
                "value_a": c.value_a,
                "value_b": c.value_b,
                "difference": c.difference,
                "difference_pct": c.difference_pct,
                "tolerance_pct": c.tolerance_pct,
                "check_status": c.check_status,
                "checked_at": c.checked_at.isoformat() if c.checked_at else None,
                "created_at": c.created_at.isoformat() if c.created_at else None,
            }
            for c in items
        ],
    }


@router.patch(
    "/anomalies/{anomaly_id}",
    summary="更新异常记录状态",
)
def update_anomaly_status(
    anomaly_id: uuid.UUID,
    body: dict = Body(
        ...,
        example={
            "status": "investigating",
            "resolved_by": None,
            "resolution_note": "正在排查原因",
        },
    ),
    current_user: dict = Depends(require_roles(["analyst", "data_admin", "admin"])),
    db=Depends(get_db),
):
    """
    更新异常记录状态（analyst+）。

    合法流转：
    - detected → investigating
    - detected → false_positive
    - investigating → resolved
    - investigating → false_positive

    请求体字段：
    - status: str（必填）— 目标状态
    - resolved_by: int | null — 处理人 user_id
    - resolution_note: str | null — 处理备注
    """
    from services.metrics_agent.anomaly_service import update_anomaly_status as _update_status

    tenant_id = uuid.UUID(str(current_user.get("tenant_id", uuid.uuid4())))

    new_status = body.get("status")
    if not new_status:
        raise HTTPException(status_code=400, detail={"error_code": "MC_400", "message": "status 字段必填"})

    resolved_by = body.get("resolved_by")
    resolution_note = body.get("resolution_note")

    anomaly = _update_status(
        db=db,
        anomaly_id=anomaly_id,
        tenant_id=tenant_id,
        new_status=new_status,
        resolved_by=resolved_by,
        resolution_note=resolution_note,
    )

    return {
        "id": str(anomaly.id),
        "metric_id": str(anomaly.metric_id),
        "status": anomaly.status,
        "resolved_by": anomaly.resolved_by,
        "resolved_at": anomaly.resolved_at.isoformat() if anomaly.resolved_at else None,
        "resolution_note": anomaly.resolution_note,
    }

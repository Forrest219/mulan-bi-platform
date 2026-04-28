"""
Spec 28 UC-2 API Routes — §1.1.1 DAU/WAU 流失归因分析端到端接口

POST /api/data-agent/dau-churn — 发起 DAU 流失归因分析
GET  /api/data-agent/dau-churn/{session_id}  — 查询会话状态+结果

输入（UC-2）：
  {
    "metric": "dau",
    "dimensions": ["user_segment", "channel", "app_version"],
    "time_range": {"start": "2026-04-08", "end": "2026-04-14"},
    "compare_mode": "wow",
    "threshold_pct": -0.03,
    "context": {"tenant_id": "xxx", "scenario": "causation", "cross_table": true}
  }

输出（UC-2）：
  {
    "delta_abs": float,
    "delta_pct": float,
    "segment_breakdown": {"new_users": {...}, "churned_users": {...}, "returned_users": {...}},
    "correlated_metric": {"metric": str, "coefficient": float, "p_value": float, ...},
    "confidence": float,
    "narrative_summary": str,
    "h1_status": str,
    "h2_status": str,
    "insight_report": dict,
    "session_id": str,
    "session_status": str,
    "steps_count": int,
    "total_time_ms": int
  }
"""

import logging
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, Header, HTTPException, status
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/data-agent/dau-churn", tags=["UC-2 dau-churn"])


# -----------------------------------------------------------------------------
# 请求/响应模型
# -----------------------------------------------------------------------------


class TimeRange(BaseModel):
    start: str = Field(..., description="开始日期 YYYY-MM-DD")
    end: str = Field(..., description="结束日期 YYYY-MM-DD")


class DauChurnRequest(BaseModel):
    metric: str = Field("dau", description="指标名（默认 dau）")
    dimensions: List[str] = Field(
        default_factory=lambda: ["user_segment", "channel", "app_version"],
        description="分解维度列表"
    )
    time_range: TimeRange = Field(..., description="分析时间范围")
    compare_mode: str = Field("wow", description="对比模式: mom/yoy/wow/custom")
    threshold_pct: float = Field(-0.03, description="异动阈值百分比")
    context: Dict[str, Any] = Field(default_factory=dict, description="扩展上下文")

    class Config:
        json_schema_extra = {
            "example": {
                "metric": "dau",
                "dimensions": ["user_segment", "channel", "app_version"],
                "time_range": {"start": "2026-04-08", "end": "2026-04-14"},
                "compare_mode": "wow",
                "threshold_pct": -0.03,
                "context": {
                    "tenant_id": "550e8400-e29b-41d4-a716-446655440000",
                    "scenario": "causation",
                    "cross_table": True,
                },
            }
        }


class SegmentData(BaseModel):
    current: float
    baseline: float
    delta: float
    delta_pct: float


class DauChurnResponse(BaseModel):
    session_id: str
    session_status: str
    delta_abs: float
    delta_pct: float
    segment_breakdown: Dict[str, Dict[str, Any]]
    correlated_metric: Optional[Dict[str, Any]]
    root_dimension: str
    root_value: str
    confidence: float
    narrative_summary: str
    anomaly_confirmed: bool
    magnitude: float
    confirmed_hypothesis_type: Optional[str]
    h1_status: str
    h2_status: str
    recommended_actions: List[Dict[str, Any]]
    hypothesis_trace: List[Dict[str, Any]]
    insight_report: Dict[str, Any]
    steps_count: int
    total_time_ms: int


class SessionStatusResponse(BaseModel):
    session_id: str
    status: str
    current_step: int
    hypothesis_tree: Optional[Dict[str, Any]]
    created_at: str
    completed_at: Optional[str]


# -----------------------------------------------------------------------------
# JWT 解析（与 causation.py 相同）
# -----------------------------------------------------------------------------


def extract_user_from_jwt(authorization: str = Header(...)) -> Dict[str, Any]:
    """
    从 Authorization: Bearer *** 解析用户信息。
    简化版：解析 JWT payload（不验签，生产需接入 Auth Service）。
    """
    import base64
    import json as _json

    if not authorization.startswith("Bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authorization header format",
        )

    token = authorization[7:]
    try:
        payload_b64 = token.split(".")[1]
        padding = 4 - len(payload_b64) % 4
        if padding != 4:
            payload_b64 += "=" * padding
        payload = base64.urlsafe_b64decode(payload_b64)
        claims = _json.loads(payload)
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid JWT token",
        )

    user_id = claims.get("user_id") or claims.get("sub")
    if not user_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="JWT missing user_id/sub claim",
        )

    return {
        "user_id": int(user_id) if str(user_id).isdigit() else hash(user_id) % 1_000_000,
        "tenant_id": str(claims.get("tenant_id", claims.get("org_id", ""))),
        "roles": claims.get("roles", []),
    }


# -----------------------------------------------------------------------------
# 依赖：获取 DB Session
# -----------------------------------------------------------------------------


def get_db():
    """FastAPI 依赖：获取数据库会话"""
    from app.core.database import SessionLocal
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# -----------------------------------------------------------------------------
# POST /api/data-agent/dau-churn — 发起 DAU 流失归因分析
# -----------------------------------------------------------------------------


@router.post(
    "",
    response_model=DauChurnResponse,
    status_code=status.HTTP_201_CREATED,
    summary="UC-2 发起 DAU 流失归因分析",
    description="DAU/WAU 较基线显著下降，识别是新客获取下滑还是老客留存恶化。",
)
async def create_dau_churn(
    req: DauChurnRequest,
    user: Dict[str, Any] = Depends(extract_user_from_jwt),
    db=Depends(get_db),
):
    """
    UC-2 DAU 流失归因分析端到端接口。

    验收标准（§1.1.1 UC-2）：
    - 8 步内收敛
    - confidence ≥ 0.7
    - 跨表 join 行数 ≤ 50000
    - |coefficient| ≥ 0.5

    双假设链：
    - H1（新客获取下滑）：验证 new_users 下降与相关指标关系
    - H2（老客留存恶化）：验证 churned_users/returned_users 变化与相关指标关系
    """
    start_time = time.time()

    # 合并 context
    context = {
        "scenario": req.context.get("scenario", "causation"),
        "tenant_id": req.context.get("tenant_id") or user.get("tenant_id", ""),
        "cross_table": req.context.get("cross_table", True),
        **req.context,
    }

    # 创建 UC-2 会话管理器
    from services.data_agent.causation_session import DauChurnSessionManager, SessionStatus

    manager = DauChurnSessionManager(db)

    # 创建会话（created 状态）
    session = manager.create_session(
        tenant_id=context.get("tenant_id", uuid.uuid4().hex),
        user_id=user["user_id"],
        metric=req.metric,
        dimensions=req.dimensions,
        time_range=req.time_range.model_dump(),
        compare_mode=req.compare_mode,
        threshold_pct=req.threshold_pct,
        context=context,
    )

    # 执行八步归因流程
    try:
        result = await manager.run_causation(
            session_id=str(session.id),
            tenant_id=str(session.tenant_id),
        )
    except Exception as e:
        logger.exception("UC-2 DauChurn run failed for session %s", session.id)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"error_code": "DAT_999", "message": str(e)},
        )

    elapsed_ms = int((time.time() - start_time) * 1000)
    logger.info(
        "UC-2 dau_churn completed: session=%s elapsed=%dms confidence=%.2f steps=%d h1=%s h2=%s",
        session.id, elapsed_ms,
        result.get("confidence", 0),
        result.get("steps_count", 0),
        result.get("h1_status", "pending"),
        result.get("h2_status", "pending"),
    )

    return DauChurnResponse(**result)


# -----------------------------------------------------------------------------
# GET /api/data-agent/dau-churn/{session_id} — 查询会话状态
# -----------------------------------------------------------------------------


@router.get(
    "/{session_id}",
    response_model=SessionStatusResponse,
    summary="查询 DAU 流失归因分析会话状态",
)
async def get_dau_churn_session(
    session_id: str,
    user: Dict[str, Any] = Depends(extract_user_from_jwt),
    db=Depends(get_db),
):
    """查询已创建的 DAU 流失归因分析会话状态和结果"""
    from services.data_agent.causation_session import DauChurnSessionManager

    manager = DauChurnSessionManager(db)
    session = manager.get_session(session_id, user.get("tenant_id", ""))

    if not session:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error_code": "DAT_002", "message": "会话不存在"},
        )

    return SessionStatusResponse(
        session_id=str(session.id),
        status=session.status,
        current_step=session.current_step or 0,
        hypothesis_tree=session.hypothesis_tree,
        created_at=session.created_at.isoformat() if session.created_at else "",
        completed_at=session.completed_at.isoformat() if session.completed_at else None,
    )


# -----------------------------------------------------------------------------
# hypothesis_store 工具 API（供内部/外部调用 UC-2 双假设链）
# -----------------------------------------------------------------------------


class HypothesisStoreRequest(BaseModel):
    action: str = Field(..., description="add/update/reject/confirm")
    hypothesis: Dict[str, Any] = Field(default_factory=dict)


@router.post(
    "/{session_id}/hypothesis",
    summary="操作 DAU 流失归因假设树（hypothesis_store 工具接口）",
)
async def hypothesis_store(
    session_id: str,
    req: HypothesisStoreRequest,
    user: Dict[str, Any] = Depends(extract_user_from_jwt),
    db=Depends(get_db),
):
    """直接操作会话的假设树（add/update/reject/confirm）"""
    from services.data_agent.causation_session import DauChurnSessionManager

    manager = DauChurnSessionManager(db)
    session = manager.get_session(session_id, user.get("tenant_id", ""))

    if not session:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error_code": "DAT_002", "message": "会话不存在"},
        )

    result = manager.hypothesis_store(session, req.action, req.hypothesis)
    return result


# -----------------------------------------------------------------------------
# 便捷端点：获取 UC-2 特定结果（H1/H2 状态）
# -----------------------------------------------------------------------------


@router.get(
    "/{session_id}/hypothesis-status",
    summary="查询双假设链（H1/H2）状态",
)
async def get_hypothesis_status(
    session_id: str,
    user: Dict[str, Any] = Depends(extract_user_from_jwt),
    db=Depends(get_db),
):
    """查询 UC-2 双假设链的 H1/H2 状态"""
    from services.data_agent.causation_session import DauChurnSessionManager

    manager = DauChurnSessionManager(db)
    session = manager.get_session(session_id, user.get("tenant_id", ""))

    if not session:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error_code": "DAT_002", "message": "会话不存在"},
        )

    tree = session.hypothesis_tree or {}
    nodes = tree.get("nodes", [])

    h1_node = next((n for n in nodes if n.get("id") == "h1_acquisition"), None)
    h2_node = next((n for n in nodes if n.get("id") == "h2_retention"), None)

    return {
        "session_id": session_id,
        "h1": {
            "id": "h1_acquisition",
            "description": "新客获取下滑",
            "status": h1_node.get("status", "pending") if h1_node else "pending",
            "confidence": h1_node.get("confidence", 0.0) if h1_node else 0.0,
        },
        "h2": {
            "id": "h2_retention",
            "description": "老客留存恶化",
            "status": h2_node.get("status", "pending") if h2_node else "pending",
            "confidence": h2_node.get("confidence", 0.0) if h2_node else 0.0,
        },
        "confirmed_path": tree.get("confirmed_path", []),
        "all_nodes": nodes,
    }

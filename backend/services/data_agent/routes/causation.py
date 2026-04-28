"""
Spec 28 UC-1 API Routes — §1.1.1 归因分析端到端接口

POST /api/data-agent/causation  — 发起归因分析
GET  /api/data-agent/causation/{session_id}  — 查询会话状态+结果
POST /api/data-agent/causation/{session_id}/pause  — 暂停会话
POST /api/data-agent/causation/{session_id}/resume  — 恢复会话

输入（UC-1）：
  {
    "metric": "gmv",
    "dimensions": ["region", "product_category", "channel"],
    "time_range": {"start": "2026-04-01", "end": "2026-04-15"},
    "compare_mode": "mom",
    "threshold_pct": -0.05,
    "context": {"tenant_id": "xxx", "scenario": "causation"}
  }

输出（UC-1）：
  {
    "delta_abs": float,
    "delta_pct": float,
    "root_dimension": str,
    "root_value": str,
    "confidence": float,
    "narrative_summary": str,
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

router = APIRouter(prefix="/api/data-agent/causation", tags=["UC-1 causation"])


# ---------------------------------------------------------------------------
# 请求/响应模型
# ---------------------------------------------------------------------------


class TimeRange(BaseModel):
    start: str = Field(..., description="开始日期 YYYY-MM-DD")
    end: str = Field(..., description="结束日期 YYYY-MM-DD")


class CausationRequest(BaseModel):
    metric: str = Field(..., description="指标名")
    dimensions: List[str] = Field(..., description="分解维度列表")
    time_range: TimeRange = Field(..., description="分析时间范围")
    compare_mode: str = Field("mom", description="对比模式: mom/yoy/wow/custom")
    threshold_pct: float = Field(-0.05, description="异动阈值百分比")
    context: Dict[str, Any] = Field(default_factory=dict, description="扩展上下文")

    class Config:
        json_schema_extra = {
            "example": {
                "metric": "gmv",
                "dimensions": ["region", "product_category", "channel"],
                "time_range": {"start": "2026-04-01", "end": "2026-04-15"},
                "compare_mode": "mom",
                "threshold_pct": -0.05,
                "context": {"tenant_id": "550e8400-e29b-41d4-a716-446655440000", "scenario": "causation"},
            }
        }


class CausationResponse(BaseModel):
    session_id: str
    session_status: str
    delta_abs: float
    delta_pct: float
    root_dimension: str
    root_value: str
    confidence: float
    narrative_summary: str
    anomaly_confirmed: bool
    magnitude: float
    concentration_point: str
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


# ---------------------------------------------------------------------------
# JWT 解析（created_by 从 JWT 提取，不存 metadata）
# ---------------------------------------------------------------------------


def extract_user_from_jwt(authorization: str = Header(...)) -> Dict[str, Any]:
    """
    从 Authorization: Bearer <token> 解析用户信息。
    简化版：解析 JWT payload（不验签，生产需接入 Auth Service）。
    created_by 从 JWT 的 sub 或 user_id 字段提取。
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
        # JWT payload = base64(urlsafe_b64decode)
        # 忽略 signature
        payload_b64 = token.split(".")[1]
        # 补齐 padding
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


# ---------------------------------------------------------------------------
# 依赖：获取 DB Session
# ---------------------------------------------------------------------------


def get_db():
    """FastAPI 依赖：获取数据库会话"""
    from app.core.database import SessionLocal
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# ---------------------------------------------------------------------------
# POST /api/data-agent/causation — 发起归因分析
# ---------------------------------------------------------------------------


@router.post(
    "",
    response_model=CausationResponse,
    status_code=status.HTTP_201_CREATED,
    summary="UC-1 发起归因分析",
    description="销售额下滑归因六步端到端接口，30s 内返回结果。",
)
async def create_causation(
    req: CausationRequest,
    user: Dict[str, Any] = Depends(extract_user_from_jwt),
    db=Depends(get_db),
):
    """
    UC-1 归因分析端到端接口。

    验收标准（§1.1.1）：
    - 6 步内收敛
    - confidence ≥ 0.7
    - 单次 sql_execute 行数 ≤ 10000
    - 端到端延迟 < 30s
    """
    start_time = time.time()

    # 合并 context
    context = {
        "scenario": req.context.get("scenario", "causation"),
        "tenant_id": req.context.get("tenant_id") or user.get("tenant_id", ""),
        **req.context,
    }

    # 创建会话管理器
    from services.data_agent.causation_session import CausationSessionManager, SessionStatus

    manager = CausationSessionManager(db)

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

    # 执行六步归因流程
    try:
        result = await manager.run_causation(
            session_id=str(session.id),
            tenant_id=str(session.tenant_id),
        )
    except Exception as e:
        logger.exception("Causation run failed for session %s", session.id)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"error_code": "DAT_999", "message": str(e)},
        )

    elapsed_ms = int((time.time() - start_time) * 1000)
    logger.info(
        "UC-1 causation completed: session=%s elapsed=%dms confidence=%.2f steps=%d",
        session.id, elapsed_ms, result.get("confidence", 0), result.get("steps_count", 0),
    )

    return CausationResponse(**result)


# ---------------------------------------------------------------------------
# GET /api/data-agent/causation/{session_id} — 查询会话状态
# ---------------------------------------------------------------------------


@router.get(
    "/{session_id}",
    response_model=SessionStatusResponse,
    summary="查询归因分析会话状态",
)
async def get_causation_session(
    session_id: str,
    user: Dict[str, Any] = Depends(extract_user_from_jwt),
    db=Depends(get_db),
):
    """查询已创建的归因分析会话状态和结果"""
    from services.data_agent.causation_session import CausationSessionManager

    manager = CausationSessionManager(db)
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


# ---------------------------------------------------------------------------
# POST /api/data-agent/causation/{session_id}/pause — 暂停会话
# ---------------------------------------------------------------------------


@router.post(
    "/{session_id}/pause",
    response_model=SessionStatusResponse,
    summary="暂停归因分析会话",
)
async def pause_causation_session(
    session_id: str,
    user: Dict[str, Any] = Depends(extract_user_from_jwt),
    db=Depends(get_db),
):
    """暂停 running 状态的分析会话（非抢占式）"""
    from services.data_agent.causation_session import CausationSessionManager, SessionStatus

    manager = CausationSessionManager(db)
    session = manager.get_session(session_id, user.get("tenant_id", ""))

    if not session:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error_code": "DAT_002", "message": "会话不存在"},
        )

    try:
        session = manager.update_session_status(session, SessionStatus.PAUSED)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"error_code": "TR_007", "message": str(e)},
        )

    return SessionStatusResponse(
        session_id=str(session.id),
        status=session.status,
        current_step=session.current_step or 0,
        hypothesis_tree=session.hypothesis_tree,
        created_at=session.created_at.isoformat() if session.created_at else "",
        completed_at=None,
    )


# ---------------------------------------------------------------------------
# POST /api/data-agent/causation/{session_id}/resume — 恢复会话
# ---------------------------------------------------------------------------


@router.post(
    "/{session_id}/resume",
    response_model=CausationResponse,
    summary="恢复归因分析会话",
)
async def resume_causation_session(
    session_id: str,
    user: Dict[str, Any] = Depends(extract_user_from_jwt),
    db=Depends(get_db),
):
    """从 paused 状态恢复分析（从头重跑六步流程）"""
    from services.data_agent.causation_session import CausationSessionManager, SessionStatus

    manager = CausationSessionManager(db)
    session = manager.get_session(session_id, user.get("tenant_id", ""))

    if not session:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error_code": "DAT_002", "message": "会话不存在"},
        )

    try:
        session = manager.update_session_status(session, SessionStatus.RUNNING)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"error_code": "TR_007", "message": str(e)},
        )

    # 重新执行
    result = await manager.run_causation(
        session_id=str(session.id),
        tenant_id=str(session.tenant_id),
    )

    return CausationResponse(**result)


# ---------------------------------------------------------------------------
# hypothesis_store 工具 API（供内部/外部调用）
# ---------------------------------------------------------------------------


class HypothesisStoreRequest(BaseModel):
    action: str = Field(..., description="add/update/reject/confirm")
    hypothesis: Dict[str, Any] = Field(default_factory=dict)


@router.post(
    "/{session_id}/hypothesis",
    summary="操作假设树（hypothesis_store 工具接口）",
)
async def hypothesis_store(
    session_id: str,
    req: HypothesisStoreRequest,
    user: Dict[str, Any] = Depends(extract_user_from_jwt),
    db=Depends(get_db),
):
    """直接操作会话的假设树（add/update/reject/confirm）"""
    from services.data_agent.causation_session import CausationSessionManager

    manager = CausationSessionManager(db)
    session = manager.get_session(session_id, user.get("tenant_id", ""))

    if not session:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error_code": "DAT_002", "message": "会话不存在"},
        )

    result = manager.hypothesis_store(session, req.action, req.hypothesis)
    return result

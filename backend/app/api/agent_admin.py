"""
Agent 监控管理 API

路由前缀：/api/admin/agent（在 main.py 中注册）

Endpoints:
    GET  /api/admin/agent/stats           — Agent 聚合统计
    GET  /api/admin/agent/runs            — 近期运行列表（分页）
    GET  /api/admin/agent/runs/{run_id}/steps — 某次运行的步骤详情

权限：仅 admin / data_admin 角色可访问。
"""
import logging
from typing import Optional, List, Any, Dict

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import func, case, desc
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.dependencies import require_roles
from services.data_agent.models import BiAgentRun, BiAgentStep, BiAgentFeedback

logger = logging.getLogger(__name__)

router = APIRouter()


# ─────────────────────────────────────────────────────────────────────────────
# Pydantic 响应模型
# ─────────────────────────────────────────────────────────────────────────────


class ToolCount(BaseModel):
    name: str
    count: int


class FeedbackSummary(BaseModel):
    up: int
    down: int


class AgentStatsResponse(BaseModel):
    total_runs: int
    success_rate: float
    failed_count: int
    avg_execution_time_ms: Optional[int] = None
    p95_execution_time_ms: Optional[int] = None
    runs_today: int
    top_tools: List[ToolCount]
    feedback_summary: FeedbackSummary


class AgentRunItem(BaseModel):
    id: str
    user_id: int
    question: str
    status: str
    execution_time_ms: Optional[int] = None
    tools_used: Optional[List[str]] = None
    created_at: Optional[str] = None


class AgentRunsResponse(BaseModel):
    items: List[AgentRunItem]
    total: int
    limit: int
    offset: int


class AgentStepItem(BaseModel):
    id: int
    run_id: str
    step_number: int
    step_type: str
    tool_name: Optional[str] = None
    tool_params: Optional[Dict[str, Any]] = None
    tool_result_summary: Optional[str] = None
    content: Optional[str] = None
    execution_time_ms: Optional[int] = None
    created_at: Optional[str] = None


# ─────────────────────────────────────────────────────────────────────────────
# Endpoints
# ─────────────────────────────────────────────────────────────────────────────


@router.get("/stats", response_model=AgentStatsResponse)
def get_agent_stats(
    db: Session = Depends(get_db),
    _user: dict = Depends(require_roles(["admin", "data_admin"])),
):
    """
    GET /api/admin/agent/stats

    返回 Agent 聚合统计：总调用量、成功率、平均/P95 耗时、今日调用、
    热门工具、反馈汇总。
    """
    # 总调用量
    total_runs: int = db.query(func.count(BiAgentRun.id)).scalar() or 0

    # 失败数
    failed_count: int = (
        db.query(func.count(BiAgentRun.id))
        .filter(BiAgentRun.status == "error")
        .scalar()
        or 0
    )

    # 成功率
    success_rate: float = 0.0
    if total_runs > 0:
        success_rate = round((total_runs - failed_count) / total_runs, 4)

    # 平均耗时
    avg_time = (
        db.query(func.avg(BiAgentRun.execution_time_ms))
        .filter(BiAgentRun.execution_time_ms.isnot(None))
        .scalar()
    )
    avg_execution_time_ms: Optional[int] = int(avg_time) if avg_time is not None else None

    # P95 耗时：取所有完成的 run 按 execution_time_ms 排序，取第 95% 位置的值
    p95_execution_time_ms: Optional[int] = None
    completed_count: int = (
        db.query(func.count(BiAgentRun.id))
        .filter(BiAgentRun.execution_time_ms.isnot(None))
        .scalar()
        or 0
    )
    if completed_count > 0:
        p95_offset = max(0, int(completed_count * 0.95) - 1)
        p95_row = (
            db.query(BiAgentRun.execution_time_ms)
            .filter(BiAgentRun.execution_time_ms.isnot(None))
            .order_by(BiAgentRun.execution_time_ms.asc())
            .offset(p95_offset)
            .limit(1)
            .first()
        )
        if p95_row and p95_row[0] is not None:
            p95_execution_time_ms = int(p95_row[0])

    # 今日调用
    runs_today: int = (
        db.query(func.count(BiAgentRun.id))
        .filter(func.date(BiAgentRun.created_at) == func.current_date())
        .scalar()
        or 0
    )

    # 热门工具：从 tools_used (ARRAY) 中展开统计
    # 使用 unnest 展开数组并聚合计数
    top_tools: List[ToolCount] = []
    try:
        tool_rows = (
            db.query(
                func.unnest(BiAgentRun.tools_used).label("tool"),
                func.count().label("cnt"),
            )
            .filter(BiAgentRun.tools_used.isnot(None))
            .group_by("tool")
            .order_by(desc("cnt"))
            .limit(10)
            .all()
        )
        top_tools = [ToolCount(name=row.tool, count=row.cnt) for row in tool_rows]
    except Exception as exc:
        logger.warning("统计热门工具失败: %s", exc)

    # 反馈汇总
    up_count: int = (
        db.query(func.count(BiAgentFeedback.id))
        .filter(BiAgentFeedback.rating == "up")
        .scalar()
        or 0
    )
    down_count: int = (
        db.query(func.count(BiAgentFeedback.id))
        .filter(BiAgentFeedback.rating == "down")
        .scalar()
        or 0
    )

    return AgentStatsResponse(
        total_runs=total_runs,
        success_rate=success_rate,
        failed_count=failed_count,
        avg_execution_time_ms=avg_execution_time_ms,
        p95_execution_time_ms=p95_execution_time_ms,
        runs_today=runs_today,
        top_tools=top_tools,
        feedback_summary=FeedbackSummary(up=up_count, down=down_count),
    )


@router.get("/runs", response_model=AgentRunsResponse)
def list_agent_runs(
    db: Session = Depends(get_db),
    _user: dict = Depends(require_roles(["admin", "data_admin"])),
    limit: int = Query(20, ge=1, le=100, description="每页条数"),
    offset: int = Query(0, ge=0, description="偏移量"),
    status: Optional[str] = Query(None, description="状态筛选: running / completed / error"),
):
    """
    GET /api/admin/agent/runs

    返回近期 Agent 运行列表，支持分页和状态筛选。
    question 截断为 100 字符。
    """
    q = db.query(BiAgentRun)

    if status is not None:
        q = q.filter(BiAgentRun.status == status)

    total: int = q.count()

    runs = (
        q.order_by(BiAgentRun.created_at.desc())
        .offset(offset)
        .limit(limit)
        .all()
    )

    items = [
        AgentRunItem(
            id=str(run.id),
            user_id=run.user_id,
            question=(run.question[:100] + "...") if len(run.question) > 100 else run.question,
            status=run.status,
            execution_time_ms=run.execution_time_ms,
            tools_used=run.tools_used,
            created_at=run.created_at.isoformat() if run.created_at else None,
        )
        for run in runs
    ]

    return AgentRunsResponse(
        items=items,
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/runs/{run_id}/steps", response_model=List[AgentStepItem])
def get_run_steps(
    run_id: str,
    db: Session = Depends(get_db),
    _user: dict = Depends(require_roles(["admin", "data_admin"])),
):
    """
    GET /api/admin/agent/runs/{run_id}/steps

    返回指定运行的所有步骤详情。
    """
    # 验证 run 存在
    run = db.query(BiAgentRun).filter(BiAgentRun.id == run_id).first()
    if run is None:
        raise HTTPException(status_code=404, detail="运行记录不存在")

    steps = (
        db.query(BiAgentStep)
        .filter(BiAgentStep.run_id == run_id)
        .order_by(BiAgentStep.step_number.asc())
        .all()
    )

    return [
        AgentStepItem(
            id=step.id,
            run_id=str(step.run_id),
            step_number=step.step_number,
            step_type=step.step_type,
            tool_name=step.tool_name,
            tool_params=step.tool_params,
            tool_result_summary=step.tool_result_summary,
            content=step.content,
            execution_time_ms=step.execution_time_ms,
            created_at=step.created_at.isoformat() if step.created_at else None,
        )
        for step in steps
    ]

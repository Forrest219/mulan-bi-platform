"""Task Runtime REST API（Spec 24 §3.1）

端点：
- POST /api/tasks/runs       创建 TaskRun
- GET  /api/tasks/runs/{id}  查详情
- GET  /api/tasks/runs/{id}/events  SSE 事件流
- POST /api/tasks/runs/{id}/cancel  取消
- GET  /api/tasks/runs       列表（自己）
"""
import asyncio
import json
import logging
import uuid
from datetime import datetime, timezone
from typing import AsyncGenerator, Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import func, desc
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.dependencies import get_current_user
from app.core.errors import TRError
from services.task_runtime.models_db import BiTaskRun, BiTaskRunStep, BiTaskRunEvent
from services.task_runtime.service import TaskRunService, TaskRunStatus
from services.task_runtime.service import VALID_TRANSITIONS
from services.task_runtime.validators import TaskRunValidator
from services.task_runtime import event_bus

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/tasks/runs", tags=["Task Runtime"])


# ==================== Request/Response Schemas ====================

class CreateTaskRunRequest(BaseModel):
    intent: str = Field(..., description="任务类型: agent_chat / nlq_query / bulk_action / health_scan")
    input: dict = Field(..., description="输入参数")
    timeout_seconds: int = Field(default=120, ge=5, le=600, description="超时秒数 [5, 600]")
    conversation_id: Optional[int] = Field(None, description="会话 ID（agent_chat 模式必填）")


class CreateTaskRunResponse(BaseModel):
    id: int
    trace_id: str
    intent: str
    status: str
    started_at: str
    events_url: str


class TaskRunDetailResponse(BaseModel):
    id: int
    trace_id: str
    conversation_id: Optional[int]
    user_id: int
    intent: str
    status: str
    input_payload: dict
    output_payload: Optional[dict]
    error_code: Optional[str]
    error_message: Optional[str]
    started_at: str
    finished_at: Optional[str]
    timeout_seconds: int
    created_at: str
    updated_at: str
    steps: list


class TaskRunListResponse(BaseModel):
    items: list
    total: int
    page: int
    page_size: int


class CancelResponse(BaseModel):
    id: int
    status: str


# ==================== Endpoint Implementations ====================

@router.post("", response_model=CreateTaskRunResponse, status_code=201)
async def create_task_run(
    request: Request,
    body: CreateTaskRunRequest,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """POST /api/tasks/runs — 创建 TaskRun"""
    # 校验
    validator = TaskRunValidator(db, current_user)
    validator.validate_create(
        intent=body.intent,
        timeout_seconds=body.timeout_seconds,
        conversation_id=body.conversation_id,
    )
    validator.validate_rbac(body.intent)

    # 生成 trace_id
    trace_id = uuid.uuid4().hex

    # 创建 TaskRun
    task_run = BiTaskRun(
        trace_id=trace_id,
        user_id=current_user["id"],
        intent=body.intent,
        status=TaskRunStatus.QUEUED,
        input_payload=body.input,
        conversation_id=body.conversation_id,
        timeout_seconds=body.timeout_seconds,
        started_at=datetime.now(timezone.utc),
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    db.add(task_run)
    db.flush()

    # 发射 task.queued 事件
    event_bus.emit_task_queued(
        db=db,
        task_run_id=task_run.id,
        trace_id=trace_id,
        intent=body.intent,
        user_id=current_user["id"],
    )

    db.commit()

    return CreateTaskRunResponse(
        id=task_run.id,
        trace_id=trace_id,
        intent=task_run.intent,
        status=task_run.status,
        started_at=task_run.started_at.isoformat(),
        events_url=f"/api/tasks/runs/{task_run.id}/events",
    )


@router.get("/{run_id}", response_model=TaskRunDetailResponse)
async def get_task_run(
    run_id: int,
    request: Request,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """GET /api/tasks/runs/{id} — 查 TaskRun 详情"""
    service = TaskRunService(db)
    run = service.get_run_or_raise(run_id, user_id=current_user["id"])

    # 权限校验：非 admin 只能查看自己的 TaskRun
    role = current_user.get("role", "user")
    if run.user_id != current_user["id"] and role != "admin":
        raise TRError.task_run_not_found()

    # 加载 steps
    steps = db.query(BiTaskRunStep).filter(
        BiTaskRunStep.task_run_id == run_id
    ).order_by(BiTaskRunStep.seq).all()

    return TaskRunDetailResponse(
        id=run.id,
        trace_id=run.trace_id,
        conversation_id=run.conversation_id,
        user_id=run.user_id,
        intent=run.intent,
        status=run.status,
        input_payload=run.input_payload,
        output_payload=run.output_payload,
        error_code=run.error_code,
        error_message=run.error_message,
        started_at=run.started_at.isoformat() if run.started_at else "",
        finished_at=run.finished_at.isoformat() if run.finished_at else None,
        timeout_seconds=run.timeout_seconds,
        created_at=run.created_at.isoformat() if run.created_at else "",
        updated_at=run.updated_at.isoformat() if run.updated_at else "",
        steps=[s.to_dict() for s in steps],
    )


@router.get("/{run_id}/events")
async def get_task_run_events(
    run_id: int,
    request: Request,
    last_event_id: Optional[str] = Header(None, alias="Last-Event-ID"),
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """GET /api/tasks/runs/{id}/events — SSE 事件流

    支持 Last-Event-ID 头用于断线重连。
    事件帧格式：
      data: {"event": "step.started", "step_id": 67, "seq": 1, ...}\n\n
    """
    service = TaskRunService(db)
    run = service.get_run_or_raise(run_id, user_id=current_user["id"])

    # 权限校验
    role = current_user.get("role", "user")
    if run.user_id != current_user["id"] and role != "admin":
        raise TRError.task_run_not_found()

    async def event_stream() -> AsyncGenerator[str, None]:
        """SSE 流生成器"""
        query = db.query(BiTaskRunEvent).filter(
            BiTaskRunEvent.task_run_id == run_id
        ).order_by(BiTaskRunEvent.emitted_at)

        # 如果有 Last-Event-ID，从该事件之后开始（续流）
        if last_event_id:
            try:
                last_id = int(last_event_id)
                query = query.filter(BiTaskRunEvent.id > last_id)
            except ValueError:
                pass  # 无效的 Last-Event-ID，从头开始

        # 实时查询已有事件 + 轮询新事件
        seen_ids = set()
        poll_interval = 0.5  # 秒

        while True:
            events = query.filter(
                ~BiTaskRunEvent.id.in_(seen_ids) if seen_ids else True
            ).limit(100).all()

            for event in events:
                seen_ids.add(event.id)
                frame = {
                    "id": event.id,
                    "event": event.event_type,
                    "data": event.payload,
                    "ts": event.emitted_at.isoformat() if event.emitted_at else "",
                }
                yield f"data: {json.dumps(frame, ensure_ascii=False)}\n\n"

            # 检查是否已到达终态
            current_run = service.get_run(run_id)
            if current_run and current_run.status in TaskRunStatus.TERMINAL:
                # 发送终态事件后结束
                if current_run.status == TaskRunStatus.SUCCEEDED:
                    yield f"data: {json.dumps({'event': 'run.completed', 'status': 'succeeded', 'ts': datetime.now(timezone.utc).isoformat()}, ensure_ascii=False)}\n\n"
                elif current_run.status == TaskRunStatus.FAILED:
                    yield f"data: {json.dumps({'event': 'run.failed', 'status': 'failed', 'error_code': current_run.error_code, 'ts': datetime.now(timezone.utc).isoformat()}, ensure_ascii=False)}\n\n"
                elif current_run.status == TaskRunStatus.CANCELLED:
                    yield f"data: {json.dumps({'event': 'run.cancelled', 'status': 'cancelled', 'ts': datetime.now(timezone.utc).isoformat()}, ensure_ascii=False)}\n\n"
                break

            await asyncio.sleep(poll_interval)

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


@router.post("/{run_id}/cancel", response_model=CancelResponse)
async def cancel_task_run(
    run_id: int,
    request: Request,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """POST /api/tasks/runs/{id}/cancel — 取消 TaskRun"""
    service = TaskRunService(db)
    run = service.get_run_or_raise(run_id, user_id=current_user["id"])

    # 权限校验：非 admin 只能取消自己的 TaskRun
    role = current_user.get("role", "user")
    if run.user_id != current_user["id"] and role != "admin":
        raise TRError.task_run_not_found()

    updated_run, was_cancelled = service.cancel(run_id)

    # 发射对应事件
    if was_cancelled:
        now = datetime.now(timezone.utc)
        if updated_run.status == TaskRunStatus.CANCELLED:
            event_bus.emit_task_cancelled(db, run_id, now)
        # cancelling 状态不发射特殊事件，等待最终状态

    db.commit()

    return CancelResponse(id=updated_run.id, status=updated_run.status)


@router.get("", response_model=TaskRunListResponse)
async def list_task_runs(
    request: Request,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    status: Optional[str] = Query(default=None),
    intent: Optional[str] = Query(default=None),
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """GET /api/tasks/runs — 列表（自己）"""
    role = current_user.get("role", "user")

    query = db.query(BiTaskRun)

    # 非 admin 只能看自己的
    if role != "admin":
        query = query.filter(BiTaskRun.user_id == current_user["id"])

    # 过滤条件
    if status:
        query = query.filter(BiTaskRun.status == status)
    if intent:
        query = query.filter(BiTaskRun.intent == intent)

    # 总数
    total = query.count()

    # 分页
    offset = (page - 1) * page_size
    runs = query.order_by(desc(BiTaskRun.started_at)).offset(offset).limit(page_size).all()

    return TaskRunListResponse(
        items=[r.to_dict() for r in runs],
        total=total,
        page=page,
        page_size=page_size,
    )

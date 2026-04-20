"""任务状态查询 API
"""
from celery.result import AsyncResult
from fastapi import APIRouter, Request

from app.core.dependencies import get_current_user
from services.tasks import celery_app

router = APIRouter()


@router.get("/{task_id}/status")
async def get_task_status(task_id: str, request: Request):
    """查询 Celery 任务状态

    注意（Spec 24 P0）：
    此端点为 legacy 接口，标记为 deprecated。
    TaskRun 编排能力请使用 /api/tasks/runs*（P1 实现后替代）。
    """
    get_current_user(request)

    result = AsyncResult(task_id, app=celery_app)

    response = {
        "task_id": task_id,
        "status": result.status,
    }

    if result.ready():
        response["result"] = result.result
    elif result.status == "STARTED":
        response["message"] = "任务执行中"
    elif result.status == "PENDING":
        response["message"] = "任务等待中"

    return response

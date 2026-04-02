"""
任务状态查询 API
"""
from fastapi import APIRouter, Request
from celery.result import AsyncResult

from services.tasks import celery_app
from app.core.dependencies import get_current_user

router = APIRouter()


@router.get("/{task_id}/status")
async def get_task_status(task_id: str, request: Request):
    """查询 Celery 任务状态"""
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

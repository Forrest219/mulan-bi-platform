"""访问日志 API
"""
from typing import Optional

from fastapi import APIRouter, Request

from app.core.dependencies import get_current_user
from services.auth import auth_service
from services.logs.models import LogDatabase

router = APIRouter(tags=["访问日志"])


@router.get("/logs")
async def get_access_logs(
    request: Request,
    limit: int = 50,
    user_id: Optional[int] = None,
    operation_type: Optional[str] = None
):
    """获取访问日志（admin 可查所有人，其他角色仅能查自己的）"""
    current_user = get_current_user(request)
    limit = min(limit, 1000)

    # 非管理员强制只读自身记录，防止信息泄露
    if current_user.get("role") != "admin":
        user_id = current_user["id"]

    db = LogDatabase()
    logs = db.get_operation_logs(limit=limit, operation_type=operation_type if operation_type else None)

    # 非管理员在内存中二次过滤（get_operation_logs 若不支持 user_id 参数时兜底）
    if current_user.get("role") != "admin":
        logs = [log for log in logs if getattr(log, "user_id", None) == user_id]

    result = [log.to_dict() for log in logs]
    return {"logs": result, "total": len(result)}


@router.get("/stats")
async def get_activity_stats(request: Request):
    """获取活动统计"""
    get_current_user(request)

    users = auth_service.get_users_with_tags()

    tag_counts = {"活跃": 0, "正常": 0, "冷门": 0, "潜水": 0, "僵尸": 0}

    for user in users:
        tag = user.get("tag", "未知")
        if tag in tag_counts:
            tag_counts[tag] += 1

    total_users = len(users)
    active_users = tag_counts["活跃"] + tag_counts["正常"]

    return {
        "total_users": total_users,
        "active_users": active_users,
        "tag_counts": tag_counts,
        "active_rate": round(active_users / total_users * 100, 1) if total_users > 0 else 0
    }

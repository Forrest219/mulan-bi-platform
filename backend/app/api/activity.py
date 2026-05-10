"""操作日志 / 访问日志 API"""
from typing import Optional
import csv
import io
from datetime import datetime

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse

from app.core.dependencies import get_current_user
from services.logs import logger
from services.logs.models import LogDatabase

router = APIRouter(tags=["操作日志"])


@router.get("/logs")
async def get_activity_logs(
    request: Request,
    page: int = 1,
    page_size: int = 20,
    operation_type: Optional[str] = None,
    start_time: Optional[str] = None,
    end_time: Optional[str] = None,
    user_id: Optional[int] = None,
):
    """分页查询操作日志"""
    current_user = get_current_user(request)
    if page < 1:
        page = 1
    if page_size < 1 or page_size > 100:
        page_size = 20

    # 非管理员强制只看自己
    if current_user.get("role") != "admin":
        user_id = current_user["id"]

    # 解析时间参数
    start_dt = None
    end_dt = None
    if start_time:
        try:
            start_dt = datetime.fromisoformat(start_time.replace("Z", "+00:00"))
        except Exception:
            start_dt = None
    if end_time:
        try:
            end_dt = datetime.fromisoformat(end_time.replace("Z", "+00:00"))
        except Exception:
            end_dt = None

    db = LogDatabase()
    offset = (page - 1) * page_size
    logs, total = db.get_operation_logs_paginated(
        limit=page_size,
        offset=offset,
        operation_type=operation_type if operation_type else None,
        start_time=start_dt,
        end_time=end_dt,
        user_id=user_id,
    )

    pages = (total + page_size - 1) // page_size if total > 0 else 1

    return {
        "logs": [log.to_dict() for log in logs],
        "total": total,
        "page": page,
        "page_size": page_size,
        "pages": pages,
    }


@router.get("/types")
async def get_activity_types(request: Request):
    """获取所有不重复的 operation_type 枚举值（动态枚举）"""
    get_current_user(request)
    db = LogDatabase()
    types = db.get_distinct_operation_types()
    return {"types": types}


@router.get("/stats")
async def get_activity_stats(request: Request, user_id: Optional[int] = None):
    """获取活动统计（可选 user_id 筛选）"""
    current_user = get_current_user(request)
    if current_user.get("role") != "admin":
        user_id = current_user["id"]

    from services.auth import auth_service
    users = auth_service.get_users_with_tags()

    # user_id 筛选
    if user_id is not None:
        users = [u for u in users if u.get("id") == user_id]

    tag_counts = {"活跃": 0, "正常": 0, "冷门": 0, "潜水": 0, "僵尸": 0}
    for user in users:
        tag = user.get("tag", "未知")
        if tag in tag_counts:
            tag_counts[tag] += 1

    total_users = len(users)
    active_users = tag_counts["活跃"] + tag_counts["正常"]

    # 如果指定了 user_id，返回该用户的操作统计
    operation_stats = {}
    if user_id is not None:
        db = LogDatabase()
        ops = db.get_operation_logs_paginated(limit=1000, user_id=user_id)
        operation_stats = {
            "total": len(ops[0]) if ops[0] else 0,
        }

    return {
        "total_users": total_users,
        "active_users": active_users,
        "tag_counts": tag_counts,
        "active_rate": round(active_users / total_users * 100, 1) if total_users > 0 else 0,
        "operation_stats": operation_stats,
    }


@router.get("/logs/export")
async def export_activity_logs(
    request: Request,
    operation_type: Optional[str] = None,
    start_time: Optional[str] = None,
    end_time: Optional[str] = None,
    user_id: Optional[int] = None,
):
    """导出操作日志为 CSV 流（支持筛选条件）"""
    current_user = get_current_user(request)

    # 解析时间参数
    start_dt = None
    end_dt = None
    if start_time:
        try:
            start_dt = datetime.fromisoformat(start_time.replace("Z", "+00:00"))
        except Exception:
            start_dt = None
    if end_time:
        try:
            end_dt = datetime.fromisoformat(end_time.replace("Z", "+00:00"))
        except Exception:
            end_dt = None

    db = LogDatabase()
    # 非管理员强制只看自己；管理员可通过 user_id 参数筛选
    if current_user.get("role") != "admin":
        user_id = current_user["id"]

    # 分页获取全部日志（每次最多 1000 条）
    all_logs = []
    offset = 0
    page_size = 1000
    while True:
        logs, _ = db.get_operation_logs_paginated(
            limit=page_size,
            offset=offset,
            operation_type=operation_type if operation_type else None,
            start_time=start_dt,
            end_time=end_dt,
            user_id=user_id,
        )
        all_logs.extend(logs)
        if len(logs) < page_size:
            break
        offset += page_size

    # 构建 CSV
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([
        "id", "op_time", "operator", "operation_type", "target",
        "status", "ip_address", "user_agent", "trace_id", "details"
    ])
    for log in all_logs:
        d = log.to_dict()
        writer.writerow([
            d.get("id", ""),
            d.get("op_time", ""),
            d.get("operator", ""),
            d.get("operation_type", ""),
            d.get("target", ""),
            d.get("status", ""),
            d.get("ip_address", "") or "",
            d.get("user_agent", "") or "",
            d.get("trace_id", "") or "",
            (d.get("details") or "").replace('"', '""'),
        ])

    output.seek(0)
    filename = f"activity-logs-{datetime.now().strftime('%Y%m%d-%H%M%S')}.csv"
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv;charset=utf-8",
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{filename}"},
    )
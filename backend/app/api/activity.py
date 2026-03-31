"""
访问日志 API
"""
from fastapi import APIRouter, Request, Depends, HTTPException
from pydantic import BaseModel
from typing import Optional, List
import os
import jwt

router = APIRouter(tags=["访问日志"])

# JWT 验签
_JWT_SECRET = os.environ.get("SESSION_SECRET")
_JWT_ALGORITHM = "HS256"


def _decode_session_token(token: str):
    """验证并解码 session token"""
    try:
        payload = jwt.decode(token, _JWT_SECRET, algorithms=[_JWT_ALGORITHM])
        return {"id": int(payload["sub"]), "username": payload["username"], "role": payload["role"]}
    except jwt.InvalidTokenError:
        return None


def get_current_user(request: Request) -> dict:
    """依赖：获取当前登录用户"""
    token = request.cookies.get("session")
    if not token:
        raise HTTPException(status_code=401, detail="未登录")
    user_info = _decode_session_token(token)
    if not user_info:
        raise HTTPException(status_code=401, detail="无效的会话")
    return user_info


@router.get("/logs")
async def get_access_logs(
    request: Request,
    limit: int = 50,
    user_id: Optional[int] = None,
    operation_type: Optional[str] = None
):
    """获取访问日志"""
    get_current_user(request)
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent / "src"))

    # 访问日志直接从日志数据库获取
    from logs import LogDatabase, OperationLog

    db = LogDatabase()
    logs = db.get_operation_logs(limit=limit, operation_type=operation_type if operation_type else None)

    # 如果指定了用户ID，过滤
    if user_id:
        # 需要关联用户，但 OperationLog 存的是 operator 字符串
        # 这里先返回所有，然后前端过滤
        pass

    result = [log.to_dict() for log in logs]
    return {"logs": result, "total": len(result)}


@router.get("/stats")
async def get_activity_stats(request: Request):
    """获取活动统计"""
    get_current_user(request)
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent / "src"))
    from auth import auth_service

    users = auth_service.get_users_with_tags()

    # 统计各状态用户数
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

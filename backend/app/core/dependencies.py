"""
共享依赖模块 - 认证和授权依赖

提供统一的认证依赖注入函数，消除 API 模块间的重复代码
"""
import sys
from pathlib import Path

import jwt
from fastapi import HTTPException, Request
from typing import Optional

sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent / "src"))

from app.core.constants import JWT_SECRET, JWT_ALGORITHM

_JWT_SECRET = JWT_SECRET
_JWT_ALGORITHM = JWT_ALGORITHM


def _decode_session_token(token: str) -> Optional[dict]:
    """验证并解码 session token（含过期校验）"""
    try:
        payload = jwt.decode(token, _JWT_SECRET, algorithms=[_JWT_ALGORITHM], options={"require": ["exp"]})
        return {
            "id": int(payload["sub"]),
            "username": payload["username"],
            "role": payload["role"]
        }
    except jwt.ExpiredSignatureError:
        return None
    except jwt.InvalidTokenError:
        return None


def get_current_user(request: Request) -> dict:
    """
    依赖：获取当前登录用户

    从 session cookie 提取并验证 JWT token，然后从数据库验证用户状态和当前角色。
    失败时抛出 HTTPException(401)

    Returns:
        {"id": int, "username": str, "role": str}
    """
    token = request.cookies.get("session")
    if not token:
        raise HTTPException(status_code=401, detail="未登录")
    token_info = _decode_session_token(token)
    if not token_info:
        raise HTTPException(status_code=401, detail="无效或已过期的会话")

    # 从数据库验证用户当前状态和角色（防止 token 中的角色过期）
    from auth import auth_service
    db_user = auth_service.get_user(token_info["id"])
    if not db_user or not db_user.get("is_active"):
        raise HTTPException(status_code=401, detail="用户不存在或已被禁用")

    return {"id": db_user["id"], "username": db_user["username"], "role": db_user["role"]}


def get_current_admin(request: Request) -> dict:
    """
    依赖：获取当前登录管理员

    验证用户已登录且角色为 admin
    失败时抛出 HTTPException(403)

    Returns:
        {"id": int, "username": str, "role": str}
    """
    user = get_current_user(request)
    if user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="需要管理员权限")
    return user


def require_roles(request: Request, allowed_roles: list) -> dict:
    """
    依赖：验证用户角色

    Args:
        allowed_roles: 允许的角色列表，如 ["admin", "data_admin"]

    Returns:
        {"id": int, "username": str, "role": str}
    """
    user = get_current_user(request)
    if user.get("role") not in allowed_roles:
        raise HTTPException(status_code=403, detail="权限不足")
    return user

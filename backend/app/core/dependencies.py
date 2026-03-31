"""
共享依赖模块 - 认证和授权依赖

提供统一的认证依赖注入函数，消除 API 模块间的重复代码
"""
import os
import jwt
from fastapi import HTTPException, Request
from typing import Optional


# JWT 验签配置
_JWT_SECRET = os.environ.get("SESSION_SECRET")
if not _JWT_SECRET:
    raise RuntimeError("SESSION_SECRET environment variable must be set")
_JWT_ALGORITHM = "HS256"


def _decode_session_token(token: str) -> Optional[dict]:
    """验证并解码 session token"""
    try:
        payload = jwt.decode(token, _JWT_SECRET, algorithms=[_JWT_ALGORITHM])
        return {
            "id": int(payload["sub"]),
            "username": payload["username"],
            "role": payload["role"]
        }
    except jwt.InvalidTokenError:
        return None


def get_current_user(request: Request) -> dict:
    """
    依赖：获取当前登录用户

    从 session cookie 提取并验证 JWT token
    失败时抛出 HTTPException(401)

    Returns:
        {"id": int, "username": str, "role": str}
    """
    token = request.cookies.get("session")
    if not token:
        raise HTTPException(status_code=401, detail="未登录")
    user_info = _decode_session_token(token)
    if not user_info:
        raise HTTPException(status_code=401, detail="无效的会话")
    return user_info


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

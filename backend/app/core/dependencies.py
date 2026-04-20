"""
共享依赖模块 - 认证和授权依赖

提供统一的认证依赖注入函数，消除 API 模块间的重复代码
"""
import jwt
from fastapi import Request, Depends
from typing import Optional, List

from app.core.database import get_db
from app.core.errors import AuthError
from sqlalchemy.orm import Session

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


def get_current_user(request: Request, db: Session = Depends(get_db)) -> dict:
    """
    依赖：获取当前登录用户

    从 session cookie 提取并验证 JWT token，然后从数据库验证用户状态和当前角色。
    失败时抛出 MulanError(AUTH_001)

    Returns:
        {"id": int, "username": str, "role": str}
    """
    token = request.cookies.get("session")
    if not token:
        raise AuthError.session_expired()
    token_info = _decode_session_token(token)
    if not token_info:
        raise AuthError.session_expired()

    # 从数据库验证用户当前状态和角色（防止 token 中的角色过期）
    from services.auth.models import UserDatabase
    auth_db = UserDatabase()
    db_user = auth_db.get_user(token_info["id"])
    if not db_user:
        raise AuthError.session_expired()
    if not db_user.is_active:
        raise AuthError.account_disabled()

    return {"id": db_user.id, "username": db_user.username, "role": db_user.role}


def get_current_admin(request: Request, db: Session = Depends(get_db)) -> dict:
    """
    依赖：获取当前登录管理员

    验证用户已登录且角色为 admin
    失败时抛出 MulanError(AUTH_004)

    Returns:
        {"id": int, "username": str, "role": str}
    """
    user = get_current_user(request, db)
    if user.get("role") != "admin":
        raise AuthError.admin_required()
    return user


def require_roles(allowed_roles: List[str]):
    """
    依赖工厂：验证用户角色是否在允许列表中。

    用法：Depends(require_roles(["admin", "data_admin"]))

    Args:
        allowed_roles: 允许的角色列表，如 ["admin", "data_admin"]

    Returns:
        可传入 Depends() 的依赖闭包
    """
    async def require_roles_dep(
        request: Request,
        db: Session = Depends(get_db),
    ) -> dict:
        user = get_current_user(request, db)
        if user.get("role") not in allowed_roles:
            raise AuthError.insufficient_permissions()
        return user

    return require_roles_dep

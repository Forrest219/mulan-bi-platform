"""
权限配置 API - 仅管理员可访问
"""
import os
import jwt
from fastapi import APIRouter, HTTPException, Request, Depends
from pydantic import BaseModel
from typing import List

router = APIRouter(tags=["权限配置"])

# JWT 验签
_JWT_SECRET = os.environ.get("SESSION_SECRET")
if not _JWT_SECRET:
    raise RuntimeError("SESSION_SECRET environment variable must be set")
_JWT_ALGORITHM = "HS256"


def _decode_session_token(token: str):
    """验证并解码 session token"""
    try:
        payload = jwt.decode(token, _JWT_SECRET, algorithms=[_JWT_ALGORITHM])
        return {"id": int(payload["sub"]), "username": payload["username"], "role": payload["role"]}
    except jwt.InvalidTokenError:
        return None


def get_current_admin(request: Request) -> dict:
    """依赖：获取当前登录管理员"""
    token = request.cookies.get("session")
    if not token:
        raise HTTPException(status_code=401, detail="未登录")
    user_info = _decode_session_token(token)
    if not user_info:
        raise HTTPException(status_code=401, detail="无效的会话")
    if user_info["role"] != "admin":
        raise HTTPException(status_code=403, detail="需要管理员权限")
    return user_info


@router.get("/")
async def get_all_permissions():
    """获取所有可用权限定义"""
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent / "src"))
    from auth import auth_service

    permissions = auth_service.get_all_available_permissions()
    return {"permissions": permissions}


@router.get("/users/{user_id}")
async def get_user_permissions(user_id: int):
    """获取用户的完整权限（个人+组继承）"""
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent / "src"))
    from auth import auth_service

    perms = auth_service.get_user_permissions_with_groups(user_id)
    return perms


@router.get("/users")
async def get_users_with_tags():
    """获取所有用户（带标签）"""
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent / "src"))
    from auth import auth_service

    users = auth_service.get_users_with_tags()
    return {"users": users}


@router.get("/groups")
async def get_groups_with_permissions():
    """获取所有用户组（带权限）"""
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent / "src"))
    from auth import auth_service

    groups = auth_service.get_groups()
    result = []
    for group in groups:
        group_id = group["id"]
        perms = auth_service.get_group_permissions(group_id)
        group["permissions"] = perms
        result.append(group)

    return {"groups": result}

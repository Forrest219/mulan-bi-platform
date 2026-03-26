"""
权限配置 API - 仅管理员可访问
"""
from fastapi import APIRouter, HTTPException, Request, Depends
from pydantic import BaseModel
from typing import List

router = APIRouter(tags=["权限配置"])


def get_current_admin(request: Request) -> dict:
    """依赖：获取当前登录管理员"""
    session = request.cookies.get("session")
    if not session:
        raise HTTPException(status_code=401, detail="未登录")

    parts = session.split(":")
    if len(parts) < 3:
        raise HTTPException(status_code=401, detail="无效的会话")

    role = parts[2]
    if role != "admin":
        raise HTTPException(status_code=403, detail="需要管理员权限")

    return {"id": int(parts[0]), "role": role}


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

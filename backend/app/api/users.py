"""
用户管理 API - 仅管理员可访问
"""
from fastapi import APIRouter, HTTPException, Request, Depends
from pydantic import BaseModel
from typing import Optional, List, Callable

router = APIRouter()


def get_current_admin(request: Request) -> dict:
    """依赖：获取当前登录管理员"""
    session = request.cookies.get("session")
    if not session:
        raise HTTPException(status_code=401, detail="未登录")

    parts = session.split(":")
    if len(parts) < 3:
        raise HTTPException(status_code=401, detail="无效的会话")

    user_id = int(parts[0])
    role = parts[2]

    if role != "admin":
        raise HTTPException(status_code=403, detail="需要管理员权限")

    return {"id": user_id, "role": role}


def get_current_user(request: Request) -> dict:
    """依赖：获取当前登录用户"""
    session = request.cookies.get("session")
    if not session:
        raise HTTPException(status_code=401, detail="未登录")

    parts = session.split(":")
    if len(parts) < 3:
        raise HTTPException(status_code=401, detail="无效的会话")

    user_id = int(parts[0])
    role = parts[2]

    return {"id": user_id, "role": role}


class CreateUserRequest(BaseModel):
    """创建用户请求"""
    username: str
    display_name: str
    password: str
    email: Optional[str] = None
    role: str = "user"  # admin, data_admin, analyst, user


class UpdateUserRoleRequest(BaseModel):
    """更新用户角色请求"""
    role: str  # admin, data_admin, analyst, user


class UpdatePermissionsRequest(BaseModel):
    """更新用户权限请求"""
    permissions: List[str]  # 权限标识列表


@router.get("/", dependencies=[Depends(get_current_admin)])
async def get_users(role: Optional[str] = None):
    """获取用户列表（管理员）"""
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent / "src"))
    from auth import auth_service

    users = auth_service.get_users(role=role)
    return {"users": users, "total": len(users)}


@router.post("/", dependencies=[Depends(get_current_admin)])
async def create_user(request: CreateUserRequest):
    """创建用户（管理员）"""
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent / "src"))
    from auth import auth_service

    VALID_ROLES = ["admin", "data_admin", "analyst", "user"]
    if request.role not in VALID_ROLES:
        raise HTTPException(status_code=400, detail="无效的角色")

    user = auth_service.create_user(
        username=request.username,
        password=request.password,
        role=request.role,
        display_name=request.display_name,
        email=request.email
    )

    if not user:
        raise HTTPException(status_code=400, detail="用户名已存在")

    return {"user": user, "message": "用户创建成功"}


@router.put("/{user_id}/role", dependencies=[Depends(get_current_admin)])
async def update_user_role(user_id: int, request: UpdateUserRoleRequest):
    """更新用户角色（管理员）"""
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent / "src"))
    from auth import auth_service

    VALID_ROLES = ["admin", "data_admin", "analyst", "user"]
    if request.role not in VALID_ROLES:
        raise HTTPException(status_code=400, detail="无效的角色")

    # 防止把自己降级
    session = request.cookies.get("session")
    if session:
        parts = session.split(":")
        current_user_id = int(parts[0])
        if current_user_id == user_id and request.role != "admin":
            raise HTTPException(status_code=400, detail="不能将自己的角色降级")

    success = auth_service.update_user_role(user_id, request.role)
    if not success:
        raise HTTPException(status_code=404, detail="用户不存在")

    return {"message": "角色更新成功"}


@router.put("/{user_id}/toggle-active", dependencies=[Depends(get_current_admin)])
async def toggle_user_active(user_id: int):
    """切换用户激活状态（管理员）"""
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent / "src"))
    from auth import auth_service

    success = auth_service.toggle_user_active(user_id)
    if not success:
        raise HTTPException(status_code=404, detail="用户不存在")

    return {"message": "状态已切换"}


@router.put("/{user_id}/permissions", dependencies=[Depends(get_current_admin)])
async def update_user_permissions(user_id: int, request: UpdatePermissionsRequest):
    """更新用户权限（管理员）"""
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent / "src"))
    from auth import auth_service

    # 验证权限
    for perm in request.permissions:
        if perm not in auth_service.ALL_PERMISSIONS:
            raise HTTPException(status_code=400, detail=f"无效的权限: {perm}")

    success = auth_service.update_user_permissions(user_id, request.permissions)
    if not success:
        raise HTTPException(status_code=404, detail="用户不存在")

    return {"message": "权限更新成功"}


@router.get("/permissions", dependencies=[Depends(get_current_admin)])
async def get_all_permissions():
    """获取所有可用权限（管理员）"""
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent / "src"))
    from auth import auth_service

    PERMISSION_LABELS = {
        "ddl_check": "DDL 规范检查",
        "ddl_generator": "DDL 生成器",
        "database_monitor": "数据库监控",
        "rule_config": "规则配置",
        "scan_logs": "扫描日志",
        "user_management": "用户管理"
    }

    permissions = [
        {"key": key, "label": PERMISSION_LABELS.get(key, key)}
        for key in auth_service.ALL_PERMISSIONS
    ]
    return {"permissions": permissions}


@router.get("/roles", dependencies=[Depends(get_current_admin)])
async def get_all_roles():
    """获取所有可用角色（管理员）"""
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent / "src"))
    from auth import auth_service

    roles = [
        {"key": key, "label": label, "permissions": auth_service.ROLE_DEFAULT_PERMISSIONS.get(key, [])}
        for key, label in auth_service.ROLE_LABELS.items()
    ]
    return {"roles": roles}


@router.delete("/{user_id}", dependencies=[Depends(get_current_admin)])
async def delete_user(user_id: int, request: Request):
    """删除用户（管理员）"""
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent / "src"))
    from auth import auth_service

    # 防止删除自己
    session = request.cookies.get("session")
    if session:
        parts = session.split(":")
        current_user_id = int(parts[0])
        if current_user_id == user_id:
            raise HTTPException(status_code=400, detail="不能删除自己")

    success = auth_service.delete_user(user_id)
    if not success:
        raise HTTPException(status_code=404, detail="用户不存在")

    return {"message": "用户已删除"}

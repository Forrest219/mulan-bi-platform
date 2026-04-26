"""用户管理 API - 仅管理员可访问
"""
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from app.core.constants import VALID_ROLES
from app.core.dependencies import get_current_admin, get_current_user
from services.auth import auth_service

router = APIRouter()


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


class UpdateUserRequest(BaseModel):
    """更新用户基础信息请求"""

    display_name: Optional[str] = None
    email: Optional[str] = None
    role: Optional[str] = None
    is_active: Optional[bool] = None
    group_ids: Optional[list[int]] = None


@router.get("/", dependencies=[Depends(get_current_admin)])
async def get_users(role: Optional[str] = None):
    """获取用户列表（管理员）"""
    users = auth_service.get_users(role=role)
    return {"users": users, "total": len(users)}


@router.post("/", dependencies=[Depends(get_current_admin)])
async def create_user(request: CreateUserRequest):
    """创建用户（管理员）"""
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


@router.get("/{user_id}", dependencies=[Depends(get_current_admin)])
async def get_user(user_id: int):
    """获取指定用户详情（管理员）"""
    user = auth_service.get_user(user_id)
    if not user:
        raise HTTPException(status_code=404, detail="用户不存在")
    return user


@router.put("/{user_id}", dependencies=[Depends(get_current_admin)])
async def update_user(user_id: int, request: UpdateUserRequest, http_request: Request):
    """更新用户基础信息（管理员）"""
    # 处理 role 变更
    if request.role is not None:
        if request.role not in VALID_ROLES:
            raise HTTPException(status_code=400, detail="无效的角色")
        # 防止把自己降级
        current_user = get_current_user(http_request)
        if current_user["id"] == user_id and request.role != "admin":
            raise HTTPException(status_code=400, detail="不能将自己的角色降级")
        auth_service.update_user_role(user_id, request.role)

    # 处理 is_active 变更
    if request.is_active is not None:
        auth_service.toggle_user_active(user_id)

    # 处理 group_ids 变更
    if request.group_ids is not None:
        user = auth_service.get_user(user_id)
        if not user:
            raise HTTPException(status_code=404, detail="用户不存在")
        # 替换组成员
        current_groups = set(auth_service.get_user_groups(user_id))
        desired_groups = set(request.group_ids)
        # 移除不在desired中的
        for g in current_groups:
            if g["id"] not in desired_groups:
                auth_service.remove_user_from_group(user_id, g["id"])
        # 添加在desired中的
        for gid in desired_groups:
            if gid not in [g["id"] for g in current_groups]:
                auth_service.add_user_to_group(user_id, gid)

    # 处理 display_name / email 变更
    if request.display_name is not None or request.email is not None:
        updated = auth_service.update_user_info(
            user_id,
            display_name=request.display_name,
            email=request.email,
        )
        if not updated:
            raise HTTPException(status_code=404, detail="用户不存在或邮箱已被使用")

    return {"user": auth_service.get_user(user_id), "message": "用户信息已更新"}


@router.put("/{user_id}/role", dependencies=[Depends(get_current_admin)])
async def update_user_role(user_id: int, request: UpdateUserRoleRequest, http_request: Request):
    """更新用户角色（管理员）"""
    if request.role not in VALID_ROLES:
        raise HTTPException(status_code=400, detail="无效的角色")

    # 防止把自己降级
    current_user = get_current_user(http_request)
    if current_user["id"] == user_id and request.role != "admin":
        raise HTTPException(status_code=400, detail="不能将自己的角色降级")

    success = auth_service.update_user_role(user_id, request.role)
    if not success:
        raise HTTPException(status_code=404, detail="用户不存在")

    return {"message": "角色更新成功"}


@router.put("/{user_id}/toggle-active", dependencies=[Depends(get_current_admin)])
async def toggle_user_active(user_id: int):
    """切换用户激活状态（管理员）"""
    success = auth_service.toggle_user_active(user_id)
    if not success:
        raise HTTPException(status_code=404, detail="用户不存在")

    return {"message": "状态已切换"}


@router.put("/{user_id}/permissions", dependencies=[Depends(get_current_admin)])
async def update_user_permissions(user_id: int, request: UpdatePermissionsRequest):
    """更新用户权限（管理员）"""
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
    """获取所有可用权限（管理员，共 8 项）"""
    permissions = [
        {"key": key, "label": label}
        for key, label in auth_service.PERMISSION_LABELS.items()
    ]
    return {"permissions": permissions}


@router.get("/roles", dependencies=[Depends(get_current_admin)])
async def get_all_roles():
    """获取所有可用角色（管理员）"""
    roles = [
        {"key": key, "label": label, "permissions": auth_service.ROLE_DEFAULT_PERMISSIONS.get(key, [])}
        for key, label in auth_service.ROLE_LABELS.items()
    ]
    return {"roles": roles}


@router.delete("/{user_id}", dependencies=[Depends(get_current_admin)])
async def delete_user(user_id: int, http_request: Request):
    """删除用户（管理员）"""
    # 防止删除自己
    current_user = get_current_user(http_request)
    if current_user["id"] == user_id:
        raise HTTPException(status_code=400, detail="不能删除自己")

    success = auth_service.delete_user(user_id)
    if not success:
        raise HTTPException(status_code=404, detail="用户不存在")

    return {"message": "用户已删除"}

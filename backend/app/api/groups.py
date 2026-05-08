"""用户组管理 API - 仅管理员可访问
"""
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.core.dependencies import get_current_admin
from app.core.errors import MulanError
from services.auth import auth_service
from services.audit.audit_service import log_action

router = APIRouter(tags=["用户组管理"])


class CreateGroupRequest(BaseModel):
    """创建用户组请求"""

    name: str
    description: Optional[str] = None
    permissions: List[str] = []


class UpdateGroupRequest(BaseModel):
    """更新用户组请求"""

    name: Optional[str] = None
    description: Optional[str] = None


class SetPermissionsRequest(BaseModel):
    """设置组权限请求"""

    permissions: List[str]


class AddMembersRequest(BaseModel):
    """添加成员请求"""

    user_ids: List[int]


@router.get("/", dependencies=[Depends(get_current_admin)])
async def get_groups():
    """获取所有用户组"""
    groups = auth_service.get_groups()
    return {"groups": groups, "total": len(groups)}


@router.get("/{group_id}", dependencies=[Depends(get_current_admin)])
async def get_group(group_id: int):
    """获取用户组详情"""
    group = auth_service.get_group(group_id)
    if not group:
        raise MulanError("AUTH_007", "用户组不存在", 404)

    return group


@router.post("/")
async def create_group(request: CreateGroupRequest, current_user: dict = Depends(get_current_admin)):
    """创建用户组（管理员）"""
    # 验证权限
    for perm in request.permissions:
        if perm not in auth_service.ALL_PERMISSIONS:
            raise MulanError("SYS_004", f"无效的权限: {perm}", 400)

    group = auth_service.create_group(
        name=request.name,
        description=request.description,
        permissions=request.permissions
    )

    if not group:
        raise MulanError("AUTH_005", "用户组名称已存在", 409)

    log_action(current_user["id"], current_user.get("username", ""), "create", "user_group", group["id"],
               after_state={"name": group["name"], "permissions": request.permissions})
    return {"group": group, "message": "用户组创建成功"}


@router.put("/{group_id}")
async def update_group(group_id: int, request: UpdateGroupRequest, current_user: dict = Depends(get_current_admin)):
    """更新用户组（管理员）"""
    success = auth_service.update_group(
        group_id=group_id,
        name=request.name,
        description=request.description
    )

    if not success:
        raise MulanError("AUTH_007", "用户组不存在", 404)

    log_action(current_user["id"], current_user.get("username", ""), "update", "user_group", group_id,
               after_state={"name": request.name, "description": request.description})
    return {"message": "用户组更新成功"}


@router.delete("/{group_id}")
async def delete_group(group_id: int, current_user: dict = Depends(get_current_admin)):
    """删除用户组（管理员）"""
    success = auth_service.delete_group(group_id)
    if not success:
        raise MulanError("AUTH_007", "用户组不存在", 404)

    log_action(current_user["id"], current_user.get("username", ""), "delete", "user_group", group_id)
    return {"message": "用户组已删除"}


@router.get("/{group_id}/members", dependencies=[Depends(get_current_admin)])
async def get_group_members(group_id: int):
    """获取组成员"""
    members = auth_service.get_group_members(group_id)
    return {"members": members, "total": len(members)}


@router.post("/{group_id}/members")
async def add_group_members(group_id: int, request: AddMembersRequest, current_user: dict = Depends(get_current_admin)):
    """添加成员到组（管理员）"""
    for user_id in request.user_ids:
        auth_service.add_user_to_group(user_id, group_id)

    members = auth_service.get_group_members(group_id)
    log_action(current_user["id"], current_user.get("username", ""), "add_members", "user_group", group_id,
               after_state={"user_ids": request.user_ids})
    return {"members": members, "message": "成员已添加"}


@router.delete("/{group_id}/members/{user_id}")
async def remove_group_member(group_id: int, user_id: int, current_user: dict = Depends(get_current_admin)):
    """从组移除成员（管理员）"""
    success = auth_service.remove_user_from_group(user_id, group_id)
    if not success:
        raise MulanError("AUTH_007", "用户或用户组不存在", 404)

    log_action(current_user["id"], current_user.get("username", ""), "remove_member", "user_group", group_id,
               after_state={"removed_user_id": user_id})
    return {"message": "成员已移除"}


@router.get("/{group_id}/permissions", dependencies=[Depends(get_current_admin)])
async def get_group_permissions(group_id: int):
    """获取组权限"""
    permissions = auth_service.get_group_permissions(group_id)
    return {"permissions": permissions}


@router.put("/{group_id}/permissions")
async def set_group_permissions(group_id: int, request: SetPermissionsRequest, current_user: dict = Depends(get_current_admin)):
    """设置组权限（管理员）"""
    # 验证权限
    for perm in request.permissions:
        if perm not in auth_service.ALL_PERMISSIONS:
            raise MulanError("SYS_004", f"无效的权限: {perm}", 400)

    success = auth_service.set_group_permissions(group_id, request.permissions)
    if not success:
        raise MulanError("AUTH_007", "用户组不存在", 404)

    log_action(current_user["id"], current_user.get("username", ""), "set_permissions", "user_group", group_id,
               after_state={"permissions": request.permissions})
    return {"message": "权限已更新"}

"""用户管理 API - 仅管理员可访问
"""
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from app.core.constants import VALID_ROLES
from app.core.dependencies import get_current_admin, get_current_user
from services.audit.audit_service import log_action
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


class AdminResetPasswordRequest(BaseModel):
    """管理员重置用户密码请求"""

    new_password: str
    totp_code: Optional[str] = None


@router.get("/", dependencies=[Depends(get_current_admin)])
async def get_users(role: Optional[str] = None):
    """获取用户列表（管理员）"""
    users = auth_service.get_users(role=role)
    return {"users": users, "total": len(users)}


@router.post("/")
async def create_user(request: CreateUserRequest, current_user: dict = Depends(get_current_admin)):
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

    log_action(current_user["id"], current_user.get("username", ""), "create", "user", user["id"], after_state=user)
    return {"user": user, "message": "用户创建成功"}


@router.get("/{user_id}", dependencies=[Depends(get_current_admin)])
async def get_user(user_id: int):
    """获取指定用户详情（管理员）"""
    user = auth_service.get_user(user_id)
    if not user:
        raise HTTPException(status_code=404, detail="用户不存在")
    return user


@router.put("/{user_id}")
async def update_user(user_id: int, request: UpdateUserRequest, current_user: dict = Depends(get_current_admin)):
    """更新用户基础信息（管理员）"""
    changed = {}

    # 处理 role 变更
    if request.role is not None:
        if request.role not in VALID_ROLES:
            raise HTTPException(status_code=400, detail="无效的角色")
        # 防止把自己降级
        if current_user["id"] == user_id and request.role != "admin":
            raise HTTPException(status_code=400, detail="不能将自己的角色降级")
        auth_service.update_user_role(user_id, request.role)
        changed["role"] = request.role

    # 处理 is_active 变更
    if request.is_active is not None:
        auth_service.toggle_user_active(user_id)
        changed["is_active"] = request.is_active

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
        changed["group_ids"] = request.group_ids

    # 处理 display_name / email 变更
    if request.display_name is not None or request.email is not None:
        updated = auth_service.update_user_info(
            user_id,
            display_name=request.display_name,
            email=request.email,
        )
        if not updated:
            raise HTTPException(status_code=404, detail="用户不存在或邮箱已被使用")
        if request.display_name is not None:
            changed["display_name"] = request.display_name
        if request.email is not None:
            changed["email"] = request.email

    if changed:
        log_action(current_user["id"], current_user.get("username", ""), "update", "user", user_id,
                   after_state=changed)
    return {"user": auth_service.get_user(user_id), "message": "用户信息已更新"}


@router.put("/{user_id}/role")
async def update_user_role(user_id: int, request: UpdateUserRoleRequest, current_user: dict = Depends(get_current_admin)):
    """更新用户角色（管理员）"""
    if request.role not in VALID_ROLES:
        raise HTTPException(status_code=400, detail="无效的角色")

    # 防止把自己降级
    if current_user["id"] == user_id and request.role != "admin":
        raise HTTPException(status_code=400, detail="不能将自己的角色降级")

    success = auth_service.update_user_role(user_id, request.role)
    if not success:
        raise HTTPException(status_code=404, detail="用户不存在")

    log_action(current_user["id"], current_user.get("username", ""), "update_role", "user", user_id,
               after_state={"role": request.role})
    return {"message": "角色更新成功"}


@router.put("/{user_id}/toggle-active")
async def toggle_user_active(user_id: int, current_user: dict = Depends(get_current_admin)):
    """切换用户激活状态（管理员）"""
    success = auth_service.toggle_user_active(user_id)
    if not success:
        raise HTTPException(status_code=404, detail="用户不存在")

    log_action(current_user["id"], current_user.get("username", ""), "toggle_active", "user", user_id)
    return {"message": "状态已切换"}


@router.put("/{user_id}/permissions")
async def update_user_permissions(user_id: int, request: UpdatePermissionsRequest, current_user: dict = Depends(get_current_admin)):
    """更新用户权限（管理员）"""
    # 验证权限
    for perm in request.permissions:
        if perm not in auth_service.ALL_PERMISSIONS:
            raise HTTPException(status_code=400, detail=f"无效的权限: {perm}")

    success = auth_service.update_user_permissions(user_id, request.permissions)
    if not success:
        raise HTTPException(status_code=404, detail="用户不存在")

    log_action(current_user["id"], current_user.get("username", ""), "update_permissions", "user", user_id,
               after_state={"permissions": request.permissions})
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

    log_action(current_user["id"], current_user.get("username", ""), "delete", "user", user_id)
    return {"message": "用户已删除"}


@router.post("/{user_id}/reset-password")
async def admin_reset_password(user_id: int, request: AdminResetPasswordRequest, http_request: Request, current_user: dict = Depends(get_current_admin)):
    """管理员重置用户密码"""
    target_user = auth_service.get_user(user_id)
    if not target_user:
        raise HTTPException(status_code=404, detail="用户不存在")

    # 安全门控：Admin 重置另一 Admin 的密码需要 TOTP 二次验证
    if target_user["role"] == "admin" and target_user["id"] != current_user["id"]:
        if not request.totp_code:
            raise HTTPException(status_code=403, detail="重置管理员密码需要提供您的 TOTP 验证码")
        current_user_detail = auth_service.get_user(current_user["id"])
        if not current_user_detail or not current_user_detail.get("mfa_enabled"):
            raise HTTPException(status_code=403, detail="重置管理员密码需要先为您的账户启用 MFA（两步验证）")
        if not auth_service.verify_mfa_code(current_user["id"], request.totp_code):
            raise HTTPException(status_code=403, detail="TOTP 验证码不正确，请重试")

    success, message = auth_service.admin_reset_password(user_id, request.new_password)
    if not success:
        raise HTTPException(status_code=400, detail=message)
    log_action(current_user["id"], current_user.get("username", ""), "reset_password", "user", user_id)
    return {"message": message}

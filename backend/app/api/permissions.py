"""权限配置 API - 仅管理员可访问
"""
from datetime import datetime, timedelta
from typing import Optional, List

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel

from app.core.database import get_db
from app.core.dependencies import get_current_admin, get_current_user
from services.auth import auth_service
from services.auth.models import SharedResourcePermission, User, UserGroup
from sqlalchemy.orm import Session

router = APIRouter(tags=["权限配置"])


# ──────────────────────────────────────────────────────────────
# Pydantic 请求/响应模型
# ──────────────────────────────────────────────────────────────

class GrantPermissionRequest(BaseModel):
    """授予共享权限请求"""
    grantee_type: str  # 'user' or 'group'
    grantee_id: int
    resource_type: str  # 'semantic_table', 'datasource', 'workbook'
    resource_id: str
    resource_name: str
    permission_level: str = "read"  # read/write/admin
    expires_at: Optional[str] = None  # ISO8601 string, null = never


class BatchRevokeRequest(BaseModel):
    """批量撤销权限请求"""
    permission_ids: List[int]


# ──────────────────────────────────────────────────────────────
# RBAC 权限（原有端点）
# ──────────────────────────────────────────────────────────────

@router.get("/", dependencies=[Depends(get_current_admin)])
async def get_all_permissions():
    """获取所有可用权限定义"""
    permissions = auth_service.get_all_available_permissions()
    return {"permissions": permissions}


@router.get("/users/{user_id}", dependencies=[Depends(get_current_admin)])
async def get_user_permissions(user_id: int):
    """获取用户的完整权限（个人+组继承）"""
    perms = auth_service.get_user_permissions_with_groups(user_id)
    return perms


@router.get("/users", dependencies=[Depends(get_current_admin)])
async def get_users_with_tags():
    """获取所有用户（带标签）"""
    users = auth_service.get_users_with_tags()
    return {"users": users}


@router.get("/groups", dependencies=[Depends(get_current_admin)])
async def get_groups_with_permissions():
    """获取所有用户组（带权限）"""
    groups = auth_service.get_groups()
    result = []
    for group in groups:
        group_id = group["id"]
        perms = auth_service.get_group_permissions(group_id)
        group["permissions"] = perms
        result.append(group)

    return {"groups": result}


# ──────────────────────────────────────────────────────────────
# 共享资源权限（Spec 11 §4.2）
# ──────────────────────────────────────────────────────────────

@router.get("/shared", dependencies=[Depends(get_current_admin)])
async def get_shared_permissions(
    request: Request,
    filter_by_user: Optional[int] = Query(None, description="按被授权用户 ID 过滤"),
    filter_by_group: Optional[int] = Query(None, description="按被授权用户组 ID 过滤"),
    db: Session = Depends(get_db),
):
    """
    获取共享权限列表（Spec 11 §4.2）
    
    支持按 user 或 group 维度过滤返回共享的语义表/datasource 权限列表。
    """
    query = db.query(SharedResourcePermission)

    if filter_by_user is not None:
        query = query.filter(
            SharedResourcePermission.grantee_type == "user",
            SharedResourcePermission.grantee_id == filter_by_user
        )
    elif filter_by_group is not None:
        query = query.filter(
            SharedResourcePermission.grantee_type == "group",
            SharedResourcePermission.grantee_id == filter_by_group
        )

    permissions = query.order_by(SharedResourcePermission.granted_at.desc()).all()

    # 填充 grantee_name 和 granted_by_name
    user_ids = set()
    group_ids = set()
    granted_by_ids = set()
    for p in permissions:
        if p.grantee_type == "user":
            user_ids.add(p.grantee_id)
        else:
            group_ids.add(p.grantee_id)
        granted_by_ids.add(p.granted_by)

    # 批量查询用户
    users_map = {}
    if user_ids:
        users = db.query(User).filter(User.id.in_(user_ids)).all()
        for u in users:
            users_map[u.id] = u.display_name or u.username

    # 批量查询组
    groups_map = {}
    if group_ids:
        groups = db.query(UserGroup).filter(UserGroup.id.in_(group_ids)).all()
        for g in groups:
            groups_map[g.id] = g.name

    # 批量查询授权人
    grantors_map = {}
    if granted_by_ids:
        grantors = db.query(User).filter(User.id.in_(granted_by_ids)).all()
        for u in grantors:
            grantors_map[u.id] = u.display_name or u.username

    result = []
    for p in permissions:
        p_dict = p.to_dict()
        if p.grantee_type == "user":
            p_dict["grantee_name"] = users_map.get(p.grantee_id, f"<用户 {p.grantee_id}>")
        else:
            p_dict["grantee_name"] = groups_map.get(p.grantee_id, f"<组 {p.grantee_id}>")
        p_dict["granted_by_name"] = grantors_map.get(p.granted_by, f"<用户 {p.granted_by}>")
        result.append(p_dict)

    return {"permissions": result, "total": len(result)}


@router.post("/shared", dependencies=[Depends(get_current_admin)])
async def grant_shared_permission(
    req: GrantPermissionRequest,
    http_request: Request,
    db: Session = Depends(get_db),
):
    """
    授予共享权限（Spec 11 §4.2）
    
    将资源（语义表/datasource）共享给指定用户或组。
    """
    if req.grantee_type not in ("user", "group"):
        raise HTTPException(status_code=400, detail="grantee_type 必须是 'user' 或 'group'")
    if req.permission_level not in ("read", "write", "admin"):
        raise HTTPException(status_code=400, detail="permission_level 必须是 'read', 'write' 或 'admin'")
    if req.resource_type not in ("semantic_table", "datasource", "workbook", "dashboard"):
        raise HTTPException(status_code=400, detail="无效的 resource_type")

    # 验证 grantee 存在
    if req.grantee_type == "user":
        grantee = db.query(User).filter(User.id == req.grantee_id).first()
        if not grantee:
            raise HTTPException(status_code=404, detail="指定的用户不存在")
    else:
        grantee = db.query(UserGroup).filter(UserGroup.id == req.grantee_id).first()
        if not grantee:
            raise HTTPException(status_code=404, detail="指定的用户组不存在")

    # 解析过期时间
    expires_at = None
    if req.expires_at:
        try:
            expires_at = datetime.fromisoformat(req.expires_at.replace("Z", "+00:00"))
        except ValueError:
            raise HTTPException(status_code=400, detail="expires_at 必须是有效的 ISO8601 格式")

    current_user = get_current_user(http_request, db)

    perm = SharedResourcePermission(
        grantee_type=req.grantee_type,
        grantee_id=req.grantee_id,
        resource_type=req.resource_type,
        resource_id=req.resource_id,
        resource_name=req.resource_name,
        permission_level=req.permission_level,
        granted_by=current_user["id"],
        expires_at=expires_at,
    )
    db.add(perm)
    db.commit()
    db.refresh(perm)

    p_dict = perm.to_dict()
    p_dict["grantee_name"] = grantee.display_name if req.grantee_type == "user" else grantee.name
    p_dict["granted_by_name"] = current_user.get("display_name") or current_user.get("username", "?")

    return {"permission": p_dict, "message": "权限授予成功"}


@router.delete("/shared/batch", dependencies=[Depends(get_current_admin)])
async def batch_revoke_shared_permissions(
    req: BatchRevokeRequest,
    db: Session = Depends(get_db),
):
    """
    批量撤销共享权限（Spec 11 §4.2）
    
    批量删除指定的共享权限记录。
    """
    if not req.permission_ids:
        raise HTTPException(status_code=400, detail="permission_ids 不能为空")

    deleted = db.query(SharedResourcePermission).filter(
        SharedResourcePermission.id.in_(req.permission_ids)
    ).delete(synchronize_session=False)
    db.commit()

    return {"deleted": deleted, "message": f"已撤销 {deleted} 条权限"}

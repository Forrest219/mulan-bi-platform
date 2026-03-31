"""
用户组管理 API - 仅管理员可访问
"""
from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from typing import Optional, List

from app.core.dependencies import get_current_admin

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
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent / "src"))
    from auth import auth_service

    groups = auth_service.get_groups()
    return {"groups": groups, "total": len(groups)}


@router.get("/{group_id}", dependencies=[Depends(get_current_admin)])
async def get_group(group_id: int):
    """获取用户组详情"""
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent / "src"))
    from auth import auth_service

    group = auth_service.get_group(group_id)
    if not group:
        raise HTTPException(status_code=404, detail="用户组不存在")

    return group


@router.post("/", dependencies=[Depends(get_current_admin)])
async def create_group(request: CreateGroupRequest):
    """创建用户组（管理员）"""
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent / "src"))
    from auth import auth_service

    # 验证权限
    for perm in request.permissions:
        if perm not in auth_service.ALL_PERMISSIONS:
            raise HTTPException(status_code=400, detail=f"无效的权限: {perm}")

    group = auth_service.create_group(
        name=request.name,
        description=request.description,
        permissions=request.permissions
    )

    if not group:
        raise HTTPException(status_code=400, detail="用户组名称已存在")

    return {"group": group, "message": "用户组创建成功"}


@router.put("/{group_id}", dependencies=[Depends(get_current_admin)])
async def update_group(group_id: int, request: UpdateGroupRequest):
    """更新用户组（管理员）"""
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent / "src"))
    from auth import auth_service

    success = auth_service.update_group(
        group_id=group_id,
        name=request.name,
        description=request.description
    )

    if not success:
        raise HTTPException(status_code=404, detail="用户组不存在")

    return {"message": "用户组更新成功"}


@router.delete("/{group_id}", dependencies=[Depends(get_current_admin)])
async def delete_group(group_id: int):
    """删除用户组（管理员）"""
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent / "src"))
    from auth import auth_service

    success = auth_service.delete_group(group_id)
    if not success:
        raise HTTPException(status_code=404, detail="用户组不存在")

    return {"message": "用户组已删除"}


@router.get("/{group_id}/members", dependencies=[Depends(get_current_admin)])
async def get_group_members(group_id: int):
    """获取组成员"""
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent / "src"))
    from auth import auth_service

    members = auth_service.get_group_members(group_id)
    return {"members": members, "total": len(members)}


@router.post("/{group_id}/members", dependencies=[Depends(get_current_admin)])
async def add_group_members(group_id: int, request: AddMembersRequest):
    """添加成员到组（管理员）"""
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent / "src"))
    from auth import auth_service

    for user_id in request.user_ids:
        auth_service.add_user_to_group(user_id, group_id)

    members = auth_service.get_group_members(group_id)
    return {"members": members, "message": "成员已添加"}


@router.delete("/{group_id}/members/{user_id}", dependencies=[Depends(get_current_admin)])
async def remove_group_member(group_id: int, user_id: int):
    """从组移除成员（管理员）"""
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent / "src"))
    from auth import auth_service

    success = auth_service.remove_user_from_group(user_id, group_id)
    if not success:
        raise HTTPException(status_code=404, detail="用户或用户组不存在")

    return {"message": "成员已移除"}


@router.get("/{group_id}/permissions", dependencies=[Depends(get_current_admin)])
async def get_group_permissions(group_id: int):
    """获取组权限"""
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent / "src"))
    from auth import auth_service

    permissions = auth_service.get_group_permissions(group_id)
    return {"permissions": permissions}


@router.put("/{group_id}/permissions", dependencies=[Depends(get_current_admin)])
async def set_group_permissions(group_id: int, request: SetPermissionsRequest):
    """设置组权限（管理员）"""
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent / "src"))
    from auth import auth_service

    # 验证权限
    for perm in request.permissions:
        if perm not in auth_service.ALL_PERMISSIONS:
            raise HTTPException(status_code=400, detail=f"无效的权限: {perm}")

    success = auth_service.set_group_permissions(group_id, request.permissions)
    if not success:
        raise HTTPException(status_code=404, detail="用户组不存在")

    return {"message": "权限已更新"}

"""
需求管理 API
"""
from pydantic import BaseModel
from fastapi import APIRouter, HTTPException, Request
from typing import Optional, List
import os
import jwt

# 导入需求模块
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent / "src"))

from requirements import requirement_service

router = APIRouter()

# JWT 验签
_JWT_SECRET = os.environ.get("SESSION_SECRET")
_JWT_ALGORITHM = "HS256"


def _decode_session_token(token: str):
    """验证并解码 session token"""
    try:
        payload = jwt.decode(token, _JWT_SECRET, algorithms=[_JWT_ALGORITHM])
        return {"id": int(payload["sub"]), "username": payload["username"], "role": payload["role"]}
    except jwt.InvalidTokenError:
        return None


def get_current_user(request: Request) -> dict:
    """获取当前登录用户"""
    token = request.cookies.get("session")
    if not token:
        raise HTTPException(status_code=401, detail="未登录")
    user_info = _decode_session_token(token)
    if not user_info:
        raise HTTPException(status_code=401, detail="无效的会话")
    return user_info


class CreateRequirementRequest(BaseModel):
    """创建需求请求"""
    title: str
    what_to_do: str
    requirement_type: str = "ddl_change"
    why_to_do: Optional[str] = None
    impact_scope: Optional[str] = None
    priority: str = "medium"
    related_tables: Optional[str] = None
    applicant: Optional[str] = None
    assignee: Optional[str] = None


class Requirement(BaseModel):
    """需求"""
    id: int
    title: str
    requirement_type: str
    what_to_do: str
    why_to_do: Optional[str]
    impact_scope: Optional[str]
    status: str
    priority: str
    related_tables: Optional[str]
    applicant: Optional[str]
    assignee: Optional[str]
    create_time: str


@router.post("/", response_model=dict)
async def create_requirement(req: CreateRequirementRequest, request: Request):
    """创建需求"""
    get_current_user(request)
    req_id = requirement_service.create_requirement(
        title=req.title,
        what_to_do=req.what_to_do,
        requirement_type=req.requirement_type,
        why_to_do=req.why_to_do,
        impact_scope=req.impact_scope,
        priority=req.priority,
        related_tables=req.related_tables,
        applicant=req.applicant,
        assignee=req.assignee
    )
    return {"id": req_id, "message": "需求创建成功"}


@router.get("/", response_model=dict)
async def get_requirements(
    request: Request,
    limit: int = 100,
    status: Optional[str] = None,
    requirement_type: Optional[str] = None,
    priority: Optional[str] = None
):
    """获取需求列表"""
    get_current_user(request)
    requirements = requirement_service.get_requirements(
        limit=limit,
        status=status,
        requirement_type=requirement_type,
        priority=priority
    )
    return {"requirements": requirements, "total": len(requirements)}


@router.get("/statistics")
async def get_statistics(request: Request):
    """获取统计数据"""
    get_current_user(request)
    stats = requirement_service.get_statistics()
    return stats


@router.post("/{req_id}/approve")
async def approve_requirement(req_id: int, request: Request, approver: str = "admin", comment: Optional[str] = None):
    """审批需求"""
    get_current_user(request)
    success = requirement_service.approve_requirement(req_id, approver=approver, comment=comment, approved=True)
    return {"success": success, "message": "已通过审批" if success else "需求不存在"}


@router.post("/{req_id}/reject")
async def reject_requirement(req_id: int, request: Request, approver: str = "admin", comment: Optional[str] = None):
    """拒绝需求"""
    get_current_user(request)
    success = requirement_service.approve_requirement(req_id, approver=approver, comment=comment, approved=False)
    return {"success": success, "message": "已拒绝" if success else "需求不存在"}


@router.post("/{req_id}/done")
async def mark_done(req_id: int, request: Request):
    """标记完成"""
    get_current_user(request)
    success = requirement_service.mark_as_done(req_id)
    return {"success": success, "message": "已标记完成" if success else "需求不存在"}


@router.delete("/{req_id}")
async def delete_requirement(req_id: int, request: Request):
    """删除需求"""
    get_current_user(request)
    success = requirement_service.delete_requirement(req_id)
    return {"success": success, "message": "已删除" if success else "需求不存在"}

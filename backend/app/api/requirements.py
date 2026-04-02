"""
需求管理 API
"""
from pydantic import BaseModel
from fastapi import APIRouter, HTTPException, Request
from typing import Optional

from services.requirements import requirement_service
from app.core.dependencies import get_current_user, require_roles

router = APIRouter()


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
    limit: int = 100,  # max 1000
    status: Optional[str] = None,
    requirement_type: Optional[str] = None,
    priority: Optional[str] = None
):
    """获取需求列表"""
    get_current_user(request)
    limit = min(limit, 1000)
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
async def approve_requirement(req_id: int, request: Request, comment: Optional[str] = None):
    """审批需求"""
    user = require_roles(request, ["admin", "data_admin"])
    approver = user["username"]
    success = requirement_service.approve_requirement(req_id, approver=approver, comment=comment, approved=True)
    if not success:
        raise HTTPException(status_code=404, detail="需求不存在")
    return {"message": "已通过审批"}


@router.post("/{req_id}/reject")
async def reject_requirement(req_id: int, request: Request, comment: Optional[str] = None):
    """拒绝需求"""
    user = require_roles(request, ["admin", "data_admin"])
    approver = user["username"]
    success = requirement_service.approve_requirement(req_id, approver=approver, comment=comment, approved=False)
    if not success:
        raise HTTPException(status_code=404, detail="需求不存在")
    return {"message": "已拒绝"}


@router.post("/{req_id}/done")
async def mark_done(req_id: int, request: Request):
    """标记完成"""
    require_roles(request, ["admin", "data_admin"])
    success = requirement_service.mark_as_done(req_id)
    if not success:
        raise HTTPException(status_code=404, detail="需求不存在")
    return {"message": "已标记完成"}


@router.delete("/{req_id}")
async def delete_requirement(req_id: int, request: Request):
    """删除需求"""
    require_roles(request, ["admin", "data_admin"])
    success = requirement_service.delete_requirement(req_id)
    if not success:
        raise HTTPException(status_code=404, detail="需求不存在")
    return {"message": "已删除"}

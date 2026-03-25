"""
需求管理 API
"""
from pydantic import BaseModel
from fastapi import APIRouter
from typing import Optional, List

# 导入需求模块
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent / "src"))

from requirements import requirement_service

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
async def create_requirement(request: CreateRequirementRequest):
    """创建需求"""
    req_id = requirement_service.create_requirement(
        title=request.title,
        what_to_do=request.what_to_do,
        requirement_type=request.requirement_type,
        why_to_do=request.why_to_do,
        impact_scope=request.impact_scope,
        priority=request.priority,
        related_tables=request.related_tables,
        applicant=request.applicant,
        assignee=request.assignee
    )
    return {"id": req_id, "message": "需求创建成功"}


@router.get("/", response_model=dict)
async def get_requirements(
    limit: int = 100,
    status: Optional[str] = None,
    requirement_type: Optional[str] = None,
    priority: Optional[str] = None
):
    """获取需求列表"""
    requirements = requirement_service.get_requirements(
        limit=limit,
        status=status,
        requirement_type=requirement_type,
        priority=priority
    )
    return {"requirements": requirements, "total": len(requirements)}


@router.get("/statistics")
async def get_statistics():
    """获取统计数据"""
    stats = requirement_service.get_statistics()
    return stats


@router.post("/{req_id}/approve")
async def approve_requirement(req_id: int, approver: str = "admin", comment: Optional[str] = None):
    """审批需求"""
    success = requirement_service.approve_requirement(req_id, approver=approver, comment=comment, approved=True)
    return {"success": success, "message": "已通过审批" if success else "需求不存在"}


@router.post("/{req_id}/reject")
async def reject_requirement(req_id: int, approver: str = "admin", comment: Optional[str] = None):
    """拒绝需求"""
    success = requirement_service.approve_requirement(req_id, approver=approver, comment=comment, approved=False)
    return {"success": success, "message": "已拒绝" if success else "需求不存在"}


@router.post("/{req_id}/done")
async def mark_done(req_id: int):
    """标记完成"""
    success = requirement_service.mark_as_done(req_id)
    return {"success": success, "message": "已标记完成" if success else "需求不存在"}


@router.delete("/{req_id}")
async def delete_requirement(req_id: int):
    """删除需求"""
    success = requirement_service.delete_requirement(req_id)
    return {"success": success, "message": "已删除" if success else "需求不存在"}

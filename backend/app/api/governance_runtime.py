"""Governance Runtime API（Spec 24 P0 — 占位桩）"""
from fastapi import APIRouter, Request
from pydantic import BaseModel

router = APIRouter()


class HealthResponse(BaseModel):
    status: str
    service: str = "governance_runtime"


@router.get("/health")
async def governance_health():
    """Governance Runtime 健康检查（占位桩）"""
    return HealthResponse(status="placeholder", service="governance_runtime")


@router.post("/evaluate")
async def evaluate(request: Request):
    """策略评估（Spec 24 P3 实现）"""
    return {"status": "placeholder", "message": "P3 implementation pending"}


@router.get("/approvals")
async def list_approvals(request: Request):
    """审批列表（Spec 24 P3 实现）"""
    return {"status": "placeholder", "message": "P3 implementation pending"}


@router.post("/approvals/{approval_id}/approve")
async def approve(request: Request, approval_id: str):
    """审批通过（Spec 24 P3 实现）"""
    return {"status": "placeholder", "message": "P3 implementation pending", "approval_id": approval_id}


@router.post("/approvals/{approval_id}/reject")
async def reject(request: Request, approval_id: str):
    """审批拒绝（Spec 24 P3 实现）"""
    return {"status": "placeholder", "message": "P3 implementation pending", "approval_id": approval_id}

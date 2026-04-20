"""Audit Runtime API（Spec 24 P0 — 占位桩）"""
from fastapi import APIRouter, Request
from pydantic import BaseModel

router = APIRouter()


class HealthResponse(BaseModel):
    status: str
    service: str = "audit_runtime"


@router.get("/health")
async def audit_health():
    """Audit Runtime 健康检查（占位桩）"""
    return HealthResponse(status="placeholder", service="audit_runtime")


@router.get("/events")
async def list_events(request: Request):
    """审计事件查询（Spec 24 P3 实现）"""
    return {"status": "placeholder", "message": "P3 implementation pending"}


@router.get("/traces/{trace_id}")
async def get_trace(request: Request, trace_id: str):
    """Trace 详情查询（Spec 24 P3 实现）"""
    return {"status": "placeholder", "message": "P3 implementation pending", "trace_id": trace_id}

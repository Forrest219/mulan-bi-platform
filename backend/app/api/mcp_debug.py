"""MCP Debugger API — Phase 1

提供给 admin / data_admin 角色使用的 MCP 工具调试接口。

端点：
  POST /api/mcp-debug/call   — 调用 MCP 工具并记录日志
  GET  /api/mcp-debug/logs   — 查询调试日志（分页 + 过滤）
"""
import logging
import time
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel
from sqlalchemy import Column, DateTime, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Session

from app.core.database import Base, get_db, sa_func
from app.core.dependencies import require_roles

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/mcp-debug", tags=["mcp-debug"])


# ── SQLAlchemy Model ──────────────────────────────────────────────────────────

class McpDebugLog(Base):
    """MCP 调试调用日志"""
    __tablename__ = "mcp_debug_logs"

    id             = Column(Integer, primary_key=True, autoincrement=True)
    user_id        = Column(Integer, nullable=False)
    username       = Column(String(64), nullable=False)
    tool_name      = Column(String(128), nullable=False)
    arguments_json = Column(JSONB, nullable=True)
    status         = Column(String(16), nullable=False)   # 'success' / 'error'
    result_summary = Column(Text, nullable=True)
    error_message  = Column(Text, nullable=True)
    duration_ms    = Column(Integer, nullable=True)
    created_at     = Column(DateTime, nullable=False, server_default=sa_func.now())

    def to_dict(self) -> dict:
        return {
            "id":             self.id,
            "user_id":        self.user_id,
            "username":       self.username,
            "tool_name":      self.tool_name,
            "arguments_json": self.arguments_json,
            "status":         self.status,
            "result_summary": self.result_summary,
            "error_message":  self.error_message,
            "duration_ms":    self.duration_ms,
            "created_at":     self.created_at.strftime("%Y-%m-%d %H:%M:%S") if self.created_at else None,
        }


# ── Pydantic Schemas ──────────────────────────────────────────────────────────

class McpDebugCallRequest(BaseModel):
    tool_name: str
    arguments: dict = {}
    server_id: Optional[int] = None


class McpDebugCallResponse(BaseModel):
    tool_name: str
    result: dict
    status: str       # 'success' / 'error'
    duration_ms: int
    log_id: int


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.post("/call", response_model=McpDebugCallResponse)
async def call_mcp_tool(
    req: McpDebugCallRequest,
    current_user: dict = Depends(require_roles(["admin", "data_admin"])),
    db: Session = Depends(get_db),
):
    """调用指定 MCP 工具，并将结果写入调试日志。"""

    # 延迟导入，避免循环依赖
    from app.api.tableau_mcp import _process_mcp_body

    mcp_body = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/call",
        "params": {
            "name": req.tool_name,
            "arguments": req.arguments,
        },
    }

    start_ms = time.monotonic()
    error: Optional[Exception] = None
    result: Optional[dict] = None

    try:
        result = await _process_mcp_body(mcp_body, server_id=req.server_id)
    except Exception as exc:
        error = exc
        logger.warning("MCP tool call failed: %s — %s", req.tool_name, exc)

    duration_ms = int((time.monotonic() - start_ms) * 1000)
    status = "error" if error or (result and "error" in result) else "success"

    # 写日志
    log = McpDebugLog(
        user_id=current_user["id"],
        username=current_user["username"],
        tool_name=req.tool_name,
        arguments_json=req.arguments,
        status=status,
        result_summary=str(result)[:200] if result else None,
        error_message=str(error)[:500] if error else (
            str(result.get("error"))[:500] if result and "error" in result else None
        ),
        duration_ms=duration_ms,
    )
    db.add(log)
    db.commit()
    db.refresh(log)

    if error:
        raise HTTPException(status_code=502, detail=f"MCP 工具调用失败: {error}")

    return McpDebugCallResponse(
        tool_name=req.tool_name,
        result=result or {},
        status=status,
        duration_ms=duration_ms,
        log_id=log.id,
    )


@router.get("/logs")
async def list_mcp_debug_logs(
    current_user: dict = Depends(require_roles(["admin", "data_admin"])),
    tool_name: Optional[str] = Query(None, description="按工具名过滤"),
    status: Optional[str] = Query(None, description="按状态过滤：success / error"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
):
    """查询 MCP 调试日志，支持按工具名和状态过滤。"""

    query = db.query(McpDebugLog)
    if tool_name:
        query = query.filter(McpDebugLog.tool_name.ilike(f"%{tool_name}%"))
    if status:
        query = query.filter(McpDebugLog.status == status)

    total = query.count()
    logs = (
        query.order_by(McpDebugLog.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )

    return {
        "logs": [log.to_dict() for log in logs],
        "total": total,
        "page": page,
        "page_size": page_size,
        "pages": (total + page_size - 1) // page_size,
    }

"""MCP 配置管理 API"""

import json
import logging
import re
from typing import Optional
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy.exc import IntegrityError

from app.core.database import SessionLocal
from app.core.dependencies import get_current_admin
from services.mcp.models import McpServer
from services.llm.service import llm_service

logger = logging.getLogger(__name__)

router = APIRouter()

MCP_TYPE_VALUES = {"tableau", "starrocks"}


class McpServerCreateRequest(BaseModel):
    name: str
    type: str
    server_url: str
    description: Optional[str] = None
    is_active: bool = True
    credentials: Optional[dict] = None


class McpServerUpdateRequest(BaseModel):
    name: Optional[str] = None
    type: Optional[str] = None
    server_url: Optional[str] = None
    description: Optional[str] = None
    is_active: Optional[bool] = None
    credentials: Optional[dict] = None


_PARSE_SYSTEM_PROMPT = """你是 MCP 配置解析助手。用户会粘贴任意格式的 MCP server 配置（JSON、.env、README、自然语言）。
请提取以下字段并以 JSON 返回，不存在的字段返回 null：
{
  "name": "配置名称",
  "type": "tableau 或 starrocks",
  "server_url": "MCP 进程的 HTTP 地址",
  "credentials": {
    // tableau: tableau_server, site_name, pat_name, pat_value
    // starrocks: host, port, user, password, database
  },
  "description": "可选描述"
}
只返回 JSON，不要解释。"""


def _strip_code_fence(text: str) -> str:
    """去除 LLM 输出中可能包裹的 markdown code fence"""
    text = text.strip()
    # 匹配 ```json ... ``` 或 ``` ... ```
    match = re.match(r"^```(?:json)?\s*([\s\S]*?)```\s*$", text, re.IGNORECASE)
    if match:
        return match.group(1).strip()
    return text


@router.post("/parse")
async def parse_mcp_config(body: dict, request: Request):
    """AI 解析任意格式的 MCP 配置文本，返回结构化字段"""
    get_current_admin(request)
    raw_text = body.get("text", "").strip()
    if not raw_text:
        raise HTTPException(status_code=400, detail="text is required")

    result = await llm_service.complete_with_temp(
        prompt=raw_text,
        system=_PARSE_SYSTEM_PROMPT,
        timeout=30,
        temperature=0.0,
        purpose="default",
    )

    if "error" in result:
        logger.warning("MCP parse LLM error: %s", result["error"])
        return {"error": "解析失败，请检查输入内容"}

    try:
        parsed = json.loads(_strip_code_fence(result["content"]))
    except (json.JSONDecodeError, ValueError) as e:
        logger.warning("MCP parse JSON decode error: %s | raw: %s", e, result["content"])
        return {"error": "解析失败，请检查输入内容"}

    return {
        "name": parsed.get("name") or None,
        "type": parsed.get("type") or None,
        "server_url": parsed.get("server_url") or None,
        "credentials": parsed.get("credentials") or {},
        "description": parsed.get("description") or None,
    }


@router.get("/")
async def list_mcp_servers(request: Request):
    """列出所有 MCP 服务器配置，按 created_at DESC"""
    get_current_admin(request)
    db = SessionLocal()
    try:
        records = db.query(McpServer).order_by(McpServer.created_at.desc()).all()
        return [r.to_dict() for r in records]
    finally:
        db.close()


@router.post("/", status_code=201)
async def create_mcp_server(req: McpServerCreateRequest, request: Request):
    """创建 MCP 服务器配置"""
    get_current_admin(request)

    if not req.name.strip():
        raise HTTPException(status_code=422, detail="name 不能为空")
    if req.type not in MCP_TYPE_VALUES:
        raise HTTPException(status_code=422, detail=f"type 必须为 {MCP_TYPE_VALUES} 之一")
    if not req.server_url.startswith("http"):
        raise HTTPException(status_code=422, detail="server_url 必须以 http 开头")

    db = SessionLocal()
    try:
        record = McpServer(
            name=req.name.strip(),
            type=req.type,
            server_url=req.server_url,
            description=req.description,
            is_active=req.is_active,
            credentials=req.credentials,
        )
        db.add(record)
        db.commit()
        db.refresh(record)
        return record.to_dict()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail=f"名称 '{req.name}' 已存在")
    finally:
        db.close()


@router.put("/{id}")
async def update_mcp_server(id: int, req: McpServerUpdateRequest, request: Request):
    """部分更新 MCP 服务器配置"""
    get_current_admin(request)
    db = SessionLocal()
    try:
        record = db.query(McpServer).filter(McpServer.id == id).first()
        if not record:
            raise HTTPException(status_code=404, detail="MCP server not found")

        if req.name is not None:
            if not req.name.strip():
                raise HTTPException(status_code=422, detail="name 不能为空")
            record.name = req.name.strip()
        if req.type is not None:
            if req.type not in MCP_TYPE_VALUES:
                raise HTTPException(status_code=422, detail=f"type 必须为 {MCP_TYPE_VALUES} 之一")
            record.type = req.type
        if req.server_url is not None:
            if not req.server_url.startswith("http"):
                raise HTTPException(status_code=422, detail="server_url 必须以 http 开头")
            record.server_url = req.server_url
        if req.description is not None:
            record.description = req.description
        if req.is_active is not None:
            record.is_active = req.is_active
        if req.credentials is not None:
            record.credentials = req.credentials

        db.commit()
        db.refresh(record)
        return record.to_dict()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="名称已存在")
    finally:
        db.close()


@router.delete("/{id}")
async def delete_mcp_server(id: int, request: Request):
    """删除 MCP 服务器配置"""
    get_current_admin(request)
    db = SessionLocal()
    try:
        record = db.query(McpServer).filter(McpServer.id == id).first()
        if not record:
            raise HTTPException(status_code=404, detail="MCP server not found")
        db.delete(record)
        db.commit()
        return {"ok": True}
    finally:
        db.close()


@router.post("/test-draft")
async def test_mcp_draft(request: Request):
    """新增配置前的连通性探测（不需要先保存）"""
    get_current_admin(request)
    body = await request.json()
    url = body.get("server_url", "").strip()
    if not url:
        raise HTTPException(status_code=400, detail="server_url is required")

    import time as _time
    import httpx as _httpx
    start = _time.monotonic()
    try:
        async with _httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(url)
        latency_ms = int((_time.monotonic() - start) * 1000)
        return {"status": "online", "latency_ms": latency_ms, "http_status": resp.status_code}
    except (_httpx.ConnectError, _httpx.TimeoutException) as e:
        latency_ms = int((_time.monotonic() - start) * 1000)
        return {"status": "offline", "latency_ms": latency_ms, "error": type(e).__name__}


@router.post("/{id}/test")
async def test_mcp_server(id: int, request: Request):
    """HTTP 可达性探测"""
    get_current_admin(request)
    db = SessionLocal()
    try:
        record = db.query(McpServer).filter(McpServer.id == id).first()
        if not record:
            raise HTTPException(status_code=404, detail="MCP server not found")
        url = record.server_url
    finally:
        db.close()

    import time as _time
    import httpx as _httpx
    start = _time.monotonic()
    try:
        async with _httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(url)
        latency_ms = int((_time.monotonic() - start) * 1000)
        return {"status": "online", "latency_ms": latency_ms, "http_status": resp.status_code}
    except (_httpx.ConnectError, _httpx.TimeoutException) as e:
        latency_ms = int((_time.monotonic() - start) * 1000)
        return {"status": "offline", "latency_ms": latency_ms, "error": type(e).__name__}

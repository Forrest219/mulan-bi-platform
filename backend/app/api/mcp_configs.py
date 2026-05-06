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
from services.events import emit_event
from services.events.constants import (
    MCP_SERVER_CHANGED,
    MCP_SERVER_DELETED,
    SOURCE_MODULE_MCP,
)

logger = logging.getLogger(__name__)


def _sync_mcp_to_tableau(mcp_name: str, mcp_server_url: str,
                          credentials: dict, owner_id: int,
                          is_active: bool = True) -> None:
    """Synchronously bridge an MCP server record to tableau_connections."""
    from services.tableau.models import TableauDatabase
    from app.core.crypto import get_tableau_crypto

    creds = credentials or {}
    pat_value = creds.get("pat_value", "")
    if not pat_value:
        logger.warning("Sync bridge: mcp '%s' has no pat_value, skipping", mcp_name)
        return

    crypto = get_tableau_crypto()
    token_encrypted = crypto.encrypt(pat_value)

    tab_db = TableauDatabase()
    conn, created = tab_db.ensure_connection_from_mcp(
        mcp_name=mcp_name,
        server_url=creds.get("tableau_server", mcp_server_url or ""),
        site=creds.get("site_name", ""),
        token_name=creds.get("pat_name", ""),
        token_encrypted=token_encrypted,
        mcp_server_url=mcp_server_url or "",
        owner_id=owner_id,
        is_active=is_active,
    )
    action = "created" if created else "updated"
    logger.info("Sync bridge: %s tableau_connection '%s' (id=%d)", action, mcp_name, conn.id)

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
    user = get_current_admin(request)

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

        if record.type == "tableau":
            try:
                _sync_mcp_to_tableau(
                    mcp_name=record.name,
                    mcp_server_url=record.server_url,
                    credentials=record.credentials,
                    owner_id=user["id"],
                )
            except Exception:
                logger.exception("Sync bridge failed on CREATE for mcp '%s'", record.name)

        return record.to_dict()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail=f"名称 '{req.name}' 已存在")
    finally:
        db.close()


@router.put("/{id}")
async def update_mcp_server(id: int, req: McpServerUpdateRequest, request: Request):
    """部分更新 MCP 服务器配置"""
    user = get_current_admin(request)
    db = SessionLocal()
    try:
        record = db.query(McpServer).filter(McpServer.id == id).first()
        if not record:
            raise HTTPException(status_code=404, detail="MCP server not found")

        old_name = record.name
        old_is_active = record.is_active
        old_credentials = record.credentials

        # 收集变更字段列表（用于反向同步事件）
        fields_changed = []

        if req.name is not None:
            if not req.name.strip():
                raise HTTPException(status_code=422, detail="name 不能为空")
            if record.name != req.name.strip():
                fields_changed.append("name")
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
            if record.is_active != req.is_active:
                fields_changed.append("is_active")
            record.is_active = req.is_active
        if req.credentials is not None:
            # 检查 credentials 中的特定字段是否变更
            old_creds = old_credentials or {}
            new_creds = req.credentials
            if old_creds.get("pat_value") != new_creds.get("pat_value"):
                fields_changed.append("pat_value")
            if old_creds.get("tableau_server") != new_creds.get("tableau_server"):
                fields_changed.append("tableau_server")
            if old_creds.get("site_name") != new_creds.get("site_name"):
                fields_changed.append("site_name")
            if old_creds.get("pat_name") != new_creds.get("pat_name"):
                fields_changed.append("pat_name")
            record.credentials = req.credentials

        # 如果 name 变更，记录 old_name 在快照中
        mcp_snapshot = {
            "id": record.id,
            "name": record.name,
            "old_name": old_name if "name" in fields_changed else None,
            "is_active": record.is_active,
            "credentials": record.credentials,
        }

        db.commit()
        db.refresh(record)

        # 发射 mcp.server.changed 事件（commit 之后）
        if record.type == "tableau" and fields_changed:
            emit_event(
                db=db,
                event_type=MCP_SERVER_CHANGED,
                source_module=SOURCE_MODULE_MCP,
                payload={
                    "mcp_id": record.id,
                    "change_type": "update",
                    "fields_changed": fields_changed,
                    "mcp_name": record.name,
                    "mcp_snapshot": mcp_snapshot,
                },
                actor_id=user["id"],
            )

        if record.type == "tableau":
            try:
                if old_name != record.name:
                    from services.tableau.models import TableauDatabase as _TDB
                    _TDB().deactivate_connection_by_name(old_name)
                _sync_mcp_to_tableau(
                    mcp_name=record.name,
                    mcp_server_url=record.server_url,
                    credentials=record.credentials,
                    owner_id=user["id"],
                    is_active=record.is_active,
                )
            except Exception:
                logger.exception("Sync bridge failed on UPDATE for mcp '%s'", record.name)

        return record.to_dict()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="名称已存在")
    finally:
        db.close()


@router.delete("/{id}")
async def delete_mcp_server(id: int, request: Request):
    """删除 MCP 服务器配置"""
    user = get_current_admin(request)
    db = SessionLocal()
    try:
        record = db.query(McpServer).filter(McpServer.id == id).first()
        if not record:
            raise HTTPException(status_code=404, detail="MCP server not found")

        # 保存删除前快照
        mcp_snapshot = {
            "id": record.id,
            "name": record.name,
            "type": record.type,
            "is_active": record.is_active,
            "credentials": record.credentials,
        }
        mcp_name = record.name
        mcp_type = record.type

        db.delete(record)
        db.commit()

        # 发射 mcp.server.deleted 事件（commit 之后）
        if mcp_type == "tableau":
            emit_event(
                db=db,
                event_type=MCP_SERVER_DELETED,
                source_module=SOURCE_MODULE_MCP,
                payload={
                    "mcp_id": id,
                    "snapshot": mcp_snapshot,
                },
                actor_id=user["id"],
            )

            try:
                from services.tableau.models import TableauDatabase
                tab_db = TableauDatabase()
                tab_db.deactivate_connection_by_name(mcp_name)
                logger.info("Sync bridge: deactivated tableau_connection '%s'", mcp_name)
            except Exception:
                logger.exception("Sync bridge failed on DELETE for mcp '%s'", mcp_name)

        return {"ok": True}
    finally:
        db.close()


async def _test_tableau_pat(credentials: dict, start: float) -> dict:
    """验证 Tableau PAT 凭证有效性，返回测试结果 dict。"""
    import time as _time
    from app.api.tableau_mcp import _tableau_signin

    tableau_server = (credentials.get("tableau_server") or "").rstrip("/")
    pat_name = credentials.get("pat_name") or ""
    pat_value = credentials.get("pat_value") or ""
    site_name = credentials.get("site_name") or ""

    if not (tableau_server and pat_name and pat_value):
        return {"status": "auth_failed", "latency_ms": 0, "error": "凭证不完整，请填写 Tableau Server、PAT 名称和密钥"}

    try:
        _, site_id = await _tableau_signin(tableau_server, pat_name, pat_value, site_name)
        latency_ms = int((_time.monotonic() - start) * 1000)
        return {"status": "online", "latency_ms": latency_ms, "auth": "ok", "site_id": site_id}
    except RuntimeError as e:
        latency_ms = int((_time.monotonic() - start) * 1000)
        return {"status": "auth_failed", "latency_ms": latency_ms, "error": str(e)}
    except Exception:
        latency_ms = int((_time.monotonic() - start) * 1000)
        return {"status": "offline", "latency_ms": latency_ms, "error": "ConnectError"}


async def _test_mcp_endpoint(url: str, start: float) -> dict:
    """Verify a streamable-http MCP endpoint can complete initialize."""
    import time as _time
    import httpx as _httpx
    from services.common.settings import get_tableau_mcp_protocol_version

    endpoint = (url or "").strip()
    if not endpoint:
        return {"status": "offline", "latency_ms": 0, "error": "MCP Endpoint 不能为空"}

    payload = {
        "jsonrpc": "2.0",
        "id": "mcp-config-test",
        "method": "initialize",
        "params": {
            "protocolVersion": get_tableau_mcp_protocol_version(),
            "capabilities": {},
            "clientInfo": {"name": "mulan-bi-config-test", "version": "1.0.0"},
        },
    }
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json, text/event-stream",
        "MCP-Protocol-Version": get_tableau_mcp_protocol_version(),
    }

    try:
        async with _httpx.AsyncClient(timeout=8.0) as client:
            resp = await client.post(endpoint, json=payload, headers=headers)
            latency_ms = int((_time.monotonic() - start) * 1000)
            if resp.status_code >= 400:
                return {
                    "status": "offline",
                    "latency_ms": latency_ms,
                    "endpoint_status": "offline",
                    "endpoint": endpoint,
                    "error": f"MCP Endpoint 返回 HTTP {resp.status_code}",
                }

            session_id = None
            for k, v in resp.headers.items():
                if k.lower() == "mcp-session-id":
                    session_id = v
                    break
            if not session_id:
                try:
                    body = resp.json()
                    session_id = body.get("sessionId") or body.get("session_id")
                except Exception:
                    pass
            if not session_id:
                return {
                    "status": "offline",
                    "latency_ms": latency_ms,
                    "endpoint_status": "invalid",
                    "endpoint": endpoint,
                    "error": "MCP Endpoint 未返回 mcp-session-id，请确认这里不是 Tableau Server URL",
                }

            try:
                await client.delete(endpoint, headers={**headers, "mcp-session-id": session_id})
            except _httpx.HTTPError:
                pass

            return {
                "status": "online",
                "latency_ms": latency_ms,
                "endpoint_status": "online",
                "endpoint": endpoint,
            }
    except _httpx.HTTPError as e:
        latency_ms = int((_time.monotonic() - start) * 1000)
        return {
            "status": "offline",
            "latency_ms": latency_ms,
            "endpoint_status": "offline",
            "endpoint": endpoint,
            "error": type(e).__name__,
        }


@router.post("/test-draft")
async def test_mcp_draft(request: Request):
    """新增配置前的连通性 + PAT 认证探测（不需要先保存）"""
    get_current_admin(request)
    body = await request.json()
    server_type = body.get("type", "")
    url = body.get("server_url", "").strip()
    credentials = body.get("credentials") or {}

    import time as _time
    import httpx as _httpx
    start = _time.monotonic()

    if server_type == "tableau":
        pat_result = await _test_tableau_pat(credentials, start)
        if pat_result["status"] != "online":
            return pat_result
        endpoint_result = await _test_mcp_endpoint(url, start)
        if endpoint_result["status"] != "online":
            return {
                **endpoint_result,
                "auth": "ok",
                "site_id": pat_result.get("site_id"),
                "error": f"Tableau PAT 认证正常，但 {endpoint_result.get('error', 'MCP Endpoint 不可用')}",
            }
        return {
            **endpoint_result,
            "auth": "ok",
            "site_id": pat_result.get("site_id"),
        }

    if not url:
        raise HTTPException(status_code=400, detail="server_url is required")
    try:
        async with _httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(url)
        latency_ms = int((_time.monotonic() - start) * 1000)
        return {"status": "online", "latency_ms": latency_ms, "http_status": resp.status_code}
    except _httpx.HTTPError as e:
        latency_ms = int((_time.monotonic() - start) * 1000)
        return {"status": "offline", "latency_ms": latency_ms, "error": type(e).__name__}


@router.post("/{id}/test")
async def test_mcp_server(id: int, request: Request):
    """连通性 + PAT 认证探测"""
    get_current_admin(request)
    db = SessionLocal()
    try:
        record = db.query(McpServer).filter(McpServer.id == id).first()
        if not record:
            raise HTTPException(status_code=404, detail="MCP server not found")
        server_type = record.type
        credentials = record.credentials or {}
        url = record.server_url
    finally:
        db.close()

    import time as _time
    import httpx as _httpx
    start = _time.monotonic()

    if server_type == "tableau":
        pat_result = await _test_tableau_pat(credentials, start)
        if pat_result["status"] != "online":
            return pat_result
        endpoint_result = await _test_mcp_endpoint(url, start)
        if endpoint_result["status"] != "online":
            return {
                **endpoint_result,
                "auth": "ok",
                "site_id": pat_result.get("site_id"),
                "error": f"Tableau PAT 认证正常，但 {endpoint_result.get('error', 'MCP Endpoint 不可用')}",
            }
        return {
            **endpoint_result,
            "auth": "ok",
            "site_id": pat_result.get("site_id"),
        }

    try:
        async with _httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(url)
        latency_ms = int((_time.monotonic() - start) * 1000)
        return {"status": "online", "latency_ms": latency_ms, "http_status": resp.status_code}
    except _httpx.HTTPError as e:
        latency_ms = int((_time.monotonic() - start) * 1000)
        return {"status": "offline", "latency_ms": latency_ms, "error": type(e).__name__}

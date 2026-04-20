"""NL-to-Query 搜索 API（PRD §14 §6）

Spec 24 P0 改动：
- trace_id 响应头透传：优先继承 X-Trace-ID 请求头，无则生成新的 UUID v4
- task_run_id 可空字段：响应中补充此字段，向后兼容
"""
import logging
from typing import Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.dependencies import get_current_user
from services.capability.audit import InvocationRecord, new_trace_id, write_audit
from services.llm.models import log_nlq_query
from services.common.redis_cache import check_rate_limit
from services.tableau.models import TableauAsset, TableauDatabase
from services.knowledge_base.glossary_service import glossary_service
from services.semantic_maintenance.context_assembler import (
    ContextAssembler,
    sanitize_fields_for_llm,
)
from services.llm.semantic_retriever import recall_fields
from services.llm.nlq_service import (
    NLQError,
    one_pass_llm,
    route_datasource,
    resolve_fields,
    format_response,
    classify_intent,
    classify_meta_intent,
    execute_query,
    is_datasource_sensitivity_blocked,
    MAX_QUERY_LENGTH,
)
from services.tableau.mcp_client import get_tableau_mcp_client

logger = logging.getLogger(__name__)
router = APIRouter()

# META 路径经由后端代理（维护 MCP session），不直连 MCP server
import os as _os
_MCP_PROXY_URL = _os.environ.get("INTERNAL_API_BASE", "http://localhost:8000") + "/tableau-mcp"


class QueryRequest(BaseModel):
    """POST /api/search/query 请求体（PRD §6.2）"""

    question: str
    datasource_luid: Optional[str] = None
    connection_id: Optional[int] = None
    conversation_id: Optional[str] = None
    options: Optional[dict] = None
    use_conversation_context: bool = False  # P2：追问时携带上轮上下文
    task_run_id: Optional[str] = None  # Spec 24 P0：关联 TaskRun（可选）


def _require_role(user, min_role: str) -> None:
    """权限拦截：analyst+"""
    role_rank = {"user": 0, "analyst": 1, "data_admin": 2, "admin": 3}
    user_rank = role_rank.get(user.get("role", "user"), 0)
    min_rank = role_rank.get(min_role, 0)
    if user_rank < min_rank:
        raise HTTPException(status_code=403, detail="权限不足")


def _build_fields_with_types(fields: list) -> str:
    """
    将已 sanitized 的字段列表格式化为 LLM 上下文字符串（Spec 14 v1.1 §5.1 Token 预算管理）。

    注意：本函数假设输入 fields 已经过 sanitize_fields_for_llm 过滤。
    本函数只负责 P0-P5 优先级截断 + Token 预算（ContextAssembler）。
    """
    if not fields:
        return "无可用字段"

    # P0-P5 优先级截断 + Token 预算（ContextAssembler 内部处理）
    assembler = ContextAssembler()
    # build_field_context 默认 max_tokens=MAX_CONTEXT_TOKENS-500=2500
    return assembler.build_field_context(fields)


def _nlq_error_response(code: str, message: str, details: dict = None):
    """NLQ 错误响应"""
    status_map = {"NLQ_003", "NLQ_006", "NLQ_008", "NLQ_009"}
    status_code = 502 if code in status_map else 400
    return HTTPException(
        status_code=status_code,
        detail={
            "code": code,
            "message": message,
            "details": details or {},
        },
    )


def _parse_mcp_resp(resp) -> dict:
    """MCP 响应可能是 SSE (text/event-stream) 或纯 JSON，统一解析成 dict。

    Tableau MCP ≥1.18 在 HTTP 传输模式下返回 SSE 格式：
      event: message
      data: {"result":...,"jsonrpc":"2.0","id":N}
    直接调 resp.json() 会因 'event:' 前缀而 JSONDecodeError。
    """
    import json as _json
    for line in resp.text.splitlines():
        line = line.strip()
        if line.startswith("data:"):
            payload = line[5:].strip()
            if payload and payload != "[DONE]":
                return _json.loads(payload)
    return resp.json()


async def _mcp_list_datasources(
    mcp_base_url: str,
    tableau_server: str,
    site_name: str,
    pat_name: str,
    pat_value: str,
    timeout: float = 30.0,
) -> list:
    """
    直接通过 MCP JSON-RPC 调用 list-datasources 工具（不依赖 TableauConnection 表）。

    用于：当 TableauConnection 为空但 MCP server config 有 credentials 时。
    """
    import httpx
    import json as _json

    protocol_ver = "2025-06-18"
    session_id = "nlq-fallback-session"

    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json, text/event-stream",
        "MCP-Protocol-Version": protocol_ver,
        "MCP-Session-ID": session_id,
    }

    async with httpx.AsyncClient(timeout=timeout) as client:
        # initialize
        await client.post(
            mcp_base_url,
            json={
                "jsonrpc": "2.0", "id": 1, "method": "initialize",
                "params": {
                    "protocolVersion": protocol_ver,
                    "clientInfo": {"name": "nlq-fallback", "version": "1.0"},
                    "serverInfo": {"name": "tableau-mcp", "version": "1.0"},
                }
            },
            headers=headers,
        )

        # notifications/initialized
        await client.post(
            mcp_base_url,
            json={"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}},
            headers=headers,
        )

        # tools/call: list-datasources
        list_resp = await client.post(
            mcp_base_url,
            json={
                "jsonrpc": "2.0", "id": 2, "method": "tools/call",
                "params": {"name": "list-datasources", "arguments": {"limit": 10}}
            },
            headers=headers,
        )
        list_data = _parse_mcp_resp(list_resp)
        if "error" in list_data:
            err = list_data["error"]
            raise RuntimeError(f"MCP list-datasources 错误 [{err.get('code')}]: {err.get('message')}")
        result = list_data.get("result", {})
        content = result.get("content", [])
        text = "".join(c.get("text", "") for c in content if c.get("type") == "text")
        if text:
            list_result = _json.loads(text)
            return list_result.get("datasources", [])
        return []


async def _mcp_get_datasource_metadata(
    mcp_base_url: str,
    datasource_luid: str,
    timeout: float = 30.0,
) -> dict:
    """
    直接通过 MCP JSON-RPC 调用 get-datasource-metadata 工具（不依赖 TableauConnection 表）。
    """
    import httpx
    import json as _json

    protocol_ver = "2025-06-18"
    session_id = "nlq-fallback-session"

    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json, text/event-stream",
        "MCP-Protocol-Version": protocol_ver,
        "MCP-Session-ID": session_id,
    }

    async with httpx.AsyncClient(timeout=timeout) as client:
        # initialize
        await client.post(
            mcp_base_url,
            json={
                "jsonrpc": "2.0", "id": 1, "method": "initialize",
                "params": {
                    "protocolVersion": protocol_ver,
                    "clientInfo": {"name": "nlq-fallback", "version": "1.0"},
                    "serverInfo": {"name": "tableau-mcp", "version": "1.0"},
                }
            },
            headers=headers,
        )

        # notifications/initialized
        await client.post(
            mcp_base_url,
            json={"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}},
            headers=headers,
        )

        # tools/call: get-datasource-metadata
        meta_resp = await client.post(
            mcp_base_url,
            json={
                "jsonrpc": "2.0", "id": 2, "method": "tools/call",
                "params": {"name": "get-datasource-metadata", "arguments": {"datasource_luid": datasource_luid}}
            },
            headers=headers,
        )
        meta_data = _parse_mcp_resp(meta_resp)
        if "error" in meta_data:
            err = meta_data["error"]
            raise RuntimeError(f"MCP get-datasource-metadata 错误 [{err.get('code')}]: {err.get('message')}")
        result = meta_data.get("result", {})
        content = result.get("content", [])
        text = "".join(c.get("text", "") for c in content if c.get("type") == "text")
        if text:
            return _json.loads(text)
        return {}


async def _mcp_list_workbooks(mcp_base_url: str, timeout: float = 30.0) -> list:
    """通过 MCP JSON-RPC 调用 list-workbooks 工具。"""
    import httpx
    import json as _json

    protocol_ver = "2025-06-18"
    session_id = "nlq-fallback-session"
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json, text/event-stream",
        "MCP-Protocol-Version": protocol_ver,
        "MCP-Session-ID": session_id,
    }

    async with httpx.AsyncClient(timeout=timeout) as client:
        await client.post(
            mcp_base_url,
            json={
                "jsonrpc": "2.0", "id": 1, "method": "initialize",
                "params": {
                    "protocolVersion": protocol_ver,
                    "clientInfo": {"name": "nlq-fallback", "version": "1.0"},
                    "serverInfo": {"name": "tableau-mcp", "version": "1.0"},
                }
            },
            headers=headers,
        )
        await client.post(
            mcp_base_url,
            json={"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}},
            headers=headers,
        )
        resp = await client.post(
            mcp_base_url,
            json={
                "jsonrpc": "2.0", "id": 2, "method": "tools/call",
                "params": {"name": "list-workbooks", "arguments": {}}
            },
            headers=headers,
        )
        data = _parse_mcp_resp(resp)
        if "error" in data:
            err = data["error"]
            raise RuntimeError(f"MCP list-workbooks 错误 [{err.get('code')}]: {err.get('message')}")
        result = data.get("result", {})
        content = result.get("content", [])
        text = "".join(c.get("text", "") for c in content if c.get("type") == "text")
        if text:
            return _json.loads(text).get("workbooks", [])
        return []


async def _mcp_get_upstream_tables(mcp_base_url: str, ds_name: str, timeout: float = 30.0) -> list:
    """通过 MCP JSON-RPC 调用 get-datasource-upstream-tables 工具。"""
    import httpx
    import json as _json

    protocol_ver = "2025-06-18"
    session_id = "nlq-fallback-session"
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json, text/event-stream",
        "MCP-Protocol-Version": protocol_ver,
        "MCP-Session-ID": session_id,
    }

    async with httpx.AsyncClient(timeout=timeout) as client:
        await client.post(
            mcp_base_url,
            json={
                "jsonrpc": "2.0", "id": 1, "method": "initialize",
                "params": {
                    "protocolVersion": protocol_ver,
                    "clientInfo": {"name": "nlq-fallback", "version": "1.0"},
                    "serverInfo": {"name": "tableau-mcp", "version": "1.0"},
                }
            },
            headers=headers,
        )
        await client.post(
            mcp_base_url,
            json={"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}},
            headers=headers,
        )
        resp = await client.post(
            mcp_base_url,
            json={
                "jsonrpc": "2.0", "id": 2, "method": "tools/call",
                "params": {"name": "get-datasource-upstream-tables", "arguments": {"datasource_name": ds_name}}
            },
            headers=headers,
        )
        data = _parse_mcp_resp(resp)
        if "error" in data:
            err = data["error"]
            raise RuntimeError(f"MCP get-datasource-upstream-tables 错误 [{err.get('code')}]: {err.get('message')}")
        result = data.get("result", {})
        content = result.get("content", [])
        text = "".join(c.get("text", "") for c in content if c.get("type") == "text")
        if text:
            return _json.loads(text).get("tables", [])
        return []


async def _mcp_get_downstream_workbooks(mcp_base_url: str, ds_name: str, timeout: float = 30.0) -> list:
    """通过 MCP JSON-RPC 调用 get-datasource-downstream-workbooks 工具。"""
    import httpx
    import json as _json

    protocol_ver = "2025-06-18"
    session_id = "nlq-fallback-session"
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json, text/event-stream",
        "MCP-Protocol-Version": protocol_ver,
        "MCP-Session-ID": session_id,
    }

    async with httpx.AsyncClient(timeout=timeout) as client:
        await client.post(
            mcp_base_url,
            json={
                "jsonrpc": "2.0", "id": 1, "method": "initialize",
                "params": {
                    "protocolVersion": protocol_ver,
                    "clientInfo": {"name": "nlq-fallback", "version": "1.0"},
                    "serverInfo": {"name": "tableau-mcp", "version": "1.0"},
                }
            },
            headers=headers,
        )
        await client.post(
            mcp_base_url,
            json={"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}},
            headers=headers,
        )
        resp = await client.post(
            mcp_base_url,
            json={
                "jsonrpc": "2.0", "id": 2, "method": "tools/call",
                "params": {"name": "get-datasource-downstream-workbooks", "arguments": {"datasource_name": ds_name}}
            },
            headers=headers,
        )
        data = _parse_mcp_resp(resp)
        if "error" in data:
            err = data["error"]
            raise RuntimeError(f"MCP get-datasource-downstream-workbooks 错误 [{err.get('code')}]: {err.get('message')}")
        result = data.get("result", {})
        content = result.get("content", [])
        text = "".join(c.get("text", "") for c in content if c.get("type") == "text")
        if text:
            return _json.loads(text).get("workbooks", [])
        return []


def _get_asset_by_luid(datasource_luid: str):
    """通过 datasource_luid 查找 TableauAsset（tableau_id 字段存储 Tableau LUID）"""
    db = TableauDatabase()
    session = db.session
    asset = session.query(TableauAsset).filter(
        TableauAsset.tableau_id == datasource_luid,
        TableauAsset.is_deleted == False,
    ).first()
    session.close()
    return asset


# === META 查询 Handler ===

async def handle_meta_query_all(meta_intent: str, db: Session, user: dict, question: str = "") -> dict:
    """
    META 查询聚合版：connection_id=None 时，跨所有活跃连接汇总结果。
    同时聚合 tableau_connections 表和 mcp_servers 表（type='tableau'）。
    """
    from services.tableau.models import TableauConnection
    from services.mcp.models import McpServer

    # 查 tableau_connections 表
    active_connections = db.query(TableauConnection).filter(
        TableauConnection.is_active == True,
    ).order_by(TableauConnection.id.asc()).all()

    # 同时聚合 mcp_servers 表中 type='tableau' 的活跃记录
    if not active_connections:
        try:
            mcp_tableau = db.query(McpServer).filter(
                McpServer.type == "tableau",
                McpServer.is_active == True,
            ).order_by(McpServer.id.asc()).all()
            if mcp_tableau:
                # 将 McpServer 包装成轻量对象供下游 handler 使用
                class _MqpConn:
                    def __init__(self, m):
                        self.id = 10000 + m.id
                        self.name = m.name
                        self.site = m.server_url
                        self.is_active = True
                active_connections = [_MqpConn(m) for m in mcp_tableau]
        except Exception:
            pass

    if not active_connections:
        return {
            "response_type": "text",
            "content": "当前系统暂无可用的数据连接，请联系管理员添加。",
            "intent": meta_intent,
            "meta": True,
        }

    if meta_intent == "meta_datasource_list":
        return await _handle_meta_datasource_list_all(active_connections, db)
    elif meta_intent == "meta_field_list":
        return await _handle_meta_field_list_all(active_connections, db, question=question)
    elif meta_intent == "meta_asset_count":
        return await _handle_meta_asset_count_all(active_connections, db)
    elif meta_intent == "meta_semantic_quality":
        return await _handle_meta_semantic_quality_all(active_connections, db)
    elif meta_intent == "meta_workbook_count":
        return await _handle_meta_workbook_count(active_connections, db)
    elif meta_intent == "meta_datasource_physical_table":
        return await _handle_meta_physical_table(active_connections, db, question=question)
    elif meta_intent == "meta_datasource_downstream":
        return await _handle_meta_downstream_workbooks(active_connections, db, question=question)
    elif meta_intent == "meta_datasource_new_in_period":
        return await _handle_meta_datasource_new_in_period(active_connections, db, question=question)
    elif meta_intent == "meta_datasource_recently_updated":
        return await _handle_meta_datasource_recently_updated(active_connections, db, question=question)
    elif meta_intent == "meta_datasource_top_by_size":
        return await _handle_meta_datasource_top_by_size(active_connections, db, question=question)
    elif meta_intent == "meta_datasource_incomplete_metadata":
        return await _handle_meta_datasource_incomplete_metadata(active_connections, db)
    elif meta_intent == "meta_datasource_duplicate":
        return await _handle_meta_datasource_duplicates(active_connections, db)
    else:
        return {
            "response_type": "text",
            "content": f"未知的 META 查询类型：{meta_intent}",
        }


async def handle_meta_query(meta_intent: str, connection_id: int, db: Session, user: dict, question: str = "") -> dict:
    """
    处理 META 查询意图，直接查本地 DB 返回结构化文本。
    不走 VizQL One-Pass LLM 流水线。

    Args:
        meta_intent: classify_meta_intent() 返回的意图 key
        connection_id: 用户在 ScopePicker 选中的连接 ID（Q1 业务口径：不 fallback）
        db: SQLAlchemy session（由 Depends(get_db) 注入，与主流程共用）
        user: 当前用户（用于 IDOR 防护：verify_connection_access）
        question: 原始用户问题（用于字段列表意图提取数据源名称）

    Returns:
        符合 PRD §6.2 响应格式的 dict（response_type + content/value 等字段）
    """
    from services.tableau.models import TableauConnection
    from sqlalchemy import or_
    from app.utils.auth import verify_connection_access

    # IDOR 防护：验证用户有权访问该连接
    verify_connection_access(connection_id, user, db)

    if meta_intent == "meta_datasource_list":
        return await _handle_meta_datasource_list(connection_id, db)
    elif meta_intent == "meta_field_list":
        # 单连接下的字段查询，先查本地资产，为空时 fallback MCP
        from services.tableau.models import TableauConnection as _TC
        conn = db.query(_TC).filter(_TC.id == connection_id).first()
        conns = [conn] if conn else []
        return await _handle_meta_field_list_all(conns, db, question=question)
    elif meta_intent == "meta_asset_count":
        return await _handle_meta_asset_count(connection_id, db)
    elif meta_intent == "meta_semantic_quality":
        return await _handle_meta_semantic_quality(connection_id, db)
    else:
        return {
            "response_type": "text",
            "content": f"未知的 META 查询类型：{meta_intent}",
        }


async def _handle_meta_datasource_list(connection_id: int, db: Session) -> dict:
    """
    META handler 1：列出当前连接下的数据源（Q1 业务口径：按 Site 分组展示）。

    - 查询范围 = connection_id 指定的连接，不 fallback
    - 按 Site（connection name）分组展示
    """
    from services.tableau.models import TableauConnection

    assets = db.query(TableauAsset).filter(
        TableauAsset.connection_id == connection_id,
        TableauAsset.asset_type == "datasource",
        TableauAsset.is_deleted == False,
    ).all()

    # 查 connection 名称，用作分组标签
    connection = db.query(TableauConnection).filter(
        TableauConnection.id == connection_id
    ).first()
    site_label = f"{connection.name}（{connection.site}）" if connection else f"连接 {connection_id}"

    if not assets:
        content = f"**{site_label}** 下暂无数据源，请先完成资产同步。"
    else:
        lines = [f"我在 **{site_label}** 中找到 **{len(assets)}** 个数据源："]
        for a in sorted(assets, key=lambda x: x.name):
            lines.append(f"- {a.name}")
        lines.append("\n> 如需了解某个数据源的字段信息，可以直接提问，例如：「管理费用数据源 有什么字段」")
        content = "\n".join(lines)

    return {
        "response_type": "text",
        "content": content,
        "intent": "meta_datasource_list",
        "meta": True,
    }


async def _handle_meta_datasource_list_all(connections: list, db: Session) -> dict:
    """跨所有活跃连接，实时调用 MCP list-datasources 获取数据源列表。"""
    mcp_base_url = _MCP_PROXY_URL
    try:
        ds_list = await _mcp_list_datasources(mcp_base_url, "", "", "", "")
    except Exception as e:
        logger.error("_handle_meta_datasource_list_all: MCP 调用失败: %s", e)
        return {
            "response_type": "text",
            "content": "数据获取暂时异常，请稍后重试或联系管理员。",
            "intent": "meta_datasource_list",
            "meta": True,
        }

    if not ds_list:
        return {
            "response_type": "text",
            "content": "当前 Tableau 中暂无已发布的数据源。",
            "intent": "meta_datasource_list",
            "meta": True,
        }

    total = len(ds_list)
    lines = [f"我在 Tableau 中找到 **{total}** 个数据源："]
    for ds in ds_list:
        name = ds.get("name") or ds.get("contentUrl") or str(ds)
        lines.append(f"- {name}")
    lines.append("\n> 如需了解某个数据源的字段信息，可以直接提问，例如：「管理费用数据源 有什么字段」")

    return {
        "response_type": "text",
        "content": "\n".join(lines),
        "intent": "meta_datasource_list",
        "meta": True,
    }


async def _handle_meta_field_list_all(connections: list, db: Session, question: str = "") -> dict:
    """
    META handler：查询指定数据源的字段列表。
    实时调用 MCP，不依赖本地 DB 缓存。
    """
    mcp_base_url = _MCP_PROXY_URL

    # 1. 通过 MCP 拉全量数据源列表（用于名称匹配）
    try:
        all_ds = await _mcp_list_datasources(mcp_base_url, "", "", "", "")
    except Exception as e:
        logger.error("_handle_meta_field_list: MCP list-datasources 失败: %s", e)
        return {
            "response_type": "text",
            "content": "数据获取暂时异常，请稍后重试或联系管理员。",
            "intent": "meta_field_list",
            "meta": True,
        }

    # 2. 从问题中匹配数据源名称（最长优先匹配）
    matched_ds = None
    if question and all_ds:
        q_lower = question.lower()
        candidates = sorted(all_ds, key=lambda x: len(x.get("name", "")), reverse=True)
        for ds in candidates:
            name = ds.get("name", "")
            if name and name.lower() in q_lower:
                matched_ds = ds
                break

    if not matched_ds:
        if all_ds:
            ds_sample = "、".join(ds.get("name", "") for ds in all_ds[:5])
            hint = f"（例如：{ds_sample}）" if ds_sample else ""
            content = f"请告诉我您想查询哪个数据源的字段，例如：「XX数据源 有什么字段」{hint}"
        else:
            content = "当前 Tableau 中暂无已发布的数据源。"
        return {
            "response_type": "text",
            "content": content,
            "intent": "meta_field_list",
            "meta": True,
        }

    ds_name = matched_ds.get("name", "")
    ds_luid = matched_ds.get("luid", "")

    if not ds_luid:
        return {
            "response_type": "text",
            "content": f"未能获取数据源「{ds_name}」的 LUID，请检查 Tableau 数据源配置。",
            "intent": "meta_field_list",
            "meta": True,
        }

    # 3. 直接通过 MCP 获取字段信息
    try:
        metadata = await _mcp_get_datasource_metadata(mcp_base_url, ds_luid)
    except Exception as e:
        logger.error("_handle_meta_field_list: MCP get-datasource-metadata 失败: %s", e)
        return {
            "response_type": "text",
            "content": f"获取「{ds_name}」字段信息暂时异常，请稍后重试或联系管理员。",
            "intent": "meta_field_list",
            "meta": True,
        }

    # MCP 返回格式：{"datasource": {..., "fields": [...]}}（REST API 格式）
    # 或 GraphQL 格式：{"data": {"publishedDatasources": [{...,"fields":[...]}]}}
    mcp_fields = []
    ds_info = metadata.get("datasource", {})
    if ds_info:
        # REST API 格式（tableau_mcp.py 实现）
        raw_fields = ds_info.get("fields", {})
        if isinstance(raw_fields, dict):
            raw_fields = raw_fields.get("field", [])
        if isinstance(raw_fields, list):
            mcp_fields = raw_fields
    else:
        # GraphQL 格式 fallback
        gql_ds = metadata.get("data", {}).get("publishedDatasources", [{}])
        if gql_ds:
            mcp_fields = gql_ds[0].get("fields", [])

    if not mcp_fields:
        content = (
            f"「{ds_name}」数据源暂无可用字段信息。\n"
            f"该数据源已存在（LUID: `{ds_luid}`），"
            f"建议完成资产同步后再查询字段详情。"
        )
    else:
        lines = [f"**{ds_name}** 共有 **{len(mcp_fields)}** 个字段："]
        for f in mcp_fields:
            fname = f.get("name") or f.get("fieldCaption") or str(f)
            ftype = f.get("dataType") or f.get("type") or ""
            frole = f.get("role") or ""
            role_label = "度量" if frole.lower() == "measure" else ("维度" if frole else "")
            meta_parts = [p for p in [role_label, ftype] if p]
            suffix = f"（{'、'.join(meta_parts)}）" if meta_parts else ""
            lines.append(f"- {fname}{suffix}")
        content = "\n".join(lines)

    return {
        "response_type": "text",
        "content": content,
        "intent": "meta_field_list",
        "meta": True,
    }


async def _handle_meta_asset_count(connection_id: int, db: Session) -> dict:
    """
    META handler 2：统计当前连接下的看板数量（Q2 业务口径：dashboard + workbook 都计入）。
    """
    dashboard_count = db.query(TableauAsset).filter(
        TableauAsset.connection_id == connection_id,
        TableauAsset.asset_type == "dashboard",
        TableauAsset.is_deleted == False,
    ).count()

    workbook_count = db.query(TableauAsset).filter(
        TableauAsset.connection_id == connection_id,
        TableauAsset.asset_type == "workbook",
        TableauAsset.is_deleted == False,
    ).count()

    total = dashboard_count + workbook_count

    content = (
        f"当前连接共有 **{total}** 个看板"
        f"（其中 Dashboard {dashboard_count} 个，Workbook {workbook_count} 个）。"
    )

    return {
        "response_type": "number",
        "value": total,
        "label": "看板总数",
        "unit": "个",
        "formatted": str(total),
        "content": content,
        "intent": "meta_asset_count",
        "meta": True,
    }


async def _handle_meta_asset_count_all(connections: list, db: Session) -> dict:
    """跨所有活跃连接，汇总看板数量。"""
    total_dashboard = 0
    total_workbook = 0
    sections = []

    for conn in connections:
        d = db.query(TableauAsset).filter(
            TableauAsset.connection_id == conn.id,
            TableauAsset.asset_type == "dashboard",
            TableauAsset.is_deleted == False,
        ).count()
        w = db.query(TableauAsset).filter(
            TableauAsset.connection_id == conn.id,
            TableauAsset.asset_type == "workbook",
            TableauAsset.is_deleted == False,
        ).count()
        total_dashboard += d
        total_workbook += w
        site_label = f"{conn.name}（{conn.site}）" if conn.site else conn.name
        sections.append(f"- **{site_label}**：Dashboard {d} 个，Workbook {w} 个")

    total = total_dashboard + total_workbook
    detail = "\n".join(sections) if sections else "暂无看板数据。"
    content = f"所有连接共有 **{total}** 个看板（Dashboard {total_dashboard} 个，Workbook {total_workbook} 个）：\n\n{detail}"

    return {
        "response_type": "text",
        "content": content,
        "intent": "meta_asset_count",
        "meta": True,
    }


async def _handle_meta_semantic_quality(connection_id: int, db: Session) -> dict:
    """
    META handler 3：分析当前连接的语义配置完整性（Q3 业务口径）。

    检查 tableau_field_semantics 表中该 connection 下的不完善项：
    - semantic_definition 为空
    - status 为 draft 或 ai_generated（未经人工审核）
    """
    from services.semantic_maintenance.models import TableauFieldSemantics
    from sqlalchemy import or_

    incomplete = db.query(TableauFieldSemantics).filter(
        TableauFieldSemantics.connection_id == connection_id,
        or_(
            TableauFieldSemantics.semantic_definition.is_(None),
            TableauFieldSemantics.semantic_definition == "",
            TableauFieldSemantics.status.in_(["draft", "ai_generated"]),
        ),
    ).all()

    if not incomplete:
        content = "当前数据源的语义配置较为完善，未发现明显缺失项。"
    else:
        lines = [f"发现 **{len(incomplete)}** 处语义配置不完善："]
        for f in incomplete[:10]:
            reason = []
            if not f.semantic_definition:
                reason.append("缺少语义定义")
            if f.status in ("draft", "ai_generated"):
                reason.append(f"状态为 {f.status}（未审核）")
            # 优先展示中文语义名，其次 tableau_field_id
            display_name = f.semantic_name_zh or f.semantic_name or f.tableau_field_id
            lines.append(f"- `{display_name}`：{', '.join(reason)}")
        if len(incomplete) > 10:
            lines.append(f"... 等共 {len(incomplete)} 处")
        content = "\n".join(lines)

    return {
        "response_type": "text",
        "content": content,
        "intent": "meta_semantic_quality",
        "meta": True,
    }


async def _handle_meta_semantic_quality_all(connections: list, db: Session) -> dict:
    """跨所有活跃连接，汇总语义配置质量。"""
    # 复用单连接逻辑，逐连接查询后汇总
    sections = []
    for conn in connections:
        result = await _handle_meta_semantic_quality(conn.id, db)
        site_label = f"{conn.name}（{conn.site}）" if conn.site else conn.name
        sections.append(f"### {site_label}\n{result.get('content', '')}")

    content = "\n\n".join(sections) if sections else "暂无语义配置数据。"
    return {
        "response_type": "text",
        "content": content,
        "intent": "meta_semantic_quality",
        "meta": True,
    }


async def _handle_meta_workbook_count(connections: list, db: Session) -> dict:
    """Q2：平台上有多少个报表（工作簿）。"""
    mcp_base_url = _MCP_PROXY_URL
    try:
        wb_list = await _mcp_list_workbooks(mcp_base_url)
    except Exception as e:
        logger.error("_handle_meta_workbook_count: MCP 调用失败: %s", e)
        return {
            "response_type": "text",
            "content": "暂时无法获取报表数据，请稍后重试或联系管理员。",
            "intent": "meta_workbook_count",
            "meta": True,
        }

    total = len(wb_list)
    if total == 0:
        content = "当前 Tableau 中暂无已发布的工作簿（报表）。"
    else:
        lines = [f"Tableau 中共有 **{total}** 个工作簿（报表）："]
        for wb in wb_list:
            proj = wb.get("projectName", "")
            proj_label = f"（{proj}）" if proj else ""
            lines.append(f"- {wb.get('name', '')}{proj_label}")
        content = "\n".join(lines)

    return {
        "response_type": "text",
        "content": content,
        "intent": "meta_workbook_count",
        "meta": True,
    }


async def _handle_meta_physical_table(connections: list, db: Session, question: str = "") -> dict:
    """Q4：数据源对应后台的物理表叫什么名字。"""
    mcp_base_url = _MCP_PROXY_URL

    # 先拉数据源列表，从问题中匹配数据源名称
    try:
        all_ds = await _mcp_list_datasources(mcp_base_url, "", "", "", "")
    except Exception as e:
        logger.error("_handle_meta_physical_table: MCP list-datasources 失败: %s", e)
        return {
            "response_type": "text",
            "content": "数据获取暂时异常，请稍后重试或联系管理员。",
            "intent": "meta_datasource_physical_table",
            "meta": True,
        }

    matched_ds = None
    if question and all_ds:
        q_lower = question.lower()
        candidates = sorted(all_ds, key=lambda x: len(x.get("name", "")), reverse=True)
        for ds in candidates:
            name = ds.get("name", "")
            if name and name.lower() in q_lower:
                matched_ds = ds
                break

    if not matched_ds:
        if all_ds:
            ds_sample = "、".join(ds.get("name", "") for ds in all_ds[:5])
            hint = f"（例如：{ds_sample}）" if ds_sample else ""
            content = f"请告诉我您想查询哪个数据源的物理表{hint}"
        else:
            content = "当前 Tableau 中暂无已发布的数据源。"
        return {
            "response_type": "text",
            "content": content,
            "intent": "meta_datasource_physical_table",
            "meta": True,
        }

    ds_name = matched_ds.get("name", "")
    try:
        tables = await _mcp_get_upstream_tables(mcp_base_url, ds_name)
    except Exception as e:
        logger.error("_handle_meta_physical_table: MCP 调用失败: %s", e)
        return {
            "response_type": "text",
            "content": f"获取「{ds_name}」物理表信息失败，请检查 Tableau 连接。",
            "intent": "meta_datasource_physical_table",
            "meta": True,
        }

    if not tables:
        content = (
            f"暂未找到「{ds_name}」的物理表信息，该数据源可能不支持数据溯源，"
            f"或直接使用了文件/提取数据。"
        )
    else:
        lines = [f"「{ds_name}」对应的后台物理表："]
        for t in tables:
            db_label = t.get("database", "")
            schema_label = t.get("schema", "")
            table_label = t.get("table", "")
            parts = [p for p in [db_label, schema_label, table_label] if p]
            lines.append(f"- {'.'.join(parts)}")
        content = "\n".join(lines)

    return {
        "response_type": "text",
        "content": content,
        "intent": "meta_datasource_physical_table",
        "meta": True,
    }


async def _handle_meta_downstream_workbooks(connections: list, db: Session, question: str = "") -> dict:
    """Q5：哪些看板和报表用了某个数据源。"""
    mcp_base_url = _MCP_PROXY_URL

    try:
        all_ds = await _mcp_list_datasources(mcp_base_url, "", "", "", "")
    except Exception as e:
        logger.error("_handle_meta_downstream_workbooks: MCP list-datasources 失败: %s", e)
        return {
            "response_type": "text",
            "content": "数据获取暂时异常，请稍后重试或联系管理员。",
            "intent": "meta_datasource_downstream",
            "meta": True,
        }

    matched_ds = None
    if question and all_ds:
        q_lower = question.lower()
        candidates = sorted(all_ds, key=lambda x: len(x.get("name", "")), reverse=True)
        # 先精确匹配完整名称
        for ds in candidates:
            name = ds.get("name", "")
            if name and name.lower() in q_lower:
                matched_ds = ds
                break
        # 再尝试去掉"数据源"后缀的核心词匹配（处理"管理费用这个数据源"等表述）
        if not matched_ds:
            for ds in candidates:
                name = ds.get("name", "")
                core = name.lower().replace("数据源", "").replace("datasource", "").strip()
                if core and core in q_lower:
                    matched_ds = ds
                    break

    if not matched_ds:
        if all_ds:
            ds_sample = "、".join(ds.get("name", "") for ds in all_ds[:5])
            hint = f"（例如：{ds_sample}）" if ds_sample else ""
            content = f"请告诉我您想查询哪个数据源的下游报表{hint}"
        else:
            content = "当前 Tableau 中暂无已发布的数据源。"
        return {
            "response_type": "text",
            "content": content,
            "intent": "meta_datasource_downstream",
            "meta": True,
        }

    ds_name = matched_ds.get("name", "")
    try:
        workbooks = await _mcp_get_downstream_workbooks(mcp_base_url, ds_name)
    except Exception as e:
        logger.error("_handle_meta_downstream_workbooks: MCP 调用失败: %s", e)
        return {
            "response_type": "text",
            "content": f"获取「{ds_name}」下游报表失败，请检查 Tableau 连接。",
            "intent": "meta_datasource_downstream",
            "meta": True,
        }

    if not workbooks:
        content = f"暂未找到使用「{ds_name}」的报表，可能该数据源尚未被任何工作簿引用。"
    else:
        lines = [f"引用「{ds_name}」的工作簿（共 {len(workbooks)} 个）："]
        for wb in workbooks:
            proj = wb.get("project", "")
            proj_label = f"（{proj}）" if proj else ""
            lines.append(f"- {wb.get('name', '')}{proj_label}")
        content = "\n".join(lines)

    return {
        "response_type": "text",
        "content": content,
        "intent": "meta_datasource_downstream",
        "meta": True,
    }


def _parse_days_from_question(question: str, default_days: int) -> int:
    """从问题中解析时间范围天数。"""
    import re
    # 提取数字
    nums = re.findall(r'\d+', question)
    if nums:
        return int(nums[0])
    if any(kw in question for kw in ["一个月", "本月", "这月", "上个月"]):
        return 30
    if any(kw in question for kw in ["一周", "本周", "这周", "上周"]):
        return 7
    if any(kw in question for kw in ["一天", "今天", "昨天"]):
        return 1
    if any(kw in question for kw in ["一季度", "本季", "这季"]):
        return 90
    return default_days


async def _handle_meta_datasource_new_in_period(connections: list, db: Session, question: str = "") -> dict:
    """Q6：最近一个月新增了哪些数据源。"""
    from datetime import datetime, timezone, timedelta

    mcp_base_url = _MCP_PROXY_URL
    try:
        ds_list = await _mcp_list_datasources(mcp_base_url, "", "", "", "")
    except Exception as e:
        logger.error("_handle_meta_datasource_new_in_period: MCP 调用失败: %s", e)
        return {
            "response_type": "text",
            "content": "获取数据源列表失败，请检查 Tableau 连接。",
            "intent": "meta_datasource_new_in_period",
            "meta": True,
        }

    days = _parse_days_from_question(question, 30)
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)

    # 检查是否有 createdAt 信息
    has_created_at = any(ds.get("createdAt") for ds in ds_list)
    if not has_created_at:
        return {
            "response_type": "text",
            "content": "Tableau 未提供创建时间信息，请联系管理员查阅审计记录。",
            "intent": "meta_datasource_new_in_period",
            "meta": True,
        }

    new_ds = []
    for ds in ds_list:
        created_at_str = ds.get("createdAt", "")
        if not created_at_str:
            continue
        try:
            created_at = datetime.fromisoformat(created_at_str.replace("Z", "+00:00"))
            if created_at >= cutoff:
                new_ds.append(ds)
        except Exception:
            continue

    if not new_ds:
        content = f"过去 {days} 天内未发现新增数据源。"
    else:
        lines = [f"过去 **{days}** 天内新增了 **{len(new_ds)}** 个数据源："]
        for ds in new_ds:
            lines.append(f"- {ds.get('name', '')}（创建于 {ds.get('createdAt', '')[:10]}）")
        content = "\n".join(lines)

    return {
        "response_type": "text",
        "content": content,
        "intent": "meta_datasource_new_in_period",
        "meta": True,
    }


async def _handle_meta_datasource_recently_updated(connections: list, db: Session, question: str = "") -> dict:
    """Q7：过去一周哪些数据源被改过了。"""
    from datetime import datetime, timezone, timedelta

    mcp_base_url = _MCP_PROXY_URL
    try:
        ds_list = await _mcp_list_datasources(mcp_base_url, "", "", "", "")
    except Exception as e:
        logger.error("_handle_meta_datasource_recently_updated: MCP 调用失败: %s", e)
        return {
            "response_type": "text",
            "content": "获取数据源列表失败，请检查 Tableau 连接。",
            "intent": "meta_datasource_recently_updated",
            "meta": True,
        }

    days = _parse_days_from_question(question, 7)
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)

    updated_ds = []
    for ds in ds_list:
        updated_at_str = ds.get("updatedAt", "")
        if not updated_at_str:
            continue
        try:
            updated_at = datetime.fromisoformat(updated_at_str.replace("Z", "+00:00"))
            if updated_at >= cutoff:
                updated_ds.append(ds)
        except Exception:
            continue

    if not updated_ds:
        content = f"过去 {days} 天内没有数据源被更新。"
    else:
        lines = [f"过去 **{days}** 天内更新过的数据源（共 **{len(updated_ds)}** 个）："]
        for ds in updated_ds:
            lines.append(f"- {ds.get('name', '')}（最后更新：{ds.get('updatedAt', '')[:10]}）")
        content = "\n".join(lines)
    content += "\n\n注：Tableau API 暂不支持获取操作人信息，如需确认修改人请查阅 Tableau Server 审计日志。"

    return {
        "response_type": "text",
        "content": content,
        "intent": "meta_datasource_recently_updated",
        "meta": True,
    }


def _format_size(size_bytes) -> str:
    """将字节数格式化为可读的 MB/GB 字符串。"""
    try:
        size_bytes = int(size_bytes)
    except (TypeError, ValueError):
        size_bytes = 0
    if size_bytes <= 0:
        return "0 B"
    if size_bytes >= 1024 ** 3:
        return f"{size_bytes / 1024 ** 3:.2f} GB"
    if size_bytes >= 1024 ** 2:
        return f"{size_bytes / 1024 ** 2:.2f} MB"
    if size_bytes >= 1024:
        return f"{size_bytes / 1024:.2f} KB"
    return f"{size_bytes} B"


async def _handle_meta_datasource_top_by_size(connections: list, db: Session, question: str = "") -> dict:
    """Q8：占用空间最大的前 N 个数据源。"""
    import re

    mcp_base_url = _MCP_PROXY_URL
    try:
        ds_list = await _mcp_list_datasources(mcp_base_url, "", "", "", "")
    except Exception as e:
        logger.error("_handle_meta_datasource_top_by_size: MCP 调用失败: %s", e)
        return {
            "response_type": "text",
            "content": "获取数据源列表失败，请检查 Tableau 连接。",
            "intent": "meta_datasource_top_by_size",
            "meta": True,
        }

    # 解析 N
    nums = re.findall(r'\d+', question)
    n = int(nums[0]) if nums else 10

    # 确保 size 为整数
    for ds in ds_list:
        try:
            ds["size"] = int(ds.get("size", 0) or 0)
        except (TypeError, ValueError):
            ds["size"] = 0

    # 检查是否有 size 信息
    if all(ds.get("size", 0) == 0 for ds in ds_list):
        return {
            "response_type": "text",
            "content": "Tableau 未返回数据源大小信息，请联系管理员查阅 Tableau Server 存储统计。",
            "intent": "meta_datasource_top_by_size",
            "meta": True,
        }

    sorted_ds = sorted(ds_list, key=lambda x: x.get("size", 0), reverse=True)
    top_n = sorted_ds[:n]

    lines = [f"占用空间最大的前 **{n}** 个数据源："]
    for i, ds in enumerate(top_n, 1):
        size_str = _format_size(ds.get("size", 0))
        lines.append(f"{i}. {ds.get('name', '')}（{size_str}）")
    content = "\n".join(lines)

    return {
        "response_type": "text",
        "content": content,
        "intent": "meta_datasource_top_by_size",
        "meta": True,
    }


async def _handle_meta_datasource_incomplete_metadata(connections: list, db: Session) -> dict:
    """Q9：哪些数据源的备注和定义没写全。"""
    mcp_base_url = _MCP_PROXY_URL
    try:
        ds_list = await _mcp_list_datasources(mcp_base_url, "", "", "", "")
    except Exception as e:
        logger.error("_handle_meta_datasource_incomplete_metadata: MCP 调用失败: %s", e)
        return {
            "response_type": "text",
            "content": "获取数据源列表失败，请检查 Tableau 连接。",
            "intent": "meta_datasource_incomplete_metadata",
            "meta": True,
        }

    incomplete = [
        ds for ds in ds_list
        if not ds.get("description") or len(ds.get("description", "")) < 10
    ]

    if not incomplete:
        content = "所有数据源的描述信息均已完善。"
    else:
        lines = [f"以下 **{len(incomplete)}** 个数据源的描述信息缺失或不完整，建议补充："]
        for ds in incomplete:
            desc = ds.get("description", "")
            status = "（无描述）" if not desc else f"（描述较短：{desc[:20]}...）"
            lines.append(f"- {ds.get('name', '')}{status}")
        lines.append("\n> 完善数据源描述有助于提升语义检索质量。")
        content = "\n".join(lines)

    return {
        "response_type": "text",
        "content": content,
        "intent": "meta_datasource_incomplete_metadata",
        "meta": True,
    }


async def _handle_meta_datasource_duplicates(connections: list, db: Session) -> dict:
    """Q10：有没有重名的数据源。"""
    mcp_base_url = _MCP_PROXY_URL
    try:
        ds_list = await _mcp_list_datasources(mcp_base_url, "", "", "", "")
    except Exception as e:
        logger.error("_handle_meta_datasource_duplicates: MCP 调用失败: %s", e)
        return {
            "response_type": "text",
            "content": "获取数据源列表失败，请检查 Tableau 连接。",
            "intent": "meta_datasource_duplicate",
            "meta": True,
        }

    from collections import defaultdict
    name_groups: dict = defaultdict(list)
    for ds in ds_list:
        name = ds.get("name", "").strip()
        if name:
            name_groups[name].append(ds)

    duplicates = {name: items for name, items in name_groups.items() if len(items) > 1}

    if not duplicates:
        content = "未发现重名的数据源，当前所有数据源名称唯一。"
    else:
        lines = [f"发现 **{len(duplicates)}** 组重名数据源，请及时处理以避免混淆："]
        for name, items in duplicates.items():
            lines.append(f"\n**{name}**（共 {len(items)} 个）：")
            for item in items:
                luid = item.get("luid", "")
                lines.append(f"  - LUID: `{luid}`")
        content = "\n".join(lines)

    return {
        "response_type": "text",
        "content": content,
        "intent": "meta_datasource_duplicate",
        "meta": True,
    }


# === API 端点 ===
@router.post("/query")
async def query(
    body: QueryRequest,
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
):
    """自然语言查询（PRD §6.2）POST /api/search/query — analyst+
    将用户自然语言问题转换为数据查询并返回结果。

    Spec 24 P0：
    - trace_id 优先继承 X-Trace-ID 请求头，无则生成新的 UUID v4
    - 响应头 X-Trace-ID 透传 trace_id
    - 响应体包含可空 task_run_id（向后兼容）
    """
    # Spec 24 P0: trace_id 继承策略
    incoming_trace = request.headers.get("X-Trace-ID")
    trace_id = incoming_trace if incoming_trace else new_trace_id()

    user = get_current_user(request=request, db=db)
    _require_role(user, "analyst")

    question = body.question
    datasource_luid = body.datasource_luid
    # connection_id >= 10000 是 MCP 虚拟连接 ID，后端不存在对应 tableau_connections 记录，视为全局路由
    connection_id = body.connection_id if (body.connection_id is None or body.connection_id < 10000) else None
    options = body.options or {}

    # P2-1：追问上下文继承 — 从上轮 query_context 中补填 connection_id / datasource_luid
    if body.use_conversation_context and body.conversation_id and not datasource_luid and not connection_id:
        try:
            import json as _json
            from sqlalchemy import text as _text
            _msg = db.execute(_text("""
                SELECT m.query_context FROM conversation_messages m
                JOIN conversations c ON c.id = m.conversation_id
                WHERE m.conversation_id=:cid AND c.user_id=:uid
                  AND m.role='assistant' AND m.query_context IS NOT NULL
                ORDER BY m.created_at DESC LIMIT 1
            """), {"cid": body.conversation_id, "uid": user.get("id")}).fetchone()
            if _msg:
                _ctx = _msg._mapping["query_context"]
                if isinstance(_ctx, str):
                    _ctx = _json.loads(_ctx)
                if isinstance(_ctx, dict):
                    if not datasource_luid and _ctx.get("datasource_luid"):
                        datasource_luid = _ctx["datasource_luid"]
                    if not connection_id and _ctx.get("connection_id"):
                        connection_id = int(_ctx["connection_id"])
        except Exception as _ctx_err:
            logger.warning("读取追问上下文失败（不影响主流程）: %s", _ctx_err)

    # 速率限制检查
    user_id = user.get("id")
    if user_id and not check_rate_limit(user_id):
        raise _nlq_error_response("NLQ_010", "查询过于频繁，请稍后再试")

    # 长度检查
    if len(question) > MAX_QUERY_LENGTH:
        raise _nlq_error_response(
            "NLQ_001",
            f"问题长度不能超过 {MAX_QUERY_LENGTH} 字符",
        )

    # 初始化审计记录（Spec 24 P0: trace_id 已在此 scope 顶部统一）
    audit_record = InvocationRecord(
        trace_id=trace_id,
        principal_id=user_id,
        principal_role=user.get("role", "user"),
        capability="query_metric",
        params_jsonb={"question_length": len(question)},
        status="started",
    )

    try:
        # ── META 查询优先检测（Q1-Q3 业务口径，不走 VizQL 流水线）────────
        # X-Intent-Hint 由 ask_data.py per-user 缓存注入，命中时跳过重复关键词匹配
        _intent_hint = request.headers.get("X-Intent-Hint", "")
        meta_intent = _intent_hint if _intent_hint else classify_meta_intent(question)
        if meta_intent:
            audit_record.params_jsonb["intent"] = meta_intent
            if connection_id is None:
                # 全部连接聚合查询
                result = await handle_meta_query_all(meta_intent, db, user, question=question)
            else:
                result = await handle_meta_query(meta_intent, connection_id, db, user, question=question)
            audit_record.status = "ok"
            # Spec 24 P0: 响应头透传 trace_id
            response.headers["X-Trace-ID"] = audit_record.trace_id
            return {
                "trace_id": audit_record.trace_id,
                "task_run_id": body.task_run_id,  # Spec 24 P0: 可空，向后兼容
                **result,
            }

        # ── 意图分类（阶段0）─────────────────────────────────────
        intent = classify_intent(question)
        audit_record.params_jsonb["intent"] = intent.intent_type if intent else None

        # ── 数据源路由（PRD §7.1）─────────────────────────────
        chosen_ds = None
        if datasource_luid:
            asset = _get_asset_by_luid(datasource_luid)
            if not asset:
                raise _nlq_error_response("NLQ_009", "数据源不存在或已删除")
            from app.utils.auth import verify_connection_access
            verify_connection_access(asset.connection_id, user, db)
            if is_datasource_sensitivity_blocked(datasource_luid):
                raise _nlq_error_response("NLQ_011", "该数据源为高敏级别")
            chosen_ds = {
                "datasource_luid": datasource_luid,
                "datasource_name": asset.name,
                "connection_id": asset.connection_id,
            }
        elif connection_id:
            from app.utils.auth import verify_connection_access
            verify_connection_access(connection_id, user, db)
            chosen_ds = route_datasource(question, connection_id=connection_id)
            if not chosen_ds:
                raise _nlq_error_response("NLQ_005", "未找到匹配的数据源，请指定 datasource_luid")
        else:
            # 尝试多数据源路由
            chosen_ds = route_datasource(question)
            if not chosen_ds:
                # Fallback：尝试通过 MCP 动态发现数据源
                logger.info("路由未命中，尝试 MCP 动态发现数据源 trace=%s", audit_record.trace_id)
                try:
                    from services.tableau.models import TableauConnection as _TableauConnection
                    from services.mcp.models import McpServer

                    db_temp = TableauDatabase()
                    session_temp = db_temp.session
                    active_conn = session_temp.query(_TableauConnection).filter(
                        _TableauConnection.is_active == True,
                    ).order_by(_TableauConnection.id.asc()).first()

                    if not active_conn:
                        # TableauConnection 为空，从活跃 MCP server config 获取 credentials
                        mcp_server_record = session_temp.query(McpServer).filter(
                            McpServer.is_active == True,
                            McpServer.type == "tableau",
                        ).order_by(McpServer.id.asc()).first()

                        if mcp_server_record and mcp_server_record.credentials:
                            creds = mcp_server_record.credentials
                            mcp_base_url = mcp_server_record.server_url
                            tableau_server = creds.get("tableau_server", "")
                            site_name = creds.get("site_name", "")
                            pat_name = creds.get("pat_name", "")
                            pat_value = creds.get("pat_value", "")

                            if tableau_server and site_name and pat_name and pat_value:
                                # 用 MCP config credentials 直接调用 MCP JSON-RPC
                                ds_list = await _mcp_list_datasources(
                                    mcp_base_url, tableau_server, site_name, pat_name, pat_value
                                )
                                if ds_list and len(ds_list) > 0:
                                    first_ds = ds_list[0]
                                    chosen_ds = {
                                        "datasource_luid": first_ds.get("luid") or first_ds.get("id", ""),
                                        "datasource_name": first_ds.get("name", "MCP 数据源"),
                                        "connection_id": None,
                                        "mcp_discovery": True,
                                        "mcp_base_url": mcp_base_url,
                                        "mcp_site": site_name,
                                        "mcp_token_name": pat_name,
                                        "mcp_token_value": pat_value,
                                    }
                                    logger.info("MCP 动态发现数据源成功: luid=%s, name=%s trace=%s",
                                                chosen_ds["datasource_luid"], chosen_ds["datasource_name"], audit_record.trace_id)

                    elif active_conn:
                        mcp_client = get_tableau_mcp_client(active_conn.id)
                        mcp_result = mcp_client.list_datasources(limit=10, timeout=15)
                        ds_list = mcp_result.get("datasources", [])
                        if ds_list and len(ds_list) > 0:
                            first_ds = ds_list[0]
                            chosen_ds = {
                                "datasource_luid": first_ds.get("luid") or first_ds.get("datasource_luid") or first_ds.get("id"),
                                "datasource_name": first_ds.get("name") or first_ds.get("datasourceName") or "MCP 数据源",
                                "connection_id": active_conn.id,
                                "mcp_discovery": True,
                            }
                            logger.info("MCP 动态发现数据源成功: luid=%s, name=%s trace=%s",
                                        chosen_ds["datasource_luid"], chosen_ds["datasource_name"], audit_record.trace_id)

                    session_temp.close()
                except Exception as mcp_err:
                    logger.warning("MCP 动态发现失败: %s trace=%s", mcp_err, audit_record.trace_id)

            if not chosen_ds:
                audit_record.status = "ok"
                return {
                    "trace_id": audit_record.trace_id,
                    "response_type": "text",
                    "content": "未能识别您想查询的数据源，您可以先问「你有哪些数据源」获取数据源列表，再指定数据源名称提问。",
                    "intent": None,
                    "confidence": None,
                    "datasource": None,
                    "datasource_luid": None,
                }

        ds_luid = chosen_ds["datasource_luid"]
        ds_name = chosen_ds["datasource_name"]
        is_mcp_discovery = chosen_ds.get("mcp_discovery", False)

        # 1c. 获取数据源字段（TableauAsset 使用 tableau_id 存储 Tableau LUID）
        db = TableauDatabase()
        session = db.session
        asset = session.query(TableauAsset).filter(
            TableauAsset.tableau_id == ds_luid,
            TableauAsset.is_deleted == False,
        ).first()
        session.close()

        # MCP 动态发现的数据源（不在本地 DB）→ 通过 MCP 获取字段元数据
        if not asset and is_mcp_discovery:
            logger.info("MCP 动态数据源，获取字段元数据 trace=%s", audit_record.trace_id)
            try:
                # connection_id 为 None 表示使用 MCP config credentials（绕过 TableauConnection）
                if chosen_ds.get("connection_id") is not None:
                    mcp_client = get_tableau_mcp_client(connection_id=chosen_ds["connection_id"])
                    metadata = mcp_client.get_datasource_metadata(ds_luid, timeout=30)
                else:
                    # 使用 MCP config credentials 直接调用 MCP JSON-RPC
                    metadata = await _mcp_get_datasource_metadata(
                        chosen_ds["mcp_base_url"], ds_luid, timeout=30
                    )
                # 解析 MCP 返回的字段（GraphQL Metadata API 格式）
                raw_fields = metadata.get("data", {}).get("publishedDatasources", [{}])
                if raw_fields and len(raw_fields) > 0:
                    mcp_fields = raw_fields[0].get("fields", [])
                    fields = []
                    for f in mcp_fields:
                        fname = f.get("name", "") or f.get("Name", "")
                        ftype = f.get("dataType", "") or f.get("dataType", "")
                        frole = f.get("role", "dimension")
                        if fname:
                            fields.append({
                                "field_caption": fname,
                                "field_name": fname,
                                "role": frole,
                                "data_type": ftype,
                                "formula": None,
                                "sensitivity_level": "low",
                            })
                    sanitized_fields = sanitize_fields_for_llm(fields)
                    fields_with_types = _build_fields_with_types(sanitized_fields)
                    asset_datasource_id = None
                    logger.info("MCP 字段元数据获取成功: %d 个字段 trace=%s", len(fields), audit_record.trace_id)
                else:
                    sanitized_fields = []
                    fields_with_types = "无可用字段"
                    asset_datasource_id = None
                    logger.warning("MCP 字段元数据为空 trace=%s", audit_record.trace_id)
            except Exception as meta_err:
                logger.error("MCP 获取字段元数据失败: %s trace=%s", meta_err, audit_record.trace_id)
                raise _nlq_error_response("NLQ_009", "无法获取数据源字段信息，请联系管理员")

        elif not asset:
            raise _nlq_error_response("NLQ_009", "数据源不存在或已删除")
        else:
            field_records = db.get_datasource_fields(asset.id)

            # 提取 field_registry_id（= TableauDatasourceField.id）用于批量查敏感度
            field_ids = [f.id for f in field_records]

            # 批量查询字段敏感度（JOIN TableauFieldSemantics）
            # 注意：使用新的 session 查询，因为前面的 session 已关闭
            sensitivity_map: Dict[int, str] = {}
            if field_ids:
                from services.semantic_maintenance.models import TableauFieldSemantics

                db2 = TableauDatabase()
                session2 = db2.session
                try:
                    semantics_records = session2.query(
                        TableauFieldSemantics.field_registry_id,
                        TableauFieldSemantics.sensitivity_level,
                    ).filter(
                        TableauFieldSemantics.field_registry_id.in_(field_ids),
                        TableauFieldSemantics.connection_id == asset.connection_id,
                    ).all()
                    sensitivity_map = {
                        row.field_registry_id: (row.sensitivity_level or "low").lower()
                        for row in semantics_records
                    }
                finally:
                    session2.close()

            fields = [
                {
                    "field_caption": f.field_caption,
                    "field_name": f.field_name,
                    "role": f.role,
                    "data_type": f.data_type,
                    "formula": f.formula,
                    "sensitivity_level": sensitivity_map.get(f.id, "low"),
                }
                for f in field_records
            ]

            # 敏感度过滤（高敏字段不暴露给 LLM）
            sanitized_fields = sanitize_fields_for_llm(fields)
            fields_with_types = _build_fields_with_types(sanitized_fields)
            asset_datasource_id = asset.datasource_id

        # ── P3 增强：recall_fields 语义重排序 ──────────────────
        try:
            recalled = await recall_fields(question, datasource_ids=[asset_datasource_id] if asset_datasource_id else None)
        except Exception as recall_err:
            logger.warning("recall_fields 失败（跳过语义重排序）: %s trace=%s", recall_err, audit_record.trace_id)
            recalled = []
        if recalled:
            recalled_names = {r["semantic_name_zh"] or r["semantic_name"] for r in recalled}
            # 将语义匹配度高的字段排在前面
            def boost_key(f):
                name = f.get("field_caption", "") or f.get("field_name", "")
                return (0 if name in recalled_names else 1, 0)
            sanitized_fields.sort(key=boost_key)

        # ── 术语表增强（PRD §8.2）──────────────────────────────
        try:
            _gl_db = TableauDatabase().session
            glossary_terms = glossary_service.match_terms(_gl_db, question)
            _gl_db.close()
        except Exception as gl_err:
            logger.warning("术语表查询失败（跳过）: %s trace=%s", gl_err, audit_record.trace_id)
            glossary_terms = []
        term_mappings = (
            "\n".join(f"{t.get('source_term', t.get('term',''))} -> {t.get('mapped_term', t.get('definition',''))}" for t in glossary_terms)
            if glossary_terms else "无"
        )

        # ── 意图分类 + VizQL 生成（One-Pass LLM）───────────────
        llm_result = await one_pass_llm(
            question=question,
            datasource_luid=ds_luid,
            datasource_name=ds_name,
            fields_with_types=fields_with_types,
            term_mappings=term_mappings,
            intent_hint=intent.intent_type if intent else None,
        )
        audit_record.llm_tokens_in = llm_result.get("tokens_in")
        audit_record.llm_tokens_out = llm_result.get("tokens_out")

        vizql_json = llm_result["vizql_json"]
        response_type = llm_result.get("response_type", "auto")

        # ── 查询执行（MCP Stage 3）─────────────────────────────
        query_result = execute_query(
            datasource_luid=ds_luid,
            vizql_json=vizql_json,
            limit=options.get("limit", 1000),
            connection_id=chosen_ds.get("connection_id"),
        )

        mcp_fields = query_result.get("fields", [])
        mcp_rows = query_result.get("rows", [])

        if response_type == "number" or (response_type == "auto" and len(mcp_rows) == 1 and len(mcp_rows[0]) == 1):
            # PRD §6.2 number 格式：
            # {"value": 345678.0, "label": "销售额", "unit": "", "formatted": "345,678.00"}
            # MCP rows = [[345678.0]]，fieldCaption = "Sales"
            if mcp_rows and isinstance(mcp_rows[0], list) and len(mcp_rows[0]) == 1:
                value = mcp_rows[0][0]
            else:
                value = mcp_rows[0] if mcp_rows else None
            if isinstance(value, (int, float)):
                formatted = f"{value:,.2f}" if isinstance(value, float) else str(value)
            else:
                formatted = str(value) if value is not None else ""
            formatted = format_response(
                value,  # 传标量，不是 [[value]]
                intent=intent,
                response_type_hint="number",
            )
            api_data = formatted  # format_response 返回完整的 data 对象

        elif response_type == "text" or (response_type == "auto" and len(mcp_rows) == 0):
            api_data = format_response([], intent=intent, response_type_hint="text")

        else:
            # PRD §6.2 table 格式：
            # {"columns": [{Name, label, type}], "rows": [{col1: v1, col2: v2}], ...}
            # MCP rows = [[v1, v2], ...]（数组），需转为 [{col1: v1, col2: v2}, ...]
            api_data = format_response(mcp_rows, intent=intent, response_type_hint="table")

        audit_record.status = "ok"
        logger.info("NLQ 查询成功 trace=%s", audit_record.trace_id)

        # 写入对话历史（可选，失败不影响主流程）
        if body.conversation_id:
            try:
                import json as _json
                answer_text = _json.dumps(api_data, ensure_ascii=False, default=str)
                # P2-1：构建 query_context 供追问继承
                _query_context = {
                    "connection_id": chosen_ds.get("connection_id"),
                    "datasource_luid": ds_luid,
                    "datasource_name": ds_name,
                    "field_names": [
                        f.get("field_caption") or f.get("field_name")
                        for f in sanitized_fields[:20]
                    ],
                }
                _append_messages_to_conversation(
                    db=db,
                    conversation_id=body.conversation_id,
                    user_id=user_id,
                    question=question,
                    answer=answer_text,
                    query_context=_query_context,
                )
            except Exception as _e:
                logger.warning("写入对话消息失败（不影响主流程）: %s", _e)

        # 写查询日志
        log_nlq_query(
            db=db,
            user_id=user_id,
            question=question,
            datasource_luid=ds_luid,
            intent_type=intent.intent_type if intent else "unknown",
            confidence=llm_result.get("confidence", 0),
            response_type=response_type,
            latency_ms=audit_record.latency_ms,
        )

        # Spec 24 P0: 响应头透传 trace_id
        response.headers["X-Trace-ID"] = audit_record.trace_id

        return {
            "trace_id": audit_record.trace_id,
            "task_run_id": body.task_run_id,  # Spec 24 P0: 可空，向后兼容
            **api_data,
            "response_type": response_type,
            "intent": intent.intent_type if intent else None,
            "confidence": llm_result.get("confidence"),
            "datasource": {"id": asset.id, "name": ds_name},
            "datasource_luid": ds_luid,
        }

    except NLQError as e:
        audit_record.status = "failed"
        audit_record.error_code = e.code
        audit_record.error_detail = e.message
        logger.warning("NLQ 错误 [%s] trace=%s: %s", e.code, audit_record.trace_id, e.message, exc_info=True)
        raise _nlq_error_response(e.code, e.message, e.details)

    except HTTPException:
        audit_record.status = "failed"
        raise

    except Exception as exc:
        audit_record.status = "failed"
        audit_record.error_code = "SYS_001"
        audit_record.error_detail = str(exc)
        logger.error("NLQ 意外错误 trace=%s: %s", audit_record.trace_id, exc, exc_info=True)
        raise HTTPException(
            status_code=500,
            detail={"code": "SYS_001", "message": "服务器内部错误", "details": {}},
        )

    finally:
        write_audit(audit_record)


def _append_messages_to_conversation(
    db,
    conversation_id: str,
    user_id: int,
    question: str,
    answer: str,
    query_context: dict = None,
) -> None:
    """将用户问题和助手回复写入对话历史（内部辅助函数）

    Args:
        query_context: P2-1 追问上下文，写入 assistant 消息的 query_context 列。
    """
    import json as _json
    import uuid
    from datetime import datetime, timezone
    from sqlalchemy import text

    now = datetime.now(timezone.utc)
    # 验证对话属于该用户，防止跨用户写入
    conv = db.execute(
        text("SELECT id FROM conversations WHERE id=:id AND user_id=:uid"),
        {"id": conversation_id, "uid": user_id},
    ).fetchone()
    if not conv:
        return
    db.execute(
        text("INSERT INTO conversation_messages (id, conversation_id, role, content, created_at) VALUES (:id, :cid, 'user', :content, :now)"),
        {"id": str(uuid.uuid4()), "cid": conversation_id, "content": question, "now": now},
    )
    db.execute(
        text(
            "INSERT INTO conversation_messages "
            "(id, conversation_id, role, content, query_context, created_at) "
            "VALUES (:id, :cid, 'assistant', :content, :qc, :now)"
        ),
        {
            "id": str(uuid.uuid4()),
            "cid": conversation_id,
            "content": answer,
            "qc": _json.dumps(query_context, ensure_ascii=False, default=str) if query_context else None,
            "now": now,
        },
    )
    db.execute(
        text("UPDATE conversations SET updated_at=:now WHERE id=:id"),
        {"now": now, "id": conversation_id},
    )
    db.commit()


@router.get("/suggestions")
async def suggestions(
    q: str,
    connection_id: int = None,
    db: Session = Depends(get_db),
):
    """查询建议（自动补全，PRD §6.3）GET /api/search/suggestions — analyst+"""
    user = get_current_user(request=None, db=db)
    _require_role(user, "analyst")

    return {
        "suggestions": [
            "各区域的销售额是多少",
            "最近6个月的月度趋势",
            "销售额前10的产品",
            "各产品类别的利润对比",
        ]
    }


@router.get("/history")
async def history(db: Session = Depends(get_db)):
    """查询历史（PRD §6.4）GET /api/search/history — analyst+"""
    user = get_current_user(request=None, db=db)
    _require_role(user, "analyst")

    return {"items": [], "total": 0, "page": 1, "page_size": 20}

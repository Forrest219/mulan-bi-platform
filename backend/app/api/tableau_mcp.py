"""
内置 Tableau MCP Server

暴露在 /tableau-mcp 路径，实现 MCP JSON-RPC 2.0 协议，
内部调用 Tableau REST API。
"""
import json
import logging

import httpx
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from app.core.database import SessionLocal
from services.mcp.models import McpServer

logger = logging.getLogger(__name__)

router = APIRouter()


# ── 工具函数 ──────────────────────────────────────────────────────────────────

def _make_error(req_id, code: int, message: str) -> dict:
    return {
        "jsonrpc": "2.0",
        "id": req_id,
        "error": {"code": code, "message": message},
    }


def _make_result(req_id, result: dict) -> dict:
    return {"jsonrpc": "2.0", "id": req_id, "result": result}


def _get_tableau_config() -> dict:
    """从 DB 读取 type='tableau' 且 is_active=True 的 McpServer，返回 credentials。"""
    db = SessionLocal()
    try:
        record = (
            db.query(McpServer)
            .filter(McpServer.type == "tableau", McpServer.is_active == True)
            .first()
        )
        if not record or not record.credentials:
            return {}
        return dict(record.credentials)
    finally:
        db.close()


async def _tableau_signin(tableau_server: str, pat_name: str, pat_value: str, site_name: str) -> tuple[str, str]:
    """
    调用 Tableau REST API 登录，返回 (token, site_id)。
    失败时抛出 RuntimeError。
    """
    signin_url = f"{tableau_server.rstrip('/')}/api/3.20/auth/signin"
    body = {
        "credentials": {
            "personalAccessTokenName": pat_name,
            "personalAccessTokenSecret": pat_value,
            "site": {"contentUrl": site_name},
        }
    }
    async with httpx.AsyncClient(timeout=30.0, verify=False) as client:
        resp = await client.post(signin_url, json=body, headers={"Accept": "application/json"})
    if resp.status_code != 200:
        logger.warning("Tableau signin failed: %s %s", resp.status_code, resp.text[:200])
        raise RuntimeError(f"Tableau 登录失败 (HTTP {resp.status_code})")
    data = resp.json()
    token = data["credentials"]["token"]
    site_id = data["credentials"]["site"]["id"]
    return token, site_id


async def _list_datasources(credentials: dict) -> list:
    """登录 Tableau 并拉取数据源列表。"""
    # MCP credentials 存储为明文 JSONB，直接使用，无需解密
    pat_value = credentials.get("pat_value", "")

    tableau_server = credentials["tableau_server"]
    pat_name = credentials["pat_name"]
    site_name = credentials.get("site_name", "")

    token, site_id = await _tableau_signin(tableau_server, pat_name, pat_value, site_name)

    ds_url = f"{tableau_server.rstrip('/')}/api/3.20/sites/{site_id}/datasources?pageSize=100"
    async with httpx.AsyncClient(timeout=30.0, verify=False) as client:
        resp = await client.get(
            ds_url,
            headers={"x-tableau-auth": token, "Accept": "application/json"},
        )
    if resp.status_code != 200:
        raise RuntimeError(f"获取数据源失败 (HTTP {resp.status_code})")

    data = resp.json()
    raw_list = data.get("datasources", {}).get("datasource", [])
    if isinstance(raw_list, dict):
        raw_list = [raw_list]
    return [
        {
            "name": ds.get("name", ""),
            "contentUrl": ds.get("contentUrl", ""),
            "luid": ds.get("id", ""),
            "createdAt": ds.get("createdAt", ""),
            "updatedAt": ds.get("updatedAt", ""),
            "size": ds.get("size", 0),
            "description": ds.get("description", ""),
        }
        for ds in raw_list
    ]


async def _list_workbooks(credentials: dict) -> list:
    """登录 Tableau 并拉取工作簿列表。"""
    pat_value = credentials.get("pat_value", "")
    tableau_server = credentials["tableau_server"]
    pat_name = credentials["pat_name"]
    site_name = credentials.get("site_name", "")

    token, site_id = await _tableau_signin(tableau_server, pat_name, pat_value, site_name)

    wb_url = f"{tableau_server.rstrip('/')}/api/3.20/sites/{site_id}/workbooks?pageSize=100"
    async with httpx.AsyncClient(timeout=30.0, verify=False) as client:
        resp = await client.get(
            wb_url,
            headers={"x-tableau-auth": token, "Accept": "application/json"},
        )
    if resp.status_code != 200:
        raise RuntimeError(f"获取工作簿列表失败 (HTTP {resp.status_code})")

    data = resp.json()
    raw_list = data.get("workbooks", {}).get("workbook", [])
    if isinstance(raw_list, dict):
        raw_list = [raw_list]
    return [
        {
            "name": wb.get("name", ""),
            "luid": wb.get("id", ""),
            "projectName": (wb.get("project") or {}).get("name", ""),
            "updatedAt": wb.get("updatedAt", ""),
        }
        for wb in raw_list
    ]


async def _get_datasource_upstream_tables(credentials: dict, ds_name: str) -> list:
    """通过 Metadata API GraphQL 查询数据源的上游物理表。"""
    pat_value = credentials.get("pat_value", "")
    tableau_server = credentials["tableau_server"]
    pat_name = credentials["pat_name"]
    site_name = credentials.get("site_name", "")

    token, _ = await _tableau_signin(tableau_server, pat_name, pat_value, site_name)

    graphql_url = f"{tableau_server.rstrip('/')}/api/metadata/graphql"
    gql_query = (
        '{ publishedDatasourcesConnection(filter: {nameWithin: ["%s"]}) {'
        '  nodes { name upstreamTables { name schema database { name } } } } }'
    ) % ds_name.replace('"', '\\"')

    async with httpx.AsyncClient(timeout=30.0, verify=False) as client:
        resp = await client.post(
            graphql_url,
            json={"query": gql_query},
            headers={
                "x-tableau-auth": token,
                "Accept": "application/json",
                "Content-Type": "application/json",
            },
        )
    if resp.status_code != 200:
        raise RuntimeError(f"Metadata API 调用失败 (HTTP {resp.status_code})")

    data = resp.json()
    nodes = (
        data.get("data", {})
        .get("publishedDatasourcesConnection", {})
        .get("nodes", [])
    )
    if not nodes:
        return []
    tables = nodes[0].get("upstreamTables", [])
    return [
        {
            "table": t.get("name", ""),
            "schema": t.get("schema", ""),
            "database": (t.get("database") or {}).get("name", ""),
        }
        for t in tables
    ]


async def _get_datasource_downstream_workbooks(credentials: dict, ds_name: str) -> list:
    """通过 Metadata API GraphQL 查询数据源的下游工作簿。"""
    pat_value = credentials.get("pat_value", "")
    tableau_server = credentials["tableau_server"]
    pat_name = credentials["pat_name"]
    site_name = credentials.get("site_name", "")

    token, _ = await _tableau_signin(tableau_server, pat_name, pat_value, site_name)

    graphql_url = f"{tableau_server.rstrip('/')}/api/metadata/graphql"
    gql_query = (
        '{ publishedDatasourcesConnection(filter: {nameWithin: ["%s"]}) {'
        '  nodes { name downstreamWorkbooks { name projectName updatedAt } } } }'
    ) % ds_name.replace('"', '\\"')

    async with httpx.AsyncClient(timeout=30.0, verify=False) as client:
        resp = await client.post(
            graphql_url,
            json={"query": gql_query},
            headers={
                "x-tableau-auth": token,
                "Accept": "application/json",
                "Content-Type": "application/json",
            },
        )
    if resp.status_code != 200:
        raise RuntimeError(f"Metadata API 调用失败 (HTTP {resp.status_code})")

    data = resp.json()
    nodes = (
        data.get("data", {})
        .get("publishedDatasourcesConnection", {})
        .get("nodes", [])
    )
    if not nodes:
        return []
    workbooks = nodes[0].get("downstreamWorkbooks", [])
    return [
        {
            "name": wb.get("name", ""),
            "project": wb.get("projectName", ""),
            "updatedAt": wb.get("updatedAt", ""),
        }
        for wb in workbooks
    ]


async def _get_datasource_metadata(credentials: dict, luid: str) -> dict:
    """登录 Tableau 并拉取指定数据源详情（含字段列表）。"""
    pat_value = credentials.get("pat_value", "")

    tableau_server = credentials["tableau_server"]
    pat_name = credentials["pat_name"]
    site_name = credentials.get("site_name", "")

    token, site_id = await _tableau_signin(tableau_server, pat_name, pat_value, site_name)

    base_url = tableau_server.rstrip("/")

    async with httpx.AsyncClient(timeout=30.0, verify=False) as client:
        # 1. 获取数据源基本信息
        ds_url = f"{base_url}/api/3.20/sites/{site_id}/datasources/{luid}"
        resp = await client.get(
            ds_url,
            headers={"x-tableau-auth": token, "Accept": "application/json"},
        )
        if resp.status_code != 200:
            raise RuntimeError(f"获取数据源详情失败 (HTTP {resp.status_code})")
        ds_info = resp.json().get("datasource", {})

        # 2. 通过 Metadata API（GraphQL）获取字段列表
        # Tableau Metadata API 的 Field 类型只暴露 name / isHidden / description
        graphql_url = f"{base_url}/api/metadata/graphql"
        gql_query = (
            '{ publishedDatasourcesConnection(filter: {luid: "%s"}) {'
            '  nodes { luid name fields { name isHidden description } } } }'
        ) % luid
        try:
            meta_resp = await client.post(
                graphql_url,
                json={"query": gql_query},
                headers={
                    "x-tableau-auth": token,
                    "Accept": "application/json",
                    "Content-Type": "application/json",
                },
            )
            if meta_resp.status_code == 200:
                meta_data = meta_resp.json()
                if meta_data and "data" in meta_data and meta_data["data"]:
                    nodes = (
                        meta_data["data"]
                        .get("publishedDatasourcesConnection", {})
                        .get("nodes", [])
                    )
                    if nodes:
                        raw_fields = nodes[0].get("fields", [])
                        # 过滤隐藏字段，规范化格式
                        ds_info["fields"] = [
                            {
                                "name": f.get("name", ""),
                                "description": f.get("description", ""),
                            }
                            for f in raw_fields
                            if not f.get("isHidden", False) and f.get("name", "")
                        ]
            else:
                logger.warning(
                    "_get_datasource_metadata: Metadata API 返回 %s，跳过字段查询",
                    meta_resp.status_code,
                )
        except Exception as e:
            logger.warning("_get_datasource_metadata: Metadata API 调用失败: %s", e)

    return ds_info


# ── MCP JSON-RPC 端点 ────────────────────────────────────────────────────────

@router.post("")
@router.post("/")
async def handle_mcp(request: Request):
    """处理 MCP JSON-RPC 2.0 请求。"""
    try:
        body = await request.json()
    except Exception:
        return JSONResponse(
            status_code=400,
            content=_make_error(None, -32700, "Parse error: invalid JSON"),
        )

    req_id = body.get("id")
    method = body.get("method", "")
    params = body.get("params", {})

    # ── initialize ───────────────────────────────────────────────────────────
    if method == "initialize":
        return JSONResponse(
            _make_result(req_id, {
                "protocolVersion": "2025-06-18",
                "serverInfo": {"name": "mulan-tableau-mcp", "version": "1.0"},
                "capabilities": {"tools": {}},
            })
        )

    # ── notifications/initialized ────────────────────────────────────────────
    if method == "notifications/initialized":
        return JSONResponse({"jsonrpc": "2.0", "result": None})

    # ── tools/list ───────────────────────────────────────────────────────────
    if method == "tools/list":
        return JSONResponse(
            _make_result(req_id, {
                "tools": [
                    {
                        "name": "list-datasources",
                        "description": "列出 Tableau 所有已发布的数据源",
                        "inputSchema": {
                            "type": "object",
                            "properties": {
                                "limit": {"type": "integer", "description": "最多返回条数（当前忽略，由 pageSize=100 控制）"}
                            },
                        },
                    },
                    {
                        "name": "get-datasource-metadata",
                        "description": "获取指定 Tableau 数据源的详情",
                        "inputSchema": {
                            "type": "object",
                            "properties": {
                                "datasource_luid": {"type": "string", "description": "数据源的 LUID（唯一标识）"}
                            },
                            "required": ["datasource_luid"],
                        },
                    },
                    {
                        "name": "list-workbooks",
                        "description": "列出 Tableau 所有已发布的工作簿",
                        "inputSchema": {
                            "type": "object",
                            "properties": {},
                        },
                    },
                    {
                        "name": "get-datasource-upstream-tables",
                        "description": "查询数据源对应的上游物理表",
                        "inputSchema": {
                            "type": "object",
                            "properties": {
                                "datasource_name": {"type": "string", "description": "数据源名称"}
                            },
                            "required": ["datasource_name"],
                        },
                    },
                    {
                        "name": "get-datasource-downstream-workbooks",
                        "description": "查询引用了该数据源的下游工作簿",
                        "inputSchema": {
                            "type": "object",
                            "properties": {
                                "datasource_name": {"type": "string", "description": "数据源名称"}
                            },
                            "required": ["datasource_name"],
                        },
                    },
                ]
            })
        )

    # ── tools/call ───────────────────────────────────────────────────────────
    if method == "tools/call":
        tool_name = params.get("name", "")
        arguments = params.get("arguments", {})

        # 1. 从 DB 读 Tableau 配置
        credentials = _get_tableau_config()
        if not credentials:
            return JSONResponse(
                _make_error(req_id, -32001, "未找到 Tableau MCP 配置"),
            )

        try:
            if tool_name == "list-datasources":
                datasources = await _list_datasources(credentials)
                text_content = json.dumps({"datasources": datasources}, ensure_ascii=False)
                return JSONResponse(
                    _make_result(req_id, {
                        "content": [{"type": "text", "text": text_content}]
                    })
                )

            elif tool_name == "get-datasource-metadata":
                luid = arguments.get("datasource_luid", "")
                if not luid:
                    return JSONResponse(
                        _make_error(req_id, -32602, "缺少必要参数: datasource_luid"),
                    )
                metadata = await _get_datasource_metadata(credentials, luid)
                text_content = json.dumps({"datasource": metadata}, ensure_ascii=False)
                return JSONResponse(
                    _make_result(req_id, {
                        "content": [{"type": "text", "text": text_content}]
                    })
                )

            elif tool_name == "list-workbooks":
                workbooks = await _list_workbooks(credentials)
                text_content = json.dumps({"workbooks": workbooks}, ensure_ascii=False)
                return JSONResponse(
                    _make_result(req_id, {
                        "content": [{"type": "text", "text": text_content}]
                    })
                )

            elif tool_name == "get-datasource-upstream-tables":
                ds_name = arguments.get("datasource_name", "")
                if not ds_name:
                    return JSONResponse(
                        _make_error(req_id, -32602, "缺少必要参数: datasource_name"),
                    )
                tables = await _get_datasource_upstream_tables(credentials, ds_name)
                text_content = json.dumps({"tables": tables}, ensure_ascii=False)
                return JSONResponse(
                    _make_result(req_id, {
                        "content": [{"type": "text", "text": text_content}]
                    })
                )

            elif tool_name == "get-datasource-downstream-workbooks":
                ds_name = arguments.get("datasource_name", "")
                if not ds_name:
                    return JSONResponse(
                        _make_error(req_id, -32602, "缺少必要参数: datasource_name"),
                    )
                workbooks = await _get_datasource_downstream_workbooks(credentials, ds_name)
                text_content = json.dumps({"workbooks": workbooks}, ensure_ascii=False)
                return JSONResponse(
                    _make_result(req_id, {
                        "content": [{"type": "text", "text": text_content}]
                    })
                )

            else:
                return JSONResponse(
                    _make_error(req_id, -32601, f"未知工具: {tool_name}"),
                )

        except RuntimeError as e:
            msg = str(e)
            if "登录失败" in msg or "认证" in msg:
                return JSONResponse(_make_error(req_id, -32002, f"Tableau 认证失败: {msg}"))
            return JSONResponse(_make_error(req_id, -32603, f"Internal Error: {msg}"))
        except Exception as e:
            logger.exception("tableau_mcp tools/call unexpected error")
            return JSONResponse(_make_error(req_id, -32603, f"Internal Error: {e}"))

    # ── 未知 method ──────────────────────────────────────────────────────────
    return JSONResponse(
        _make_error(req_id, -32601, f"Method not found: {method}"),
    )

"""
内置 Tableau MCP Server

暴露在 /tableau-mcp 路径，实现 MCP JSON-RPC 2.0 协议，
内部调用 Tableau REST API。
"""
import asyncio
import json
import logging
import os
import urllib.parse
from datetime import datetime

import httpx
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, StreamingResponse
from sqlalchemy import or_

from app.core.database import SessionLocal
from services.mcp.models import McpServer
from services.semantic_maintenance.models import (
    TableauFieldSemantics,
    TableauFieldSemanticVersion,
)

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


def _get_tableau_config(server_id: int | None = None) -> dict:
    """
    读取 Tableau 连接配置，优先级：
    1. 指定 server_id → 直接取该记录
    2. 环境变量（TABLEAU_SERVER / TABLEAU_SITE / TABLEAU_PAT_NAME / TABLEAU_PAT_TOKEN）
    3. DB 里 type='tableau' 且 is_active=True 的 McpServer credentials
    """
    if server_id is not None:
        db = SessionLocal()
        try:
            record = db.query(McpServer).filter(McpServer.id == server_id).first()
            if not record or not record.credentials:
                return {}
            return dict(record.credentials)
        finally:
            db.close()

    # 环境变量优先，支持 tester 独立注入
    env_server = os.environ.get("TABLEAU_SERVER", "").rstrip("/")
    env_site = os.environ.get("TABLEAU_SITE", "")
    env_pat_name = os.environ.get("TABLEAU_PAT_NAME", "")
    env_pat_token = os.environ.get("TABLEAU_PAT_TOKEN", "")

    if env_server and env_pat_name and env_pat_token:
        return {
            "tableau_server": env_server,
            "site_name": env_site,
            "pat_name": env_pat_name,
            "pat_value": env_pat_token,
        }

    # 回退到 DB
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


# ── P2 工具实现函数 ────────────────────────────────────────────────────────────

async def _query_datasource(
    credentials: dict,
    datasource_luid: str,
    fields: list,
    filters: list,
    limit: int,
) -> dict:
    """通过 VizQL Data Service 查询 Tableau 数据源，返回数据行。"""
    tableau_server = credentials["tableau_server"]
    pat_name = credentials["pat_name"]
    pat_value = credentials.get("pat_value", "")
    site_name = credentials.get("site_name", "")

    token, site_id = await _tableau_signin(tableau_server, pat_name, pat_value, site_name)

    url = f"{tableau_server.rstrip('/')}/api/v1/vizql-data-service/query-datasource"
    body = {
        "datasource": {"datasourceLuid": datasource_luid},
        "fields": [{"fieldName": f} for f in fields],
        "options": {"maxRows": limit},
    }
    if filters:
        body["filters"] = filters

    async with httpx.AsyncClient(timeout=60.0, verify=False) as client:
        resp = await client.post(
            url,
            json=body,
            headers={
                "x-tableau-auth": token,
                "Accept": "application/json",
                "Content-Type": "application/json",
            },
        )
    if resp.status_code != 200:
        raise RuntimeError(f"VizQL Data Service 查询失败 (HTTP {resp.status_code}): {resp.text[:200]}")

    data = resp.json()
    return {
        "columns": data.get("columnTypes", []),
        "rows": data.get("data", []),
        "rowCount": len(data.get("data", [])),
    }


async def _search_content(
    credentials: dict,
    terms: str,
    content_types: list,
    limit: int,
) -> dict:
    """调用 Tableau Search API，跨类型全站内容搜索。"""
    tableau_server = credentials["tableau_server"]
    pat_name = credentials["pat_name"]
    pat_value = credentials.get("pat_value", "")
    site_name = credentials.get("site_name", "")

    token, site_id = await _tableau_signin(tableau_server, pat_name, pat_value, site_name)

    params: dict = {"q": terms, "limit": limit}
    if content_types:
        params["type"] = ",".join(content_types)

    url = f"{tableau_server.rstrip('/')}/api/3.20/sites/{site_id}/search"
    async with httpx.AsyncClient(timeout=30.0, verify=False) as client:
        resp = await client.get(
            url,
            params=params,
            headers={"x-tableau-auth": token, "Accept": "application/json"},
        )
    if resp.status_code != 200:
        raise RuntimeError(f"内容搜索失败 (HTTP {resp.status_code})")

    data = resp.json()
    results = data.get("searchResult", {}).get("hits", {}).get("hit", [])
    if isinstance(results, dict):
        results = [results]
    return {
        "results": [
            {
                "type": r.get("type", ""),
                "name": r.get("value", {}).get("name", ""),
                "luid": r.get("value", {}).get("luid", ""),
                "project": r.get("value", {}).get("projectName", ""),
                "owner": r.get("value", {}).get("ownerName", ""),
            }
            for r in results
        ],
        "total": len(results),
    }


async def _get_workbook(credentials: dict, workbook_id: str) -> dict:
    """获取指定工作簿的详情及视图列表。"""
    tableau_server = credentials["tableau_server"]
    pat_name = credentials["pat_name"]
    pat_value = credentials.get("pat_value", "")
    site_name = credentials.get("site_name", "")

    token, site_id = await _tableau_signin(tableau_server, pat_name, pat_value, site_name)
    base = tableau_server.rstrip("/")

    async with httpx.AsyncClient(timeout=30.0, verify=False) as client:
        resp = await client.get(
            f"{base}/api/3.20/sites/{site_id}/workbooks/{workbook_id}",
            headers={"x-tableau-auth": token, "Accept": "application/json"},
        )
        if resp.status_code != 200:
            raise RuntimeError(f"获取工作簿详情失败 (HTTP {resp.status_code})")
        wb = resp.json().get("workbook", {})

        views_resp = await client.get(
            f"{base}/api/3.20/sites/{site_id}/workbooks/{workbook_id}/views",
            headers={"x-tableau-auth": token, "Accept": "application/json"},
        )
        views = []
        if views_resp.status_code == 200:
            raw = views_resp.json().get("views", {}).get("view", [])
            if isinstance(raw, dict):
                raw = [raw]
            views = [
                {
                    "name": v.get("name", ""),
                    "luid": v.get("id", ""),
                    "contentUrl": v.get("contentUrl", ""),
                }
                for v in raw
            ]

    return {
        "name": wb.get("name", ""),
        "luid": wb.get("id", ""),
        "projectName": (wb.get("project") or {}).get("name", ""),
        "description": wb.get("description", ""),
        "updatedAt": wb.get("updatedAt", ""),
        "views": views,
    }


async def _list_views(credentials: dict, workbook_id: str, limit: int) -> dict:
    """列出视图列表，可按 workbook_id 过滤。"""
    tableau_server = credentials["tableau_server"]
    pat_name = credentials["pat_name"]
    pat_value = credentials.get("pat_value", "")
    site_name = credentials.get("site_name", "")

    token, site_id = await _tableau_signin(tableau_server, pat_name, pat_value, site_name)
    base = tableau_server.rstrip("/")

    if workbook_id:
        url = f"{base}/api/3.20/sites/{site_id}/workbooks/{workbook_id}/views"
    else:
        url = f"{base}/api/3.20/sites/{site_id}/views?pageSize={min(limit, 100)}"

    async with httpx.AsyncClient(timeout=30.0, verify=False) as client:
        resp = await client.get(
            url,
            headers={"x-tableau-auth": token, "Accept": "application/json"},
        )
    if resp.status_code != 200:
        raise RuntimeError(f"获取视图列表失败 (HTTP {resp.status_code})")

    data = resp.json()
    raw = data.get("views", {}).get("view", [])
    if isinstance(raw, dict):
        raw = [raw]
    views = [
        {
            "name": v.get("name", ""),
            "luid": v.get("id", ""),
            "contentUrl": v.get("contentUrl", ""),
            "workbook": (v.get("workbook") or {}).get("name", ""),
            "owner": (v.get("owner") or {}).get("name", ""),
            "updatedAt": v.get("updatedAt", ""),
        }
        for v in raw[:limit]
    ]
    return {"views": views, "count": len(views)}


async def _get_view_data(credentials: dict, view_id: str, filters: dict) -> dict:
    """获取视图数据（CSV），转换为 JSON 行返回。"""
    import csv
    import io

    tableau_server = credentials["tableau_server"]
    pat_name = credentials["pat_name"]
    pat_value = credentials.get("pat_value", "")
    site_name = credentials.get("site_name", "")

    token, site_id = await _tableau_signin(tableau_server, pat_name, pat_value, site_name)

    params: dict = {}
    for field, value in (filters or {}).items():
        params[f"vf_{field}"] = value

    url = f"{tableau_server.rstrip('/')}/api/3.20/sites/{site_id}/views/{view_id}/data"
    async with httpx.AsyncClient(timeout=60.0, verify=False) as client:
        resp = await client.get(
            url,
            params=params,
            headers={"x-tableau-auth": token, "Accept": "text/csv"},
        )
    if resp.status_code != 200:
        raise RuntimeError(f"获取视图数据失败 (HTTP {resp.status_code})")

    reader = csv.DictReader(io.StringIO(resp.text))
    rows = list(reader)
    return {"rows": rows, "rowCount": len(rows)}


# ── P2.3 工具实现函数 ──────────────────────────────────────────────────────────

async def _get_view_image(credentials: dict, view_id: str, fmt: str) -> dict:
    """获取视图截图，返回 base64 编码图片。fmt: 'png'（默认）或 'svg'。"""
    import base64

    tableau_server = credentials["tableau_server"]
    pat_name = credentials["pat_name"]
    pat_value = credentials.get("pat_value", "")
    site_name = credentials.get("site_name", "")

    token, site_id = await _tableau_signin(tableau_server, pat_name, pat_value, site_name)

    accept = "image/svg+xml" if fmt == "svg" else "image/png"
    url = f"{tableau_server.rstrip('/')}/api/3.20/sites/{site_id}/views/{view_id}/image"
    async with httpx.AsyncClient(timeout=60.0, verify=False) as client:
        resp = await client.get(
            url,
            headers={"x-tableau-auth": token, "Accept": accept},
        )
    if resp.status_code != 200:
        raise RuntimeError(f"获取视图截图失败 (HTTP {resp.status_code})")

    encoded = base64.b64encode(resp.content).decode("utf-8")
    return {"format": fmt, "data": encoded, "mimeType": accept}


def _pulse_headers(token: str) -> dict:
    return {"x-tableau-auth": token, "Accept": "application/json", "Content-Type": "application/json"}


async def _list_all_pulse_metric_definitions(credentials: dict, view: str, limit: int) -> dict:
    """列出所有 Pulse 指标定义（需要 Tableau Cloud / Server 2024.2+）。"""
    tableau_server = credentials["tableau_server"]
    token, _ = await _tableau_signin(
        tableau_server, credentials["pat_name"], credentials.get("pat_value", ""), credentials.get("site_name", "")
    )
    params: dict = {"page_size": min(limit, 200)}
    if view:
        params["view"] = view
    url = f"{tableau_server.rstrip('/')}/api/pulse/v1/definition"
    async with httpx.AsyncClient(timeout=30.0, verify=False) as client:
        resp = await client.get(url, params=params, headers=_pulse_headers(token))
    if resp.status_code == 404:
        raise RuntimeError("Pulse API 不可用，请确认 Tableau Server 版本 ≥ 2024.2 或使用 Tableau Cloud")
    if resp.status_code != 200:
        raise RuntimeError(f"Pulse API 调用失败 (HTTP {resp.status_code}): {resp.text[:200]}")
    return resp.json()


async def _list_pulse_metric_definitions_from_ids(credentials: dict, definition_ids: list, view: str) -> dict:
    """按定义 ID 列表查询 Pulse 指标定义。"""
    tableau_server = credentials["tableau_server"]
    token, _ = await _tableau_signin(
        tableau_server, credentials["pat_name"], credentials.get("pat_value", ""), credentials.get("site_name", "")
    )
    params: list = [("definition_id", did) for did in definition_ids]
    if view:
        params.append(("view", view))
    url = f"{tableau_server.rstrip('/')}/api/pulse/v1/definition"
    async with httpx.AsyncClient(timeout=30.0, verify=False) as client:
        resp = await client.get(url, params=params, headers=_pulse_headers(token))
    if resp.status_code == 404:
        raise RuntimeError("Pulse API 不可用，请确认 Tableau Server 版本 ≥ 2024.2 或使用 Tableau Cloud")
    if resp.status_code != 200:
        raise RuntimeError(f"Pulse API 调用失败 (HTTP {resp.status_code})")
    return resp.json()


async def _list_pulse_metrics_from_definition_id(credentials: dict, definition_id: str) -> dict:
    """按指标定义 ID 查询所有 Pulse 指标。"""
    tableau_server = credentials["tableau_server"]
    token, _ = await _tableau_signin(
        tableau_server, credentials["pat_name"], credentials.get("pat_value", ""), credentials.get("site_name", "")
    )
    url = f"{tableau_server.rstrip('/')}/api/pulse/v1/metric"
    async with httpx.AsyncClient(timeout=30.0, verify=False) as client:
        resp = await client.get(url, params={"definition_id": definition_id}, headers=_pulse_headers(token))
    if resp.status_code == 404:
        raise RuntimeError("Pulse API 不可用，请确认 Tableau Server 版本 ≥ 2024.2 或使用 Tableau Cloud")
    if resp.status_code != 200:
        raise RuntimeError(f"Pulse API 调用失败 (HTTP {resp.status_code})")
    return resp.json()


async def _list_pulse_metrics_from_ids(credentials: dict, metric_ids: list) -> dict:
    """按指标 ID 列表查询 Pulse 指标。"""
    tableau_server = credentials["tableau_server"]
    token, _ = await _tableau_signin(
        tableau_server, credentials["pat_name"], credentials.get("pat_value", ""), credentials.get("site_name", "")
    )
    params = [("metric_id", mid) for mid in metric_ids]
    url = f"{tableau_server.rstrip('/')}/api/pulse/v1/metric"
    async with httpx.AsyncClient(timeout=30.0, verify=False) as client:
        resp = await client.get(url, params=params, headers=_pulse_headers(token))
    if resp.status_code == 404:
        raise RuntimeError("Pulse API 不可用，请确认 Tableau Server 版本 ≥ 2024.2 或使用 Tableau Cloud")
    if resp.status_code != 200:
        raise RuntimeError(f"Pulse API 调用失败 (HTTP {resp.status_code})")
    return resp.json()


async def _list_pulse_metric_subscriptions(credentials: dict) -> dict:
    """列出当前用户的所有 Pulse 指标订阅。"""
    tableau_server = credentials["tableau_server"]
    token, _ = await _tableau_signin(
        tableau_server, credentials["pat_name"], credentials.get("pat_value", ""), credentials.get("site_name", "")
    )
    url = f"{tableau_server.rstrip('/')}/api/pulse/v1/subscription"
    async with httpx.AsyncClient(timeout=30.0, verify=False) as client:
        resp = await client.get(url, headers=_pulse_headers(token))
    if resp.status_code == 404:
        raise RuntimeError("Pulse API 不可用，请确认 Tableau Server 版本 ≥ 2024.2 或使用 Tableau Cloud")
    if resp.status_code != 200:
        raise RuntimeError(f"Pulse API 调用失败 (HTTP {resp.status_code})")
    return resp.json()


async def _generate_pulse_insight_bundle(credentials: dict, bundle_request: dict, bundle_type: str) -> dict:
    """为 Pulse 指标值生成洞察捆绑包。"""
    tableau_server = credentials["tableau_server"]
    token, _ = await _tableau_signin(
        tableau_server, credentials["pat_name"], credentials.get("pat_value", ""), credentials.get("site_name", "")
    )
    body = {"bundle_request": bundle_request}
    if bundle_type:
        body["bundle_type"] = bundle_type
    url = f"{tableau_server.rstrip('/')}/api/pulse/v1/insight/batch_create_metric_insights"
    async with httpx.AsyncClient(timeout=60.0, verify=False) as client:
        resp = await client.post(url, json=body, headers=_pulse_headers(token))
    if resp.status_code == 404:
        raise RuntimeError("Pulse Insight API 不可用，请确认 Tableau Server 版本 ≥ 2024.2 或使用 Tableau Cloud")
    if resp.status_code not in (200, 201):
        raise RuntimeError(f"Pulse Insight API 调用失败 (HTTP {resp.status_code}): {resp.text[:200]}")
    return resp.json()


async def _generate_pulse_insight_brief(credentials: dict, brief_request: dict) -> dict:
    """通过 AI 对话生成 Pulse 指标洞察摘要（支持多轮对话）。"""
    tableau_server = credentials["tableau_server"]
    token, _ = await _tableau_signin(
        tableau_server, credentials["pat_name"], credentials.get("pat_value", ""), credentials.get("site_name", "")
    )
    url = f"{tableau_server.rstrip('/')}/api/pulse/v1/insight/chat"
    async with httpx.AsyncClient(timeout=60.0, verify=False) as client:
        resp = await client.post(url, json=brief_request, headers=_pulse_headers(token))
    if resp.status_code == 404:
        raise RuntimeError("Pulse Insight Chat API 不可用，请确认 Tableau Server 版本 ≥ 2024.2 或使用 Tableau Cloud")
    if resp.status_code not in (200, 201):
        raise RuntimeError(f"Pulse Insight Chat API 调用失败 (HTTP {resp.status_code}): {resp.text[:200]}")
    return resp.json()


async def _revoke_access_token(credentials: dict) -> dict:
    """撤销当前会话使用的 Tableau 访问令牌（调用后 server 需重新登录）。"""
    tableau_server = credentials["tableau_server"]
    pat_name = credentials["pat_name"]
    pat_value = credentials.get("pat_value", "")
    site_name = credentials.get("site_name", "")

    token, _ = await _tableau_signin(tableau_server, pat_name, pat_value, site_name)
    url = f"{tableau_server.rstrip('/')}/api/3.20/auth/signout"
    async with httpx.AsyncClient(timeout=30.0, verify=False) as client:
        resp = await client.post(url, headers={"x-tableau-auth": token, "Accept": "application/json"})
    if resp.status_code not in (200, 204):
        raise RuntimeError(f"撤销令牌失败 (HTTP {resp.status_code})")
    return {"success": True, "message": "访问令牌已撤销，后续请求需重新认证"}


async def _reset_consent(credentials: dict) -> dict:
    """重置 Tableau OAuth 同意记录（仅适用于使用 Bearer 认证模式的场景）。"""
    tableau_server = credentials["tableau_server"]
    pat_name = credentials["pat_name"]
    pat_value = credentials.get("pat_value", "")
    site_name = credentials.get("site_name", "")

    token, _ = await _tableau_signin(tableau_server, pat_name, pat_value, site_name)
    url = f"{tableau_server.rstrip('/')}/api/3.20/auth/oauth/consent"
    async with httpx.AsyncClient(timeout=30.0, verify=False) as client:
        resp = await client.delete(url, headers={"x-tableau-auth": token, "Accept": "application/json"})
    if resp.status_code == 404:
        raise RuntimeError("OAuth Consent API 不可用，此功能仅适用于启用了 Tableau 授权服务器的场景")
    if resp.status_code not in (200, 204):
        raise RuntimeError(f"重置 OAuth 同意失败 (HTTP {resp.status_code})")
    return {"success": True, "message": "OAuth 同意已重置"}


# ── P3 新增工具实现函数 ────────────────────────────────────────────────────────

# 用于调用内部 Mulan API 的 base URL，优先从环境变量读取
_MULAN_INTERNAL_BASE_URL: str = os.environ.get("MULAN_INTERNAL_API_BASE_URL", "http://localhost:8000")

# GraphQL 查询：完整字段 schema（含 formula 等大字段）
_GQL_FULL_FIELDS = """
{ publishedDatasourcesConnection(filter: {luid: "%s"}) {
    nodes {
      luid
      name
      fields {
        name
        fullyQualifiedName
        description
        dataType
        role
        dataCategory
        isHidden
        formula
        defaultAggregation
      }
    }
  }
}
"""


async def _get_field_schema(credentials: dict, datasource_luid: str) -> dict:
    """获取 Tableau 数据源字段的完整 schema（含 role / dataType / formula）。"""
    tableau_server = credentials["tableau_server"]
    pat_name = credentials["pat_name"]
    pat_value = credentials.get("pat_value", "")
    site_name = credentials.get("site_name", "")

    token, _ = await _tableau_signin(tableau_server, pat_name, pat_value, site_name)

    graphql_url = f"{tableau_server.rstrip('/')}/api/metadata/graphql"
    gql_query = _GQL_FULL_FIELDS % datasource_luid.replace('"', '\\"')

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
        raise RuntimeError(
            f"Metadata API 调用失败 (HTTP {resp.status_code}): {resp.text[:300]}"
        )

    data = resp.json()
    if "errors" in data:
        raise RuntimeError(f"Tableau GraphQL 错误: {data['errors']}")

    nodes = (
        data.get("data", {})
        .get("publishedDatasourcesConnection", {})
        .get("nodes", [])
    )
    if not nodes:
        return {
            "datasource_luid": datasource_luid,
            "datasource_name": None,
            "field_count": 0,
            "fields": [],
        }

    node = nodes[0]
    raw_fields = node.get("fields", [])
    fields = [
        {
            "name": f.get("name", ""),
            "fully_qualified_name": f.get("fullyQualifiedName", ""),
            "data_type": f.get("dataType"),
            "role": f.get("role"),
            "data_category": f.get("dataCategory"),
            "description": f.get("description"),
            "formula": f.get("formula"),
            "default_aggregation": f.get("defaultAggregation"),
            "is_hidden": f.get("isHidden", False),
        }
        for f in raw_fields
    ]

    return {
        "datasource_luid": node.get("luid", datasource_luid),
        "datasource_name": node.get("name", ""),
        "field_count": len(fields),
        "fields": fields,
    }


async def _resolve_field_name(
    connection_id: int,
    fuzzy_name: str,
    datasource_luid: str,
    top_k: int,
) -> dict:
    """将模糊字段名映射到语义层候选字段。

    优先调用内部向量搜索 API；若该 API 不可用（404/连接失败），
    降级为对 tableau_field_semantics 表做 LIKE 查询。
    """
    resolve_url = f"{_MULAN_INTERNAL_BASE_URL}/api/semantic-maintenance/fields/resolve"
    payload: dict = {
        "connection_id": connection_id,
        "fuzzy_name": fuzzy_name,
        "top_k": top_k,
    }
    if datasource_luid:
        payload["datasource_luid"] = datasource_luid

    # --- 优先尝试内部 API ---
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            api_resp = await client.post(resolve_url, json=payload)

        if api_resp.status_code == 404:
            logger.info(
                "_resolve_field_name: 内部 API %s 尚未实现，切换 DB fallback", resolve_url
            )
        elif api_resp.status_code == 200:
            return api_resp.json()
        else:
            logger.warning(
                "_resolve_field_name: 内部 API 返回 %s，切换 DB fallback",
                api_resp.status_code,
            )
    except httpx.ConnectError:
        logger.info(
            "_resolve_field_name: 内部 API 连接失败（服务未启动），切换 DB fallback"
        )
    except Exception as exc:
        logger.warning("_resolve_field_name: 内部 API 调用异常 %s，切换 DB fallback", exc)

    # --- DB fallback：LIKE 查询 ---
    db = SessionLocal()
    try:
        q = db.query(TableauFieldSemantics).filter(
            TableauFieldSemantics.connection_id == connection_id,
            or_(
                TableauFieldSemantics.semantic_name.ilike(f"%{fuzzy_name}%"),
                TableauFieldSemantics.semantic_name_zh.ilike(f"%{fuzzy_name}%"),
                TableauFieldSemantics.tableau_field_id.ilike(f"%{fuzzy_name}%"),
            ),
        )
        rows = q.limit(top_k).all()
    finally:
        db.close()

    candidates = []
    for row in rows:
        # 判断命中了哪个字段，用于设置 match_source 和置信度
        fn_lower = fuzzy_name.lower()
        if row.semantic_name_zh and fn_lower in (row.semantic_name_zh or "").lower():
            match_source = "semantic_name_zh_like"
            confidence = 0.7
        elif row.semantic_name and fn_lower in (row.semantic_name or "").lower():
            match_source = "semantic_name_like"
            confidence = 0.65
        else:
            match_source = "tableau_field_id_like"
            confidence = 0.5

        candidates.append(
            {
                "tableau_field_id": row.tableau_field_id,
                "semantic_name": row.semantic_name,
                "semantic_name_zh": row.semantic_name_zh,
                "connection_id": row.connection_id,
                "role": None,  # TableauFieldSemantics 不直接存储 role
                "confidence": confidence,
                "match_source": match_source,
            }
        )

    return {
        "query": fuzzy_name,
        "method": "db_fallback",
        "blocking_note": (
            "向量搜索 API 未就绪（/api/semantic-maintenance/fields/resolve 尚未实现），"
            "当前使用 LIKE 查询（准确率较低）"
        ),
        "candidates": candidates,
    }


async def _get_datasource_fields_summary(
    credentials: dict,
    datasource_luid: str,
    include_hidden: bool,
) -> dict:
    """返回数据源所有字段的紧凑摘要，按 role 分组（DIMENSION / MEASURE / other）。"""
    tableau_server = credentials["tableau_server"]
    pat_name = credentials["pat_name"]
    pat_value = credentials.get("pat_value", "")
    site_name = credentials.get("site_name", "")

    token, _ = await _tableau_signin(tableau_server, pat_name, pat_value, site_name)

    graphql_url = f"{tableau_server.rstrip('/')}/api/metadata/graphql"
    # 只查摘要字段，不拉 formula 等大字段
    gql_query = (
        '{ publishedDatasourcesConnection(filter: {luid: "%s"}) {'
        '  nodes { luid name fields {'
        '    name fullyQualifiedName description dataType role isHidden defaultAggregation'
        '  } } } }'
    ) % datasource_luid.replace('"', '\\"')

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
        raise RuntimeError(
            f"Metadata API 调用失败 (HTTP {resp.status_code}): {resp.text[:300]}"
        )

    data = resp.json()
    if "errors" in data:
        raise RuntimeError(f"Tableau GraphQL 错误: {data['errors']}")

    nodes = (
        data.get("data", {})
        .get("publishedDatasourcesConnection", {})
        .get("nodes", [])
    )
    if not nodes:
        return {
            "datasource_luid": datasource_luid,
            "datasource_name": None,
            "total_fields": 0,
            "visible_fields": 0,
            "dimensions": [],
            "measures": [],
            "other_fields": [],
        }

    node = nodes[0]
    raw_fields = node.get("fields", [])
    total_fields = len(raw_fields)
    visible_fields = sum(1 for f in raw_fields if not f.get("isHidden", False))

    dimensions: list = []
    measures: list = []
    other_fields: list = []

    for f in raw_fields:
        is_hidden = f.get("isHidden", False)
        if is_hidden and not include_hidden:
            continue

        role = f.get("role", "")
        entry: dict = {
            "name": f.get("name", ""),
            "data_type": f.get("dataType"),
            "description": f.get("description"),
        }
        if role == "MEASURE":
            entry["default_aggregation"] = f.get("defaultAggregation")
            measures.append(entry)
        elif role == "DIMENSION":
            dimensions.append(entry)
        else:
            entry["role"] = role
            other_fields.append(entry)

    return {
        "datasource_luid": node.get("luid", datasource_luid),
        "datasource_name": node.get("name", ""),
        "total_fields": total_fields,
        "visible_fields": visible_fields,
        "dimensions": dimensions,
        "measures": measures,
        "other_fields": other_fields,
    }


# ── Agentic Phase 2 工具实现函数（视图控制 + 语义写回）──────────────────────


async def _get_view_filter_url(credentials: dict, view_id: str, filters: list) -> dict:
    """生成带 filter 参数的 Tableau 视图 URL（临时过滤视角）。"""
    tableau_server = credentials["tableau_server"]
    pat_name = credentials["pat_name"]
    pat_value = credentials.get("pat_value", "")
    site_name = credentials.get("site_name", "")

    token, site_id = await _tableau_signin(tableau_server, pat_name, pat_value, site_name)
    base = tableau_server.rstrip("/")

    # 获取视图的 content_url
    async with httpx.AsyncClient(timeout=30.0, verify=False) as client:
        resp = await client.get(
            f"{base}/api/3.20/sites/{site_id}/views/{view_id}",
            headers={"x-tableau-auth": token, "Accept": "application/json"},
        )
    if resp.status_code != 200:
        raise RuntimeError(f"获取视图详情失败 (HTTP {resp.status_code})")

    view_data = resp.json().get("view", {})
    content_url = view_data.get("contentUrl", "")
    view_name = view_data.get("name", "")

    # 构造 filter URL（content_url 已含 WorkbookName/sheets/ViewName）
    filter_parts = []
    for f in filters:
        field_enc = urllib.parse.quote(f["field_name"], safe="")
        value_enc = urllib.parse.quote(f["value"], safe="")
        filter_parts.append(f"vf_{field_enc}={value_enc}")

    query_string = "&".join(filter_parts)
    filter_url = f"{base}/views/{content_url}?{query_string}" if query_string else f"{base}/views/{content_url}"

    return {
        "view_id": view_id,
        "view_name": view_name,
        "filter_url": filter_url,
        "filters_applied": filters,
        "note": "此 URL 为临时过滤视角，需在浏览器中打开，不修改原始视图。",
    }


async def _create_custom_view(credentials: dict, view_id: str, custom_view_name: str, shared: bool) -> dict:
    """在 Tableau 创建带 filter 状态的 Custom View。"""
    tableau_server = credentials["tableau_server"]
    pat_name = credentials["pat_name"]
    pat_value = credentials.get("pat_value", "")
    site_name = credentials.get("site_name", "")

    token, site_id = await _tableau_signin(tableau_server, pat_name, pat_value, site_name)
    base = tableau_server.rstrip("/")

    # 自动追加 [Mulan Agent] 标签
    tagged_name = f"{custom_view_name} [Mulan Agent]"
    shared_str = "true" if shared else "false"

    xml_body = (
        f'<tsRequest>'
        f'<customView name="{tagged_name}" shared="{shared_str}">'
        f'<view id="{view_id}" />'
        f'</customView>'
        f'</tsRequest>'
    )

    async with httpx.AsyncClient(timeout=30.0, verify=False) as client:
        resp = await client.post(
            f"{base}/api/3.18/sites/{site_id}/customviews",
            content=xml_body.encode("utf-8"),
            headers={
                "x-tableau-auth": token,
                "Content-Type": "application/xml",
                "Accept": "application/json",
            },
        )

    if resp.status_code == 404:
        raise RuntimeError("Custom View API 需要 Tableau Server 3.18+")
    if resp.status_code not in (200, 201):
        raise RuntimeError(f"创建 Custom View 失败 (HTTP {resp.status_code}): {resp.text[:200]}")

    cv_data = resp.json().get("customView", {})
    result = {
        "custom_view_id": cv_data.get("id", ""),
        "custom_view_name": cv_data.get("name", tagged_name),
        "view_id": view_id,
        "shared": cv_data.get("shared", shared),
        "owner": (cv_data.get("owner") or {}).get("name", ""),
        "created_at": cv_data.get("createdAt", ""),
    }

    # 写审计日志
    db = SessionLocal()
    try:
        from app.api.mcp_debug import McpDebugLog
        log = McpDebugLog(
            user_id=0,
            username="mulan-agent",
            tool_name="create-custom-view",
            arguments_json={"view_id": view_id, "custom_view_name": custom_view_name, "shared": shared},
            status="success",
            result_summary=str(result)[:200],
            duration_ms=None,
        )
        db.add(log)
        db.commit()
    except Exception as log_exc:
        logger.warning("create-custom-view 审计日志写入失败: %s", log_exc)
    finally:
        db.close()

    return result


async def _update_custom_view(
    credentials: dict,
    custom_view_id: str,
    custom_view_name: str | None,
    shared: bool | None,
) -> dict:
    """更新已有 Custom View 的名称或共享状态。"""
    tableau_server = credentials["tableau_server"]
    pat_name = credentials["pat_name"]
    pat_value = credentials.get("pat_value", "")
    site_name = credentials.get("site_name", "")

    token, site_id = await _tableau_signin(tableau_server, pat_name, pat_value, site_name)
    base = tableau_server.rstrip("/")

    attrs = ""
    if custom_view_name is not None:
        attrs += f' name="{custom_view_name}"'
    if shared is not None:
        attrs += f' shared="{"true" if shared else "false"}"'

    xml_body = f'<tsRequest><customView{attrs} /></tsRequest>'

    async with httpx.AsyncClient(timeout=30.0, verify=False) as client:
        resp = await client.put(
            f"{base}/api/3.18/sites/{site_id}/customviews/{custom_view_id}",
            content=xml_body.encode("utf-8"),
            headers={
                "x-tableau-auth": token,
                "Content-Type": "application/xml",
                "Accept": "application/json",
            },
        )

    if resp.status_code == 404:
        raise RuntimeError("Custom View API 需要 Tableau Server 3.18+，或指定的 custom_view_id 不存在")
    if resp.status_code not in (200, 201):
        raise RuntimeError(f"更新 Custom View 失败 (HTTP {resp.status_code}): {resp.text[:200]}")

    cv_data = resp.json().get("customView", {})
    return {
        "custom_view_id": cv_data.get("id", custom_view_id),
        "custom_view_name": cv_data.get("name", ""),
        "shared": cv_data.get("shared", None),
        "owner": (cv_data.get("owner") or {}).get("name", ""),
        "updated": True,
    }


async def _list_custom_views_for_view(credentials: dict, view_id: str) -> dict:
    """列出某视图下的所有 Custom View（不传 view_id 则返回全站）。"""
    tableau_server = credentials["tableau_server"]
    pat_name = credentials["pat_name"]
    pat_value = credentials.get("pat_value", "")
    site_name = credentials.get("site_name", "")

    token, site_id = await _tableau_signin(tableau_server, pat_name, pat_value, site_name)
    base = tableau_server.rstrip("/")

    url = f"{base}/api/3.18/sites/{site_id}/customviews"
    params = {}
    if view_id:
        params["viewId"] = view_id

    async with httpx.AsyncClient(timeout=30.0, verify=False) as client:
        resp = await client.get(
            url,
            params=params,
            headers={"x-tableau-auth": token, "Accept": "application/json"},
        )

    if resp.status_code == 404:
        raise RuntimeError("Custom View API 需要 Tableau Server 3.18+")
    if resp.status_code != 200:
        raise RuntimeError(f"获取 Custom View 列表失败 (HTTP {resp.status_code}): {resp.text[:200]}")

    data = resp.json()
    raw = data.get("customViews", {}).get("customView", [])
    if isinstance(raw, dict):
        raw = [raw]
    custom_views = [
        {
            "custom_view_id": cv.get("id", ""),
            "custom_view_name": cv.get("name", ""),
            "shared": cv.get("shared", False),
            "owner": (cv.get("owner") or {}).get("name", ""),
            "view_id": (cv.get("view") or {}).get("id", ""),
            "view_name": (cv.get("view") or {}).get("name", ""),
            "created_at": cv.get("createdAt", ""),
            "updated_at": cv.get("updatedAt", ""),
        }
        for cv in raw
    ]
    return {"custom_views": custom_views, "count": len(custom_views)}


async def _update_field_semantic_attr(
    credentials: dict,
    datasource_luid: str,
    connection_id: int,
    field_name: str,
    attr_name: str,
    new_value: str,
    change_reason: str | None,
    tool_name_for_audit: str,
) -> dict:
    """
    通用内部函数：更新 TableauFieldSemantics 的指定属性（semantic_name 或 semantic_definition）。
    同时创建版本快照，写审计日志，尝试调用 Tableau REST API 更新 description。
    """
    tableau_server = credentials["tableau_server"]
    pat_name = credentials["pat_name"]
    pat_value = credentials.get("pat_value", "")
    site_name = credentials.get("site_name", "")

    db = SessionLocal()
    try:
        field_semantic = db.query(TableauFieldSemantics).filter(
            TableauFieldSemantics.connection_id == connection_id,
            TableauFieldSemantics.tableau_field_id == field_name,
        ).first()

        old_value = None
        semantic_record_id = None
        new_version = 1

        if field_semantic:
            old_value = getattr(field_semantic, attr_name, None)
            # 创建版本快照
            version_snapshot = TableauFieldSemanticVersion(
                field_semantic_id=field_semantic.id,
                version=field_semantic.version + 1,
                snapshot_json=field_semantic.to_dict(),
                changed_by=None,
                change_reason=change_reason or f"Agent 修改字段 {attr_name}",
            )
            db.add(version_snapshot)
            setattr(field_semantic, attr_name, new_value)
            field_semantic.version += 1
            field_semantic.source = "ai"
            field_semantic.status = "ai_generated"
            db.commit()
            semantic_record_id = field_semantic.id
            new_version = field_semantic.version
        else:
            # INSERT 新语义记录
            new_semantic = TableauFieldSemantics(
                connection_id=connection_id,
                tableau_field_id=field_name,
                source="ai",
                status="ai_generated",
                version=1,
            )
            setattr(new_semantic, attr_name, new_value)
            db.add(new_semantic)
            db.commit()
            db.refresh(new_semantic)
            semantic_record_id = new_semantic.id
            new_version = 1

        # 写审计日志
        try:
            from app.api.mcp_debug import McpDebugLog
            log = McpDebugLog(
                user_id=0,
                username="mulan-agent",
                tool_name=tool_name_for_audit,
                arguments_json={
                    "connection_id": connection_id,
                    "datasource_luid": datasource_luid,
                    "field_name": field_name,
                    attr_name: new_value,
                    "change_reason": change_reason,
                },
                status="success",
                result_summary=f"field={field_name}, {attr_name}={new_value[:80]}",
                duration_ms=None,
            )
            db.add(log)
            db.commit()
        except Exception as log_exc:
            logger.warning("%s 审计日志写入失败: %s", tool_name_for_audit, log_exc)

    finally:
        db.close()

    # 尝试 Tableau REST API 更新 datasource description（尽力而为）
    tableau_api_note = "Tableau REST API 不支持直接修改字段 Caption，已更新 Mulan 语义层。发布到 Tableau 请使用 publish-field-semantic 工具。"
    try:
        token, site_id = await _tableau_signin(tableau_server, pat_name, pat_value, site_name)
        base = tableau_server.rstrip("/")
        update_body = {
            "datasource": {"description": f"[Mulan Agent] {field_name} {attr_name} updated"}
        }
        async with httpx.AsyncClient(timeout=15.0, verify=False) as client:
            api_resp = await client.put(
                f"{base}/api/3.20/sites/{site_id}/datasources/{datasource_luid}",
                json=update_body,
                headers={
                    "x-tableau-auth": token,
                    "Accept": "application/json",
                    "Content-Type": "application/json",
                },
            )
        if api_resp.status_code not in (200, 201):
            tableau_api_note = (
                f"Tableau REST API 更新 datasource 元数据失败 (HTTP {api_resp.status_code})，"
                "但语义层已成功更新。"
            )
    except Exception as api_exc:
        logger.warning("%s Tableau API 更新失败（尽力而为）: %s", tool_name_for_audit, api_exc)

    return {
        "datasource_luid": datasource_luid,
        "field_name": field_name,
        "old_value": old_value,
        "new_value": new_value,
        "attr_updated": attr_name,
        "semantic_layer_updated": True,
        "semantic_record_id": semantic_record_id,
        "new_version": new_version,
        "tableau_api_note": tableau_api_note,
    }


async def _update_field_caption(
    credentials: dict,
    connection_id: int,
    datasource_luid: str,
    field_name: str,
    new_caption: str,
    change_reason: str | None,
) -> dict:
    """修改字段显示名称（Caption），同步更新 Mulan 语义层。"""
    result = await _update_field_semantic_attr(
        credentials=credentials,
        datasource_luid=datasource_luid,
        connection_id=connection_id,
        field_name=field_name,
        attr_name="semantic_name",
        new_value=new_caption,
        change_reason=change_reason,
        tool_name_for_audit="update-field-caption",
    )
    return {
        "datasource_luid": result["datasource_luid"],
        "field_name": result["field_name"],
        "old_caption": result["old_value"],
        "new_caption": result["new_value"],
        "semantic_layer_updated": result["semantic_layer_updated"],
        "semantic_record_id": result["semantic_record_id"],
        "new_version": result["new_version"],
        "tableau_api_note": result["tableau_api_note"],
    }


async def _update_field_description(
    credentials: dict,
    connection_id: int,
    datasource_luid: str,
    field_name: str,
    new_description: str,
    change_reason: str | None,
) -> dict:
    """修改字段描述，同步更新 Mulan 语义层 semantic_definition 字段。"""
    result = await _update_field_semantic_attr(
        credentials=credentials,
        datasource_luid=datasource_luid,
        connection_id=connection_id,
        field_name=field_name,
        attr_name="semantic_definition",
        new_value=new_description,
        change_reason=change_reason,
        tool_name_for_audit="update-field-description",
    )
    return {
        "datasource_luid": result["datasource_luid"],
        "field_name": result["field_name"],
        "old_description": result["old_value"],
        "new_description": result["new_value"],
        "semantic_layer_updated": result["semantic_layer_updated"],
        "semantic_record_id": result["semantic_record_id"],
        "new_version": result["new_version"],
        "tableau_api_note": result["tableau_api_note"],
    }


# ── Agentic Phase 3 工具实现函数（Parameter + VizQL RunCommand）────────────────

async def _get_workbook_parameters(credentials: dict, workbook_luid: str) -> dict:
    """通过 Metadata API GraphQL 查询工作簿中推断的 Parameter 列表。
    Tableau Metadata API 不直接暴露 Parameter 类型——Parameters 内部以计算字段方式存储。
    本函数返回 CalculatedField 中特征匹配的字段并标注为推断结果。
    """
    tableau_server = credentials["tableau_server"]
    pat_name = credentials["pat_name"]
    pat_value = credentials.get("pat_value", "")
    site_name = credentials.get("site_name", "")

    token, _ = await _tableau_signin(tableau_server, pat_name, pat_value, site_name)

    graphql_url = f"{tableau_server.rstrip('/')}/api/metadata/graphql"
    gql_query = (
        '{ publishedWorkbooksConnection(filter: {luid: "%s"}) {'
        '  nodes {'
        '    luid name'
        '    embeddedDatasourcesConnection {'
        '      nodes {'
        '        fields {'
        '          ... on CalculatedField {'
        '            name formula dataType role'
        '          }'
        '        }'
        '      }'
        '    }'
        '  }'
        '} }'
    ) % workbook_luid.replace('"', '\\"')

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
        raise RuntimeError(
            f"Metadata API 调用失败 (HTTP {resp.status_code}): {resp.text[:300]}"
        )

    data = resp.json()
    if "errors" in data:
        raise RuntimeError(f"Tableau GraphQL 错误: {data['errors']}")

    nodes = (
        data.get("data", {})
        .get("publishedWorkbooksConnection", {})
        .get("nodes", [])
    )
    if not nodes:
        return {
            "workbook_luid": workbook_luid,
            "workbook_name": None,
            "parameters": [],
            "blocking_note": "Tableau Metadata API 不提供完整 Parameter 元数据，结果为近似推断",
        }

    node = nodes[0]
    workbook_name = node.get("name", "")

    # 参数特征检测关键词（Parameters 在 Tableau 内部的计算字段特征）
    _PARAM_FORMULA_KEYWORDS = [
        "MAKEDATE", "MAKETIME", "MAKEDATETIME",
        "DATEADD", "DATEDIFF", "DATEPART",
        "Parameters.", "[Parameters.",
    ]
    _PARAM_ROLE_HINT = {"MEASURE", "DIMENSION"}

    parameters = []
    seen_names: set = set()

    ds_conn = node.get("embeddedDatasourcesConnection", {})
    for ds_node in ds_conn.get("nodes", []):
        for field in ds_node.get("fields", []):
            name = field.get("name", "")
            formula = field.get("formula") or ""
            data_type = field.get("dataType")
            role = field.get("role")

            if not name or name in seen_names:
                continue

            # 推断是否为 Parameter
            is_param = any(kw.lower() in formula.lower() for kw in _PARAM_FORMULA_KEYWORDS)
            if not is_param:
                # 名称包含 "Parameter" 或 "Param" 也视为候选
                if "parameter" in name.lower() or "param" in name.lower():
                    is_param = True

            if is_param:
                seen_names.add(name)
                parameters.append({
                    "name": name,
                    "data_type": data_type,
                    "formula": formula if formula else None,
                    "field_type": "parameter (inferred)",
                    "note": "Tableau REST API 不直接返回 Parameter 列表，以下为推断结果",
                })

    return {
        "workbook_luid": workbook_luid,
        "workbook_name": workbook_name,
        "parameters": parameters,
        "blocking_note": "Tableau Metadata API 不提供完整 Parameter 元数据，结果为近似推断",
    }


async def _set_parameter_via_url(credentials: dict, view_id: str, parameters: list) -> dict:
    """构造带 Parameter 值的 Tableau 视图 URL，供用户在浏览器中打开。
    与 get-view-filter-url 类似，但 query string 不加 vf_ 前缀。
    """
    tableau_server = credentials["tableau_server"]
    pat_name = credentials["pat_name"]
    pat_value = credentials.get("pat_value", "")
    site_name = credentials.get("site_name", "")

    token, site_id = await _tableau_signin(tableau_server, pat_name, pat_value, site_name)
    base = tableau_server.rstrip("/")

    # 获取视图的 content_url
    async with httpx.AsyncClient(timeout=30.0, verify=False) as client:
        resp = await client.get(
            f"{base}/api/3.20/sites/{site_id}/views/{view_id}",
            headers={"x-tableau-auth": token, "Accept": "application/json"},
        )
    if resp.status_code != 200:
        raise RuntimeError(f"获取视图详情失败 (HTTP {resp.status_code})")

    view_data = resp.json().get("view", {})
    content_url = view_data.get("contentUrl", "")
    view_name = view_data.get("name", "")

    # 构造 Parameter URL（不加 vf_ 前缀，直接用参数名）
    param_parts = []
    for p in parameters:
        param_name_enc = urllib.parse.quote_plus(p["param_name"])
        value_enc = urllib.parse.quote_plus(p["value"])
        param_parts.append(f"{param_name_enc}={value_enc}")

    query_string = "&".join(param_parts)
    param_url = f"{base}/views/{content_url}?{query_string}" if query_string else f"{base}/views/{content_url}"

    return {
        "view_id": view_id,
        "view_name": view_name,
        "parameter_url": param_url,
        "parameters_applied": parameters,
        "note": "此 URL 为带 Parameter 值的视图链接，需在浏览器中打开。Parameter 修改不持久化，刷新页面后恢复默认值。",
    }


async def _run_vizql_command(
    credentials: dict,
    datasource_luid: str,
    command_type: str,
    field_name: str,
    value: str,
) -> dict:
    """通过 VizQL RunCommand API 执行参数/过滤器修改（Server 2023.1+ beta）。
    此操作为会话级，不持久化。如需持久化请使用 create-custom-view。
    """
    tableau_server = credentials["tableau_server"]
    pat_name = credentials["pat_name"]
    pat_value = credentials.get("pat_value", "")
    site_name = credentials.get("site_name", "")

    token, _ = await _tableau_signin(tableau_server, pat_name, pat_value, site_name)

    url = f"{tableau_server.rstrip('/')}/api/v1/vizql-data-service/run-command"

    # 根据 command_type 构造命令体
    if command_type == "set-filter":
        command_fn = "filter"
        command_body = {
            "fn": command_fn,
            "fieldCaption": field_name,
            "values": [value],
        }
    elif command_type == "set-parameter":
        command_fn = "setParameter"
        command_body = {
            "fn": command_fn,
            "parameterName": field_name,
            "value": value,
        }
    else:
        raise RuntimeError(f"不支持的 command_type: {command_type}，必须为 set-filter 或 set-parameter")

    body = {
        "datasourceLuid": datasource_luid,
        "commands": [command_body],
    }

    async with httpx.AsyncClient(timeout=30.0, verify=False) as client:
        resp = await client.post(
            url,
            json=body,
            headers={
                "x-tableau-auth": token,
                "Accept": "application/json",
                "Content-Type": "application/json",
            },
        )

    if resp.status_code == 404:
        raise RuntimeError(
            "VizQL RunCommand API 不可用。请确认 Tableau Server 版本 >= 2023.1（该接口为 beta）。"
            "替代方案：使用 set-parameter-via-url 构造带参数的 URL，或使用 create-custom-view 保存视图状态。"
        )
    if resp.status_code not in (200, 201):
        raise RuntimeError(
            f"VizQL RunCommand API 调用失败 (HTTP {resp.status_code}): {resp.text[:200]}"
        )

    return {
        "command_type": command_type,
        "field_name": field_name,
        "value": value,
        "datasource_luid": datasource_luid,
        "status": "executed",
        "note": "VizQL RunCommand 为会话级操作，不持久化。如需持久化请使用 create-custom-view。",
    }


async def _publish_field_semantic(
    credentials: dict,
    connection_id: int,
    field_semantic_id: int,
) -> dict:
    """将已审批的字段语义标记为已发布，并尝试写回 Tableau。"""
    tableau_server = credentials["tableau_server"]
    pat_name = credentials["pat_name"]
    pat_value = credentials.get("pat_value", "")
    site_name = credentials.get("site_name", "")

    db = SessionLocal()
    try:
        field_semantic = db.query(TableauFieldSemantics).filter(
            TableauFieldSemantics.id == field_semantic_id,
        ).first()

        if not field_semantic:
            raise RuntimeError(f"未找到 field_semantic_id={field_semantic_id} 的语义记录")

        if field_semantic.status != "approved":
            raise RuntimeError(
                f"字段语义状态为 '{field_semantic.status}'，需先通过 review 流程将状态变更为 'approved' 才能发布。"
            )

        field_name = field_semantic.tableau_field_id
        datasource_luid = str(field_semantic.field_registry_id or "")  # 尽力而为获取 luid

        field_semantic.status = "published"
        field_semantic.published_to_tableau = True
        field_semantic.published_at = datetime.utcnow()
        db.commit()

        published_at_str = field_semantic.published_at.strftime("%Y-%m-%d %H:%M:%S")

        # 写审计日志
        try:
            from app.api.mcp_debug import McpDebugLog
            log = McpDebugLog(
                user_id=0,
                username="mulan-agent",
                tool_name="publish-field-semantic",
                arguments_json={
                    "connection_id": connection_id,
                    "field_semantic_id": field_semantic_id,
                },
                status="success",
                result_summary=f"field_semantic_id={field_semantic_id}, field={field_name}, status=published",
                duration_ms=None,
            )
            db.add(log)
            db.commit()
        except Exception as log_exc:
            logger.warning("publish-field-semantic 审计日志写入失败: %s", log_exc)

    finally:
        db.close()

    # 尝试 Tableau REST API 写回（尽力而为）
    tableau_sync_attempted = False
    tableau_sync_success = False
    tableau_sync_note = "Tableau REST API 不支持字段级写回，语义层状态已发布。"

    if datasource_luid:
        tableau_sync_attempted = True
        try:
            token, site_id = await _tableau_signin(tableau_server, pat_name, pat_value, site_name)
            base = tableau_server.rstrip("/")
            update_body = {"datasource": {"description": f"[Mulan Agent Published] {field_name}"}}
            async with httpx.AsyncClient(timeout=15.0, verify=False) as client:
                api_resp = await client.put(
                    f"{base}/api/3.20/sites/{site_id}/datasources/{datasource_luid}",
                    json=update_body,
                    headers={
                        "x-tableau-auth": token,
                        "Accept": "application/json",
                        "Content-Type": "application/json",
                    },
                )
            if api_resp.status_code in (200, 201):
                tableau_sync_success = True
                tableau_sync_note = "Tableau REST API 元数据更新成功（字段级写回仍需手动操作 .tds）。"
            else:
                tableau_sync_note = (
                    f"Tableau REST API 更新失败 (HTTP {api_resp.status_code})，"
                    "语义层状态已发布，Tableau 字段需手动同步。"
                )
        except Exception as sync_exc:
            logger.warning("publish-field-semantic Tableau 同步失败（尽力而为）: %s", sync_exc)
            tableau_sync_note = f"Tableau REST API 调用异常: {sync_exc}，语义层状态已发布。"

    return {
        "field_semantic_id": field_semantic_id,
        "field_name": field_name,
        "status": "published",
        "published_at": published_at_str,
        "tableau_sync_attempted": tableau_sync_attempted,
        "tableau_sync_success": tableau_sync_success,
        "tableau_sync_note": tableau_sync_note,
    }


# ── MCP JSON-RPC 核心处理（返回 dict，不含 HTTP 包装）────────────────────────

async def _process_mcp_body(body: dict, server_id: int | None = None) -> dict:
    """处理 MCP JSON-RPC 2.0 消息体，返回响应 dict（不含 JSONResponse 包装）。"""
    req_id = body.get("id")
    method = body.get("method", "")
    params = body.get("params", {})

    # ── initialize ───────────────────────────────────────────────────────────
    if method == "initialize":
        return _make_result(req_id, {
            "protocolVersion": "2025-06-18",
            "serverInfo": {"name": "mulan-tableau-mcp", "version": "1.0"},
            "capabilities": {"tools": {}},
        })

    # ── notifications/initialized ────────────────────────────────────────────
    if method == "notifications/initialized":
        return {"jsonrpc": "2.0", "result": None}

    # ── tools/list ───────────────────────────────────────────────────────────
    if method == "tools/list":
        return _make_result(req_id, {
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
                    "description": "列出 Tableau 所有已发布的工作簿（固定返回最多 100 条，无需传参）",
                    "inputSchema": {
                        "type": "object",
                        "properties": {},
                        "additionalProperties": False,
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
                {
                    "name": "query-datasource",
                    "description": "对 Tableau 数据源执行查询，返回真实数据行",
                    "inputSchema": {
                        "type": "object",
                        "properties": {
                            "datasource_luid": {"type": "string", "description": "数据源的 LUID"},
                            "fields": {
                                "type": "array",
                                "items": {"type": "string"},
                                "description": "要查询的字段名列表"
                            },
                            "filters": {
                                "type": "array",
                                "description": "过滤条件列表（可选），每项为 {field, operator, values}"
                            },
                            "limit": {"type": "integer", "description": "最多返回行数，默认 100", "default": 100}
                        },
                        "required": ["datasource_luid", "fields"],
                    },
                },
                {
                    "name": "search-content",
                    "description": "在 Tableau 站点全站搜索内容（工作簿、数据源、视图等）",
                    "inputSchema": {
                        "type": "object",
                        "properties": {
                            "terms": {"type": "string", "description": "搜索关键词"},
                            "content_types": {
                                "type": "array",
                                "items": {
                                    "type": "string",
                                    "enum": ["workbook", "datasource", "view", "flow", "lens"]
                                },
                                "description": "内容类型过滤（可选，不传则全类型搜索）"
                            },
                            "limit": {"type": "integer", "description": "最多返回条数，默认 20", "default": 20}
                        },
                        "required": ["terms"],
                    },
                },
                {
                    "name": "get-workbook",
                    "description": "获取指定工作簿的详情，包含所有视图列表",
                    "inputSchema": {
                        "type": "object",
                        "properties": {
                            "workbook_id": {"type": "string", "description": "工作簿的 LUID"}
                        },
                        "required": ["workbook_id"],
                    },
                },
                {
                    "name": "list-views",
                    "description": "列出 Tableau 站点的视图及元数据",
                    "inputSchema": {
                        "type": "object",
                        "properties": {
                            "workbook_id": {"type": "string", "description": "按工作簿 LUID 过滤（可选）"},
                            "limit": {"type": "integer", "description": "最多返回条数，默认 100", "default": 100}
                        },
                    },
                },
                {
                    "name": "get-view-data",
                    "description": "获取指定视图的数据（CSV 格式转为 JSON 行）",
                    "inputSchema": {
                        "type": "object",
                        "properties": {
                            "view_id": {"type": "string", "description": "视图的 LUID"},
                            "filters": {
                                "type": "object",
                                "description": "视图过滤字段与值的映射（可选），如 {\"Region\": \"West\"}"
                            }
                        },
                        "required": ["view_id"],
                    },
                },
                {
                    "name": "get-view-image",
                    "description": "获取视图的截图，返回 base64 编码图片",
                    "inputSchema": {
                        "type": "object",
                        "properties": {
                            "view_id": {"type": "string", "description": "视图的 LUID"},
                            "format": {
                                "type": "string",
                                "enum": ["png", "svg"],
                                "description": "图片格式，默认 png；svg 需要 Tableau Server 2026.2+",
                                "default": "png",
                            },
                        },
                        "required": ["view_id"],
                    },
                },
                {
                    "name": "list-all-pulse-metric-definitions",
                    "description": "列出 Tableau 站点所有已发布的 Pulse 指标定义（需要 Server 2024.2+）",
                    "inputSchema": {
                        "type": "object",
                        "properties": {
                            "view": {
                                "type": "string",
                                "enum": ["DEFINITION_VIEW_BASIC", "DEFINITION_VIEW_FULL", "DEFINITION_VIEW_DEFAULT"],
                                "description": "返回视图详细程度，默认 DEFINITION_VIEW_BASIC",
                                "default": "DEFINITION_VIEW_BASIC",
                            },
                            "limit": {"type": "integer", "description": "最多返回条数，默认 50", "default": 50},
                        },
                    },
                },
                {
                    "name": "list-pulse-metric-definitions-from-definition-ids",
                    "description": "按定义 ID 列表查询 Pulse 指标定义（需要 Server 2024.2+）",
                    "inputSchema": {
                        "type": "object",
                        "properties": {
                            "definition_ids": {
                                "type": "array",
                                "items": {"type": "string"},
                                "description": "指标定义 ID 列表（36 字符 UUID 格式）",
                            },
                            "view": {
                                "type": "string",
                                "enum": ["DEFINITION_VIEW_BASIC", "DEFINITION_VIEW_FULL", "DEFINITION_VIEW_DEFAULT"],
                                "description": "返回视图详细程度",
                            },
                        },
                        "required": ["definition_ids"],
                    },
                },
                {
                    "name": "list-pulse-metrics-from-metric-definition-id",
                    "description": "按指标定义 ID 查询所有 Pulse 指标（需要 Server 2024.2+）",
                    "inputSchema": {
                        "type": "object",
                        "properties": {
                            "definition_id": {"type": "string", "description": "Pulse 指标定义 ID（36 字符 UUID）"},
                        },
                        "required": ["definition_id"],
                    },
                },
                {
                    "name": "list-pulse-metrics-from-metric-ids",
                    "description": "按指标 ID 列表查询 Pulse 指标（需要 Server 2024.2+）",
                    "inputSchema": {
                        "type": "object",
                        "properties": {
                            "metric_ids": {
                                "type": "array",
                                "items": {"type": "string"},
                                "description": "Pulse 指标 ID 列表（36 字符 UUID 格式）",
                            },
                        },
                        "required": ["metric_ids"],
                    },
                },
                {
                    "name": "list-pulse-metric-subscriptions",
                    "description": "列出当前用户的所有 Pulse 指标订阅（需要 Server 2024.2+）",
                    "inputSchema": {
                        "type": "object",
                        "properties": {},
                        "additionalProperties": False,
                    },
                },
                {
                    "name": "generate-pulse-metric-value-insight-bundle",
                    "description": "为 Pulse 指标值生成 AI 洞察捆绑包（需要 Server 2024.2+）",
                    "inputSchema": {
                        "type": "object",
                        "properties": {
                            "bundle_request": {
                                "type": "object",
                                "description": "洞察捆绑生成请求体（含 metric、definition、output_format、time_zone、language 等）",
                            },
                            "bundle_type": {
                                "type": "string",
                                "enum": ["ban", "springboard", "basic", "detail"],
                                "description": "洞察类型：ban（基础）/ springboard / basic / detail（全面），默认 ban",
                                "default": "ban",
                            },
                        },
                        "required": ["bundle_request"],
                    },
                },
                {
                    "name": "generate-pulse-insight-brief",
                    "description": "通过 AI 多轮对话为 Pulse 指标生成洞察摘要（需要 Server 2024.2+）",
                    "inputSchema": {
                        "type": "object",
                        "properties": {
                            "brief_request": {
                                "type": "object",
                                "description": "对话请求体（含 language、locale、messages 数组、now、time_zone）",
                            },
                        },
                        "required": ["brief_request"],
                    },
                },
                {
                    "name": "revoke-access-token",
                    "description": "撤销当前 Tableau MCP 会话使用的访问令牌（破坏性操作，调用后需重新认证）",
                    "inputSchema": {
                        "type": "object",
                        "properties": {},
                        "additionalProperties": False,
                    },
                },
                {
                    "name": "reset-consent",
                    "description": "重置 Tableau OAuth 同意记录（仅适用于 Bearer 认证模式 / 启用了授权服务器的环境）",
                    "inputSchema": {
                        "type": "object",
                        "properties": {},
                        "additionalProperties": False,
                    },
                },
                {
                    "name": "get-field-schema",
                    "description": "获取 Tableau 数据源字段的完整 schema（含 role / dataType / formula / description 等），比 get-datasource-metadata 返回更完整的字段信息",
                    "inputSchema": {
                        "type": "object",
                        "properties": {
                            "connection_id": {
                                "type": "integer",
                                "description": "Mulan 连接 ID（当前暂不使用，预留用于多租户鉴权）"
                            },
                            "datasource_luid": {
                                "type": "string",
                                "description": "Tableau 数据源 LUID"
                            },
                        },
                        "required": ["connection_id", "datasource_luid"],
                    },
                },
                {
                    "name": "resolve-field-name",
                    "description": "将模糊字段名映射到语义层候选字段（含置信度）。优先调用内部向量搜索 API，不可用时降级为 LIKE 查询",
                    "inputSchema": {
                        "type": "object",
                        "properties": {
                            "connection_id": {
                                "type": "integer",
                                "description": "Mulan 连接 ID"
                            },
                            "fuzzy_name": {
                                "type": "string",
                                "description": "用户描述的模糊字段名，如'那个区域维度'"
                            },
                            "datasource_luid": {
                                "type": "string",
                                "description": "限定搜索范围的数据源 LUID（可选）"
                            },
                            "top_k": {
                                "type": "integer",
                                "description": "返回候选数量，默认 5",
                                "default": 5
                            },
                        },
                        "required": ["connection_id", "fuzzy_name"],
                    },
                },
                {
                    "name": "get-datasource-fields-summary",
                    "description": "返回数据源所有字段的紧凑摘要（name + role + dataType），按 role 分组，适合作为 LLM 上下文输入，供 LLM 在 query-datasource 前了解可用字段",
                    "inputSchema": {
                        "type": "object",
                        "properties": {
                            "connection_id": {
                                "type": "integer",
                                "description": "Mulan 连接 ID（当前暂不使用，预留用于多租户鉴权）"
                            },
                            "datasource_luid": {
                                "type": "string",
                                "description": "Tableau 数据源 LUID"
                            },
                            "include_hidden": {
                                "type": "boolean",
                                "description": "是否包含隐藏字段，默认 false",
                                "default": False,
                            },
                        },
                        "required": ["connection_id", "datasource_luid"],
                    },
                },
                # ── Agentic Phase 2：视图控制 + 语义写回 ──────────────────────
                {
                    "name": "get-view-filter-url",
                    "description": "生成带 filter 参数的 Tableau 视图 URL（临时过滤视角），用户在浏览器中打开，不修改原始视图",
                    "inputSchema": {
                        "type": "object",
                        "properties": {
                            "connection_id": {"type": "integer"},
                            "view_id": {"type": "string", "description": "视图的 Tableau LUID"},
                            "filters": {
                                "type": "array",
                                "description": "过滤条件列表",
                                "items": {
                                    "type": "object",
                                    "properties": {
                                        "field_name": {"type": "string"},
                                        "value": {"type": "string"},
                                    },
                                    "required": ["field_name", "value"],
                                },
                            },
                        },
                        "required": ["connection_id", "view_id", "filters"],
                    },
                },
                {
                    "name": "create-custom-view",
                    "description": "在 Tableau 创建带 filter 状态的 Custom View（需要 Tableau Server 3.18+）",
                    "inputSchema": {
                        "type": "object",
                        "properties": {
                            "connection_id": {"type": "integer"},
                            "view_id": {"type": "string", "description": "基础视图的 LUID"},
                            "custom_view_name": {"type": "string", "description": "自定义视图名称"},
                            "shared": {"type": "boolean", "description": "是否公开共享，默认 false", "default": False},
                        },
                        "required": ["connection_id", "view_id", "custom_view_name"],
                    },
                },
                {
                    "name": "update-custom-view",
                    "description": "更新已有 Custom View 的名称或共享状态（需要 Tableau Server 3.18+）",
                    "inputSchema": {
                        "type": "object",
                        "properties": {
                            "connection_id": {"type": "integer"},
                            "custom_view_id": {"type": "string", "description": "Custom View 的 LUID"},
                            "custom_view_name": {"type": "string", "description": "新名称（可选）"},
                            "shared": {"type": "boolean", "description": "是否公开共享（可选）"},
                        },
                        "required": ["connection_id", "custom_view_id"],
                    },
                },
                {
                    "name": "list-custom-views-for-view",
                    "description": "列出某视图下的所有 Custom View（需要 Tableau Server 3.18+），不传 view_id 则返回全站",
                    "inputSchema": {
                        "type": "object",
                        "properties": {
                            "connection_id": {"type": "integer"},
                            "view_id": {"type": "string", "description": "基础视图的 LUID（可选，不传则返回全站）"},
                        },
                        "required": ["connection_id"],
                    },
                },
                {
                    "name": "update-field-caption",
                    "description": "修改 Tableau 数据源字段的显示名称（Caption），并同步更新 Mulan 语义层。注意：Tableau REST API 不支持字段级写回，变更仅保存在语义层，需用 publish-field-semantic 发布",
                    "inputSchema": {
                        "type": "object",
                        "properties": {
                            "connection_id": {"type": "integer"},
                            "datasource_luid": {"type": "string"},
                            "field_name": {"type": "string", "description": "字段原始名称"},
                            "new_caption": {"type": "string", "description": "新的显示名称"},
                            "change_reason": {"type": "string", "description": "修改原因（用于审计）"},
                        },
                        "required": ["connection_id", "datasource_luid", "field_name", "new_caption"],
                    },
                },
                {
                    "name": "update-field-description",
                    "description": "修改 Tableau 数据源字段描述，并同步更新 Mulan 语义层 semantic_definition。注意：Tableau REST API 不支持字段级写回，变更仅保存在语义层，需用 publish-field-semantic 发布",
                    "inputSchema": {
                        "type": "object",
                        "properties": {
                            "connection_id": {"type": "integer"},
                            "datasource_luid": {"type": "string"},
                            "field_name": {"type": "string", "description": "字段原始名称"},
                            "new_description": {"type": "string", "description": "新的字段描述"},
                            "change_reason": {"type": "string", "description": "修改原因（用于审计）"},
                        },
                        "required": ["connection_id", "datasource_luid", "field_name", "new_description"],
                    },
                },
                {
                    "name": "publish-field-semantic",
                    "description": "将 Mulan 语义层中已审批（approved 状态）的字段语义标记为已发布，并尝试写回 Tableau（尽力而为，失败不回滚语义层状态）",
                    "inputSchema": {
                        "type": "object",
                        "properties": {
                            "connection_id": {"type": "integer"},
                            "field_semantic_id": {"type": "integer", "description": "tableau_field_semantics 表的主键 ID"},
                        },
                        "required": ["connection_id", "field_semantic_id"],
                    },
                },
                # ── Agentic Phase 3：Parameter 控制 + VizQL RunCommand ──────────
                {
                    "name": "get-workbook-parameters",
                    "description": "获取工作簿中所有推断的 Parameter 定义（名称、类型、公式）。注意：Tableau Metadata API 不直接暴露 Parameter 类型，结果为近似推断",
                    "inputSchema": {
                        "type": "object",
                        "properties": {
                            "connection_id": {"type": "integer"},
                            "workbook_luid": {"type": "string", "description": "工作簿的 Tableau LUID"},
                        },
                        "required": ["connection_id", "workbook_luid"],
                    },
                },
                {
                    "name": "set-parameter-via-url",
                    "description": "构造带 Parameter 值的 Tableau 视图 URL，供用户在浏览器中打开。Parameter 修改不持久化，刷新后恢复默认值",
                    "inputSchema": {
                        "type": "object",
                        "properties": {
                            "connection_id": {"type": "integer"},
                            "view_id": {"type": "string", "description": "视图 LUID"},
                            "parameters": {
                                "type": "array",
                                "items": {
                                    "type": "object",
                                    "properties": {
                                        "param_name": {"type": "string"},
                                        "value": {"type": "string"},
                                    },
                                    "required": ["param_name", "value"],
                                },
                                "description": "要设置的参数列表，每项含 param_name 和 value",
                            },
                        },
                        "required": ["connection_id", "view_id", "parameters"],
                    },
                },
                {
                    "name": "run-vizql-command",
                    "description": "通过 VizQL RunCommand API 执行参数/过滤器修改（Server 2023.1+ beta）。操作为会话级，不持久化",
                    "inputSchema": {
                        "type": "object",
                        "properties": {
                            "connection_id": {"type": "integer"},
                            "datasource_luid": {"type": "string"},
                            "command_type": {
                                "type": "string",
                                "enum": ["set-filter", "set-parameter"],
                                "description": "命令类型：set-filter 设置过滤器，set-parameter 设置参数值",
                            },
                            "field_name": {"type": "string", "description": "字段名或参数名"},
                            "value": {"type": "string", "description": "目标值"},
                        },
                        "required": ["connection_id", "datasource_luid", "command_type", "field_name", "value"],
                    },
                },
            ]
        })

    # ── tools/call ───────────────────────────────────────────────────────────
    if method == "tools/call":
        tool_name = params.get("name", "")
        arguments = params.get("arguments", {})

        credentials = _get_tableau_config(server_id)
        if not credentials:
            return _make_error(req_id, -32001, "未找到 Tableau MCP 配置")

        try:
            if tool_name == "list-datasources":
                datasources = await _list_datasources(credentials)
                text = json.dumps({"datasources": datasources}, ensure_ascii=False)
                return _make_result(req_id, {"content": [{"type": "text", "text": text}]})

            elif tool_name == "get-datasource-metadata":
                luid = arguments.get("datasource_luid", "")
                if not luid:
                    return _make_error(req_id, -32602, "缺少必要参数: datasource_luid")
                metadata = await _get_datasource_metadata(credentials, luid)
                text = json.dumps({"datasource": metadata}, ensure_ascii=False)
                return _make_result(req_id, {"content": [{"type": "text", "text": text}]})

            elif tool_name == "list-workbooks":
                workbooks = await _list_workbooks(credentials)
                text = json.dumps({"workbooks": workbooks}, ensure_ascii=False)
                return _make_result(req_id, {"content": [{"type": "text", "text": text}]})

            elif tool_name == "get-datasource-upstream-tables":
                ds_name = arguments.get("datasource_name", "")
                if not ds_name:
                    return _make_error(req_id, -32602, "缺少必要参数: datasource_name")
                tables = await _get_datasource_upstream_tables(credentials, ds_name)
                text = json.dumps({"tables": tables}, ensure_ascii=False)
                return _make_result(req_id, {"content": [{"type": "text", "text": text}]})

            elif tool_name == "get-datasource-downstream-workbooks":
                ds_name = arguments.get("datasource_name", "")
                if not ds_name:
                    return _make_error(req_id, -32602, "缺少必要参数: datasource_name")
                workbooks = await _get_datasource_downstream_workbooks(credentials, ds_name)
                text = json.dumps({"workbooks": workbooks}, ensure_ascii=False)
                return _make_result(req_id, {"content": [{"type": "text", "text": text}]})

            elif tool_name == "query-datasource":
                luid = arguments.get("datasource_luid", "")
                fields = arguments.get("fields", [])
                if not luid or not fields:
                    return _make_error(req_id, -32602, "缺少必要参数: datasource_luid 或 fields")
                filters = arguments.get("filters", [])
                limit = arguments.get("limit", 100)
                result = await _query_datasource(credentials, luid, fields, filters, limit)
                text = json.dumps(result, ensure_ascii=False)
                return _make_result(req_id, {"content": [{"type": "text", "text": text}]})

            elif tool_name == "search-content":
                terms = arguments.get("terms", "")
                if not terms:
                    return _make_error(req_id, -32602, "缺少必要参数: terms")
                content_types = arguments.get("content_types", [])
                limit = arguments.get("limit", 20)
                result = await _search_content(credentials, terms, content_types, limit)
                text = json.dumps(result, ensure_ascii=False)
                return _make_result(req_id, {"content": [{"type": "text", "text": text}]})

            elif tool_name == "get-workbook":
                workbook_id = arguments.get("workbook_id", "")
                if not workbook_id:
                    return _make_error(req_id, -32602, "缺少必要参数: workbook_id")
                result = await _get_workbook(credentials, workbook_id)
                text = json.dumps(result, ensure_ascii=False)
                return _make_result(req_id, {"content": [{"type": "text", "text": text}]})

            elif tool_name == "list-views":
                workbook_id = arguments.get("workbook_id", "")
                limit = arguments.get("limit", 100)
                result = await _list_views(credentials, workbook_id, limit)
                text = json.dumps(result, ensure_ascii=False)
                return _make_result(req_id, {"content": [{"type": "text", "text": text}]})

            elif tool_name == "get-view-data":
                view_id = arguments.get("view_id", "")
                if not view_id:
                    return _make_error(req_id, -32602, "缺少必要参数: view_id")
                filters = arguments.get("filters", {})
                result = await _get_view_data(credentials, view_id, filters)
                text = json.dumps(result, ensure_ascii=False)
                return _make_result(req_id, {"content": [{"type": "text", "text": text}]})

            elif tool_name == "get-view-image":
                view_id = arguments.get("view_id", "")
                if not view_id:
                    return _make_error(req_id, -32602, "缺少必要参数: view_id")
                fmt = arguments.get("format", "png")
                result = await _get_view_image(credentials, view_id, fmt)
                return _make_result(req_id, {"content": [{"type": "image", "data": result["data"], "mimeType": result["mimeType"]}]})

            elif tool_name == "list-all-pulse-metric-definitions":
                view = arguments.get("view", "")
                limit = arguments.get("limit", 50)
                result = await _list_all_pulse_metric_definitions(credentials, view, limit)
                text = json.dumps(result, ensure_ascii=False)
                return _make_result(req_id, {"content": [{"type": "text", "text": text}]})

            elif tool_name == "list-pulse-metric-definitions-from-definition-ids":
                definition_ids = arguments.get("definition_ids", [])
                if not definition_ids:
                    return _make_error(req_id, -32602, "缺少必要参数: definition_ids")
                view = arguments.get("view", "")
                result = await _list_pulse_metric_definitions_from_ids(credentials, definition_ids, view)
                text = json.dumps(result, ensure_ascii=False)
                return _make_result(req_id, {"content": [{"type": "text", "text": text}]})

            elif tool_name == "list-pulse-metrics-from-metric-definition-id":
                definition_id = arguments.get("definition_id", "")
                if not definition_id:
                    return _make_error(req_id, -32602, "缺少必要参数: definition_id")
                result = await _list_pulse_metrics_from_definition_id(credentials, definition_id)
                text = json.dumps(result, ensure_ascii=False)
                return _make_result(req_id, {"content": [{"type": "text", "text": text}]})

            elif tool_name == "list-pulse-metrics-from-metric-ids":
                metric_ids = arguments.get("metric_ids", [])
                if not metric_ids:
                    return _make_error(req_id, -32602, "缺少必要参数: metric_ids")
                result = await _list_pulse_metrics_from_ids(credentials, metric_ids)
                text = json.dumps(result, ensure_ascii=False)
                return _make_result(req_id, {"content": [{"type": "text", "text": text}]})

            elif tool_name == "list-pulse-metric-subscriptions":
                result = await _list_pulse_metric_subscriptions(credentials)
                text = json.dumps(result, ensure_ascii=False)
                return _make_result(req_id, {"content": [{"type": "text", "text": text}]})

            elif tool_name == "generate-pulse-metric-value-insight-bundle":
                bundle_request = arguments.get("bundle_request")
                if not bundle_request:
                    return _make_error(req_id, -32602, "缺少必要参数: bundle_request")
                bundle_type = arguments.get("bundle_type", "ban")
                result = await _generate_pulse_insight_bundle(credentials, bundle_request, bundle_type)
                text = json.dumps(result, ensure_ascii=False)
                return _make_result(req_id, {"content": [{"type": "text", "text": text}]})

            elif tool_name == "generate-pulse-insight-brief":
                brief_request = arguments.get("brief_request")
                if not brief_request:
                    return _make_error(req_id, -32602, "缺少必要参数: brief_request")
                result = await _generate_pulse_insight_brief(credentials, brief_request)
                text = json.dumps(result, ensure_ascii=False)
                return _make_result(req_id, {"content": [{"type": "text", "text": text}]})

            elif tool_name == "revoke-access-token":
                result = await _revoke_access_token(credentials)
                text = json.dumps(result, ensure_ascii=False)
                return _make_result(req_id, {"content": [{"type": "text", "text": text}]})

            elif tool_name == "reset-consent":
                result = await _reset_consent(credentials)
                text = json.dumps(result, ensure_ascii=False)
                return _make_result(req_id, {"content": [{"type": "text", "text": text}]})

            elif tool_name == "get-field-schema":
                luid = arguments.get("datasource_luid", "")
                if not luid:
                    return _make_error(req_id, -32602, "缺少必要参数: datasource_luid")
                result = await _get_field_schema(credentials, luid)
                text = json.dumps(result, ensure_ascii=False)
                return _make_result(req_id, {"content": [{"type": "text", "text": text}]})

            elif tool_name == "resolve-field-name":
                connection_id = arguments.get("connection_id")
                fuzzy_name = arguments.get("fuzzy_name", "")
                if connection_id is None or not fuzzy_name:
                    return _make_error(req_id, -32602, "缺少必要参数: connection_id 或 fuzzy_name")
                datasource_luid = arguments.get("datasource_luid", "")
                top_k = arguments.get("top_k", 5)
                result = await _resolve_field_name(connection_id, fuzzy_name, datasource_luid, top_k)
                text = json.dumps(result, ensure_ascii=False)
                return _make_result(req_id, {"content": [{"type": "text", "text": text}]})

            elif tool_name == "get-datasource-fields-summary":
                luid = arguments.get("datasource_luid", "")
                if not luid:
                    return _make_error(req_id, -32602, "缺少必要参数: datasource_luid")
                include_hidden = arguments.get("include_hidden", False)
                result = await _get_datasource_fields_summary(credentials, luid, include_hidden)
                text = json.dumps(result, ensure_ascii=False)
                return _make_result(req_id, {"content": [{"type": "text", "text": text}]})

            # ── Agentic Phase 2：视图控制 + 语义写回 ──────────────────────────

            elif tool_name == "get-view-filter-url":
                view_id = arguments.get("view_id", "")
                filters = arguments.get("filters", [])
                if not view_id:
                    return _make_error(req_id, -32602, "缺少必要参数: view_id")
                if not isinstance(filters, list) or not filters:
                    return _make_error(req_id, -32602, "缺少必要参数: filters（需为非空数组）")
                result = await _get_view_filter_url(credentials, view_id, filters)
                text = json.dumps(result, ensure_ascii=False)
                return _make_result(req_id, {"content": [{"type": "text", "text": text}]})

            elif tool_name == "create-custom-view":
                view_id = arguments.get("view_id", "")
                custom_view_name = arguments.get("custom_view_name", "")
                if not view_id or not custom_view_name:
                    return _make_error(req_id, -32602, "缺少必要参数: view_id 或 custom_view_name")
                shared = arguments.get("shared", False)
                result = await _create_custom_view(credentials, view_id, custom_view_name, shared)
                text = json.dumps(result, ensure_ascii=False)
                return _make_result(req_id, {"content": [{"type": "text", "text": text}]})

            elif tool_name == "update-custom-view":
                custom_view_id = arguments.get("custom_view_id", "")
                if not custom_view_id:
                    return _make_error(req_id, -32602, "缺少必要参数: custom_view_id")
                custom_view_name = arguments.get("custom_view_name", None)
                shared = arguments.get("shared", None)
                result = await _update_custom_view(credentials, custom_view_id, custom_view_name, shared)
                text = json.dumps(result, ensure_ascii=False)
                return _make_result(req_id, {"content": [{"type": "text", "text": text}]})

            elif tool_name == "list-custom-views-for-view":
                view_id = arguments.get("view_id", "")
                result = await _list_custom_views_for_view(credentials, view_id)
                text = json.dumps(result, ensure_ascii=False)
                return _make_result(req_id, {"content": [{"type": "text", "text": text}]})

            elif tool_name == "update-field-caption":
                connection_id = arguments.get("connection_id")
                datasource_luid = arguments.get("datasource_luid", "")
                field_name = arguments.get("field_name", "")
                new_caption = arguments.get("new_caption", "")
                if connection_id is None or not datasource_luid or not field_name or not new_caption:
                    return _make_error(req_id, -32602, "缺少必要参数: connection_id / datasource_luid / field_name / new_caption")
                change_reason = arguments.get("change_reason", None)
                result = await _update_field_caption(
                    credentials, connection_id, datasource_luid, field_name, new_caption, change_reason
                )
                text = json.dumps(result, ensure_ascii=False)
                return _make_result(req_id, {"content": [{"type": "text", "text": text}]})

            elif tool_name == "update-field-description":
                connection_id = arguments.get("connection_id")
                datasource_luid = arguments.get("datasource_luid", "")
                field_name = arguments.get("field_name", "")
                new_description = arguments.get("new_description", "")
                if connection_id is None or not datasource_luid or not field_name or not new_description:
                    return _make_error(req_id, -32602, "缺少必要参数: connection_id / datasource_luid / field_name / new_description")
                change_reason = arguments.get("change_reason", None)
                result = await _update_field_description(
                    credentials, connection_id, datasource_luid, field_name, new_description, change_reason
                )
                text = json.dumps(result, ensure_ascii=False)
                return _make_result(req_id, {"content": [{"type": "text", "text": text}]})

            elif tool_name == "publish-field-semantic":
                connection_id = arguments.get("connection_id")
                field_semantic_id = arguments.get("field_semantic_id")
                if connection_id is None or field_semantic_id is None:
                    return _make_error(req_id, -32602, "缺少必要参数: connection_id 或 field_semantic_id")
                result = await _publish_field_semantic(credentials, connection_id, field_semantic_id)
                text = json.dumps(result, ensure_ascii=False)
                return _make_result(req_id, {"content": [{"type": "text", "text": text}]})

            # ── Agentic Phase 3：Parameter 控制 + VizQL RunCommand ────────────

            elif tool_name == "get-workbook-parameters":
                workbook_luid = arguments.get("workbook_luid", "")
                if not workbook_luid:
                    return _make_error(req_id, -32602, "缺少必要参数: workbook_luid")
                result = await _get_workbook_parameters(credentials, workbook_luid)
                text = json.dumps(result, ensure_ascii=False)
                return _make_result(req_id, {"content": [{"type": "text", "text": text}]})

            elif tool_name == "set-parameter-via-url":
                view_id = arguments.get("view_id", "")
                parameters = arguments.get("parameters", [])
                if not view_id:
                    return _make_error(req_id, -32602, "缺少必要参数: view_id")
                if not isinstance(parameters, list) or not parameters:
                    return _make_error(req_id, -32602, "缺少必要参数: parameters（需为非空数组）")
                result = await _set_parameter_via_url(credentials, view_id, parameters)
                text = json.dumps(result, ensure_ascii=False)
                return _make_result(req_id, {"content": [{"type": "text", "text": text}]})

            elif tool_name == "run-vizql-command":
                datasource_luid = arguments.get("datasource_luid", "")
                command_type = arguments.get("command_type", "")
                field_name = arguments.get("field_name", "")
                value = arguments.get("value", "")
                if not datasource_luid or not command_type or not field_name or value == "":
                    return _make_error(req_id, -32602, "缺少必要参数: datasource_luid / command_type / field_name / value")
                result = await _run_vizql_command(credentials, datasource_luid, command_type, field_name, value)
                text = json.dumps(result, ensure_ascii=False)
                return _make_result(req_id, {"content": [{"type": "text", "text": text}]})

            else:
                return _make_error(req_id, -32601, f"未知工具: {tool_name}")

        except RuntimeError as e:
            msg = str(e)
            if "登录失败" in msg or "认证" in msg:
                return _make_error(req_id, -32002, f"Tableau 认证失败: {msg}")
            return _make_error(req_id, -32603, f"Internal Error: {msg}")
        except Exception as e:
            logger.exception("tableau_mcp tools/call unexpected error")
            return _make_error(req_id, -32603, f"Internal Error: {e}")

    # ── 未知 method ──────────────────────────────────────────────────────────
    return _make_error(req_id, -32601, f"Method not found: {method}")


# ── MCP HTTP 端点（JSON + SSE Streamable Transport）────────────────────────────

@router.post("")
@router.post("/")
async def handle_mcp(request: Request):
    """处理 MCP JSON-RPC 2.0 请求，支持 JSON 和 SSE（HTTP Streamable Transport）。"""
    server_id_raw = request.query_params.get("server_id")
    server_id = int(server_id_raw) if server_id_raw and server_id_raw.isdigit() else None

    try:
        body = await request.json()
    except Exception:
        return JSONResponse(
            status_code=400,
            content=_make_error(None, -32700, "Parse error: invalid JSON"),
        )

    result = await _process_mcp_body(body, server_id)

    if "text/event-stream" in request.headers.get("accept", ""):
        payload = json.dumps(result, ensure_ascii=False)
        async def sse_once():
            yield f"data: {payload}\n\n"
        return StreamingResponse(sse_once(), media_type="text/event-stream")

    return JSONResponse(result)


@router.get("")
@router.get("/")
async def mcp_sse_stream(request: Request):
    """MCP HTTP Streamable Transport — GET SSE 端点（MCP Inspector 使用）。"""
    async def keep_alive():
        while True:
            if await request.is_disconnected():
                break
            yield ": ping\n\n"
            await asyncio.sleep(15)
    return StreamingResponse(keep_alive(), media_type="text/event-stream")

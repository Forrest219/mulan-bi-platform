"""Tableau 管理 API
"""
import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.crypto import get_tableau_crypto
from app.core.database import get_db  # 导入中央数据库依赖
from app.core.dependencies import get_current_user, require_roles
from app.utils.auth import verify_connection_access  # 导入统一的权限验证函数
from services.tableau.models import TableauDatabase
from services.tableau.sync_service import TableauSyncService

router = APIRouter()

logger = logging.getLogger(__name__)

_crypto = get_tableau_crypto()
_encrypt = _crypto.encrypt
_decrypt = _crypto.decrypt


# _db_path 函数不再需要，因为 TableauDatabase 将使用中央配置
# def _db_path():
#     return str(Path(__file__).parent.parent.parent.parent / "data" / "tableau.db")


# require_admin_or_data_admin 已经通过 app.core.dependencies.require_roles 替代
# def require_admin_or_data_admin(request: Request) -> dict:
#     """仅管理员或数据管理员可访问"""
#     user = get_current_user(request)
#     if user["role"] not in ("admin", "data_admin"):
#         raise HTTPException(status_code=403, detail="需要管理员或数据管理员权限")
#     return user

# _verify_connection_access 已经提取到 app.utils.auth.py
# def _verify_connection_access(connection_id: int, user: dict, _db: TableauDatabase) -> None:
#     """验证用户有权访问指定连接（IDOR 修复）"""
#     conn = _db.get_connection(connection_id)
#     if not conn:
#         raise HTTPException(status_code=404, detail="连接不存在")
#     # admin 可访问所有连接，非 admin 只能访问自己的
#     if user["role"] != "admin" and conn.owner_id != user["id"]:
#         raise HTTPException(status_code=403, detail="无权访问该连接")


# --- Pydantic Models ---

class CreateConnectionRequest(BaseModel):
    name: str
    server_url: str
    site: str
    api_version: str = "3.21"
    connection_type: str = "mcp"  # 'mcp' or 'tsc'
    token_name: str
    token_value: str


class UpdateConnectionRequest(BaseModel):
    name: Optional[str] = None
    server_url: Optional[str] = None
    site: Optional[str] = None
    api_version: Optional[str] = None
    connection_type: Optional[str] = None
    token_name: Optional[str] = None
    token_value: Optional[str] = None
    is_active: Optional[bool] = None
    auto_sync_enabled: Optional[bool] = None
    sync_interval_hours: Optional[int] = None


# --- REST API 直连测试（MCP 模式） ---

def _test_connection_rest(server_url: str, site: str, token_name: str,
                          token_value: str, api_version: str = "3.21") -> dict:
    """通过 REST API 直接测试 Tableau 连接（不依赖 TSC 库）"""
    import requests
    url = f"{server_url.rstrip('/')}/api/{api_version}/auth/signin"
    payload = {
        "credentials": {
            "personalAccessTokenName": token_name,
            "personalAccessTokenSecret": token_value,
            "site": {"contentUrl": site}
        }
    }
    headers = {"Content-Type": "application/json", "Accept": "application/json"}
    try:
        resp = requests.post(url, json=payload, headers=headers, timeout=15)
        if resp.status_code == 200:
            data = resp.json()
            token = data.get("credentials", {}).get("token", "")
            site_id = data.get("credentials", {}).get("site", {}).get("id", "")
            if not token:
                return {"success": False, "message": "REST API 认证失败：未获取到 token"}
            # Sign out 清理 session
            try:
                requests.post(
                    f"{server_url.rstrip('/')}/api/{api_version}/auth/signout",
                    headers={"X-Tableau-Auth": token},
                    timeout=5
                )
            except Exception as e:
                logger.debug("Tableau signout failed (non-critical): %s", e)
            return {"success": True, "message": f"REST API 连接成功 (site_id={site_id})"}
        else:
            detail = resp.text[:200]
            return {"success": False, "message": f"REST API 认证失败 (HTTP {resp.status_code}): {detail}"}
    except Exception as e:
        if "Timeout" in type(e).__name__:
            return {"success": False, "message": "连接超时，请检查 Server URL 是否可达"}
        if "ConnectionError" in type(e).__name__:
            return {"success": False, "message": "无法连接到服务器，请检查 URL"}
        return {"success": False, "message": f"REST API 测试失败: {str(e)}"}


# --- Endpoints ---

@router.get("/connections")
async def list_connections(request: Request, db: Session = Depends(get_db), include_inactive: bool = False):
    """获取 Tableau 连接列表"""
    user = get_current_user(request, db)
    _db = TableauDatabase(session=db)

    if user["role"] == "admin":
        connections = _db.get_all_connections(include_inactive=include_inactive)
    else:
        connections = _db.get_all_connections(owner_id=user["id"], include_inactive=include_inactive)

    connection_dicts = [c.to_dict() for c in connections]

    # 补充 mcp_servers 表中 type='tableau' 且 is_active=True 的记录，
    # 让前端 ScopePicker 在 tableau_connections 表为空时也能看到连接
    try:
        from services.mcp.models import McpServer
        mcp_servers = db.query(McpServer).filter(
            McpServer.type == "tableau",
            McpServer.is_active == True,
        ).all()

        # 按 name 建立已有连接的索引，tableau_connections 优先
        existing_names = {d["name"] for d in connection_dicts}

        for mcp in mcp_servers:
            if mcp.name in existing_names:
                continue  # tableau_connections 中已有同名记录，跳过
            connection_dicts.append({
                "id": 10000 + mcp.id,
                "name": mcp.name,
                "server_url": mcp.server_url or "",
                "site": mcp.server_url or "",
                "api_version": "3.21",
                "connection_type": "mcp",
                "token_name": "",
                "owner_id": None,
                "is_active": True,
                "auto_sync_enabled": False,
                "sync_interval_hours": 24,
                "last_test_at": None,
                "last_test_success": None,
                "last_test_message": None,
                "last_sync_at": None,
                "last_sync_duration_sec": None,
                "sync_status": "idle",
                "mcp_direct_enabled": True,
                "mcp_server_url": mcp.server_url or "",
                "next_sync_at": None,
                "created_at": mcp.created_at.strftime("%Y-%m-%d %H:%M:%S") if mcp.created_at else None,
                "updated_at": mcp.updated_at.strftime("%Y-%m-%d %H:%M:%S") if mcp.updated_at else None,
            })
            existing_names.add(mcp.name)
    except Exception:
        logger.exception("从 mcp_servers 聚合 Tableau 连接时出错，返回仅 tableau_connections 的结果")

    return {"connections": connection_dicts, "total": len(connection_dicts)}


@router.post("/connections")
async def create_connection(
    req: CreateConnectionRequest,
    current_user: dict = Depends(require_roles(["admin", "data_admin"])),
    db: Session = Depends(get_db),
):
    """创建 Tableau 连接"""
    _db = TableauDatabase(session=db)

    if req.connection_type not in ("mcp", "tsc"):
        raise HTTPException(status_code=400, detail="connection_type 必须为 'mcp' 或 'tsc'")

    encrypted_token = _encrypt(req.token_value)

    conn = _db.create_connection(
        name=req.name,
        server_url=req.server_url,
        site=req.site,
        token_name=req.token_name,
        token_encrypted=encrypted_token,
        owner_id=current_user["id"],
        api_version=req.api_version,
        connection_type=req.connection_type
    )

    return {"connection": conn.to_dict(), "message": "连接创建成功"}


@router.put("/connections/{conn_id}")
async def update_connection(
    conn_id: int,
    req: UpdateConnectionRequest,
    current_user: dict = Depends(require_roles(["admin", "data_admin"])),
    db: Session = Depends(get_db),
):
    """更新 Tableau 连接"""
    _db = TableauDatabase(session=db)

    # 使用统一的权限验证函数
    verify_connection_access(conn_id, current_user, db)

    update_data = req.model_dump(exclude_unset=True)
    if "token_value" in update_data and update_data["token_value"]:
        # 用户提供了新 token_value，同时更新 token_name 和加密后的 token
        update_data["token_encrypted"] = _encrypt(update_data.pop("token_value"))
        if req.token_name:
            update_data["token_name"] = req.token_name
    elif "token_value" in update_data and not update_data["token_value"]:
        # token_value 为空字符串，不更新 token 相关字段
        update_data.pop("token_value", None)
        update_data.pop("token_name", None)

    _db.update_connection(conn_id, **update_data)
    return {"message": "连接更新成功"}


@router.delete("/connections/{conn_id}")
async def delete_connection(
    conn_id: int,
    current_user: dict = Depends(require_roles(["admin", "data_admin"])),
    db: Session = Depends(get_db),
):
    """删除 Tableau 连接"""
    _db = TableauDatabase(session=db)

    # 使用统一的权限验证函数
    verify_connection_access(conn_id, current_user, db)

    _db.delete_connection(conn_id)
    return {"message": "连接已删除"}


@router.post("/connections/{conn_id}/test")
async def test_connection(
    conn_id: int,
    current_user: dict = Depends(require_roles(["admin", "data_admin"])),
    db: Session = Depends(get_db),
):
    """测试 Tableau 连接"""
    _db = TableauDatabase(session=db)

    # 使用统一的权限验证函数
    verify_connection_access(conn_id, current_user, db)

    conn = _db.get_connection(conn_id)
    if not conn:
        raise HTTPException(status_code=404, detail="连接不存在")

    from cryptography.fernet import InvalidToken as FernetInvalidToken
    try:
        decrypted_token = _decrypt(conn.token_encrypted)
    except FernetInvalidToken:
        msg = "Token 解密失败：加密密钥可能已变更，请重新保存 PAT Token"
        _db.update_connection_health(conn_id, False, msg)
        return {"success": False, "message": msg}
    except Exception as e:
        msg = f"Token 解密失败：{e}"
        _db.update_connection_health(conn_id, False, msg)
        return {"success": False, "message": msg}

    # MCP 模式：通过 REST API 直连测试
    if getattr(conn, "connection_type", "mcp") == "mcp":
        result = _test_connection_rest(
            server_url=conn.server_url,
            site=conn.site,
            token_name=conn.token_name,
            token_value=decrypted_token,
            api_version=conn.api_version
        )
        _db.update_connection_health(conn_id, result["success"], result["message"])
        return result

    # TSC 模式：通过 tableauserverclient 库测试
    try:
        service = TableauSyncService(
            server_url=conn.server_url,
            site=conn.site,
            token_name=conn.token_name,
            token_value=decrypted_token,
            api_version=conn.api_version
        )
        try:
            result = service.test_connection()
            # 保存测试结果到数据库
            _db.update_connection_health(conn_id, result.get("success", False), result.get("message", ""))
            return result
        finally:
            service.disconnect()
    except Exception as e:
        error_msg = str(e)
        # 保存测试失败结果到数据库
        _db.update_connection_health(conn_id, False, f"测试失败: {error_msg}")
        return {"success": False, "message": f"测试失败: {error_msg}"}


# @router.post("/connections/{conn_id}/sync")  # Moved to ~line 540 with degraded check (Spec 13 §3.4 T2)


@router.get("/assets")
async def list_assets(
    request: Request,
    connection_id: int = Query(..., description="连接 ID"),
    asset_type: Optional[str] = Query(None, description="资产类型: workbook, view, datasource"),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=100),
    db: Session = Depends(get_db)
):
    """获取资产列表（分页）"""
    user = get_current_user(request, db)
    _db = TableauDatabase(session=db)

    # 验证用户有权访问该连接
    verify_connection_access(connection_id, user, db)

    assets, total = _db.get_assets(
        connection_id=connection_id,
        asset_type=asset_type,
        page=page,
        page_size=page_size
    )

    return {
        "assets": [a.to_dict() for a in assets],
        "total": total,
        "page": page,
        "page_size": page_size,
        "pages": (total + page_size - 1) // page_size
    }


@router.get("/assets/search")
async def search_assets(
    request: Request,
    q: str = Query(..., min_length=1, description="搜索关键词"),
    connection_id: Optional[int] = Query(None),
    asset_type: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=100),
    db: Session = Depends(get_db)
):
    """搜索资产。

    多租户隔离约束（Spec 07 §3.3.2 P0 IDOR 修复）：
    - admin 用户：可不指定 connection_id（搜索所有可访问连接）。
    - 非 admin 用户：
        - 指定 connection_id：仅返回该连接下的资产（需有访问权）。
        - 未指定 connection_id：强制限定为当前用户自己创建的连接（owner_id 过滤）。
    """
    user = get_current_user(request, db)
    _db = TableauDatabase(session=db)

    # 如果指定了 connection_id，验证用户有权访问
    if connection_id is not None:
        verify_connection_access(connection_id, user, db)

    # 非 admin 且未指定 connection_id 时，强制按 owner_id 过滤（IDOR 防护）
    owner_id_filter: Optional[int] = None
    if user["role"] != "admin" and connection_id is None:
        owner_id_filter = user["id"]

    assets, total = _db.search_assets(
        connection_id=connection_id,
        query=q,
        asset_type=asset_type,
        page=page,
        page_size=page_size,
        owner_id=owner_id_filter,
    )

    return {
        "assets": [a.to_dict() for a in assets],
        "total": total,
        "page": page,
        "page_size": page_size
    }


@router.get("/assets/{asset_id}")
async def get_asset(asset_id: int, request: Request, db: Session = Depends(get_db)):
    """获取资产详情"""
    user = get_current_user(request, db)
    _db = TableauDatabase(session=db)

    asset = _db.get_asset(asset_id)
    if not asset or asset.is_deleted:
        raise HTTPException(status_code=404, detail="资产不存在")

    # 验证用户有权访问该资产所属的连接
    verify_connection_access(asset.connection_id, user, db)

    result = asset.to_dict()

    # 获取关联的数据源
    datasources = _db.get_asset_datasources(asset_id)
    result["datasources"] = [ds.to_dict() for ds in datasources]

    # 获取连接信息（含 server_url 用于跳转链接）
    conn = _db.get_connection(asset.connection_id)
    if conn:
        result["server_url"] = conn.server_url

    return result


@router.get("/projects")
async def get_projects(
    request: Request,
    connection_id: int = Query(..., description="连接 ID"),
    db: Session = Depends(get_db)
):
    """获取项目树"""
    user = get_current_user(request, db)
    _db = TableauDatabase(session=db)

    # 验证用户有权访问该连接
    verify_connection_access(connection_id, user, db)

    projects = _db.get_project_tree(connection_id)
    return {"projects": projects}


# --- Sync Logs (Phase 2a) ---

@router.get("/connections/{conn_id}/sync-logs")
async def list_sync_logs(
    conn_id: int,
    request: Request,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db)
):
    """获取同步日志列表"""
    user = get_current_user(request, db)
    _db = TableauDatabase(session=db)
    verify_connection_access(conn_id, user, db)

    logs, total = _db.get_sync_logs(conn_id, page=page, page_size=page_size)
    return {
        "logs": [log.to_dict() for log in logs],
        "total": total,
        "page": page,
        "page_size": page_size,
        "pages": (total + page_size - 1) // page_size,
    }


@router.get("/connections/{conn_id}/sync-logs/{log_id}")
async def get_sync_log(conn_id: int, log_id: int, request: Request, db: Session = Depends(get_db)):
    """获取同步日志详情"""
    user = get_current_user(request, db)
    _db = TableauDatabase(session=db)
    verify_connection_access(conn_id, user, db)

    log = _db.get_sync_log(log_id)
    if not log or log.connection_id != conn_id:
        raise HTTPException(status_code=404, detail="同步日志不存在")
    return log.to_dict()


@router.get("/connections/{conn_id}/sync-status")
async def get_sync_status(conn_id: int, request: Request, db: Session = Depends(get_db)):
    """获取连接同步状态"""
    user = get_current_user(request, db)
    _db = TableauDatabase(session=db)
    verify_connection_access(conn_id, user, db)

    conn = _db.get_connection(conn_id)
    if not conn:
        raise HTTPException(status_code=404, detail="连接不存在")

    next_sync_at = None
    if conn.auto_sync_enabled:
        from datetime import timedelta  # 局部导入
        if conn.last_sync_at:
            next_dt = conn.last_sync_at + timedelta(hours=conn.sync_interval_hours or 24)
            next_sync_at = next_dt.strftime("%Y-%m-%d %H:%M:%S")
        else:
            next_sync_at = "即将执行"

    return {
        "status": conn.sync_status or "idle",
        "last_sync_at": conn.last_sync_at.strftime("%Y-%m-%d %H:%M:%S") if conn.last_sync_at else None,
        "last_sync_duration_sec": conn.last_sync_duration_sec,
        "auto_sync_enabled": conn.auto_sync_enabled,
        "sync_interval_hours": conn.sync_interval_hours,
        "next_sync_at": next_sync_at,
    }


# ── Spec 13 §3.4: MCP Offline Degradation ────────────────────────────────────

from services.tableau.connection_health import (
    build_connection_status_response,
    get_mcp_health,
    is_mcp_degraded,
)


@router.get("/connections/{conn_id}/status")
async def get_connection_status(conn_id: int, request: Request, db: Session = Depends(get_db)):
    """
    Spec 13 §3.4 T3: 获取连接 MCP 健康状态 + 数据新鲜度。
    
    Returns:
        - mcp_health: 'healthy' | 'degraded' | 'unhealthy'
        - data_freshness: {status, hours_since_sync, description}
        - connection metadata
    """
    user = get_current_user(request, db)
    _db = TableauDatabase(session=db)
    verify_connection_access(conn_id, user, db)

    conn = _db.get_connection(conn_id)
    if not conn:
        raise HTTPException(status_code=404, detail="连接不存在")

    return build_connection_status_response(conn)


@router.post("/connections/{conn_id}/sync")
async def sync_connection(
    conn_id: int,
    current_user: dict = Depends(require_roles(["admin", "data_admin"])),
    db: Session = Depends(get_db),
):
    """
    Spec 13 §3.4 T2: 触发 Tableau 资产同步（Celery 异步任务）。
    
    degraded 状态下返回 503 Service Unavailable。
    """
    _db = TableauDatabase(session=db)

    verify_connection_access(conn_id, current_user, db)

    conn = _db.get_connection(conn_id)
    if not conn:
        raise HTTPException(status_code=404, detail="连接不存在")

    # Spec 13 §3.4 T2: 检查 MCP 是否 degraded
    mcp_url = getattr(conn, 'mcp_server_url', None) or conn.server_url
    if is_mcp_degraded(mcp_url):
        raise HTTPException(
            status_code=503,
            detail={
                "error_code": "MCP_003",
                "message": "MCP 服务不可用（degraded 状态），同步操作暂停。请等待服务恢复。",
                "mcp_health": get_mcp_health(mcp_url).value,
            },
        )

    if conn.sync_status == "running":
        return {"message": "同步正在进行中", "status": "running"}

    from services.tasks.tableau_tasks import sync_connection_task
    task = sync_connection_task.delay(conn_id)
    return {"task_id": task.id, "message": "同步任务已提交", "status": "pending"}


# --- Asset Hierarchy (Phase 2a) ---

@router.get("/assets/{asset_id}/children")
async def get_asset_children(asset_id: int, request: Request, db: Session = Depends(get_db)):
    """获取 workbook 下属的 view/dashboard"""
    user = get_current_user(request, db) # 传递 db
    _db = TableauDatabase(session=db)

    asset = _db.get_asset(asset_id)
    if not asset or asset.is_deleted:
        raise HTTPException(status_code=404, detail="资产不存在")
    verify_connection_access(asset.connection_id, user, db)

    if asset.asset_type != "workbook":
        return {"children": []}

    children = _db.get_children_assets(asset.tableau_id, asset.connection_id)
    return {"children": [c.to_dict() for c in children]}


@router.get("/assets/{asset_id}/parent")
async def get_asset_parent(asset_id: int, request: Request, db: Session = Depends(get_db)):
    """获取 view/dashboard 的父 workbook"""
    user = get_current_user(request, db) # 传递 db
    _db = TableauDatabase(session=db)

    asset = _db.get_asset(asset_id)
    if not asset or asset.is_deleted:
        raise HTTPException(status_code=404, detail="资产不存在")
    verify_connection_access(asset.connection_id, user, db)

    parent = _db.get_parent_asset(asset_id)
    return {"parent": parent.to_dict() if parent else None}


# --- Deep AI Explain (Phase 2a) ---

class ExplainRequest(BaseModel):
    refresh: bool = False


@router.post("/assets/{asset_id}/explain")
async def explain_asset(asset_id: int, req: ExplainRequest, request: Request, db: Session = Depends(get_db)):
    """生成/获取深度 AI 解读"""
    user = get_current_user(request, db) # 传递 db
    _db = TableauDatabase(session=db)

    asset = _db.get_asset(asset_id)
    if not asset or asset.is_deleted:
        raise HTTPException(status_code=404, detail="资产不存在")
    verify_connection_access(asset.connection_id, user, db)

    # 获取数据源字段元数据（用于 field_semantics，无论是否缓存都需要）
    fields = _db.get_datasource_fields(asset_id)
    field_semantics = []
    if fields:
        for f in fields:
            field_semantics.append({
                "field": f.field_name,
                "caption": f.ai_caption or f.field_caption or "",
                "role": f.role or "",
                "data_type": f.data_type or "",
                "meaning": f.ai_description or f.description or "",
            })

    # 缓存：1 小时内不重新生成（除非强制刷新）
    if not req.refresh and asset.ai_explain and asset.ai_explain_at:
        from datetime import datetime, timedelta  # 局部导入
        if datetime.now() - asset.ai_explain_at < timedelta(hours=1):
            return {
                "explain": asset.ai_explain,
                "cached": True,
                "generated_at": asset.ai_explain_at.strftime("%Y-%m-%d %H:%M:%S"),
                "field_semantics": field_semantics,
            }

    # 获取关联数据源信息
    datasources = _db.get_asset_datasources(asset_id)
    ds_text = "\n".join([f"- {ds.datasource_name} ({ds.datasource_type or '未知类型'})" for ds in datasources]) or "无"

    # 构建字段文本用于 prompt
    field_text = "暂无字段元数据"
    if fields:
        field_lines = []
        for f in fields:
            caption = f.ai_caption or f.field_caption or ""
            desc = f.ai_description or f.description or ""
            role_str = f.role or ""
            line = f"- {f.field_name}"
            if caption:
                line += f" ({caption})"
            line += f" [{f.data_type or ''}] [{role_str}]"
            if f.formula:
                line += f" 公式: {f.formula}"
            if desc:
                line += f" — {desc}"
            field_lines.append(line)
        field_text = "\n".join(field_lines)

    # 获取父工作簿信息
    parent_info = "无"
    if asset.parent_workbook_name:
        parent_info = asset.parent_workbook_name

    # 调用 LLM 生成深度解读
    try:
        from services.llm.prompts import ASSET_EXPLAIN_TEMPLATE
        from services.llm.service import LLMService
        llm = LLMService()

        prompt = ASSET_EXPLAIN_TEMPLATE.format(
            name=asset.name,
            asset_type=asset.asset_type,
            project_name=asset.project_name or "未分类",
            description=asset.description or "无",
            owner_name=asset.owner_name or "未知",
            parent_workbook_info=parent_info,
            datasources=ds_text,
            field_metadata=field_text,
        )

        result = await llm.complete(prompt, system="你是一个专业的 BI 报表解读专家。", timeout=30)
        if isinstance(result, dict) and "error" in result:
            return {"explain": None, "error": result["error"], "cached": False, "field_semantics": field_semantics}

        explain_text = result if isinstance(result, str) else result.get("content", str(result))
        _db.update_asset_explain(asset_id, explain_text)

        return {
            "explain": explain_text,
            "cached": False,
            "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "field_semantics": field_semantics,
        }

    except ImportError:
        return {"explain": None, "error": "LLM 服务未配置", "cached": False, "field_semantics": field_semantics}
    except Exception as e:
        return {"explain": None, "error": f"生成失败: {str(e)}", "cached": False, "field_semantics": field_semantics}


# --- Asset Health Score (Phase 2b) ---

@router.get("/assets/{asset_id}/health")
async def get_asset_health(asset_id: int, request: Request, db: Session = Depends(get_db)):
    """获取资产健康评分"""
    user = get_current_user(request, db) # 传递 db
    _db = TableauDatabase(session=db)
    asset = _db.get_asset(asset_id)
    if not asset or asset.is_deleted:
        raise HTTPException(status_code=404, detail="资产不存在")
    verify_connection_access(asset.connection_id, user, db)


    from services.tableau.health import compute_asset_health

    datasources = _db.get_asset_datasources(asset_id)
    fields = _db.get_datasource_fields(asset_id)
    result = compute_asset_health(asset.to_dict(), datasources, fields)

    _db.update_asset_health(asset.id, result["score"], result) # JSONB 字段直接传入 dict

    return result


@router.get("/connections/{conn_id}/health-overview")
async def get_connection_health_overview(conn_id: int, request: Request, db: Session = Depends(get_db)):
    """连接级健康总览"""
    user = get_current_user(request, db) # 传递 db
    _db = TableauDatabase(session=db)
    conn = _db.get_connection(conn_id)
    if not conn:
        raise HTTPException(status_code=404, detail="连接不存在")
    verify_connection_access(conn_id, user, db)


    from services.tableau.health import compute_asset_health, get_health_level

    assets, total = _db.get_assets(conn_id, include_deleted=False, page=1, page_size=9999)
    asset_ids = [asset.id for asset in assets]
    datasources_by_asset = _db.get_asset_datasources_bulk(asset_ids)
    fields_by_asset = _db.get_datasource_fields_bulk(asset_ids)
    health_by_asset = {}
    results = []
    total_score = 0.0
    level_counts = {"excellent": 0, "good": 0, "warning": 0, "poor": 0}
    top_issues = {}

    for asset in assets:
        datasources = datasources_by_asset.get(asset.id, [])
        fields = fields_by_asset.get(asset.id, [])
        health = compute_asset_health(asset.to_dict(), datasources, fields)
        health_by_asset[asset.id] = health
        total_score += health["score"]
        level_counts[health["level"]] += 1

        for check in health["checks"]:
            if not check["passed"]:
                top_issues[check["key"]] = top_issues.get(check["key"], 0) + 1

        results.append({
            "asset_id": asset.id,
            "name": asset.name,
            "asset_type": asset.asset_type,
            "score": health["score"],
            "level": health["level"],
        })

    _db.update_assets_health_bulk(health_by_asset)

    avg_score = round(total_score / len(assets), 1) if assets else 0
    sorted_issues = sorted(top_issues.items(), key=lambda x: x[1], reverse=True)

    return {
        "connection_id": conn_id,
        "connection_name": conn.name,
        "total_assets": len(assets),
        "avg_score": avg_score,
        "avg_level": get_health_level(avg_score),
        "level_distribution": level_counts,
        "top_issues": [{"check": k, "count": v} for k, v in sorted_issues[:5]],
        "assets": sorted(results, key=lambda x: x["score"]),
    }


# ── Tableau MCP Server 状态检查 ─────────────────────────────────────────────

import asyncio as _asyncio
import time as _time

try:
    import httpx as _httpx
except ImportError:
    _httpx = None  # type: ignore

from services.common.settings import get_tableau_mcp_server_url, get_tableau_mcp_timeout


@router.get("/mcp-status")
async def get_mcp_status():
    """探测 Tableau MCP Server 连通性（UI 状态指示器用）"""
    url = get_tableau_mcp_server_url()
    timeout = min(get_tableau_mcp_timeout(), 5)
    if _httpx is None:
        return {"status": "unknown", "url": url, "latency_ms": 0, "error": "httpx not installed"}

    for attempt in range(2):
        start = _time.monotonic()
        try:
            async with _httpx.AsyncClient(timeout=timeout) as client:
                resp = await client.get(url)
            return {
                "status": "online",
                "url": url,
                "latency_ms": int((_time.monotonic() - start) * 1000),
                "http_status": resp.status_code,
                **({"retried": True} if attempt == 1 else {}),
            }
        except _httpx.TimeoutException as e:
            return {
                "status": "offline",
                "url": url,
                "latency_ms": int((_time.monotonic() - start) * 1000),
                "error": type(e).__name__,
            }
        except _httpx.ConnectError as e:
            if attempt == 0:
                await _asyncio.sleep(1)  # 参考 Spec 22 _post_mcp：ConnectError 重试 1 次间隔 1s
                continue
            return {
                "status": "offline",
                "url": url,
                "latency_ms": int((_time.monotonic() - start) * 1000),
                "error": type(e).__name__,
                "retried": True,
            }


# ── V2: Tableau MCP Direct Connect REST Endpoints ────────────────────────────

from services.tableau.mcp_client import get_tableau_mcp_client, TableauMCPError
from services.tableau.models import TableauDatabase


class VizQLQueryRequest(BaseModel):
    """简化的 VizQL 查询结构"""
    measures: list[dict] = []
    dimensions: list[dict] = []
    filters: list[dict] = []
    limit: int = 100


class TableauQueryRequest(BaseModel):
    connection_id: int
    datasource_luid: str
    vizql: VizQLQueryRequest
    timeout: int = 30


def _build_vizql_query(vizql: VizQLQueryRequest) -> dict:
    """将简化 VizQL 结构转换为 MCP query-datasource 格式"""
    fields = []
    for m in vizql.measures:
        f = {"fieldCaption": m["field"]}
        if m.get("aggregation"):
            f["function"] = m["aggregation"]
        if m.get("alias"):
            f["fieldAlias"] = m["alias"]
        fields.append(f)
    for d in vizql.dimensions:
        f = {"fieldCaption": d["field"]}
        if d.get("alias"):
            f["fieldAlias"] = d["alias"]
        fields.append(f)
    query = {"fields": fields}
    if vizql.filters:
        query["filters"] = vizql.filters
    return query


def _mcp_error_response(exc: TableauMCPError) -> tuple[int, dict]:
    """将 TableauMCPError 映射为 HTTP 状态码 + 错误体"""
    code_map = {
        "NLQ_006": "MCP_003",
        "NLQ_007": "MCP_004",
        "NLQ_009": "MCP_005",
        "MCP_010": "MCP_006",
    }
    http_status = {
        "MCP_003": 503,
        "MCP_004": 504,
        "MCP_005": 401,
        "MCP_006": 400,
    }.get(code_map.get(exc.code, ""), 503)
    return http_status, {
        "error_code": code_map.get(exc.code, "MCP_001"),
        "message": exc.message,
    }


@router.post("/query")
async def tableau_v2_query(
    req: TableauQueryRequest,
    request: Request,
    db: Session = Depends(get_db),
):
    """V2-1: MCP Direct Connect — 执行 VizQL 查询"""
    user = get_current_user(request, db)
    _db = TableauDatabase(session=db)

    verify_connection_access(req.connection_id, user, db)
    conn = _db.get_connection(req.connection_id)
    if not conn:
        raise HTTPException(status_code=404, detail="连接不存在")

    if not getattr(conn, "mcp_direct_enabled", False):
        raise HTTPException(
            status_code=400,
            detail={"error_code": "MCP_010", "message": "连接未开启 V2 直连模式，请使用 V1 API"},
        )

    vizql_query = _build_vizql_query(req.vizql)

    try:
        client = get_tableau_mcp_client(req.connection_id)
        result = client.query_datasource(
            datasource_luid=req.datasource_luid,
            query=vizql_query,
            limit=min(req.vizql.limit, 10000),
            timeout=req.timeout,
            connection_id=req.connection_id,
        )

        # 解析 MCP 返回：{"fields": [...], "rows": [[...]], ...}
        raw_fields = result.get("fields", [])
        raw_rows = result.get("rows", [])

        # 映射为统一列定义
        columns = []
        for f in raw_fields:
            name = f.get("fieldAlias") or f.get("fieldCaption") or f.get("fieldName", "?")
            columns.append({"name": name, "dataType": f.get("dataType", "STRING")})

        return {
            "columns": columns,
            "rows": raw_rows,
            "row_count": len(raw_rows),
            "truncated": result.get("truncated", False),
            "datasource_luid": req.datasource_luid,
            "executed_at": _time.strftime("%Y-%m-%dT%H:%M:%SZ", _time.gmtime()),
        }

    except TableauMCPError as e:
        status, body = _mcp_error_response(e)
        raise HTTPException(status_code=status, detail=body)


@router.get("/datasources/{asset_id}/metadata")
async def tableau_v2_metadata(
    asset_id: int,
    request: Request,
    refresh: bool = False,
    db: Session = Depends(get_db),
):
    """V2-2: 获取数据源字段元数据（带缓存）"""
    user = get_current_user(request, db)
    _db = TableauDatabase(session=db)

    asset = _db.get_asset(asset_id)
    if not asset or asset.is_deleted:
        raise HTTPException(status_code=404, detail="资产不存在")
    if asset.asset_type != "datasource":
        raise HTTPException(
            status_code=400,
            detail={"error_code": "MCP_010", "message": "该资产不是 datasource 类型"},
        )

    verify_connection_access(asset.connection_id, user, db)
    conn = _db.get_connection(asset.connection_id)
    if not conn:
        raise HTTPException(status_code=404, detail="连接不存在")

    cached_fields = _db.get_datasource_fields(asset_id)
    now = _time.time()
    cache_ttl = 24 * 3600  # 24h

    def _fields_to_dict(fields):
        return [
            {
                "name": f.field_name,
                "caption": f.field_caption or "",
                "data_type": f.data_type or "STRING",
                "role": f.role or "dimension",
                "description": f.description or "",
                "aggregation": f.aggregation,
            }
            for f in fields
        ]

    # 缓存命中且未过期
    if cached_fields and not refresh:
        oldest = min((f.fetched_at.timestamp() for f in cached_fields), default=0)
        if now - oldest < cache_ttl:
            return {
                "datasource_luid": asset.tableau_id,
                "fields": _fields_to_dict(cached_fields),
                "cache_status": "cached",
                "cached_at": _time.strftime("%Y-%m-%dT%H:%M:%SZ", _time.gmtime(oldest)),
            }

    # 需要拉取（首次 or refresh=true）
    try:
        client = get_tableau_mcp_client(asset.connection_id)
        raw = client.get_datasource_metadata(asset.tableau_id, timeout=30)
        raw_fields = raw.get("fields", [])

        # 写入缓存
        if raw_fields:
            parsed = []
            for f in raw_fields:
                parsed.append({
                    "field_name": f.get("fieldName", ""),
                    "field_caption": f.get("fieldCaption", ""),
                    "data_type": f.get("dataType", "STRING"),
                    "role": f.get("role", "dimension").lower(),
                    "description": f.get("description", ""),
                    "aggregation": f.get("aggregation"),
                    "is_calculated": f.get("isCalculated", False),
                    "formula": f.get("formula"),
                    "metadata_json": f,
                })
            _db.upsert_datasource_fields(asset.id, asset.tableau_id, parsed)

        # 重新读取（包含新数据）
        cached_fields = _db.get_datasource_fields(asset_id)
        oldest = min((f.fetched_at.timestamp() for f in cached_fields), default=0)
        return {
            "datasource_luid": asset.tableau_id,
            "fields": _fields_to_dict(cached_fields),
            "cache_status": "fresh",
            "cached_at": _time.strftime("%Y-%m-%dT%H:%M:%SZ", _time.gmtime(oldest)) if cached_fields else None,
        }

    except TableauMCPError:
        # MCP 不可达，降级返回缓存数据
        if cached_fields:
            oldest = min((f.fetched_at.timestamp() for f in cached_fields), default=0)
            return {
                "datasource_luid": asset.tableau_id,
                "fields": _fields_to_dict(cached_fields),
                "cache_status": "stale",
                "cached_at": _time.strftime("%Y-%m-%dT%H:%M:%SZ", _time.gmtime(oldest)),
            }
        raise HTTPException(
            status_code=503,
            detail={"error_code": "MCP_003", "message": "MCP Server 不可达，且无缓存数据"},
        )


@router.get("/datasources/{asset_id}/preview")
async def tableau_v2_preview(
    asset_id: int,
    request: Request,
    limit: int = Query(20, ge=1, le=500),
    db: Session = Depends(get_db),
):
    """V2-3: 数据预览（自动选取字段）"""
    user = get_current_user(request, db)
    _db = TableauDatabase(session=db)

    asset = _db.get_asset(asset_id)
    if not asset or asset.is_deleted:
        raise HTTPException(status_code=404, detail="资产不存在")
    if asset.asset_type != "datasource":
        raise HTTPException(
            status_code=400,
            detail={"error_code": "MCP_010", "message": "该资产不是 datasource 类型"},
        )

    verify_connection_access(asset.connection_id, user, db)

    # 从缓存字段中选取前几个（dimension 优先）
    fields = _db.get_datasource_fields(asset_id)
    preview_fields = []
    for f in fields:
        if len(preview_fields) >= 10:
            break
        preview_fields.append(f)

    vizql_fields = []
    for f in preview_fields:
        vizql_fields.append({"fieldCaption": f.field_name})
        if f.role == "measure":
            vizql_fields[-1]["function"] = "NONE"

    query = {"fields": vizql_fields}

    try:
        client = get_tableau_mcp_client(asset.connection_id)
        result = client.query_datasource(
            datasource_luid=asset.tableau_id,
            query=query,
            limit=limit,
            timeout=30,
            connection_id=asset.connection_id,
        )

        raw_fields = result.get("fields", [])
        raw_rows = result.get("rows", [])
        columns = []
        for f in raw_fields:
            name = f.get("fieldAlias") or f.get("fieldCaption") or f.get("fieldName", "?")
            columns.append({"name": name, "dataType": f.get("dataType", "STRING")})

        return {
            "columns": columns,
            "rows": raw_rows,
            "row_count": len(raw_rows),
            "truncated": result.get("truncated", False),
            "datasource_luid": asset.tableau_id,
            "executed_at": _time.strftime("%Y-%m-%dT%H:%M:%SZ", _time.gmtime()),
        }

    except TableauMCPError as e:
        status, body = _mcp_error_response(e)
        raise HTTPException(status_code=status, detail=body)

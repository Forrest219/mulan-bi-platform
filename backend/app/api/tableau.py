"""
Tableau 管理 API
"""
import sys
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, HTTPException, Request, Query
from pydantic import BaseModel

sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent / "src"))
from tableau.models import TableauDatabase
from tableau.sync_service import TableauSyncService
from app.core.dependencies import get_current_user
from app.core.crypto import get_tableau_crypto

router = APIRouter()

_crypto = get_tableau_crypto()
_encrypt = _crypto.encrypt
_decrypt = _crypto.decrypt


def _db_path():
    return str(Path(__file__).parent.parent.parent.parent / "data" / "tableau.db")


def require_admin_or_data_admin(request: Request) -> dict:
    """仅管理员或数据管理员可访问"""
    user = get_current_user(request)
    if user["role"] not in ("admin", "data_admin"):
        raise HTTPException(status_code=403, detail="需要管理员或数据管理员权限")
    return user


def _verify_connection_access(connection_id: int, user: dict, _db: TableauDatabase) -> None:
    """验证用户有权访问指定连接（IDOR 修复）"""
    conn = _db.get_connection(connection_id)
    if not conn:
        raise HTTPException(status_code=404, detail="连接不存在")
    # admin 可访问所有连接，非 admin 只能访问自己的
    if user["role"] != "admin" and conn.owner_id != user["id"]:
        raise HTTPException(status_code=403, detail="无权访问该连接")


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
            # Sign out 清理 session
            if token:
                try:
                    requests.post(
                        f"{server_url.rstrip('/')}/api/{api_version}/auth/signout",
                        headers={"X-Tableau-Auth": token},
                        timeout=5
                    )
                except Exception:
                    pass
            return {"success": True, "message": f"REST API 连接成功 (site: {site_id})"}
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
async def list_connections(request: Request, include_inactive: bool = False):
    """获取 Tableau 连接列表"""
    user = get_current_user(request)
    _db = TableauDatabase(db_path=_db_path())

    if user["role"] == "admin":
        connections = _db.get_all_connections(include_inactive=include_inactive)
    else:
        connections = _db.get_all_connections(owner_id=user["id"], include_inactive=include_inactive)

    return {"connections": [c.to_dict() for c in connections], "total": len(connections)}


@router.post("/connections")
async def create_connection(req: CreateConnectionRequest, request: Request):
    """创建 Tableau 连接"""
    user = require_admin_or_data_admin(request)
    _db = TableauDatabase(db_path=_db_path())

    if req.connection_type not in ("mcp", "tsc"):
        raise HTTPException(status_code=400, detail="connection_type 必须为 'mcp' 或 'tsc'")

    encrypted_token = _encrypt(req.token_value)

    conn = _db.create_connection(
        name=req.name,
        server_url=req.server_url,
        site=req.site,
        token_name=req.token_name,
        token_encrypted=encrypted_token,
        owner_id=user["id"],
        api_version=req.api_version,
        connection_type=req.connection_type
    )

    return {"connection": conn.to_dict(), "message": "连接创建成功"}


@router.put("/connections/{conn_id}")
async def update_connection(conn_id: int, req: UpdateConnectionRequest, request: Request):
    """更新 Tableau 连接"""
    user = require_admin_or_data_admin(request)
    _db = TableauDatabase(db_path=_db_path())

    conn = _db.get_connection(conn_id)
    if not conn:
        raise HTTPException(status_code=404, detail="连接不存在")

    if user["role"] != "admin" and conn.owner_id != user["id"]:
        raise HTTPException(status_code=403, detail="无权修改该连接")

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
async def delete_connection(conn_id: int, request: Request):
    """删除 Tableau 连接"""
    user = require_admin_or_data_admin(request)
    _db = TableauDatabase(db_path=_db_path())

    conn = _db.get_connection(conn_id)
    if not conn:
        raise HTTPException(status_code=404, detail="连接不存在")

    if user["role"] != "admin" and conn.owner_id != user["id"]:
        raise HTTPException(status_code=403, detail="无权删除该连接")

    _db.delete_connection(conn_id)
    return {"message": "连接已删除"}


@router.post("/connections/{conn_id}/test")
async def test_connection(conn_id: int, request: Request):
    """测试 Tableau 连接"""
    user = require_admin_or_data_admin(request)
    _db = TableauDatabase(db_path=_db_path())

    conn = _db.get_connection(conn_id)
    if not conn:
        raise HTTPException(status_code=404, detail="连接不存在")

    if user["role"] != "admin" and conn.owner_id != user["id"]:
        raise HTTPException(status_code=403, detail="无权操作该连接")

    try:
        decrypted_token = _decrypt(conn.token_encrypted)
    except Exception as decrypt_err:
        err_str = str(decrypt_err)
        if "InvalidToken" in err_str or "decrypt" in err_str.lower():
            msg = "Token 解密失败：加密密钥可能已变更，请重新保存 PAT Token"
            _db.update_connection_health(conn_id, False, msg)
            return {"success": False, "message": msg}
        raise

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


@router.post("/connections/{conn_id}/sync")
async def sync_connection(conn_id: int, request: Request):
    """触发 Tableau 资产同步"""
    user = require_admin_or_data_admin(request)
    _db = TableauDatabase(db_path=_db_path())

    conn = _db.get_connection(conn_id)
    if not conn:
        raise HTTPException(status_code=404, detail="连接不存在")

    if user["role"] != "admin" and conn.owner_id != user["id"]:
        raise HTTPException(status_code=403, detail="无权操作该连接")

    try:
        decrypted_token = _decrypt(conn.token_encrypted)
    except Exception as decrypt_err:
        err_str = str(decrypt_err)
        if "InvalidToken" in err_str or "decrypt" in err_str.lower():
            msg = "Token 解密失败：加密密钥可能已变更，请重新保存 PAT Token"
            _db.update_connection_health(conn_id, False, msg)
            return {"success": False, "message": msg}
        raise
    try:
        service = TableauSyncService(
            server_url=conn.server_url,
            site=conn.site,
            token_name=conn.token_name,
            token_value=decrypted_token,
            api_version=conn.api_version
        )

        try:
            if not service.connect():
                return {"success": False, "message": "无法连接到 Tableau Server"}

            result = service.sync_all_assets(_db, conn_id)

            wb_ids = result['synced'].get("workbook", [])
            db_ids = result['synced'].get("dashboard", [])
            view_ids = result['synced'].get("view", [])
            ds_ids = result['synced'].get("datasource", [])
            details = f"工作簿:{len(wb_ids)} 仪表板:{len(db_ids)} 视图:{len(view_ids)} 数据源:{len(ds_ids)}"
            # 保存同步成功状态和详情（复用健康状态字段）
            _db.update_connection_health(conn_id, True, f"同步成功，{details}，标记{result['deleted']}个已删除")
            return {
                "success": True,
                "message": f"同步完成，共 {result['total']} 个资产，标记 {result['deleted']} 个已删除，{details}"
            }
        finally:
            service.disconnect()

    except Exception as e:
        error_msg = str(e)
        _db.update_connection_health(conn_id, False, f"同步失败: {error_msg}")
        return {"success": False, "message": f"同步失败: {error_msg}"}


@router.get("/assets")
async def list_assets(
    request: Request,
    connection_id: int = Query(..., description="连接 ID"),
    asset_type: Optional[str] = Query(None, description="资产类型: workbook, view, datasource"),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=100)
):
    """获取资产列表（分页）"""
    user = get_current_user(request)
    _db = TableauDatabase(db_path=_db_path())

    # 验证用户有权访问该连接
    _verify_connection_access(connection_id, user, _db)

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
    page_size: int = Query(50, ge=1, le=100)
):
    """搜索资产"""
    user = get_current_user(request)
    _db = TableauDatabase(db_path=_db_path())

    # 如果指定了 connection_id，验证用户有权访问
    if connection_id is not None:
        _verify_connection_access(connection_id, user, _db)

    assets, total = _db.search_assets(
        connection_id=connection_id,
        query=q,
        asset_type=asset_type,
        page=page,
        page_size=page_size
    )

    return {
        "assets": [a.to_dict() for a in assets],
        "total": total,
        "page": page,
        "page_size": page_size
    }


@router.get("/assets/{asset_id}")
async def get_asset(asset_id: int, request: Request):
    """获取资产详情"""
    user = get_current_user(request)
    _db = TableauDatabase(db_path=_db_path())

    asset = _db.get_asset(asset_id)
    if not asset or asset.is_deleted:
        raise HTTPException(status_code=404, detail="资产不存在")

    # 验证用户有权访问该资产所属的连接
    _verify_connection_access(asset.connection_id, user, _db)

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
    connection_id: int = Query(..., description="连接 ID")
):
    """获取项目树"""
    user = get_current_user(request)
    _db = TableauDatabase(db_path=_db_path())

    # 验证用户有权访问该连接
    _verify_connection_access(connection_id, user, _db)

    projects = _db.get_project_tree(connection_id)
    return {"projects": projects}

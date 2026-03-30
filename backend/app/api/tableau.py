"""
Tableau 管理 API
"""
import json
import os
import sys
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, HTTPException, Request, Query
from pydantic import BaseModel

sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent / "src"))
from tableau.models import TableauDatabase
from tableau.sync_service import TableauSyncService

router = APIRouter()

# 加密密钥：优先 TABLEAU_ENCRYPTION_KEY，没有则复用 DATASOURCE_ENCRYPTION_KEY（已有数据依赖）
# 生产环境应单独设置 TABLEAU_ENCRYPTION_KEY，禁止两个都为空
_ENCRYPTION_KEY = os.environ.get("TABLEAU_ENCRYPTION_KEY") or os.environ.get("DATASOURCE_ENCRYPTION_KEY")
if not _ENCRYPTION_KEY:
    raise RuntimeError("TABLEAU_ENCRYPTION_KEY or DATASOURCE_ENCRYPTION_KEY must be set")


def _get_cipher():
    from cryptography.fernet import Fernet
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.backends import default_backend
    import base64

    key_bytes = _ENCRYPTION_KEY.encode()
    # Derive a proper 32-byte Fernet key from the password using PBKDF2
    from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=b'mulan-tableau-salt-v1',
        iterations=100000,
        backend=default_backend()
    )
    key = base64.urlsafe_b64encode(kdf.derive(key_bytes))
    return Fernet(key)


def _encrypt(text: str) -> str:
    return _get_cipher().encrypt(text.encode()).decode()


def _decrypt(token: str) -> str:
    return _get_cipher().decrypt(token.encode()).decode()


def _db_path():
    return str(Path(__file__).parent.parent.parent.parent / "data" / "tableau.db")


def get_current_user(request: Request) -> dict:
    """获取当前登录用户"""
    session = request.cookies.get("session")
    if not session:
        raise HTTPException(status_code=401, detail="未登录")
    parts = session.split(":")
    if len(parts) < 3:
        raise HTTPException(status_code=401, detail="无效的会话")
    return {"id": int(parts[0]), "username": parts[1], "role": parts[2]}


def require_admin_or_data_admin(request: Request) -> dict:
    """仅管理员或数据管理员可访问"""
    user = get_current_user(request)
    if user["role"] not in ("admin", "data_admin"):
        raise HTTPException(status_code=403, detail="需要管理员或数据管理员权限")
    return user


# --- Pydantic Models ---

class CreateConnectionRequest(BaseModel):
    name: str
    server_url: str
    site: str
    api_version: str = "3.21"
    token_name: str
    token_value: str


class UpdateConnectionRequest(BaseModel):
    name: Optional[str] = None
    server_url: Optional[str] = None
    site: Optional[str] = None
    api_version: Optional[str] = None
    token_name: Optional[str] = None
    token_value: Optional[str] = None
    is_active: Optional[bool] = None


# --- Endpoints ---

@router.get("/connections")
async def list_connections(request: Request):
    """获取 Tableau 连接列表"""
    user = get_current_user(request)
    _db = TableauDatabase(db_path=_db_path())

    if user["role"] == "admin":
        connections = _db.get_all_connections(include_inactive=False)
    else:
        connections = _db.get_all_connections(owner_id=user["id"], include_inactive=False)

    return {"connections": [c.to_dict() for c in connections], "total": len(connections)}


@router.post("/connections")
async def create_connection(req: CreateConnectionRequest, request: Request):
    """创建 Tableau 连接"""
    user = require_admin_or_data_admin(request)
    _db = TableauDatabase(db_path=_db_path())

    encrypted_token = _encrypt(req.token_value)

    conn = _db.create_connection(
        name=req.name,
        server_url=req.server_url,
        site=req.site,
        token_name=req.token_name,
        token_encrypted=encrypted_token,
        owner_id=user["id"],
        api_version=req.api_version
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
        update_data["token_encrypted"] = _encrypt(update_data.pop("token_value"))
        if not req.token_name:
            update_data.pop("token_name", None)
    elif "token_name" in update_data:
        update_data.pop("token_name", None)
        update_data.pop("token_value", None)

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
        service = TableauSyncService(
            server_url=conn.server_url,
            site=conn.site,
            token_name=conn.token_name,
            token_value=decrypted_token,
            api_version=conn.api_version
        )
        result = service.test_connection()
        service.disconnect()
        return result
    except Exception as e:
        return {"success": False, "message": f"测试失败: {str(e)}"}


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
        service = TableauSyncService(
            server_url=conn.server_url,
            site=conn.site,
            token_name=conn.token_name,
            token_value=decrypted_token,
            api_version=conn.api_version
        )

        if not service.connect():
            return {"success": False, "message": "无法连接到 Tableau Server"}

        result = service.sync_all_assets(_db, conn_id)
        service.disconnect()

        return {
            "success": True,
            "message": f"同步完成，共 {result['total']} 个资产，标记 {result['deleted']} 个已删除"
        }

    except Exception as e:
        return {"success": False, "message": f"同步失败: {str(e)}"}


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


@router.get("/assets/{asset_id}")
async def get_asset(asset_id: int, request: Request):
    """获取资产详情"""
    user = get_current_user(request)
    _db = TableauDatabase(db_path=_db_path())

    asset = _db.get_asset(asset_id)
    if not asset or asset.is_deleted:
        raise HTTPException(status_code=404, detail="资产不存在")

    result = asset.to_dict()

    # 获取关联的数据源
    datasources = _db.get_asset_datasources(asset_id)
    result["datasources"] = [ds.to_dict() for ds in datasources]

    return result


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


@router.get("/projects")
async def get_projects(
    request: Request,
    connection_id: int = Query(..., description="连接 ID")
):
    """获取项目树"""
    user = get_current_user(request)
    _db = TableauDatabase(db_path=_db_path())

    conn = _db.get_connection(connection_id)
    if not conn:
        raise HTTPException(status_code=404, detail="连接不存在")

    projects = _db.get_project_tree(connection_id)
    return {"projects": projects}


# --- Dev: 初始化测试连接 ---

try:
    import tableauserverclient  # noqa: F401
except ImportError:
    pass

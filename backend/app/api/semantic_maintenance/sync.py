"""
语义维护 - 字段同步 API
"""
import asyncio
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, HTTPException, Request, Query
from pydantic import BaseModel

sys_path = str(Path(__file__).parent.parent.parent.parent.parent / "src")
import sys
sys.path.insert(0, sys_path)

from app.core.dependencies import get_current_user
from app.core.crypto import get_tableau_crypto

router = APIRouter()
_crypto = get_tableau_crypto()


def _db_path():
    return str(Path(__file__).parent.parent.parent.parent.parent / "data" / "semantic_maintenance.db")


def _tableau_db_path():
    return str(Path(__file__).parent.parent.parent.parent.parent / "data" / "tableau.db")


def _verify_connection_access(connection_id: int, user: dict) -> None:
    """验证用户有权访问指定连接"""
    import sqlite3
    conn = sqlite3.connect(_tableau_db_path())
    cursor = conn.cursor()
    cursor.execute("SELECT owner_id FROM tableau_connections WHERE id = ?", (connection_id,))
    row = cursor.fetchone()
    conn.close()
    if not row:
        raise HTTPException(status_code=404, detail="连接不存在")
    if user["role"] != "admin" and row[0] != user["id"]:
        raise HTTPException(status_code=403, detail="无权访问该连接")


class SyncFieldsRequest(BaseModel):
    tableau_datasource_id: str  # Tableau 数据源 ID（LUID）
    asset_id: Optional[int] = None  # 可选：对应 tableau_assets.id
    force: bool = False  # 强制刷新（跳过变更检测）


@router.post("/connections/{conn_id}/sync-fields")
async def sync_datasource_fields(
    conn_id: int,
    req: SyncFieldsRequest,
    request: Request,
):
    """触发数据源字段级元数据同步"""
    import sqlite3
    from semantic_maintenance.field_sync import FieldSyncJob

    user = get_current_user(request)
    _verify_connection_access(conn_id, user)

    # 获取连接信息
    conn = sqlite3.connect(_tableau_db_path())
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute(
        "SELECT id, server_url, site, token_name, token_encrypted, api_version, connection_type "
        "FROM tableau_connections WHERE id = ?", (conn_id,)
    )
    row = cursor.fetchone()
    conn.close()
    if not row:
        raise HTTPException(status_code=404, detail="连接不存在")

    # 获取 datasource asset
    asset_id = req.asset_id
    if not asset_id:
        cursor2 = sqlite3.connect(_tableau_db_path())
        cursor2.row_factory = sqlite3.Row
        c2 = cursor2.cursor()
        c2.execute(
            "SELECT id FROM tableau_assets WHERE connection_id = ? AND tableau_id = ? AND is_deleted = 0",
            (conn_id, req.tableau_datasource_id)
        )
        asset_row = c2.fetchone()
        cursor2.close()
        if not asset_row:
            raise HTTPException(status_code=404, detail=f"未找到 tableau_id={req.tableau_datasource_id} 的资产记录")
        asset_id = asset_row["id"]

    # 解密 token
    try:
        token_value = _crypto.decrypt(row["token_encrypted"])
    except Exception:
        raise HTTPException(status_code=500, detail="Token 解密失败，请重新保存连接凭证")

    # 获取 site content_url（需要用 REST signin 获取）
    site_content_url = row["site"]

    # 异步执行同步任务
    job = FieldSyncJob(
        connection_id=conn_id,
        tableau_datasource_id=req.tableau_datasource_id,
        asset_id=asset_id,
        datasource_luid=req.tableau_datasource_id,
        server_url=row["server_url"],
        site_content_url=site_content_url,
        token_name=row["token_name"],
        token_value=token_value,
        api_version=row["api_version"] or "3.21",
        db_path=_db_path(),
    )

    # 在线程池中执行（避免阻塞事件循环）
    loop = asyncio.get_running_loop()
    result = await loop.run_in_executor(None, job.run)

    return {
        "message": f"字段同步完成：更新 {result.get('synced', 0)} 个字段，跳过 {result.get('skipped', 0)} 个无变更",
        "connection_id": conn_id,
        "tableau_datasource_id": req.tableau_datasource_id,
        "asset_id": asset_id,
        "status": result.get("status", "unknown"),
        "synced": result.get("synced", 0),
        "skipped": result.get("skipped", 0),
        "errors": result.get("errors", []),
    }


@router.get("/connections/{conn_id}/sync-fields/status")
async def get_sync_fields_status(
    conn_id: int,
    request: Request,
):
    """获取字段同步状态（P2 占位：可扩展为查询上次同步状态）"""
    user = get_current_user(request)
    _verify_connection_access(conn_id, user)

    return {
        "connection_id": conn_id,
        "status": "supported",
        "message": "字段同步状态查询在 P2 中扩展",
    }

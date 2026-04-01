"""
语义维护 - 发布管理 API
"""
import asyncio
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, HTTPException, Request, Query
from pydantic import BaseModel

sys_path = str(Path(__file__).parent.parent.parent.parent.parent / "src")
import sys
sys.path.insert(0, sys_path)

from semantic_maintenance.service import SemanticMaintenanceService
from semantic_maintenance.publish_service import PublishService
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


def _get_publish_service(connection_id: int, user: dict) -> PublishService:
    """创建 PublishService 实例（带认证）"""
    import sqlite3
    conn = sqlite3.connect(_tableau_db_path())
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute(
        "SELECT server_url, site, token_name, token_encrypted, api_version "
        "FROM tableau_connections WHERE id = ?", (connection_id,)
    )
    row = cursor.fetchone()
    conn.close()
    if not row:
        raise HTTPException(status_code=404, detail="连接不存在")
    try:
        token_value = _crypto.decrypt(row["token_encrypted"])
    except Exception:
        raise HTTPException(status_code=500, detail="Token 解密失败，请重新保存连接凭证")
    service = PublishService(
        server_url=row["server_url"],
        site_content_url=row["site"],
        token_name=row["token_name"],
        token_value=token_value,
        api_version=row["api_version"] or "3.21",
        db_path=_db_path(),
    )
    if not service.connect():
        raise HTTPException(status_code=502, detail="无法连接到 Tableau Server")
    return service


class PreviewDiffRequest(BaseModel):
    connection_id: int
    object_type: str  # 'datasource' / 'field'
    object_id: int


class PublishDatasourceRequest(BaseModel):
    ds_id: int
    connection_id: int
    simulate: bool = False


class PublishFieldsRequest(BaseModel):
    connection_id: int
    field_ids: list[int]
    simulate: bool = False


class RetryPublishRequest(BaseModel):
    log_id: int
    connection_id: int


class RollbackPublishRequest(BaseModel):
    log_id: int
    connection_id: int


# --- Diff Preview ---

@router.post("/publish/diff")
async def preview_diff(req: PreviewDiffRequest, request: Request):
    """预览发布差异：展示 Tableau 当前值 vs Mulan 待发布值"""
    user = get_current_user(request)
    _verify_connection_access(req.connection_id, user)

    service = _get_publish_service(req.connection_id, user)
    try:
        if req.object_type == "datasource":
            result, err = service.preview_datasource_diff(req.connection_id, req.object_id)
        elif req.object_type == "field":
            result, err = service.preview_field_diff(req.connection_id, req.object_id)
        else:
            raise HTTPException(status_code=400, detail="object_type 必须是 datasource 或 field")
    finally:
        service.disconnect()

    if err:
        raise HTTPException(status_code=400, detail=err)
    return result


# --- Publish ---

@router.post("/publish/datasource")
async def publish_datasource(req: PublishDatasourceRequest, request: Request):
    """发布数据源语义到 Tableau"""
    user = get_current_user(request)
    if user["role"] not in ("admin", "publisher"):
        raise HTTPException(status_code=403, detail="需要 publisher 或 admin 权限")
    _verify_connection_access(req.connection_id, user)

    service = _get_publish_service(req.connection_id, user)
    try:
        result, err = service.publish_datasource(
            connection_id=req.connection_id,
            ds_id=req.ds_id,
            operator=user["id"],
            simulate=req.simulate,
        )
    finally:
        service.disconnect()

    if err:
        raise HTTPException(status_code=400, detail=err)
    return result


@router.post("/publish/fields")
async def publish_fields(req: PublishFieldsRequest, request: Request):
    """批量发布字段语义到 Tableau"""
    user = get_current_user(request)
    if user["role"] not in ("admin", "publisher"):
        raise HTTPException(status_code=403, detail="需要 publisher 或 admin 权限")
    _verify_connection_access(req.connection_id, user)

    service = _get_publish_service(req.connection_id, user)
    try:
        result, err = service.publish_fields(
            connection_id=req.connection_id,
            field_ids=req.field_ids,
            operator=user["id"],
            simulate=req.simulate,
        )
    finally:
        service.disconnect()

    if err:
        raise HTTPException(status_code=400, detail=err)
    return result


# --- Retry & Rollback ---

@router.post("/publish/retry")
async def retry_publish(req: RetryPublishRequest, request: Request):
    """重试失败发布"""
    user = get_current_user(request)
    if user["role"] not in ("admin", "publisher"):
        raise HTTPException(status_code=403, detail="需要 publisher 或 admin 权限")
    _verify_connection_access(req.connection_id, user)

    service = _get_publish_service(req.connection_id, user)
    try:
        result, err = service.retry_publish(log_id=req.log_id, operator=user["id"])
    finally:
        service.disconnect()

    if err:
        raise HTTPException(status_code=400, detail=err)
    return result


@router.post("/publish/rollback")
async def rollback_publish(req: RollbackPublishRequest, request: Request):
    """回滚已发布内容"""
    user = get_current_user(request)
    if user["role"] != "admin":
        raise HTTPException(status_code=403, detail="需要 admin 权限")
    _verify_connection_access(req.connection_id, user)

    service = _get_publish_service(req.connection_id, user)
    try:
        result, err = service.rollback_publish(log_id=req.log_id, operator=user["id"])
    finally:
        service.disconnect()

    if err:
        raise HTTPException(status_code=400, detail=err)
    return result

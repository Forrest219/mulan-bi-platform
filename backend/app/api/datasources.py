"""数据源管理 API
"""
import logging
import sys
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.crypto import get_datasource_crypto
from app.core.database import get_db  # 导入中央数据库依赖
from app.core.dependencies import get_current_user, require_roles
from services.datasources.models import DataSourceDatabase

router = APIRouter()

_crypto = get_datasource_crypto()
_encrypt = _crypto.encrypt
_decrypt = _crypto.decrypt


class CreateDataSourceRequest(BaseModel):
    """创建数据源请求模型"""

    name: str
    db_type: str
    host: str
    port: int
    database_name: str
    username: str
    password: str
    extra_config: Optional[dict] = None


class UpdateDataSourceRequest(BaseModel):
    """更新数据源请求模型"""

    name: Optional[str] = None
    db_type: Optional[str] = None
    host: Optional[str] = None
    port: Optional[int] = None
    database_name: Optional[str] = None
    username: Optional[str] = None
    password: Optional[str] = None
    extra_config: Optional[dict] = None
    is_active: Optional[bool] = None


@router.get("/")
async def list_datasources(request: Request, db: Session = Depends(get_db)):
    """获取数据源列表"""
    user = get_current_user(request, db)
    _db = DataSourceDatabase()

    # 管理员看所有，其他用户只看自己创建的
    if user["role"] == "admin":
        sources = _db.get_all(db, include_inactive=False)
    else:
        sources = _db.get_all(db, owner_id=user["id"], include_inactive=False)

    return {"datasources": [s.to_dict() for s in sources], "total": len(sources)}


@router.post("/")
async def create_datasource(
    request: CreateDataSourceRequest,
    current_user: dict = Depends(require_roles(["admin", "data_admin"])),
    db: Session = Depends(get_db),
):
    """创建数据源"""
    _db = DataSourceDatabase()

    encrypted_password = _encrypt(request.password)
    extra_config = request.extra_config if request.extra_config else None

    ds = _db.create(
        db,
        name=request.name,
        db_type=request.db_type,
        host=request.host,
        port=request.port,
        database_name=request.database_name,
        username=request.username,
        password_encrypted=encrypted_password,
        owner_id=current_user["id"],
        extra_config=extra_config,
    )

    return {"datasource": ds.to_dict(), "message": "数据源创建成功"}


@router.get("/{ds_id}")
async def get_datasource(ds_id: int, request: Request, db: Session = Depends(get_db)):
    """获取单个数据源"""
    user = get_current_user(request, db)
    _db = DataSourceDatabase()

    ds = _db.get(db, ds_id)
    if not ds:
        raise HTTPException(status_code=404, detail="数据源不存在")

    # 非管理员只能看自己的
    if user["role"] != "admin" and ds.owner_id != user["id"]:
        raise HTTPException(status_code=403, detail="无权访问该数据源")

    return ds.to_dict()


@router.put("/{ds_id}")
async def update_datasource(
    ds_id: int,
    request: UpdateDataSourceRequest,
    current_user: dict = Depends(require_roles(["admin", "data_admin"])),
    db: Session = Depends(get_db),
):
    """更新数据源"""
    _db = DataSourceDatabase()

    ds = _db.get(db, ds_id)
    if not ds:
        raise HTTPException(status_code=404, detail="数据源不存在")

    if current_user["role"] != "admin" and ds.owner_id != current_user["id"]:
        raise HTTPException(status_code=403, detail="无权修改该数据源")

    update_data = request.model_dump(exclude_unset=True)
    if "password" in update_data:
        update_data["password_encrypted"] = _encrypt(update_data.pop("password"))
    if "extra_config" in update_data and update_data["extra_config"] is not None:
        update_data["extra_config"] = update_data["extra_config"]

    _db.update(db, ds_id, **update_data)
    return {"message": "数据源更新成功"}


@router.delete("/{ds_id}")
async def delete_datasource(
    ds_id: int,
    current_user: dict = Depends(require_roles(["admin", "data_admin"])),
    db: Session = Depends(get_db),
):
    """删除数据源（软删除）"""
    _db = DataSourceDatabase()

    ds = _db.get(db, ds_id)
    if not ds:
        raise HTTPException(status_code=404, detail="数据源不存在")

    if current_user["role"] != "admin" and ds.owner_id != current_user["id"]:
        raise HTTPException(status_code=403, detail="无权删除该数据源")

    _db.delete(db, ds_id)
    return {"message": "数据源已删除"}


@router.post("/{ds_id}/test")
async def test_connection(
    ds_id: int,
    current_user: dict = Depends(require_roles(["admin", "data_admin"])),
    db: Session = Depends(get_db),
):
    """测试数据源连接（10秒超时）"""
    import asyncio

    _db = DataSourceDatabase()

    ds = _db.get(db, ds_id)
    if not ds:
        raise HTTPException(status_code=404, detail="数据源不存在")

    if current_user["role"] != "admin" and ds.owner_id != current_user["id"]:
        raise HTTPException(status_code=403, detail="无权操作该数据源")

    try:
        password = _decrypt(ds.password_encrypted)
        db_config = {
            "db_type": ds.db_type,
            "host": ds.host,
            "port": ds.port,
            "database": ds.database_name,
            "user": ds.username,
            "password": password,
        }

        sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent / "modules" / "ddl_check_engine"))
        from ddl_check_engine.connector import DatabaseConnector

        def _do_connect():
            connector = DatabaseConnector(db_config)
            return connector.connect()

        connected = await asyncio.wait_for(asyncio.to_thread(_do_connect), timeout=10.0)
        return {"success": connected, "message": "连接成功" if connected else "连接失败"}

    except asyncio.TimeoutError:
        return {"success": False, "message": "连接超时（10秒），请检查主机和网络"}
    except Exception as e:
        # P1 安全修复：脱敏敏感关键词，防止异常信息泄露
        error_msg = str(e)
        if any(k in error_msg.lower() for k in ["password", "secret", "user", "@", "pwd", "credential"]):
            error_msg = "数据库连接失败，请检查配置（详细信息已隐藏）"
        logging.getLogger(__name__).error("数据源连接测试失败: %s", error_msg)
        return {"success": False, "message": "连接失败，请检查配置"}

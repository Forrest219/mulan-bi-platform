"""
数据源管理 API
"""
import json
import os
import sys
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, HTTPException, Request, Depends
from pydantic import BaseModel

sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent / "src"))
from datasources.models import DataSourceDatabase

router = APIRouter()

# 加密密钥（生产环境必须通过环境变量设置）
_ENCRYPTION_KEY = os.environ.get("DATASOURCE_ENCRYPTION_KEY", "mulan-datasource-dev-key-32bytes!!")


def _get_cipher():
    from cryptography.fernet import Fernet
    key = _ENCRYPTION_KEY.encode()
    if len(key) != 32:
        key = Fernet.generate_key()
    return Fernet(key)


def _encrypt(text: str) -> str:
    return _get_cipher().encrypt(text.encode()).decode()


def _decrypt(token: str) -> str:
    return _get_cipher().decrypt(token.encode()).decode()


def _db_path():
    return str(Path(__file__).parent.parent.parent.parent / "data" / "datasources.db")


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


class CreateDataSourceRequest(BaseModel):
    name: str
    db_type: str
    host: str
    port: int
    database_name: str
    username: str
    password: str
    extra_config: Optional[dict] = None


class UpdateDataSourceRequest(BaseModel):
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
async def list_datasources(request: Request):
    """获取数据源列表"""
    user = get_current_user(request)
    _db = DataSourceDatabase(db_path=_db_path())

    # 管理员看所有，其他用户只看自己创建的
    if user["role"] == "admin":
        sources = _db.get_all(include_inactive=False)
    else:
        sources = _db.get_all(owner_id=user["id"], include_inactive=False)

    return {"datasources": [s.to_dict() for s in sources], "total": len(sources)}


@router.post("/")
async def create_datasource(request: CreateDataSourceRequest, req: Request):
    """创建数据源"""
    user = require_admin_or_data_admin(req)
    _db = DataSourceDatabase(db_path=_db_path())

    encrypted_password = _encrypt(request.password)
    extra_config = json.dumps(request.extra_config) if request.extra_config else None

    ds = _db.create(
        name=request.name,
        db_type=request.db_type,
        host=request.host,
        port=request.port,
        database_name=request.database_name,
        username=request.username,
        password_encrypted=encrypted_password,
        owner_id=user["id"],
        extra_config=extra_config
    )

    return {"datasource": ds.to_dict(), "message": "数据源创建成功"}


@router.get("/{ds_id}")
async def get_datasource(ds_id: int, request: Request):
    """获取单个数据源"""
    user = get_current_user(request)
    _db = DataSourceDatabase(db_path=_db_path())

    ds = _db.get(ds_id)
    if not ds:
        raise HTTPException(status_code=404, detail="数据源不存在")

    # 非管理员只能看自己的
    if user["role"] != "admin" and ds.owner_id != user["id"]:
        raise HTTPException(status_code=403, detail="无权访问该数据源")

    return ds.to_dict()


@router.put("/{ds_id}")
async def update_datasource(ds_id: int, request: UpdateDataSourceRequest, req: Request):
    """更新数据源"""
    user = require_admin_or_data_admin(req)
    _db = DataSourceDatabase(db_path=_db_path())

    ds = _db.get(ds_id)
    if not ds:
        raise HTTPException(status_code=404, detail="数据源不存在")

    if user["role"] != "admin" and ds.owner_id != user["id"]:
        raise HTTPException(status_code=403, detail="无权修改该数据源")

    update_data = request.dict(exclude_unset=True)
    if "password" in update_data:
        update_data["password_encrypted"] = _encrypt(update_data.pop("password"))
    if "extra_config" in update_data and update_data["extra_config"]:
        update_data["extra_config"] = json.dumps(update_data["extra_config"])

    _db.update(ds_id, **update_data)
    return {"message": "数据源更新成功"}


@router.delete("/{ds_id}")
async def delete_datasource(ds_id: int, request: Request):
    """删除数据源"""
    user = require_admin_or_data_admin(request)
    _db = DataSourceDatabase(db_path=_db_path())

    ds = _db.get(ds_id)
    if not ds:
        raise HTTPException(status_code=404, detail="数据源不存在")

    if user["role"] != "admin" and ds.owner_id != user["id"]:
        raise HTTPException(status_code=403, detail="无权删除该数据源")

    _db.delete(ds_id)
    return {"message": "数据源已删除"}


@router.post("/{ds_id}/test")
async def test_connection(ds_id: int, request: Request):
    """测试数据源连接"""
    user = require_admin_or_data_admin(request)
    _db = DataSourceDatabase(db_path=_db_path())

    ds = _db.get(ds_id)
    if not ds:
        raise HTTPException(status_code=404, detail="数据源不存在")

    if user["role"] != "admin" and ds.owner_id != user["id"]:
        raise HTTPException(status_code=403, detail="无权操作该数据源")

    try:
        password = _decrypt(ds.password_encrypted)
        db_config = {
            "db_type": ds.db_type,
            "host": ds.host,
            "port": ds.port,
            "database": ds.database_name,
            "user": ds.username,
            "password": password
        }

        sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent / "modules" / "ddl_check_engine"))
        from ddl_check_engine.connector import DatabaseConnector
        connector = DatabaseConnector(db_config)
        connected = connector.connect()

        return {"success": connected, "message": "连接成功" if connected else "连接失败"}

    except Exception as e:
        return {"success": False, "message": f"连接失败: {str(e)}"}

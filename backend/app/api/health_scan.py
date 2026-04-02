"""数仓健康检查 API"""
import asyncio
import logging
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from app.core.dependencies import get_current_user, require_roles
from app.core.crypto import get_datasource_crypto
from services.datasources.models import DataSourceDatabase
from services.health_scan.models import HealthScanDatabase
from services.health_scan.engine import HealthScanEngine

logger = logging.getLogger(__name__)
router = APIRouter()


def _db_path():
    return str(Path(__file__).parent.parent.parent / "data" / "health_scan.db")


def _ds_db_path():
    return str(Path(__file__).parent.parent.parent / "data" / "datasources.db")


class ScanRequest(BaseModel):
    datasource_id: int


@router.post("/scan")
async def trigger_scan(body: ScanRequest, request: Request):
    """发起健康扫描"""
    user = get_current_user(request)
    require_roles(request, ["admin", "data_admin"])

    ds_db = DataSourceDatabase(db_path=_ds_db_path())
    ds = ds_db.get_datasource(body.datasource_id)
    if not ds:
        raise HTTPException(status_code=404, detail="数据源不存在")

    # 非管理员只能扫描自己的数据源
    if user["role"] not in ("admin",) and ds.owner_id != user["id"]:
        raise HTTPException(status_code=403, detail="无权操作此数据源")

    scan_db = HealthScanDatabase(db_path=_db_path())
    record = scan_db.create_scan(
        datasource_id=ds.id,
        datasource_name=ds.name,
        db_type=ds.db_type,
        database_name=ds.database_name,
        triggered_by=user["id"],
    )

    # 解密密码并构建连接配置
    crypto = get_datasource_crypto()
    password = crypto.decrypt(ds.password_encrypted)
    db_config = {
        "db_type": ds.db_type,
        "host": ds.host,
        "port": ds.port,
        "user": ds.username,
        "password": password,
        "database": ds.database_name,
    }

    # 后台线程执行扫描
    engine = HealthScanEngine(db_config)
    loop = asyncio.get_running_loop()
    loop.run_in_executor(None, engine.run_scan, scan_db, record.id)

    return {"scan_id": record.id, "message": "扫描已启动"}


@router.get("/scans")
async def list_scans(request: Request, datasource_id: Optional[int] = None,
                     page: int = 1, page_size: int = 20):
    """扫描历史列表"""
    get_current_user(request)
    scan_db = HealthScanDatabase(db_path=_db_path())
    return scan_db.list_scans(datasource_id=datasource_id, page=page, page_size=page_size)


@router.get("/scans/{scan_id}")
async def get_scan(scan_id: int, request: Request):
    """扫描详情"""
    get_current_user(request)
    scan_db = HealthScanDatabase(db_path=_db_path())
    record = scan_db.get_scan(scan_id)
    if not record:
        raise HTTPException(status_code=404, detail="扫描记录不存在")
    return record.to_dict()


@router.get("/scans/{scan_id}/issues")
async def get_scan_issues(scan_id: int, request: Request,
                          severity: Optional[str] = None,
                          page: int = 1, page_size: int = 50):
    """扫描问题列表"""
    get_current_user(request)
    scan_db = HealthScanDatabase(db_path=_db_path())
    record = scan_db.get_scan(scan_id)
    if not record:
        raise HTTPException(status_code=404, detail="扫描记录不存在")
    return scan_db.get_scan_issues(scan_id, severity=severity, page=page, page_size=page_size)


@router.get("/summary")
async def get_health_summary(request: Request):
    """总览：每个数据源的最新扫描"""
    get_current_user(request)
    scan_db = HealthScanDatabase(db_path=_db_path())
    records = scan_db.get_latest_scans()
    return {"scans": [r.to_dict() for r in records]}

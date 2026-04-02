"""数仓健康检查 API"""
import asyncio
import logging
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse
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


@router.get("/scans/{scan_id}/report")
async def get_scan_report(scan_id: int, request: Request):
    """导出 HTML 格式扫描报告"""
    get_current_user(request)
    scan_db = HealthScanDatabase(db_path=_db_path())
    record = scan_db.get_scan(scan_id)
    if not record:
        raise HTTPException(status_code=404, detail="扫描记录不存在")
    if record.status != "success":
        raise HTTPException(status_code=400, detail="扫描未完成，无法导出报告")

    all_issues = scan_db.get_scan_issues(scan_id, page=1, page_size=9999)
    issues = all_issues["issues"]

    severity_label = {"high": "高风险", "medium": "中风险", "low": "低风险"}
    severity_class = {"high": "level-error", "medium": "level-warning", "low": "level-info"}
    score = record.health_score if record.health_score is not None else 0
    score_color = "#16a34a" if score >= 90 else "#d97706" if score >= 75 else "#dc2626"

    html = f"""<!DOCTYPE html>
<html><head><meta charset="utf-8">
<title>数仓健康检查报告 - {record.datasource_name}</title>
<style>
body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; margin: 0; padding: 30px; background: #f8fafc; color: #334155; }}
.container {{ max-width: 900px; margin: 0 auto; }}
h1 {{ font-size: 22px; margin-bottom: 4px; }}
.subtitle {{ color: #94a3b8; font-size: 13px; margin-bottom: 24px; }}
.stats {{ display: flex; gap: 16px; margin-bottom: 24px; }}
.stat {{ background: #fff; border: 1px solid #e2e8f0; border-radius: 10px; padding: 16px 20px; flex: 1; }}
.stat-label {{ font-size: 11px; color: #94a3b8; text-transform: uppercase; letter-spacing: 0.5px; }}
.stat-value {{ font-size: 28px; font-weight: 700; margin-top: 4px; }}
.score {{ color: {score_color}; }}
table {{ border-collapse: collapse; width: 100%; background: #fff; border: 1px solid #e2e8f0; border-radius: 10px; overflow: hidden; }}
th {{ background: #f1f5f9; text-align: left; padding: 10px 14px; font-size: 11px; color: #64748b; font-weight: 600; text-transform: uppercase; letter-spacing: 0.5px; }}
td {{ padding: 10px 14px; border-top: 1px solid #f1f5f9; font-size: 13px; }}
.level-error {{ background: #fef2f2; }}
.level-warning {{ background: #fffbeb; }}
.level-info {{ background: #eff6ff; }}
.badge {{ display: inline-block; padding: 2px 8px; border-radius: 9999px; font-size: 11px; font-weight: 600; }}
.badge-high {{ background: #fee2e2; color: #dc2626; }}
.badge-medium {{ background: #fef3c7; color: #d97706; }}
.badge-low {{ background: #dbeafe; color: #2563eb; }}
.footer {{ text-align: center; margin-top: 30px; font-size: 11px; color: #94a3b8; }}
</style></head><body>
<div class="container">
<h1>数仓健康检查报告</h1>
<p class="subtitle">{record.datasource_name} · {record.db_type} · {record.database_name} · {record.finished_at or record.started_at or ''}</p>
<div class="stats">
  <div class="stat"><div class="stat-label">健康评分</div><div class="stat-value score">{score}</div></div>
  <div class="stat"><div class="stat-label">检查表数</div><div class="stat-value">{record.total_tables}</div></div>
  <div class="stat"><div class="stat-label">问题总数</div><div class="stat-value">{record.total_issues}</div></div>
  <div class="stat"><div class="stat-label">高 / 中 / 低</div><div class="stat-value" style="font-size:20px">{record.high_count} / {record.medium_count} / {record.low_count}</div></div>
</div>
<table>
<thead><tr><th>风险</th><th>对象类型</th><th>对象名称</th><th>问题类型</th><th>描述</th><th>建议</th></tr></thead>
<tbody>"""

    for issue in issues:
        sev = issue["severity"]
        cls = severity_class.get(sev, "level-info")
        label = severity_label.get(sev, sev)
        badge = f"badge-{sev}"
        obj_type = "表" if issue["object_type"] == "table" else "字段"
        html += f"""
<tr class="{cls}">
  <td><span class="badge {badge}">{label}</span></td>
  <td>{obj_type}</td>
  <td style="font-family:monospace">{issue["object_name"]}</td>
  <td>{issue["issue_type"]}</td>
  <td>{issue["description"]}</td>
  <td>{issue["suggestion"]}</td>
</tr>"""

    if not issues:
        html += '<tr><td colspan="6" style="text-align:center;color:#94a3b8;padding:30px">未发现问题</td></tr>'

    html += """
</tbody></table>
<div class="footer">Mulan BI Platform · 数仓健康检查</div>
</div></body></html>"""

    return HTMLResponse(content=html, headers={
        "Content-Disposition": f'attachment; filename="health-report-{scan_id}.html"'
    })


@router.get("/summary")
async def get_health_summary(request: Request):
    """总览：每个数据源的最新扫描"""
    get_current_user(request)
    scan_db = HealthScanDatabase(db_path=_db_path())
    records = scan_db.get_latest_scans()
    return {"scans": [r.to_dict() for r in records]}

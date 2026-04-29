"""语义维护 - 发布管理 API
"""

from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.crypto import get_tableau_crypto

# 导入中央数据库依赖和统一的权限验证函数
from app.core.database import get_db
from app.core.dependencies import get_current_user
from app.utils.auth import verify_connection_access
from services.semantic_maintenance.rollback_service import RollbackService
from services.semantic_maintenance.publish_service import PublishService
from services.semantic_maintenance.service import SemanticMaintenanceService

# 导入 Tableau 模型和数据库服务
from services.tableau.models import TableauDatabase

router = APIRouter()
_crypto = get_tableau_crypto()


# _db_path 和 _tableau_db_path 不再需要
# def _db_path():
#     return str(Path(__file__).parent.parent.parent.parent.parent / "data" / "semantic_maintenance.db")
#
#
# def _tableau_db_path():
#     return str(Path(__file__).parent.parent.parent.parent.parent / "data" / "tableau.db")


# _verify_connection_access 已经提取到 app.utils.auth.py
# def _verify_connection_access(connection_id: int, user: dict) -> None:
#     """验证用户有权访问指定连接"""
#     import sqlite3
#     conn = sqlite3.connect(_tableau_db_path())
#     cursor = conn.cursor()
#     cursor.execute("SELECT owner_id FROM tableau_connections WHERE id = ?", (connection_id,))
#     row = cursor.fetchone()
#     conn.close()
#     if not row:
#         raise HTTPException(status_code=404, detail="连接不存在")
#     if user["role"] != "admin" and row[0] != user["id"]:
#         raise HTTPException(status_code=403, detail="无权访问该连接")


def _get_publish_service(connection_id: int, user: dict, db: Session) -> PublishService:
    """创建 PublishService 实例（带认证），使用 ORM 获取连接信息"""
    tableau_db = TableauDatabase(session=db)  # Use injected session
    conn = tableau_db.get_connection(connection_id)  # Use ORM 获取连接
    if not conn:
        raise HTTPException(status_code=404, detail="连接不存在")
    try:
        token_value = _crypto.decrypt(conn.token_encrypted)
    except Exception:
        raise HTTPException(status_code=500, detail="Token 解密失败，请重新保存连接凭证")
    service = PublishService(
        server_url=conn.server_url,
        site_content_url=conn.site,
        token_name=conn.token_name,
        token_value=token_value,
        api_version=conn.api_version or "3.21",
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
async def preview_diff(req: PreviewDiffRequest, request: Request, db: Session = Depends(get_db)):
    """预览发布差异：展示 Tableau 当前值 vs Mulan 待发布值"""
    user = get_current_user(request, db) # 传递 db
    verify_connection_access(req.connection_id, user, db) # 使用统一的权限验证函数

    service = _get_publish_service(req.connection_id, user, db) # 传递 db
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
async def publish_datasource(req: PublishDatasourceRequest, request: Request, db: Session = Depends(get_db)):
    """发布数据源语义到 Tableau"""
    user = get_current_user(request, db) # 传递 db
    if user["role"] not in ("admin", "publisher"):
        raise HTTPException(status_code=403, detail="需要 publisher 或 admin 权限")
    verify_connection_access(req.connection_id, user, db) # 使用统一的权限验证函数

    service = _get_publish_service(req.connection_id, user, db) # 传递 db
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

    # Spec 9 → Spec 16: 发布成功发布事件 semantic_table.published
    try:
        from services.events import emit_event
        from services.events.constants import SEMANTIC_TABLE_PUBLISHED, SOURCE_MODULE_SEMANTIC
        ds = sm.db.get_datasource_semantics_by_id(req.ds_id)
        if ds:
            emit_event(
                db=db,
                event_type=SEMANTIC_TABLE_PUBLISHED,
                source_module=SOURCE_MODULE_SEMANTIC,
                payload={
                    "ds_id": req.ds_id,
                    "tableau_datasource_id": ds.tableau_datasource_id,
                    "semantic_name": ds.semantic_name or "",
                    "status": ds.status,
                    "author_id": ds.created_by or user["id"],
                    "actor_id": user["id"],
                },
                actor_id=user["id"],
                extra_data={
                    "semantic_table_id": req.ds_id,
                    "table_name": ds.semantic_name or ds.tableau_datasource_id,
                    "connection_id": req.connection_id,
                },
            )
    except Exception:
        pass  # 事件发布失败不影响主流程

    return result


@router.post("/publish/fields")
async def publish_fields(req: PublishFieldsRequest, request: Request, db: Session = Depends(get_db)):
    """批量发布字段语义到 Tableau"""
    user = get_current_user(request, db) # 传递 db
    if user["role"] not in ("admin", "publisher"):
        raise HTTPException(status_code=403, detail="需要 publisher 或 admin 权限")
    verify_connection_access(req.connection_id, user, db) # 使用统一的权限验证函数

    service = _get_publish_service(req.connection_id, user, db) # 传递 db
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
async def retry_publish(req: RetryPublishRequest, request: Request, db: Session = Depends(get_db)):
    """重试失败发布"""
    user = get_current_user(request, db) # 传递 db
    if user["role"] not in ("admin", "publisher"):
        raise HTTPException(status_code=403, detail="需要 publisher 或 admin 权限")
    verify_connection_access(req.connection_id, user, db) # 使用统一的权限验证函数

    service = _get_publish_service(req.connection_id, user, db) # 传递 db
    try:
        result, err = service.retry_publish(log_id=req.log_id, operator=user["id"], connection_id=req.connection_id)
    finally:
        service.disconnect()

    if err:
        raise HTTPException(status_code=400, detail=err)
    return result


@router.post("/publish/rollback")
async def rollback_publish(req: RollbackPublishRequest, request: Request, db: Session = Depends(get_db)):
    """回滚已发布内容"""
    user = get_current_user(request, db) # 传递 db
    if user["role"] != "admin":
        raise HTTPException(status_code=403, detail="需要 admin 权限")
    verify_connection_access(req.connection_id, user, db) # 使用统一的权限验证函数

    service = _get_publish_service(req.connection_id, user, db) # 传递 db
    try:
        result, err = service.rollback_publish(log_id=req.log_id, operator=user["id"], connection_id=req.connection_id)
    finally:
        service.disconnect()

    if err:
        raise HTTPException(status_code=400, detail=err)
    return result


# --- Publish Logs API (Spec 19) ---


class PublishLogListParams(BaseModel):
    page: int = 1
    page_size: int = 20
    connection_id: Optional[int] = None
    object_type: Optional[str] = None
    status: Optional[str] = None
    operator_id: Optional[int] = None
    start_date: Optional[datetime] = None
    end_date: Optional[datetime] = None
    sort_by: str = "created_at"
    sort_order: str = "desc"


@router.get("/publish-logs")
async def list_publish_logs(
    request: Request,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    connection_id: Optional[int] = Query(None),
    object_type: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    operator_id: Optional[int] = Query(None),
    start_date: Optional[datetime] = Query(None),
    end_date: Optional[datetime] = Query(None),
    sort_by: str = Query("created_at"),
    sort_order: str = Query("desc"),
    db: Session = Depends(get_db),
):
    """
    获取发布日志列表（分页+过滤）。

    - admin/data_admin: 返回全部日志
    - analyst: 仅返回自己操作的日志
    - user: 禁止访问
    """
    user = get_current_user(request, db)

    # user 角色禁止访问
    if user["role"] == "user":
        raise HTTPException(status_code=403, detail={"error_code": "SM_021"})

    # analyst 强制只能查看自己的操作日志
    if user["role"] == "analyst":
        operator_id = user["id"]

    # Validate status
    valid_statuses = ("pending", "success", "failed", "rolled_back", "not_supported")
    if status and status not in valid_statuses:
        raise HTTPException(status_code=400, detail={"error_code": "SM_023"})

    # Validate sort_by
    valid_sort_fields = ("created_at", "id", "status")
    if sort_by not in valid_sort_fields:
        raise HTTPException(status_code=400, detail={"error_code": "SM_024"})

    # Validate sort_order
    if sort_order not in ("asc", "desc"):
        sort_order = "desc"

    # Validate date range
    if start_date and end_date and start_date > end_date:
        raise HTTPException(status_code=400, detail={"error_code": "SM_022"})

    sm = SemanticMaintenanceService()
    items, total = sm.list_publish_logs_with_filters(
        connection_id=connection_id,
        object_type=object_type,
        status=status,
        operator_id=operator_id,
        start_date=start_date,
        end_date=end_date,
        page=page,
        page_size=page_size,
        sort_by=sort_by,
        sort_order=sort_order,
    )

    pages = (total + page_size - 1) // page_size if total > 0 else 0
    return {
        "items": items,
        "total": total,
        "page": page,
        "page_size": page_size,
        "pages": pages,
    }


@router.get("/publish-logs/{log_id}")
async def get_publish_log_detail(
    log_id: int,
    request: Request,
    db: Session = Depends(get_db),
):
    """
    获取发布日志详情（含完整 diff）。
    """
    user = get_current_user(request, db)

    # user 角色禁止访问
    if user["role"] == "user":
        raise HTTPException(status_code=403, detail={"error_code": "SM_021"})

    sm = SemanticMaintenanceService()
    detail = sm.get_publish_log_detail(log_id)

    if not detail:
        raise HTTPException(status_code=404, detail={"error_code": "SM_020"})

    # analyst 只能查看自己操作的日志
    if user["role"] == "analyst" and detail.get("operator"):
        if detail["operator"].get("id") != user["id"]:
            raise HTTPException(status_code=403, detail={"error_code": "SM_021"})

    return detail


# --- Rollback by log_id (Spec 19) ---


class RollbackByLogRequest(BaseModel):
    connection_id: Optional[int] = None


@router.post("/publish-logs/{log_id}/rollback")
async def rollback_publish_log(
    log_id: int,
    request: Request,
    body: Optional[RollbackByLogRequest] = None,
    db: Session = Depends(get_db),
):
    """
    回滚指定发布日志（Spec 19）。

    - 给定 sm_publish_log_id，还原到发布前状态
    - 回滚操作类型：field_mapping变更 → 恢复旧映射 / metric定义变更 → 恢复旧定义 / status变更 → 恢复旧status
    - 回滚前需验证：当前状态允许回滚（非 deprecated 等 terminal 状态）
    - 回滚后记录：sm_publish_log.action='rollback' + previous_version_snapshot

    仅 admin 可执行此操作。
    """
    user = get_current_user(request, db)

    # 仅 admin 可回滚
    if user["role"] != "admin":
        raise HTTPException(status_code=403, detail={"error_code": "SM_025"})

    connection_id = body.connection_id if body else None

    # 权限校验（如果提供了 connection_id）
    if connection_id is not None:
        verify_connection_access(connection_id, user, db)

    rollback_svc = RollbackService()
    result, err = rollback_svc.execute_rollback(
        log_id=log_id,
        operator=user["id"],
        connection_id=connection_id,
    )

    if err:
        # 根据错误类型返回不同状态码
        if "不存在" in err:
            raise HTTPException(status_code=404, detail={"error_code": "SM_020", "message": err})
        elif "不匹配" in err:
            raise HTTPException(status_code=400, detail={"error_code": "SM_026", "message": err})
        elif "只能回滚 success" in err or "已回滚" in err:
            raise HTTPException(status_code=409, detail={"error_code": "SM_027", "message": err})
        else:
            raise HTTPException(status_code=400, detail={"error_code": "SM_028", "message": err})

    return result

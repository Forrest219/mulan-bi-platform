"""
Spec 14 T-09 / T-10 — 管理员 Query 相关 API

路由前缀：/api/admin/query（在 main.py 中注册）

T-09 Endpoints：
    GET    /api/admin/query/connected-app          — 查询当前激活的密钥配置（脱敏）
    PUT    /api/admin/query/connected-app          — 保存/更新密钥配置
    DELETE /api/admin/query/connected-app          — 停用当前配置

T-10 Endpoints：
    GET    /api/admin/query/errors                 — 分页查询告警列表（支持 resolved/error_code 筛选）
    POST   /api/admin/query/errors/{event_id}/resolve — 标记告警为已解决

权限：仅 admin 角色可访问，其他角色返回 403。

职责边界（严格遵守）：
    路由层只做：HTTP 参数解析 / 权限检查（get_current_admin）/ 调用 service
    业务逻辑（加密/解密/upsert/查询）均在 service 层内。
"""
import logging
from datetime import datetime, timezone
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.dependencies import get_current_admin
from app.core.errors import MulanError
from services.query.jwt_service import ConnectedAppSecretsDatabase
from services.query.query_service import QueryErrorEvent

logger = logging.getLogger(__name__)

router = APIRouter()

_secrets_db = ConnectedAppSecretsDatabase()


# ─────────────────────────────────────────────────────────────────────────────
# Pydantic 请求 / 响应模型
# ─────────────────────────────────────────────────────────────────────────────


class ConnectedAppUpsertRequest(BaseModel):
    """PUT /api/admin/query/connected-app 请求体"""

    connection_id: int = Field(..., description="Tableau 连接 ID", gt=0)
    client_id: str = Field(..., description="Connected App Client ID", min_length=1, max_length=256)
    secret_value: str = Field(..., description="Connected App Secret Value（明文，服务层加密后存储）", min_length=1)


class ConnectedAppStatusResponse(BaseModel):
    """GET /api/admin/query/connected-app 响应体（脱敏）"""

    configured: bool
    connection_id: Optional[int] = None
    client_id: Optional[str] = None
    secret_masked: Optional[str] = None  # "***" 或末4位
    is_active: Optional[bool] = None
    created_at: Optional[str] = None


def _mask_secret(secret_encrypted: str) -> str:
    """返回脱敏后的 secret 展示字符串（末4位或 ***）。

    注意：secret_encrypted 是 Fernet 密文，此处不解密，
    直接返回固定掩码——前端只需知道"已配置"即可，不展示任何明文信息。
    """
    return "***"


# ─────────────────────────────────────────────────────────────────────────────
# Endpoints
# ─────────────────────────────────────────────────────────────────────────────


@router.get("/connected-app", response_model=ConnectedAppStatusResponse)
def get_connected_app(
    connection_id: int,
    db: Session = Depends(get_db),
    _admin: dict = Depends(get_current_admin),
):
    """
    GET /api/admin/query/connected-app?connection_id=<id>

    查询指定 Tableau 连接当前激活的 Connected App 密钥配置（脱敏）。
    secret_value 不返回明文，仅返回 "***"。

    Response:
        {
          "configured": true,
          "connection_id": 1,
          "client_id": "my-connected-app-client-id",
          "secret_masked": "***",
          "is_active": true,
          "created_at": "2026-04-21T10:00:00"
        }
    或未配置时：
        {"configured": false}
    """
    record = _secrets_db.get_active(db, connection_id)
    if record is None:
        return ConnectedAppStatusResponse(configured=False)

    return ConnectedAppStatusResponse(
        configured=True,
        connection_id=record.connection_id,
        client_id=record.client_id,
        secret_masked=_mask_secret(record.secret_encrypted),
        is_active=record.is_active,
        created_at=record.created_at.isoformat() if record.created_at else None,
    )


@router.put("/connected-app")
def upsert_connected_app(
    body: ConnectedAppUpsertRequest,
    db: Session = Depends(get_db),
    user: dict = Depends(get_current_admin),
):
    """
    PUT /api/admin/query/connected-app

    新增或替换指定 Tableau 连接的 Connected App 密钥。
    策略：将旧记录标记为 is_active=False，插入新记录。

    Request body:
        connection_id — Tableau 连接 ID
        client_id     — Connected App Client ID
        secret_value  — Connected App Secret Value（明文，服务层 Fernet 加密后存储）

    Response:
        {
          "ok": true,
          "connection_id": 1,
          "client_id": "my-connected-app-client-id",
          "is_active": true,
          "created_at": "2026-04-21T10:00:00"
        }
    """

    try:
        record = _secrets_db.upsert(
            db=db,
            connection_id=body.connection_id,
            client_id=body.client_id,
            secret_plaintext=body.secret_value,
            created_by=user["id"],
        )
        db.commit()
    except Exception as exc:
        db.rollback()
        logger.error(
            "upsert_connected_app 失败 connection_id=%s operator=%s error=%s",
            body.connection_id, user["username"], exc,
        )
        raise MulanError("Q_001", "密钥保存失败，请稍后重试", 500) from exc

    try:
        from services.logs import logger as audit_logger
        audit_logger.log_operation(
            operation_type="connected_app_upsert",
            target=str(body.connection_id),
            status="success",
            operator=user["username"],
            detail=f"配置 Connected App 密钥 connection_id={body.connection_id} client_id={body.client_id}",
        )
    except Exception as log_exc:
        logger.warning("审计日志记录失败: %s", log_exc)

    return {
        "ok": True,
        "connection_id": record.connection_id,
        "client_id": record.client_id,
        "is_active": record.is_active,
        "created_at": record.created_at.isoformat() if record.created_at else None,
    }


@router.delete("/connected-app")
def deactivate_connected_app(
    connection_id: int,
    db: Session = Depends(get_db),
    user: dict = Depends(get_current_admin),
):
    """
    DELETE /api/admin/query/connected-app?connection_id=<id>

    停用指定 Tableau 连接的 Connected App 密钥配置（软删除，is_active=False）。
    如果本来就没有激活的配置，返回 404。

    Response:
        {"ok": true, "deactivated": 1}
    """

    try:
        affected = _secrets_db.deactivate(db, connection_id)
        db.commit()
    except Exception as exc:
        db.rollback()
        logger.error(
            "deactivate_connected_app 失败 connection_id=%s operator=%s error=%s",
            connection_id, user["username"], exc,
        )
        raise MulanError("Q_001", "停用操作失败，请稍后重试", 500) from exc

    if affected == 0:
        raise MulanError("Q_002", "未找到激活的 Connected App 配置", 404)

    try:
        from services.logs import logger as audit_logger
        audit_logger.log_operation(
            operation_type="connected_app_deactivate",
            target=str(connection_id),
            status="success",
            operator=user["username"],
            detail=f"停用 Connected App 密钥 connection_id={connection_id}",
        )
    except Exception as log_exc:
        logger.warning("审计日志记录失败: %s", log_exc)

    return {"ok": True, "deactivated": affected}


# ─────────────────────────────────────────────────────────────────────────────
# T-10：告警事件管理
# ─────────────────────────────────────────────────────────────────────────────

# 合法的 error_code 枚举值（与 query_service.py 中定义一致）
_VALID_ERROR_CODES = {"Q_JWT_001", "Q_PERM_002", "Q_TIMEOUT_003", "Q_MCP_004", "Q_LLM_005"}

# error_code → error_type 映射（query_error_events.error_type 字段存储的是 error_type，非 code）
_ERROR_CODE_TO_TYPE: dict = {
    "Q_JWT_001": "identity_not_found",
    "Q_PERM_002": "perm_denied",
    "Q_TIMEOUT_003": "mcp_timeout",
    "Q_MCP_004": "mcp_error",
    "Q_LLM_005": "llm_error",
}


class QueryErrorEventResponse(BaseModel):
    """单条告警事件响应体"""

    id: int
    username: str
    error_type: str
    connection_id: Optional[int] = None
    raw_error: Optional[str] = None
    resolved: bool
    created_at: str
    resolved_at: Optional[str] = None


class QueryErrorListResponse(BaseModel):
    """GET /api/admin/query/errors 响应体"""

    items: List[QueryErrorEventResponse]
    total: int
    page: int
    page_size: int


@router.get("/errors", response_model=QueryErrorListResponse)
def list_query_errors(
    db: Session = Depends(get_db),
    _admin: dict = Depends(get_current_admin),
    resolved: bool = Query(False, description="true=已解决，false=未解决（默认）"),
    error_code: Optional[str] = Query(None, description="按错误码筛选：Q_JWT_001 / Q_PERM_002 / Q_TIMEOUT_003 / Q_MCP_004 / Q_LLM_005"),
    page: int = Query(1, ge=1, description="页码，从 1 开始"),
    page_size: int = Query(20, ge=1, le=100, description="每页条数（1-100）"),
):
    """
    GET /api/admin/query/errors

    分页查询问数告警事件列表。

    筛选参数：
        resolved   — 是否已解决（默认 false，只看未处理告警）
        error_code — 可选，按错误码筛选（映射到 error_type 字段）
        page       — 页码（从 1 开始）
        page_size  — 每页条数（默认 20，最大 100）

    Response:
        {
          "items": [...],
          "total": 42,
          "page": 1,
          "page_size": 20
        }
    """

    # 校验 error_code 参数
    if error_code is not None and error_code not in _VALID_ERROR_CODES:
        raise MulanError("Q_005", f"无效的 error_code，允许值：{sorted(_VALID_ERROR_CODES)}", 422)

    # 构造基础查询
    q = db.query(QueryErrorEvent).filter(QueryErrorEvent.resolved == resolved)

    # 按 error_code 筛选（转换为 error_type 字段）
    if error_code is not None:
        error_type_filter = _ERROR_CODE_TO_TYPE.get(error_code)
        if error_type_filter:
            q = q.filter(QueryErrorEvent.error_type == error_type_filter)

    # 计算总数
    total = q.count()

    # 分页 + 排序（按创建时间倒序，最新告警在前）
    offset = (page - 1) * page_size
    events = (
        q.order_by(QueryErrorEvent.created_at.desc())
        .offset(offset)
        .limit(page_size)
        .all()
    )

    items = [
        QueryErrorEventResponse(
            id=ev.id,
            username=ev.username,
            error_type=ev.error_type,
            connection_id=ev.connection_id,
            raw_error=ev.raw_error,
            resolved=ev.resolved,
            created_at=ev.created_at.isoformat() if ev.created_at else "",
            resolved_at=ev.resolved_at.isoformat() if getattr(ev, "resolved_at", None) else None,
        )
        for ev in events
    ]

    return QueryErrorListResponse(
        items=items,
        total=total,
        page=page,
        page_size=page_size,
    )


@router.post("/errors/{event_id}/resolve")
def resolve_query_error(
    event_id: int,
    db: Session = Depends(get_db),
    user: dict = Depends(get_current_admin),
):
    """
    POST /api/admin/query/errors/{event_id}/resolve

    标记指定告警事件为已解决，记录 resolved_at 时间戳。

    Response:
        {"ok": true, "id": 42, "resolved": true, "resolved_at": "2026-04-21T10:00:00"}

    Errors:
        404 — 事件不存在
        409 — 事件已经是已解决状态
    """

    event = db.query(QueryErrorEvent).filter(QueryErrorEvent.id == event_id).first()
    if event is None:
        raise MulanError("Q_003", f"告警事件 {event_id} 不存在", 404)

    if event.resolved:
        raise MulanError("Q_004", "该告警事件已经是已解决状态", 409)

    try:
        event.resolved = True
        # resolved_at 字段需要在 ORM 模型上存在；若模型尚未定义该列，此处会静默忽略
        # （数据库列通过 Alembic 迁移添加，路由层只做赋值）
        now_utc = datetime.now(timezone.utc).replace(tzinfo=None)  # 存入 naive UTC
        setattr(event, "resolved_at", now_utc)
        db.commit()
        db.refresh(event)
    except Exception as exc:
        db.rollback()
        logger.error(
            "resolve_query_error 失败 event_id=%s operator=%s error=%s",
            event_id, user["username"], exc,
        )
        raise MulanError("Q_001", "标记已解决失败，请稍后重试", 500) from exc

    resolved_at_val = getattr(event, "resolved_at", None)
    return {
        "ok": True,
        "id": event.id,
        "resolved": event.resolved,
        "resolved_at": resolved_at_val.isoformat() if resolved_at_val else None,
    }

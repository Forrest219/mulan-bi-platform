"""
Spec 14 T-04 — 问数 API 路由层

路由前缀：/api/query（在 main.py 中注册）

Endpoints：
    GET  /api/query/datasources?connection_id=<id>  — 当前用户有权限的数据源列表
    POST /api/query/ask                             — 核心问数接口
    GET  /api/query/sessions                        — 当前用户历史对话列表
    GET  /api/query/sessions/{session_id}/messages  — 某对话的消息历史

职责边界（严格遵守）：
    路由层只做：HTTP 参数解析 / 权限检查（get_current_user）/ 调用 service / 返回响应
    业务逻辑禁止写在路由层。

自然语言 → VizQL JSON（占位说明）：
    TODO (T-04 placeholder): 当前实现将 message 原样作为 vizql_query 的 question 字段透传，
    未经 NLQ 引擎解析。正式版本应接入 NLQ 解析流水线（与 /api/search/query 路径对齐），
    将自然语言 message 解析为 VizQL 结构化 JSON 后再传给 QueryService.ask()。
    在该占位逻辑下，MCP 将以 fallback 空查询处理，返回结果可能为空。

权限设计：
    仅登录即可（Depends(get_current_user)），不新增独立权限，不改动 Auth 模块。
"""
import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.dependencies import get_current_user
from services.query.query_service import QueryService, QueryServiceError

logger = logging.getLogger(__name__)

router = APIRouter()


# ─────────────────────────────────────────────────────────────────────────────
# Pydantic 请求 / 响应模型
# ─────────────────────────────────────────────────────────────────────────────


class AskRequest(BaseModel):
    """POST /api/query/ask 请求体"""

    connection_id: int
    datasource_luid: str
    message: str
    session_id: Optional[str] = None  # None 则新建 session


class AskResponse(BaseModel):
    """POST /api/query/ask 响应体"""

    session_id: str
    answer: str           # LLM 分析摘要（降级时为空字符串）
    data: Dict[str, Any]  # MCP 原始查询结果 {"fields": [...], "rows": [...]}
    error: Optional[str] = None  # 非阻断性错误描述（如 LLM 降级原因）


# ─────────────────────────────────────────────────────────────────────────────
# 内部工具
# ─────────────────────────────────────────────────────────────────────────────


def _map_service_error(exc: QueryServiceError) -> HTTPException:
    """将 QueryServiceError 映射为合适的 HTTP 状态码。"""
    code_to_status = {
        "Q_JWT_001": 503,   # 密钥未配置 → 服务不可用
        "Q_PERM_002": 403,  # Tableau 权限不足
        "Q_TIMEOUT_003": 504,  # MCP 超时 → 网关超时
        "Q_MCP_004": 502,   # MCP 其他失败 → Bad Gateway
        "Q_LLM_005": 502,   # LLM 失败（通常降级，不走此路径）
        "Q_INPUT_006": 400, # 输入校验失败
    }
    status = code_to_status.get(exc.code, 500)
    return HTTPException(
        status_code=status,
        detail={"error_code": exc.code, "message": exc.message, "details": exc.details},
    )


def _build_vizql_query(message: str) -> Dict[str, Any]:
    """
    TODO (T-04 placeholder): 将自然语言 message 解析为 VizQL 结构化 JSON。

    当前为占位实现：直接将 message 封装为 {"question": message}，
    由 QueryService.ask() 以 fallback 空查询处理。

    正式版本应调用 NLQ 解析流水线，生成符合 Tableau VizQL 规范的 JSON，例如：
    {
        "datasource": {"datasourceName": "..."},
        "columns": [{"columnName": "Sales", "function": "SUM"}],
        "filters": [...],
        ...
    }
    """
    return {"question": message}


# ─────────────────────────────────────────────────────────────────────────────
# Endpoints
# ─────────────────────────────────────────────────────────────────────────────


@router.get("/datasources")
def list_query_datasources(
    connection_id: int = Query(..., description="Tableau 连接 ID"),
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """
    GET /api/query/datasources?connection_id=<id>

    返回当前用户在指定 Tableau 连接中有权限访问的数据源列表。
    权限检查由 Tableau Connected Apps JWT（以用户身份签发）实现。

    Response:
        {"datasources": [{"luid": "...", "name": "..."}, ...], "total": N}
    """
    svc = QueryService(db=db)
    try:
        datasources = svc.list_datasources(
            username=current_user["username"],
            connection_id=connection_id,
            user_id=current_user["id"],
        )
    except QueryServiceError as exc:
        logger.warning(
            "list_datasources 失败 user=%s connection_id=%s code=%s msg=%s",
            current_user["username"], connection_id, exc.code, exc.message,
        )
        raise _map_service_error(exc)

    return {"datasources": datasources, "total": len(datasources)}


@router.post("/ask")
async def ask(
    body: AskRequest,
    request: Request,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """
    POST /api/query/ask  — SSE 流式响应（Spec 14 §5.2）

    改为 text/event-stream 格式，逐 token 推送，前端用 ReadableStream 消费。

    Request body:
        session_id      — 可选，续接历史对话；None 则新建 session
        connection_id   — Tableau 连接 ID
        datasource_luid — 数据源 LUID
        message         — 自然语言问题

    SSE Events:
        data: {"type": "token",  "content": "<chunk>"}\n\n
        data: {"type": "done",   "session_id": "...", "answer": "...", "data_table": [...]}\n\n
        data: {"type": "error",  "code": "Q_XXX_NNN", "message": "..."}\n\n
    """
    # 路由层将自然语言 message 解析为 VizQL JSON（当前为占位实现，详见 _build_vizql_query 注释）
    vizql_query = _build_vizql_query(body.message)

    svc = QueryService(db=db)

    logger.info(
        "ask_stream 请求 user=%s connection_id=%s ds=%s session=%s",
        current_user["username"], body.connection_id,
        body.datasource_luid, body.session_id,
    )

    return StreamingResponse(
        svc.ask_stream(
            username=current_user["username"],
            user_id=current_user["id"],
            connection_id=body.connection_id,
            datasource_luid=body.datasource_luid,
            message=body.message,
            session_id=body.session_id,
            vizql_query=vizql_query,
        ),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


@router.get("/sessions")
def list_sessions(
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """
    GET /api/query/sessions

    返回当前用户的历史问数对话列表（按 updated_at 或 created_at 降序，最多 100 条）。

    Response:
        {"items": [{"id": "...", "title": "...", "created_at": "...", "updated_at": "..."}, ...], "total": N}
    """
    from services.query.query_service import QuerySession

    user_id = current_user["id"]
    rows: List[QuerySession] = (
        db.query(QuerySession)
        .filter(QuerySession.user_id == user_id, QuerySession.is_active == True)  # noqa: E712
        .order_by(QuerySession.created_at.desc())
        .limit(100)
        .all()
    )

    sessions = [
        {
            "id": str(s.id),
            "title": s.title,
            "created_at": s.created_at.isoformat() if s.created_at else None,
            "updated_at": s.updated_at.isoformat() if s.updated_at else None,
        }
        for s in rows
    ]
    return {"items": sessions, "total": len(sessions)}


@router.get("/sessions/{session_id}/messages")
def list_session_messages(
    session_id: str,
    limit: int = Query(default=50, ge=1, le=200, description="最多返回条数"),
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """
    GET /api/query/sessions/{session_id}/messages

    返回指定对话的消息历史（按 created_at 升序）。
    若 session_id 不存在或不属于当前用户，返回 404。

    Response:
        {
            "session_id": "...",
            "messages": [
                {
                    "id": 1,
                    "role": "user" | "assistant",
                    "content": "...",
                    "data_table": {...} | null,
                    "created_at": "..."
                },
                ...
            ],
            "total": N
        }
    """
    from services.query.query_service import QueryMessageDatabase, QueryServiceError as _QSE

    msg_db = QueryMessageDatabase()
    try:
        messages = msg_db.list_messages(
            db=db,
            session_id=session_id,
            user_id=current_user["id"],
            limit=limit,
        )
    except _QSE as exc:
        raise _map_service_error(exc)

    # list_messages 在 session 不存在/无权时返回空列表；
    # 为提供明确的 404，额外做一次 session 归属校验。
    if not messages:
        from services.query.query_service import QuerySession
        import uuid as _uuid
        try:
            uid = _uuid.UUID(session_id)
        except ValueError:
            raise HTTPException(status_code=404, detail="session 不存在")
        sess = (
            db.query(QuerySession)
            .filter(
                QuerySession.id == uid,
                QuerySession.user_id == current_user["id"],
            )
            .first()
        )
        if sess is None:
            raise HTTPException(status_code=404, detail="session 不存在或无权访问")

    serialized = [
        {
            "id": m.id,
            "role": m.role,
            "content": m.content,
            "data_table": m.data_table,
            "datasource_luid": m.datasource_luid,
            "created_at": m.created_at.isoformat() if m.created_at else None,
        }
        for m in messages
    ]
    return {"session_id": session_id, "messages": serialized, "total": len(serialized)}

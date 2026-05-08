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

自然语言 → VizQL JSON（LLM One-Pass）：
    _build_vizql_query 调用 llm_service.complete_with_temp 将自然语言解析为
    VizQL 结构化 JSON，传给 QueryService.ask_stream()。解析失败时 fallback 到
    {"question": message}，不阻断主流程。

权限设计：
    仅登录即可（Depends(get_current_user)），不新增独立权限，不改动 Auth 模块。
"""
import json
import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.dependencies import get_current_user
from services.llm.service import llm_service
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


_NLQ_SYSTEM_PROMPT = (
    "你是将自然语言问题转换为数据查询 JSON 的解析器。\n"
    "输出格式（仅输出纯 JSON，不含任何 markdown 或额外文字）：\n"
    "{\n"
    '  "question": "原始自然语言问题",\n'
    '  "fields": [\n'
    '    {"fieldCaption": "字段名", "function": "SUM|AVG|COUNT|MAX|MIN|COUNTD|DAY|MONTH|YEAR|<留空>"},\n'
    '    ...\n'
    '  ],\n'
    '  "filters": [\n'
    '    {"field": {"fieldCaption": "字段名"}, "filterType": "SET", "values": ["值1", "值2"]},\n'
    '    ...\n'
    '  ],\n'
    '  "limit": 100\n'
    "}\n"
    "规则：\n"
    "1. fields 包含问题涉及的度量字段（需聚合时写 function）和维度字段（function 留空）\n"
    "2. filters 仅在问题有明确过滤条件时填写，其余情况为空数组\n"
    "3. limit 默认 100；用户要求 TOP N 时填写 N\n"
    "4. question 必须保留原始问题"
)


async def _build_vizql_query(message: str) -> Dict[str, Any]:
    """将自然语言 message 解析为 VizQL 结构化 JSON（LLM One-Pass）。

    调用 llm_service.complete_with_temp（temperature=0.0 保证输出稳定）。
    任何错误均 fallback 到 {"question": message}，保证不阻断主流程。
    """
    try:
        result = await llm_service.complete_with_temp(
            prompt=message,
            system=_NLQ_SYSTEM_PROMPT,
            temperature=0.0,
            timeout=10,
        )
        if "error" in result or "content" not in result:
            return {"question": message}

        content = result["content"].strip()
        # 去除可能的 markdown 代码块包装
        if content.startswith("```"):
            lines = content.split("\n")
            # 去掉首行 ```json / ``` 和末行 ```
            content = "\n".join(lines[1:-1]) if lines[-1].strip() == "```" else "\n".join(lines[1:])

        parsed = json.loads(content)
        if not isinstance(parsed, dict):
            return {"question": message}
        # 确保 question 字段始终存在
        parsed.setdefault("question", message)
        return parsed
    except Exception:
        logger.debug("NLQ 解析失败，使用 fallback 空查询", exc_info=True)
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
    # NL→VizQL: LLM One-Pass 解析（失败时 fallback 到 {"question": message}）
    vizql_query = await _build_vizql_query(body.message)

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


@router.delete("/sessions/{session_id}", status_code=204)
def delete_session(
    session_id: str,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """
    DELETE /api/query/sessions/{session_id}

    软删除指定对话（设置 is_active=False）。
    仅允许删除属于当前用户的 session，否则返回 404。
    """
    import uuid as _uuid
    from services.query.query_service import QuerySession

    try:
        uid = _uuid.UUID(session_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="session 不存在")

    sess = (
        db.query(QuerySession)
        .filter(
            QuerySession.id == uid,
            QuerySession.user_id == current_user["id"],
            QuerySession.is_active == True,  # noqa: E712
        )
        .first()
    )
    if sess is None:
        raise HTTPException(status_code=404, detail="session 不存在或无权访问")

    sess.is_active = False
    db.commit()
    return None

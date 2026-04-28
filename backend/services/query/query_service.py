"""
Spec 14 T-02 — 问数业务服务层

职责边界（严格遵守）：
- QueryService  : 问数核心业务逻辑（不 import web framework / Request）
  - list_datasources()  : 签发用户 JWT → 调用 MCP 获取该用户有权限的数据源列表
  - ask()               : 签发 JWT → MCP 查询（以用户身份）→ LLM 摘要 → 持久化消息记录
- QueryMessageDatabase : query_sessions / query_messages 表 CRUD
- QueryErrorDatabase   : query_error_events 表 CRUD（错误告警持久化）

错误处理规范：
- JWT 签发失败（RuntimeError）→ QueryServiceError(code="Q_JWT_001")
- Tableau 无权限（TableauMCPError NLQ_009）→ QueryServiceError(code="Q_PERM_002")
- MCP 超时（TableauMCPError NLQ_007）→ QueryServiceError(code="Q_TIMEOUT_003")
- MCP 其他失败（TableauMCPError NLQ_006）→ QueryServiceError(code="Q_MCP_004")
- LLM 调用失败 → QueryServiceError(code="Q_LLM_005")，不阻断返回（降级返回数据表）
"""
import asyncio
import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Any, AsyncGenerator, Dict, List, Optional

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Session

from app.core.database import Base, sa_func, sa_text

# 模块顶层导入（允许测试通过 patch 替换）
# services.tableau / services.llm 均不依赖 services.query，无循环风险
from services.tableau.mcp_client import TableauMCPClient, TableauMCPError  # noqa: E402
from services.llm.service import llm_service  # noqa: E402
from services.llm.nlq_service import get_wrapper, get_principal  # noqa: E402

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# 错误类型
# ─────────────────────────────────────────────────────────────────────────────

class QueryServiceError(Exception):
    """问数业务层统一异常。

    code 规范：
        Q_JWT_001     — Connected App 密钥未配置，无法签发 JWT
        Q_PERM_002    — Tableau 返回权限不足（用户无数据源访问权）
        Q_TIMEOUT_003 — MCP 请求超时
        Q_MCP_004     — MCP 其他失败（网络、格式等）
        Q_LLM_005     — LLM 摘要生成失败（非阻断性，通常降级处理）
        Q_INPUT_006   — 输入参数校验失败
    """

    def __init__(self, code: str, message: str, details: dict = None) -> None:
        self.code = code
        self.message = message
        self.details = details or {}
        super().__init__(f"[{code}] {message}")


# ─────────────────────────────────────────────────────────────────────────────
# ORM 模型（与迁移 20260421_030000 对应）
# ─────────────────────────────────────────────────────────────────────────────

class QuerySession(Base):
    """query_sessions — 用户问数对话 Session"""

    __tablename__ = "query_sessions"

    id = Column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=sa_text("gen_random_uuid()"),
    )
    user_id = Column(
        Integer,
        ForeignKey("auth_users.id", ondelete="CASCADE"),
        nullable=False,
    )
    title = Column(String(128), nullable=True)
    created_at = Column(DateTime, nullable=False, server_default=sa_func.now())
    updated_at = Column(DateTime, nullable=True)
    is_active = Column(Boolean, nullable=False, server_default=sa_text("true"))


class QueryMessage(Base):
    """query_messages — 对话消息记录（user / assistant）"""

    __tablename__ = "query_messages"

    id = Column(Integer, primary_key=True, autoincrement=True)
    session_id = Column(
        UUID(as_uuid=True),
        ForeignKey("query_sessions.id", ondelete="CASCADE"),
        nullable=False,
    )
    role = Column(String(16), nullable=False)  # 'user' | 'assistant'
    content = Column(Text, nullable=False)
    data_table = Column(JSONB, nullable=True)
    connection_id = Column(
        Integer,
        ForeignKey("tableau_connections.id", ondelete="SET NULL"),
        nullable=True,
    )
    datasource_luid = Column(String(256), nullable=True)
    query_context = Column(JSONB, nullable=True)
    created_at = Column(DateTime, nullable=False, server_default=sa_func.now())


class QueryErrorEvent(Base):
    """query_error_events — Tableau 身份问题告警（管理员监控）"""

    __tablename__ = "query_error_events"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(
        Integer,
        ForeignKey("auth_users.id", ondelete="SET NULL"),
        nullable=True,
    )
    username = Column(String(64), nullable=False)
    error_type = Column(String(64), nullable=False)
    connection_id = Column(
        Integer,
        ForeignKey("tableau_connections.id", ondelete="SET NULL"),
        nullable=True,
    )
    raw_error = Column(Text, nullable=True)
    resolved = Column(Boolean, nullable=False, server_default=sa_text("false"))
    resolved_at = Column(DateTime, nullable=True)  # T-10：标记已解决时记录时间戳
    created_at = Column(DateTime, nullable=False, server_default=sa_func.now())


# ─────────────────────────────────────────────────────────────────────────────
# 数据库访问层
# ─────────────────────────────────────────────────────────────────────────────

class QueryMessageDatabase:
    """
    query_sessions / query_messages 表 CRUD。

    所有方法接受 db: Session，由调用方控制事务边界。
    """

    def get_or_create_session(
        self, db: Session, user_id: int, session_id: Optional[str] = None
    ) -> QuerySession:
        """
        获取或创建问数 Session。

        若 session_id 为 None，创建新 session。
        若 session_id 不存在或已失效，抛出 QueryServiceError(Q_INPUT_006)。
        """
        if session_id is None:
            sess = QuerySession(user_id=user_id)
            db.add(sess)
            db.flush()
            return sess

        # 将 str UUID 转换为 UUID 对象（PostgreSQL UUID 类型）
        try:
            uid = uuid.UUID(session_id) if isinstance(session_id, str) else session_id
        except ValueError:
            raise QueryServiceError(
                code="Q_INPUT_006",
                message=f"session_id 格式无效: {session_id}",
            )

        sess = (
            db.query(QuerySession)
            .filter(QuerySession.id == uid, QuerySession.user_id == user_id)
            .first()
        )
        if sess is None:
            raise QueryServiceError(
                code="Q_INPUT_006",
                message="session 不存在或无权访问",
                details={"session_id": session_id, "user_id": user_id},
            )
        return sess

    def append_message(
        self,
        db: Session,
        session_id: Any,
        role: str,
        content: str,
        connection_id: Optional[int] = None,
        datasource_luid: Optional[str] = None,
        data_table: Optional[dict] = None,
        query_context: Optional[dict] = None,
    ) -> QueryMessage:
        """向 session 追加一条消息记录，返回持久化后的对象。"""
        msg = QueryMessage(
            session_id=session_id,
            role=role,
            content=content,
            connection_id=connection_id,
            datasource_luid=datasource_luid,
            data_table=data_table,
            query_context=query_context,
        )
        db.add(msg)
        db.flush()
        return msg

    def list_messages(
        self,
        db: Session,
        session_id: str,
        user_id: int,
        limit: int = 50,
    ) -> List[QueryMessage]:
        """按时间正序返回 session 内最近 N 条消息。"""
        try:
            uid = uuid.UUID(session_id) if isinstance(session_id, str) else session_id
        except ValueError:
            return []
        # 先校验 session 归属
        sess = (
            db.query(QuerySession)
            .filter(QuerySession.id == uid, QuerySession.user_id == user_id)
            .first()
        )
        if sess is None:
            return []
        return (
            db.query(QueryMessage)
            .filter(QueryMessage.session_id == uid)
            .order_by(QueryMessage.created_at.asc())
            .limit(limit)
            .all()
        )


class QueryErrorDatabase:
    """query_error_events 表 CRUD（管理员监控用）。"""

    def record(
        self,
        db: Session,
        username: str,
        error_type: str,
        user_id: Optional[int] = None,
        connection_id: Optional[int] = None,
        raw_error: Optional[str] = None,
    ) -> QueryErrorEvent:
        """写入一条错误告警记录。"""
        ev = QueryErrorEvent(
            username=username,
            error_type=error_type,
            user_id=user_id,
            connection_id=connection_id,
            raw_error=raw_error,
        )
        db.add(ev)
        db.flush()
        return ev


# ─────────────────────────────────────────────────────────────────────────────
# LLM 分析摘要 Prompt 模板
# ─────────────────────────────────────────────────────────────────────────────

_ANALYSIS_SYSTEM = (
    "你是一名数据分析师，根据用户问题和查询到的数据表生成简洁的中文分析摘要。"
    "摘要应聚焦关键发现，不超过 200 字，避免重复数据表中已有的数字。"
)

_ANALYSIS_PROMPT_TEMPLATE = """用户问题：{question}

数据结果（前 10 行）：
{data_preview}

请用中文生成一段分析摘要，指出关键趋势或发现。"""


def _build_data_preview(data: dict, max_rows: int = 10) -> str:
    """将 MCP 返回的 fields/rows 格式化为简单的文本预览。"""
    fields = data.get("fields", [])
    rows = data.get("rows", [])
    if not fields:
        return "（无数据）"
    header = " | ".join(str(f) for f in fields)
    lines = [header, "-" * len(header)]
    for row in rows[:max_rows]:
        lines.append(" | ".join(str(v) for v in row))
    if len(rows) > max_rows:
        lines.append(f"... 共 {len(rows)} 行")
    return "\n".join(lines)


# ─────────────────────────────────────────────────────────────────────────────
# 核心业务服务
# ─────────────────────────────────────────────────────────────────────────────

class QueryService:
    """
    问数业务服务层（T-02）。

    设计原则：
    - 不持有 DB Session（db 由调用方每次传入）
    - 不 import web framework / Request（services/ 层隔离规范）
    - 每次请求实例化 JWTService（不缓存 JWT token，防重放）
    - MCP 调用以用户身份发起（jwt_token 注入 Authorization header）
    - LLM 摘要失败时降级：返回数据表 + 空摘要，不抛异常

    用法：
        svc = QueryService(db=session)
        ds_list = svc.list_datasources(username="alice", connection_id=1)
        result = await svc.ask(
            username="alice",
            user_id=42,
            connection_id=1,
            datasource_luid="abc-123",
            session_id=None,   # None 则新建 session
            message="销售额最高的前5个地区？",
        )
    """

    def __init__(self, db: Session) -> None:
        self._db = db
        self._msg_db = QueryMessageDatabase()
        self._err_db = QueryErrorDatabase()

    # ── 内部：JWT 签发 ──────────────────────────────────────────────────────

    def _issue_jwt(self, username: str, connection_id: int) -> str:
        """
        为当前用户签发 Tableau Connected Apps JWT。

        每次请求调用，不缓存 token（Tableau 要求 jti 唯一）。

        Raises:
            QueryServiceError(Q_JWT_001): 密钥未配置或签发失败
        """
        from services.query.jwt_service import JWTService

        svc = JWTService()
        try:
            return svc.issue(username=username, connection_id=connection_id, db=self._db)
        except RuntimeError as e:
            raise QueryServiceError(
                code="Q_JWT_001",
                message=f"JWT 签发失败：{e}",
                details={"connection_id": connection_id, "username": username},
            ) from e
        except ValueError as e:
            raise QueryServiceError(
                code="Q_INPUT_006",
                message=f"JWT 签发参数错误：{e}",
                details={"username": username},
            ) from e

    # ── 内部：错误分类 & 告警写入 ──────────────────────────────────────────

    def _classify_and_record_mcp_error(
        self,
        exc: Exception,
        username: str,
        user_id: Optional[int],
        connection_id: int,
    ) -> QueryServiceError:
        """
        将 TableauMCPError 分类映射为 QueryServiceError，并写入 query_error_events。
        返回映射后的 QueryServiceError（不抛出，由调用方决定是否 raise）。
        """
        if not isinstance(exc, TableauMCPError):
            return QueryServiceError(
                code="Q_MCP_004",
                message=str(exc),
                details={"raw": str(exc)},
            )

        mcp_err: TableauMCPError = exc

        if mcp_err.code == "NLQ_009":
            # 区分 identity_not_found（401 / user not found）与 perm_denied（403）
            # 判断依据：
            #   1. HTTP 层传入的 status_code（HTTP 401 → identity_not_found）
            #   2. MCP 协议层错误码字符串 "unauthorized"（Tableau 401 语义）
            #   3. message 包含 "user not found" / "not found" 等身份不存在语义
            http_status = mcp_err.details.get("status_code")
            msg_lower = mcp_err.message.lower()
            is_identity_error = (
                http_status == 401
                or "unauthorized" in str(mcp_err.details).lower()
                or "user not found" in msg_lower
                or "not found" in msg_lower
                or "identity" in msg_lower
                or "invalid user" in msg_lower
            )
            if is_identity_error:
                error_type = "identity_not_found"
                svc_code = "Q_PERM_002"
            else:
                error_type = "perm_denied"
                svc_code = "Q_PERM_002"
        elif mcp_err.code == "NLQ_007":
            error_type = "mcp_timeout"
            svc_code = "Q_TIMEOUT_003"
        else:
            error_type = "mcp_error"
            svc_code = "Q_MCP_004"

        # 写入告警（使用独立 DB session + 独立 commit，确保主事务 rollback 时告警仍落地）
        try:
            from app.core.database import SessionLocal as _SessionLocal
            _alert_db = _SessionLocal()
            try:
                self._err_db.record(
                    db=_alert_db,
                    username=username,
                    error_type=error_type,
                    user_id=user_id,
                    connection_id=connection_id,
                    raw_error=f"[{mcp_err.code}] {mcp_err.message}",
                )
                _alert_db.commit()
            except Exception as e_inner:
                _alert_db.rollback()
                raise e_inner
            finally:
                _alert_db.close()
        except Exception as e_rec:
            logger.warning("query_error_events 写入失败（忽略）: %s", e_rec)

        return QueryServiceError(
            code=svc_code,
            message=mcp_err.message,
            details={**mcp_err.details, "mcp_code": mcp_err.code},
        )

    # ── 公开 API ───────────────────────────────────────────────────────────

    def list_datasources(
        self,
        username: str,
        connection_id: int,
        user_id: Optional[int] = None,
        limit: int = 50,
        timeout: int = 30,
    ) -> List[Dict[str, Any]]:
        """
        获取当前用户在 Tableau 有权限的数据源列表。

        流程：
            1. 为 username 签发 Connected Apps JWT（以用户身份）
            2. 调用 MCP list_datasources，JWT 注入 Authorization header
            3. 返回标准化的数据源列表

        Args:
            username: Tableau 用户名（与 AD 账户一致）
            connection_id: Tableau 连接 ID
            user_id: 当前用户 DB id（仅用于错误告警记录，可为 None）
            limit: 最大返回条数
            timeout: MCP 请求超时秒数

        Returns:
            [{"luid": "...", "name": "..."}, ...]（Tableau 返回内容，原样透传）

        Raises:
            QueryServiceError: Q_JWT_001 / Q_PERM_002 / Q_TIMEOUT_003 / Q_MCP_004
        """
        # Step 1: 签发 JWT
        jwt_token = self._issue_jwt(username=username, connection_id=connection_id)

        # Step 2: 调用 MCP（以用户身份）
        client = TableauMCPClient(connection_id=connection_id, username=username)
        try:
            result = client.list_datasources(
                limit=limit,
                timeout=timeout,
                connection_id=connection_id,
                jwt_token=jwt_token,
            )
        except TableauMCPError as e:
            raise self._classify_and_record_mcp_error(
                exc=e,
                username=username,
                user_id=user_id,
                connection_id=connection_id,
            ) from e

        # Step 3: 标准化返回
        datasources = result.get("datasources", [])
        if not isinstance(datasources, list):
            datasources = []
        return datasources

    async def ask(
        self,
        username: str,
        connection_id: int,
        datasource_luid: str,
        message: str,
        session_id: Optional[str] = None,
        user_id: Optional[int] = None,
        vizql_query: Optional[Dict[str, Any]] = None,
        limit: int = 1000,
        timeout: int = 30,
    ) -> Dict[str, Any]:
        """
        核心问数链路（异步）。

        流程：
            1. 获取/创建 QuerySession
            2. 持久化用户消息（role=user）
            3. 签发 Tableau Connected Apps JWT
            4. 调用 MCP query_datasource（以用户身份）
            5. 调用 LLM 生成分析摘要（失败时降级返回空摘要）
            6. 持久化 assistant 消息（含 data_table + 摘要）
            7. 返回结构化响应

        Args:
            username: Tableau 用户名
            connection_id: Tableau 连接 ID
            datasource_luid: 数据源 LUID
            message: 用户问题（自然语言）
            session_id: 已有 session UUID（None 则新建）
            user_id: 当前用户 DB id（可为 None）
            vizql_query: VizQL JSON 查询体（由上层 NLQ 解析后传入；None 则使用 fallback 空查询）
            limit: MCP 返回行数上限
            timeout: MCP 请求超时秒数

        Returns:
            {
                "session_id": str,   # UUID
                "message_id": int,   # assistant 消息 id
                "summary": str,      # LLM 摘要（失败时为 ""）
                "data": {            # MCP 原始查询结果
                    "fields": [...],
                    "rows": [...]
                },
                "llm_error": str | None  # LLM 摘要失败原因（降级时非 None）
            }

        Raises:
            QueryServiceError: Q_JWT_001 / Q_PERM_002 / Q_TIMEOUT_003 / Q_MCP_004 / Q_INPUT_006
        """
        # TODO (T-04): 路由层实现时必须传入解析后的 VizQL JSON，当前 vizql_query=None 将导致 MCP 返回空结果
        # ── Step 1: 获取 / 创建 Session ──────────────────────────────────
        if user_id is None:
            raise QueryServiceError(
                code="Q_INPUT_006",
                message="user_id 为必填参数（问数请求必须关联登录用户）",
            )

        sess = self._msg_db.get_or_create_session(
            db=self._db, user_id=user_id, session_id=session_id
        )

        # ── Step 2: 持久化用户消息 ──────────────────────────────────────
        self._msg_db.append_message(
            db=self._db,
            session_id=sess.id,
            role="user",
            content=message,
            connection_id=connection_id,
            datasource_luid=datasource_luid,
        )

        # ── Step 3: 签发 JWT ──────────────────────────────────────────
        jwt_token = self._issue_jwt(username=username, connection_id=connection_id)

        # ── Step 4: MCP 查询（以用户身份）────────────────────────────
        if vizql_query is None:
            # fallback：使用空 query 对象；实际项目中应由 NLQ 层传入
            vizql_query = {}

        client = TableauMCPClient(connection_id=connection_id, username=username)
        try:
            mcp_data = client.query_datasource(
                datasource_luid=datasource_luid,
                query=vizql_query,
                limit=limit,
                timeout=timeout,
                connection_id=connection_id,
                jwt_token=jwt_token,
            )
        except TableauMCPError as e:
            # 写入错误告警并将用户消息标记为失败（在 assistant 消息中记录错误）
            svc_err = self._classify_and_record_mcp_error(
                exc=e,
                username=username,
                user_id=user_id,
                connection_id=connection_id,
            )
            # 持久化错误 assistant 消息（content 保存错误描述）
            err_msg = self._msg_db.append_message(
                db=self._db,
                session_id=sess.id,
                role="assistant",
                content=f"查询失败：[{svc_err.code}] {svc_err.message}",
                connection_id=connection_id,
                datasource_luid=datasource_luid,
                query_context={"error_code": svc_err.code, "mcp_code": e.code},
            )
            self._db.commit()
            raise svc_err from e

        # ── Step 5: LLM 摘要（失败降级）────────────────────────────────
        summary = ""
        llm_error: Optional[str] = None
        try:
            data_preview = _build_data_preview(mcp_data)
            prompt = _ANALYSIS_PROMPT_TEMPLATE.format(
                question=message,
                data_preview=data_preview,
            )
            # T1.3: 通过 wrapper.invoke("llm_complete") 包装（fallback 保持兼容）
            wrapper = get_wrapper()
            principal = get_principal() or {"id": 0, "role": "analyst"}
            if wrapper is not None:
                cap_result = await wrapper.invoke(
                    principal=principal,
                    capability_name="llm_complete",
                    params={
                        "prompt": prompt,
                        "system": _ANALYSIS_SYSTEM,
                        "timeout": 20,
                        "purpose": "default",
                    },
                )
                llm_result = cap_result.data if hasattr(cap_result, "data") else cap_result
            else:
                llm_result = await llm_service.complete(
                    prompt=prompt,
                    system=_ANALYSIS_SYSTEM,
                    timeout=20,
                    purpose="default",
                )
            if "error" in llm_result:
                llm_error = llm_result["error"]
                logger.warning("LLM 摘要生成失败（降级）: %s", llm_error)
            else:
                summary = llm_result.get("content", "")
        except Exception as e_llm:
            llm_error = str(e_llm)
            logger.warning("LLM 摘要生成异常（降级）: %s", e_llm)

        # ── Step 6: 持久化 assistant 消息 ────────────────────────────────
        assistant_content = summary if summary else "（数据已返回，摘要生成失败）"
        asst_msg = self._msg_db.append_message(
            db=self._db,
            session_id=sess.id,
            role="assistant",
            content=assistant_content,
            connection_id=connection_id,
            datasource_luid=datasource_luid,
            data_table=mcp_data,
            query_context={
                "vizql_query": vizql_query,
                "llm_error": llm_error,
            },
        )
        self._db.commit()

        # ── Step 7: 返回 ─────────────────────────────────────────────────
        return {
            "session_id": str(sess.id),
            "message_id": asst_msg.id,
            "summary": summary,
            "data": mcp_data,
            "llm_error": llm_error,
        }

    async def ask_stream(
        self,
        username: str,
        connection_id: int,
        datasource_luid: str,
        message: str,
        session_id: Optional[str] = None,
        user_id: Optional[int] = None,
        vizql_query: Optional[Dict[str, Any]] = None,
        limit: int = 1000,
        timeout: int = 30,
    ) -> AsyncGenerator[str, None]:
        """
        核心问数链路 — SSE 流式版本（Spec 14 §5.2）。

        与 ask() 相同的业务链路：
            1. 获取/创建 QuerySession
            2. 持久化用户消息（role=user）
            3. 签发 Tableau Connected Apps JWT
            4. 调用 MCP query_datasource（以用户身份）
            5. LLM 摘要以流式方式 yield（见下方注释）
            6. 持久化 assistant 消息（在 done event 发送前完成）
            7. yield done event

        Yield 格式（遵循 Spec §5.2）：
            data: {"type": "token", "content": "<chunk>"}\n\n
            data: {"type": "done", "session_id": "...", "answer": "...", "data_table": [...]}\n\n

        异常时 yield：
            data: {"type": "error", "code": "Q_XXX_NNN", "message": "..."}\n\n

        NOTE（模拟流式）：
            当前 llm_service 不支持原生流式调用（仅有 complete() 同步聚合接口）。
            此处采用"先完整调用 LLM，再将结果逐字符 yield"的模拟流式实现，
            每个字符间隔 20ms asyncio.sleep，保持 SSE 接口格式正确。
            正式版本接入 llm_service.stream_complete() 后，删除此注释及模拟逻辑，
            改为直接 yield LLM 流式 chunk。
        """

        def _sse(payload: dict) -> str:
            """格式化为 SSE data 行（含双换行）。"""
            return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"

        # ── Step 1: 参数校验 & 获取 / 创建 Session ───────────────────────
        if user_id is None:
            yield _sse({
                "type": "error",
                "code": "Q_INPUT_006",
                "message": "user_id 为必填参数（问数请求必须关联登录用户）",
            })
            return

        try:
            sess = self._msg_db.get_or_create_session(
                db=self._db, user_id=user_id, session_id=session_id
            )
        except QueryServiceError as exc:
            yield _sse({"type": "error", "code": exc.code, "message": exc.message})
            return

        # ── Step 2: 持久化用户消息 ──────────────────────────────────────
        try:
            self._msg_db.append_message(
                db=self._db,
                session_id=sess.id,
                role="user",
                content=message,
                connection_id=connection_id,
                datasource_luid=datasource_luid,
            )
        except Exception as exc:
            logger.error("持久化用户消息失败: %s", exc)
            yield _sse({"type": "error", "code": "Q_MCP_004", "message": "消息持久化失败"})
            return

        # ── Step 3: 签发 JWT ──────────────────────────────────────────
        try:
            jwt_token = self._issue_jwt(username=username, connection_id=connection_id)
        except QueryServiceError as exc:
            yield _sse({"type": "error", "code": exc.code, "message": exc.message})
            return

        # ── Step 4: MCP 查询（以用户身份）────────────────────────────
        _vizql = vizql_query if vizql_query is not None else {}
        client = TableauMCPClient(connection_id=connection_id, username=username)
        try:
            mcp_data = client.query_datasource(
                datasource_luid=datasource_luid,
                query=_vizql,
                limit=limit,
                timeout=timeout,
                connection_id=connection_id,
                jwt_token=jwt_token,
            )
        except TableauMCPError as e:
            svc_err = self._classify_and_record_mcp_error(
                exc=e,
                username=username,
                user_id=user_id,
                connection_id=connection_id,
            )
            # 持久化错误 assistant 消息
            try:
                self._msg_db.append_message(
                    db=self._db,
                    session_id=sess.id,
                    role="assistant",
                    content=f"查询失败：[{svc_err.code}] {svc_err.message}",
                    connection_id=connection_id,
                    datasource_luid=datasource_luid,
                    query_context={"error_code": svc_err.code, "mcp_code": e.code},
                )
                self._db.commit()
            except Exception as e_persist:
                logger.warning("错误消息持久化失败（忽略）: %s", e_persist)
            yield _sse({"type": "error", "code": svc_err.code, "message": svc_err.message})
            return

        # ── Step 5: LLM 摘要（模拟流式 yield）───────────────────────────
        # NOTE: 模拟流式实现——先完整调用 LLM，再逐字符 yield token。
        #       正式版本应替换为 llm_service.stream_complete() 原生流式调用。
        summary = ""
        llm_error: Optional[str] = None
        try:
            data_preview = _build_data_preview(mcp_data)
            prompt = _ANALYSIS_PROMPT_TEMPLATE.format(
                question=message,
                data_preview=data_preview,
            )
            # T1.3: 通过 wrapper.invoke("llm_complete") 包装（fallback 保持兼容）
            wrapper = get_wrapper()
            principal = get_principal() or {"id": 0, "role": "analyst"}
            if wrapper is not None:
                cap_result = await wrapper.invoke(
                    principal=principal,
                    capability_name="llm_complete",
                    params={
                        "prompt": prompt,
                        "system": _ANALYSIS_SYSTEM,
                        "timeout": 20,
                        "purpose": "default",
                    },
                )
                llm_result = cap_result.data if hasattr(cap_result, "data") else cap_result
            else:
                llm_result = await llm_service.complete(
                    prompt=prompt,
                    system=_ANALYSIS_SYSTEM,
                    timeout=20,
                    purpose="default",
                )
            if "error" in llm_result:
                llm_error = llm_result["error"]
                logger.warning("LLM 摘要生成失败（降级）: %s", llm_error)
            else:
                summary = llm_result.get("content", "")
        except Exception as e_llm:
            llm_error = str(e_llm)
            logger.warning("LLM 摘要生成异常（降级）: %s", e_llm)

        # NOTE: 模拟流式——逐字符 yield，每字符间隔 20ms。
        #       正式版本接入 llm_service.stream_complete() 后删除此段，改为直接 yield stream chunk。
        if summary:
            for char in summary:
                yield _sse({"type": "token", "content": char})
                await asyncio.sleep(0.02)
        else:
            # 降级：无摘要时发送一个空 token，保持流格式完整
            fallback_msg = "（数据已返回，摘要生成失败）"
            for char in fallback_msg:
                yield _sse({"type": "token", "content": char})
                await asyncio.sleep(0.02)

        # ── Step 6: 持久化 assistant 消息（done 前完成）──────────────────
        assistant_content = summary if summary else "（数据已返回，摘要生成失败）"
        try:
            self._msg_db.append_message(
                db=self._db,
                session_id=sess.id,
                role="assistant",
                content=assistant_content,
                connection_id=connection_id,
                datasource_luid=datasource_luid,
                data_table=mcp_data,
                query_context={
                    "vizql_query": _vizql,
                    "llm_error": llm_error,
                },
            )
            self._db.commit()
        except Exception as e_persist:
            logger.error("assistant 消息持久化失败: %s", e_persist)
            # 持久化失败时仍 yield done，不阻断用户侧响应

        # ── Step 7: yield done event ─────────────────────────────────────
        # data_table 格式：将 mcp_data rows 转换为前端期望的列表格式
        data_table = mcp_data.get("rows", []) if isinstance(mcp_data, dict) else []
        yield _sse({
            "type": "done",
            "session_id": str(sess.id),
            "answer": assistant_content,
            "data_table": data_table,
        })

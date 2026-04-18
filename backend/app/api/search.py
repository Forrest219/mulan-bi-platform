"""NL-to-Query 搜索 API（PRD §14 §6）"""
import logging
from typing import Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.dependencies import get_current_user
from services.capability.audit import InvocationRecord, new_trace_id, write_audit
from services.llm.models import log_nlq_query
from services.common.redis_cache import check_rate_limit
from services.tableau.models import TableauAsset, TableauDatabase
from services.knowledge_base.glossary_service import glossary_service
from services.semantic_maintenance.context_assembler import (
    ContextAssembler,
    sanitize_fields_for_llm,
)
from services.llm.semantic_retriever import recall_fields
from services.llm.nlq_service import (
    NLQError,
    one_pass_llm,
    route_datasource,
    resolve_fields,
    format_response,
    classify_intent,
    classify_meta_intent,
    execute_query,
    is_datasource_sensitivity_blocked,
    MAX_QUERY_LENGTH,
)
from services.tableau.mcp_client import get_tableau_mcp_client

logger = logging.getLogger(__name__)
router = APIRouter()


class QueryRequest(BaseModel):
    """POST /api/search/query 请求体（PRD §6.2）"""

    question: str
    datasource_luid: Optional[str] = None
    connection_id: Optional[int] = None
    conversation_id: Optional[str] = None
    options: Optional[dict] = None
    use_conversation_context: bool = False  # P2：追问时携带上轮上下文


def _require_role(user, min_role: str) -> None:
    """权限拦截：analyst+"""
    role_rank = {"user": 0, "analyst": 1, "data_admin": 2, "admin": 3}
    user_rank = role_rank.get(user.get("role", "user"), 0)
    min_rank = role_rank.get(min_role, 0)
    if user_rank < min_rank:
        raise HTTPException(status_code=403, detail="权限不足")


def _build_fields_with_types(fields: list) -> str:
    """
    将已 sanitized 的字段列表格式化为 LLM 上下文字符串（Spec 14 v1.1 §5.1 Token 预算管理）。

    注意：本函数假设输入 fields 已经过 sanitize_fields_for_llm 过滤。
    本函数只负责 P0-P5 优先级截断 + Token 预算（ContextAssembler）。
    """
    if not fields:
        return "无可用字段"

    # P0-P5 优先级截断 + Token 预算（ContextAssembler 内部处理）
    assembler = ContextAssembler()
    # build_field_context 默认 max_tokens=MAX_CONTEXT_TOKENS-500=2500
    return assembler.build_field_context(fields)


def _nlq_error_response(code: str, message: str, details: dict = None):
    """NLQ 错误响应"""
    status_map = {"NLQ_003", "NLQ_006", "NLQ_008", "NLQ_009"}
    status_code = 502 if code in status_map else 400
    return HTTPException(
        status_code=status_code,
        detail={
            "code": code,
            "message": message,
            "details": details or {},
        },
    )


async def _mcp_list_datasources(
    mcp_base_url: str,
    tableau_server: str,
    site_name: str,
    pat_name: str,
    pat_value: str,
    timeout: float = 30.0,
) -> list:
    """
    直接通过 MCP JSON-RPC 调用 list-datasources 工具（不依赖 TableauConnection 表）。

    用于：当 TableauConnection 为空但 MCP server config 有 credentials 时。
    """
    import httpx
    import json as _json

    protocol_ver = "2025-06-18"
    session_id = "nlq-fallback-session"

    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json, text/event-stream",
        "MCP-Protocol-Version": protocol_ver,
        "MCP-Session-ID": session_id,
    }

    async with httpx.AsyncClient(timeout=timeout) as client:
        # initialize
        await client.post(
            mcp_base_url,
            json={
                "jsonrpc": "2.0", "id": 1, "method": "initialize",
                "params": {
                    "protocolVersion": protocol_ver,
                    "clientInfo": {"name": "nlq-fallback", "version": "1.0"},
                    "serverInfo": {"name": "tableau-mcp", "version": "1.0"},
                }
            },
            headers=headers,
        )

        # notifications/initialized
        await client.post(
            mcp_base_url,
            json={"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}},
            headers=headers,
        )

        # tools/call: list-datasources
        list_resp = await client.post(
            mcp_base_url,
            json={
                "jsonrpc": "2.0", "id": 2, "method": "tools/call",
                "params": {"name": "list-datasources", "arguments": {"limit": 10}}
            },
            headers=headers,
        )
        list_data = list_resp.json()
        result = list_data.get("result", {})
        content = result.get("content", [])
        text = "".join(c.get("text", "") for c in content if c.get("type") == "text")
        if text:
            list_result = _json.loads(text)
            return list_result.get("datasources", [])
        return []


async def _mcp_get_datasource_metadata(
    mcp_base_url: str,
    datasource_luid: str,
    timeout: float = 30.0,
) -> dict:
    """
    直接通过 MCP JSON-RPC 调用 get-datasource-metadata 工具（不依赖 TableauConnection 表）。
    """
    import httpx
    import json as _json

    protocol_ver = "2025-06-18"
    session_id = "nlq-fallback-session"

    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json, text/event-stream",
        "MCP-Protocol-Version": protocol_ver,
        "MCP-Session-ID": session_id,
    }

    async with httpx.AsyncClient(timeout=timeout) as client:
        # initialize
        await client.post(
            mcp_base_url,
            json={
                "jsonrpc": "2.0", "id": 1, "method": "initialize",
                "params": {
                    "protocolVersion": protocol_ver,
                    "clientInfo": {"name": "nlq-fallback", "version": "1.0"},
                    "serverInfo": {"name": "tableau-mcp", "version": "1.0"},
                }
            },
            headers=headers,
        )

        # notifications/initialized
        await client.post(
            mcp_base_url,
            json={"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}},
            headers=headers,
        )

        # tools/call: get-datasource-metadata
        meta_resp = await client.post(
            mcp_base_url,
            json={
                "jsonrpc": "2.0", "id": 2, "method": "tools/call",
                "params": {"name": "get-datasource-metadata", "arguments": {"datasourceLuid": datasource_luid}}
            },
            headers=headers,
        )
        meta_data = meta_resp.json()
        result = meta_data.get("result", {})
        content = result.get("content", [])
        text = "".join(c.get("text", "") for c in content if c.get("type") == "text")
        if text:
            return _json.loads(text)
        return {}


def _get_asset_by_luid(datasource_luid: str):
    """通过 datasource_luid 查找 TableauAsset"""
    db = TableauDatabase()
    session = db.session
    asset = session.query(TableauAsset).filter(
        TableauAsset.datasource_luid == datasource_luid,
        not TableauAsset.is_deleted,
    ).first()
    session.close()
    return asset


# === META 查询 Handler ===

async def handle_meta_query(meta_intent: str, connection_id: int, db: Session) -> dict:
    """
    处理 3 种 META 查询意图，直接查本地 DB 返回结构化文本。
    不走 VizQL One-Pass LLM 流水线。

    Args:
        meta_intent: classify_meta_intent() 返回的意图 key
        connection_id: 用户在 ScopePicker 选中的连接 ID（Q1 业务口径：不 fallback）
        db: SQLAlchemy session（由 Depends(get_db) 注入，与主流程共用）

    Returns:
        符合 PRD §6.2 响应格式的 dict（response_type + content/value 等字段）
    """
    from services.tableau.models import TableauConnection
    from sqlalchemy import or_

    if meta_intent == "meta_datasource_list":
        return await _handle_meta_datasource_list(connection_id, db)
    elif meta_intent == "meta_asset_count":
        return await _handle_meta_asset_count(connection_id, db)
    elif meta_intent == "meta_semantic_quality":
        return await _handle_meta_semantic_quality(connection_id, db)
    else:
        return {
            "response_type": "text",
            "content": f"未知的 META 查询类型：{meta_intent}",
        }


async def _handle_meta_datasource_list(connection_id: int, db: Session) -> dict:
    """
    META handler 1：列出当前连接下的数据源（Q1 业务口径：按 Site 分组展示）。

    - 查询范围 = connection_id 指定的连接，不 fallback
    - 按 Site（connection name）分组展示
    """
    from services.tableau.models import TableauConnection

    assets = db.query(TableauAsset).filter(
        TableauAsset.connection_id == connection_id,
        TableauAsset.asset_type == "datasource",
        TableauAsset.is_deleted == False,
    ).all()

    # 查 connection 名称，用作分组标签
    connection = db.query(TableauConnection).filter(
        TableauConnection.id == connection_id
    ).first()
    site_label = f"{connection.name}（{connection.site}）" if connection else f"连接 {connection_id}"

    if not assets:
        content = f"**{site_label}** 下暂无数据源，请先完成资产同步。"
    else:
        lines = [f"**{site_label}** 共有 {len(assets)} 个数据源："]
        for a in sorted(assets, key=lambda x: x.name):
            lines.append(f"- {a.name}")
        content = "\n".join(lines)

    return {
        "response_type": "text",
        "content": content,
        "intent": "meta_datasource_list",
        "meta": True,
    }


async def _handle_meta_asset_count(connection_id: int, db: Session) -> dict:
    """
    META handler 2：统计当前连接下的看板数量（Q2 业务口径：dashboard + workbook 都计入）。
    """
    dashboard_count = db.query(TableauAsset).filter(
        TableauAsset.connection_id == connection_id,
        TableauAsset.asset_type == "dashboard",
        TableauAsset.is_deleted == False,
    ).count()

    workbook_count = db.query(TableauAsset).filter(
        TableauAsset.connection_id == connection_id,
        TableauAsset.asset_type == "workbook",
        TableauAsset.is_deleted == False,
    ).count()

    total = dashboard_count + workbook_count

    content = (
        f"当前连接共有 **{total}** 个看板"
        f"（其中 Dashboard {dashboard_count} 个，Workbook {workbook_count} 个）。"
    )

    return {
        "response_type": "number",
        "value": total,
        "label": "看板总数",
        "unit": "个",
        "formatted": str(total),
        "content": content,
        "intent": "meta_asset_count",
        "meta": True,
    }


async def _handle_meta_semantic_quality(connection_id: int, db: Session) -> dict:
    """
    META handler 3：分析当前连接的语义配置完整性（Q3 业务口径）。

    检查 tableau_field_semantics 表中该 connection 下的不完善项：
    - semantic_definition 为空
    - status 为 draft 或 ai_generated（未经人工审核）
    """
    from services.semantic_maintenance.models import TableauFieldSemantics
    from sqlalchemy import or_

    incomplete = db.query(TableauFieldSemantics).filter(
        TableauFieldSemantics.connection_id == connection_id,
        or_(
            TableauFieldSemantics.semantic_definition.is_(None),
            TableauFieldSemantics.semantic_definition == "",
            TableauFieldSemantics.status.in_(["draft", "ai_generated"]),
        ),
    ).all()

    if not incomplete:
        content = "当前数据源的语义配置较为完善，未发现明显缺失项。"
    else:
        lines = [f"发现 **{len(incomplete)}** 处语义配置不完善："]
        for f in incomplete[:10]:
            reason = []
            if not f.semantic_definition:
                reason.append("缺少语义定义")
            if f.status in ("draft", "ai_generated"):
                reason.append(f"状态为 {f.status}（未审核）")
            # 优先展示中文语义名，其次 tableau_field_id
            display_name = f.semantic_name_zh or f.semantic_name or f.tableau_field_id
            lines.append(f"- `{display_name}`：{', '.join(reason)}")
        if len(incomplete) > 10:
            lines.append(f"... 等共 {len(incomplete)} 处")
        content = "\n".join(lines)

    return {
        "response_type": "text",
        "content": content,
        "intent": "meta_semantic_quality",
        "meta": True,
    }


# === API 端点 ===
@router.post("/query")
async def query(
    body: QueryRequest,
    request: Request,
    db: Session = Depends(get_db),
):
    """自然语言查询（PRD §6.2）POST /api/search/query — analyst+
    将用户自然语言问题转换为数据查询并返回结果。
    """
    user = get_current_user(request=request, db=db)
    _require_role(user, "analyst")

    question = body.question
    datasource_luid = body.datasource_luid
    connection_id = body.connection_id
    options = body.options or {}

    # P2-1：追问上下文继承 — 从上轮 query_context 中补填 connection_id / datasource_luid
    if body.use_conversation_context and body.conversation_id and not datasource_luid and not connection_id:
        try:
            import json as _json
            from sqlalchemy import text as _text
            _msg = db.execute(_text("""
                SELECT query_context FROM conversation_messages
                WHERE conversation_id=:cid AND role='assistant' AND query_context IS NOT NULL
                ORDER BY created_at DESC LIMIT 1
            """), {"cid": body.conversation_id}).fetchone()
            if _msg:
                _ctx = _msg._mapping["query_context"]
                if isinstance(_ctx, str):
                    _ctx = _json.loads(_ctx)
                if isinstance(_ctx, dict):
                    if not datasource_luid and _ctx.get("datasource_luid"):
                        datasource_luid = _ctx["datasource_luid"]
                    if not connection_id and _ctx.get("connection_id"):
                        connection_id = int(_ctx["connection_id"])
        except Exception as _ctx_err:
            logger.warning("读取追问上下文失败（不影响主流程）: %s", _ctx_err)

    # 速率限制检查
    user_id = user.get("id")
    if user_id and not check_rate_limit(user_id):
        raise _nlq_error_response("NLQ_010", "查询过于频繁，请稍后再试")

    # 长度检查
    if len(question) > MAX_QUERY_LENGTH:
        raise _nlq_error_response(
            "NLQ_001",
            f"问题长度不能超过 {MAX_QUERY_LENGTH} 字符",
        )

    # 初始化审计记录
    audit_record = InvocationRecord(
        trace_id=new_trace_id(),
        principal_id=user_id,
        principal_role=user.get("role", "user"),
        capability="query_metric",
        params_jsonb={"question_length": len(question)},
        status="started",
    )

    try:
        # ── META 查询优先检测（Q1-Q3 业务口径，不走 VizQL 流水线）────────
        # classify_meta_intent 基于规则关键词，无 LLM 调用，优先于 VizQL 意图分类
        meta_intent = classify_meta_intent(question)
        if meta_intent:
            if connection_id is None:
                audit_record.status = "ok"
                return {
                    "trace_id": audit_record.trace_id,
                    "response_type": "text",
                    "content": "请先在左上角选择 Tableau 连接，再提问。",
                    "intent": meta_intent,
                    "meta": True,
                }
            audit_record.params_jsonb["intent"] = meta_intent
            result = await handle_meta_query(meta_intent, connection_id, db)
            audit_record.status = "ok"
            return {
                "trace_id": audit_record.trace_id,
                **result,
            }

        # ── 意图分类（阶段0）─────────────────────────────────────
        intent = classify_intent(question)
        audit_record.params_jsonb["intent"] = intent.intent_type if intent else None

        # ── 数据源路由（PRD §7.1）─────────────────────────────
        chosen_ds = None
        if datasource_luid:
            asset = _get_asset_by_luid(datasource_luid)
            if not asset:
                raise _nlq_error_response("NLQ_009", "数据源不存在或已删除")
            if is_datasource_sensitivity_blocked(datasource_luid):
                raise _nlq_error_response("NLQ_011", "该数据源为高敏级别")
            chosen_ds = {
                "datasource_luid": datasource_luid,
                "datasource_name": asset.name,
                "connection_id": asset.connection_id,
            }
        elif connection_id:
            chosen_ds = route_datasource(question, connection_id=connection_id)
            if not chosen_ds:
                raise _nlq_error_response("NLQ_005", "未找到匹配的数据源，请指定 datasource_luid")
        else:
            # 尝试多数据源路由
            chosen_ds = route_datasource(question)
            if not chosen_ds:
                # Fallback：尝试通过 MCP 动态发现数据源
                logger.info("路由未命中，尝试 MCP 动态发现数据源 trace=%s", audit_record.trace_id)
                try:
                    from services.tableau.models import TableauConnection as _TableauConnection
                    from services.mcp.models import McpServer

                    db_temp = TableauDatabase()
                    session_temp = db_temp.session
                    active_conn = session_temp.query(_TableauConnection).filter(
                        _TableauConnection.is_active == True,
                    ).order_by(_TableauConnection.id.asc()).first()

                    if not active_conn:
                        # TableauConnection 为空，从活跃 MCP server config 获取 credentials
                        mcp_server_record = session_temp.query(McpServer).filter(
                            McpServer.is_active == True,
                            McpServer.type == "tableau",
                        ).order_by(McpServer.id.asc()).first()

                        if mcp_server_record and mcp_server_record.credentials:
                            creds = mcp_server_record.credentials
                            mcp_base_url = mcp_server_record.server_url
                            tableau_server = creds.get("tableau_server", "")
                            site_name = creds.get("site_name", "")
                            pat_name = creds.get("pat_name", "")
                            pat_value = creds.get("pat_value", "")

                            if tableau_server and site_name and pat_name and pat_value:
                                # 用 MCP config credentials 直接调用 MCP JSON-RPC
                                ds_list = await _mcp_list_datasources(
                                    mcp_base_url, tableau_server, site_name, pat_name, pat_value
                                )
                                if ds_list and len(ds_list) > 0:
                                    first_ds = ds_list[0]
                                    chosen_ds = {
                                        "datasource_luid": first_ds.get("luid") or first_ds.get("id", ""),
                                        "datasource_name": first_ds.get("name", "MCP 数据源"),
                                        "connection_id": None,
                                        "mcp_discovery": True,
                                        "mcp_base_url": mcp_base_url,
                                        "mcp_site": site_name,
                                        "mcp_token_name": pat_name,
                                        "mcp_token_value": pat_value,
                                    }
                                    logger.info("MCP 动态发现数据源成功: luid=%s, name=%s trace=%s",
                                                chosen_ds["datasource_luid"], chosen_ds["datasource_name"], audit_record.trace_id)

                    elif active_conn:
                        mcp_client = get_tableau_mcp_client(active_conn.id)
                        mcp_result = mcp_client.list_datasources(limit=10, timeout=15)
                        ds_list = mcp_result.get("datasources", [])
                        if ds_list and len(ds_list) > 0:
                            first_ds = ds_list[0]
                            chosen_ds = {
                                "datasource_luid": first_ds.get("luid") or first_ds.get("datasource_luid") or first_ds.get("id"),
                                "datasource_name": first_ds.get("name") or first_ds.get("datasourceName") or "MCP 数据源",
                                "connection_id": active_conn.id,
                                "mcp_discovery": True,
                            }
                            logger.info("MCP 动态发现数据源成功: luid=%s, name=%s trace=%s",
                                        chosen_ds["datasource_luid"], chosen_ds["datasource_name"], audit_record.trace_id)

                    session_temp.close()
                except Exception as mcp_err:
                    logger.warning("MCP 动态发现失败: %s trace=%s", mcp_err, audit_record.trace_id)

            if not chosen_ds:
                raise _nlq_error_response("NLQ_005", "请指定数据源（datasource_luid 或 connection_id）")

        ds_luid = chosen_ds["datasource_luid"]
        ds_name = chosen_ds["datasource_name"]
        is_mcp_discovery = chosen_ds.get("mcp_discovery", False)

        # 1c. 获取数据源字段
        db = TableauDatabase()
        session = db.session
        asset = session.query(TableauAsset).filter(
            TableauAsset.datasource_luid == ds_luid,
            not TableauAsset.is_deleted,
        ).first()
        session.close()

        # MCP 动态发现的数据源（不在本地 DB）→ 通过 MCP 获取字段元数据
        if not asset and is_mcp_discovery:
            logger.info("MCP 动态数据源，获取字段元数据 trace=%s", audit_record.trace_id)
            try:
                # connection_id 为 None 表示使用 MCP config credentials（绕过 TableauConnection）
                if chosen_ds.get("connection_id") is not None:
                    mcp_client = get_tableau_mcp_client(connection_id=chosen_ds["connection_id"])
                    metadata = mcp_client.get_datasource_metadata(ds_luid, timeout=30)
                else:
                    # 使用 MCP config credentials 直接调用 MCP JSON-RPC
                    metadata = await _mcp_get_datasource_metadata(
                        chosen_ds["mcp_base_url"], ds_luid, timeout=30
                    )
                # 解析 MCP 返回的字段（GraphQL Metadata API 格式）
                raw_fields = metadata.get("data", {}).get("publishedDatasources", [{}])
                if raw_fields and len(raw_fields) > 0:
                    mcp_fields = raw_fields[0].get("fields", [])
                    fields = []
                    for f in mcp_fields:
                        fname = f.get("name", "") or f.get("Name", "")
                        ftype = f.get("dataType", "") or f.get("dataType", "")
                        frole = f.get("role", "dimension")
                        if fname:
                            fields.append({
                                "field_caption": fname,
                                "field_name": fname,
                                "role": frole,
                                "data_type": ftype,
                                "formula": None,
                                "sensitivity_level": "low",
                            })
                    sanitized_fields = sanitize_fields_for_llm(fields)
                    fields_with_types = _build_fields_with_types(sanitized_fields)
                    asset_datasource_id = None
                    logger.info("MCP 字段元数据获取成功: %d 个字段 trace=%s", len(fields), audit_record.trace_id)
                else:
                    sanitized_fields = []
                    fields_with_types = "无可用字段"
                    asset_datasource_id = None
                    logger.warning("MCP 字段元数据为空 trace=%s", audit_record.trace_id)
            except Exception as meta_err:
                logger.error("MCP 获取字段元数据失败: %s trace=%s", meta_err, audit_record.trace_id)
                raise _nlq_error_response("NLQ_009", "无法获取数据源字段信息，请联系管理员")

        elif not asset:
            raise _nlq_error_response("NLQ_009", "数据源不存在或已删除")
        else:
            field_records = db.get_datasource_fields(asset.id)

            # 提取 field_registry_id（= TableauDatasourceField.id）用于批量查敏感度
            field_ids = [f.id for f in field_records]

            # 批量查询字段敏感度（JOIN TableauFieldSemantics）
            # 注意：使用新的 session 查询，因为前面的 session 已关闭
            sensitivity_map: Dict[int, str] = {}
            if field_ids:
                from services.semantic_maintenance.models import TableauFieldSemantics

                db2 = TableauDatabase()
                session2 = db2.session
                try:
                    semantics_records = session2.query(
                        TableauFieldSemantics.field_registry_id,
                        TableauFieldSemantics.sensitivity_level,
                    ).filter(
                        TableauFieldSemantics.field_registry_id.in_(field_ids),
                        TableauFieldSemantics.connection_id == asset.connection_id,
                    ).all()
                    sensitivity_map = {
                        row.field_registry_id: (row.sensitivity_level or "low").lower()
                        for row in semantics_records
                    }
                finally:
                    session2.close()

            fields = [
                {
                    "field_caption": f.field_caption,
                    "field_name": f.field_name,
                    "role": f.role,
                    "data_type": f.data_type,
                    "formula": f.formula,
                    "sensitivity_level": sensitivity_map.get(f.id, "low"),
                }
                for f in field_records
            ]

            # 敏感度过滤（高敏字段不暴露给 LLM）
            sanitized_fields = sanitize_fields_for_llm(fields)
            fields_with_types = _build_fields_with_types(sanitized_fields)
            asset_datasource_id = asset.datasource_id

        # ── P3 增强：recall_fields 语义重排序 ──────────────────
        recalled = await recall_fields(question, datasource_ids=[asset_datasource_id] if asset_datasource_id else None)
        if recalled:
            recalled_names = {r["semantic_name_zh"] or r["semantic_name"] for r in recalled}
            # 将语义匹配度高的字段排在前面
            def boost_key(f):
                name = f.get("field_caption", "") or f.get("field_name", "")
                return (0 if name in recalled_names else 1, 0)
            sanitized_fields.sort(key=boost_key)

        # ── 术语表增强（PRD §8.2）──────────────────────────────
        glossary_terms = glossary_service.get_matching_terms(question)
        term_mappings = (
            "\n".join(f"{t['source_term']} -> {t['mapped_term']}" for t in glossary_terms)
            if glossary_terms else "无"
        )

        # ── 意图分类 + VizQL 生成（One-Pass LLM）───────────────
        llm_result = await one_pass_llm(
            question=question,
            datasource_luid=ds_luid,
            datasource_name=ds_name,
            fields_with_types=fields_with_types,
            term_mappings=term_mappings,
            intent_hint=intent.intent_type if intent else None,
        )
        audit_record.llm_tokens_in = llm_result.get("tokens_in")
        audit_record.llm_tokens_out = llm_result.get("tokens_out")

        vizql_json = llm_result["vizql_json"]
        response_type = llm_result.get("response_type", "auto")

        # ── 查询执行（MCP Stage 3）─────────────────────────────
        query_result = execute_query(
            datasource_luid=ds_luid,
            vizql_json=vizql_json,
            limit=options.get("limit", 1000),
            connection_id=chosen_ds.get("connection_id"),
        )

        mcp_fields = query_result.get("fields", [])
        mcp_rows = query_result.get("rows", [])

        if response_type == "number" or (response_type == "auto" and len(mcp_rows) == 1 and len(mcp_rows[0]) == 1):
            # PRD §6.2 number 格式：
            # {"value": 345678.0, "label": "销售额", "unit": "", "formatted": "345,678.00"}
            # MCP rows = [[345678.0]]，fieldCaption = "Sales"
            if mcp_rows and isinstance(mcp_rows[0], list) and len(mcp_rows[0]) == 1:
                value = mcp_rows[0][0]
            else:
                value = mcp_rows[0] if mcp_rows else None
            if isinstance(value, (int, float)):
                formatted = f"{value:,.2f}" if isinstance(value, float) else str(value)
            else:
                formatted = str(value) if value is not None else ""
            formatted = format_response(
                value,  # 传标量，不是 [[value]]
                intent=intent,
                response_type_hint="number",
            )
            api_data = formatted  # format_response 返回完整的 data 对象

        elif response_type == "text" or (response_type == "auto" and len(mcp_rows) == 0):
            api_data = format_response([], intent=intent, response_type_hint="text")

        else:
            # PRD §6.2 table 格式：
            # {"columns": [{Name, label, type}], "rows": [{col1: v1, col2: v2}], ...}
            # MCP rows = [[v1, v2], ...]（数组），需转为 [{col1: v1, col2: v2}, ...]
            api_data = format_response(mcp_rows, intent=intent, response_type_hint="table")

        audit_record.status = "ok"
        logger.info("NLQ 查询成功 trace=%s", audit_record.trace_id)

        # 写入对话历史（可选，失败不影响主流程）
        if body.conversation_id:
            try:
                import json as _json
                answer_text = _json.dumps(api_data, ensure_ascii=False, default=str)
                # P2-1：构建 query_context 供追问继承
                _query_context = {
                    "connection_id": chosen_ds.get("connection_id"),
                    "datasource_luid": ds_luid,
                    "datasource_name": ds_name,
                    "field_names": [
                        f.get("field_caption") or f.get("field_name")
                        for f in sanitized_fields[:20]
                    ],
                }
                _append_messages_to_conversation(
                    db=db,
                    conversation_id=body.conversation_id,
                    user_id=user_id,
                    question=question,
                    answer=answer_text,
                    query_context=_query_context,
                )
            except Exception as _e:
                logger.warning("写入对话消息失败（不影响主流程）: %s", _e)

        # 写查询日志
        log_nlq_query(
            db=db,
            user_id=user_id,
            question=question,
            datasource_luid=ds_luid,
            intent_type=intent.intent_type if intent else "unknown",
            confidence=llm_result.get("confidence", 0),
            response_type=response_type,
            latency_ms=audit_record.latency_ms,
        )

        return {
            "trace_id": audit_record.trace_id,
            **api_data,
            "response_type": response_type,
            "intent": intent.intent_type if intent else None,
            "confidence": llm_result.get("confidence"),
            "datasource": {"id": asset.id, "name": ds_name},
            "datasource_luid": ds_luid,
        }

    except NLQError as e:
        audit_record.status = "failed"
        audit_record.error_code = e.code
        audit_record.error_detail = e.message
        logger.warning("NLQ 错误 [%s] trace=%s: %s", e.code, audit_record.trace_id, e.message, exc_info=True)
        raise _nlq_error_response(e.code, e.message, e.details)

    except HTTPException:
        audit_record.status = "failed"
        raise

    except Exception as exc:
        audit_record.status = "failed"
        audit_record.error_code = "SYS_001"
        audit_record.error_detail = str(exc)
        logger.error("NLQ 意外错误 trace=%s: %s", audit_record.trace_id, exc, exc_info=True)
        raise HTTPException(
            status_code=500,
            detail={"code": "SYS_001", "message": "服务器内部错误", "details": {}},
        )

    finally:
        write_audit(audit_record)


def _append_messages_to_conversation(
    db,
    conversation_id: str,
    user_id: int,
    question: str,
    answer: str,
    query_context: dict = None,
) -> None:
    """将用户问题和助手回复写入对话历史（内部辅助函数）

    Args:
        query_context: P2-1 追问上下文，写入 assistant 消息的 query_context 列。
    """
    import json as _json
    import uuid
    from datetime import datetime, timezone
    from sqlalchemy import text

    now = datetime.now(timezone.utc)
    # 验证对话属于该用户，防止跨用户写入
    conv = db.execute(
        text("SELECT id FROM conversations WHERE id=:id AND user_id=:uid"),
        {"id": conversation_id, "uid": user_id},
    ).fetchone()
    if not conv:
        return
    db.execute(
        text("INSERT INTO conversation_messages (id, conversation_id, role, content, created_at) VALUES (:id, :cid, 'user', :content, :now)"),
        {"id": str(uuid.uuid4()), "cid": conversation_id, "content": question, "now": now},
    )
    db.execute(
        text(
            "INSERT INTO conversation_messages "
            "(id, conversation_id, role, content, query_context, created_at) "
            "VALUES (:id, :cid, 'assistant', :content, :qc, :now)"
        ),
        {
            "id": str(uuid.uuid4()),
            "cid": conversation_id,
            "content": answer,
            "qc": _json.dumps(query_context, ensure_ascii=False, default=str) if query_context else None,
            "now": now,
        },
    )
    db.execute(
        text("UPDATE conversations SET updated_at=:now WHERE id=:id"),
        {"now": now, "id": conversation_id},
    )
    db.commit()


@router.get("/suggestions")
async def suggestions(
    q: str,
    connection_id: int = None,
    db: Session = Depends(get_db),
):
    """查询建议（自动补全，PRD §6.3）GET /api/search/suggestions — analyst+"""
    user = get_current_user(request=None, db=db)
    _require_role(user, "analyst")

    return {
        "suggestions": [
            "各区域的销售额是多少",
            "最近6个月的月度趋势",
            "销售额前10的产品",
            "各产品类别的利润对比",
        ]
    }


@router.get("/history")
async def history(db: Session = Depends(get_db)):
    """查询历史（PRD §6.4）GET /api/search/history — analyst+"""
    user = get_current_user(request=None, db=db)
    _require_role(user, "analyst")

    return {"items": [], "total": 0, "page": 1, "page_size": 20}

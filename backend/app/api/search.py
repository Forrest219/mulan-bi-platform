"""NL-to-Query 搜索 API（PRD §14 §6）"""
import logging
from typing import Dict, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.dependencies import get_current_user
from services.capability.audit import InvocationRecord, new_trace_id, write_audit
from services.common.redis_cache import check_rate_limit
from services.knowledge_base.glossary_service import glossary_service
from services.llm.models import log_nlq_query
from services.llm.nlq_service import (
    MAX_QUERY_LENGTH,
    NLQError,
    classify_intent,
    execute_query,
    format_response,
    is_datasource_sensitivity_blocked,
    one_pass_llm,
    resolve_fields,
    route_datasource,
)
from services.llm.semantic_retriever import recall_fields
from services.semantic_maintenance.context_assembler import (
    ContextAssembler,
    sanitize_fields_for_llm,
)
from services.tableau.models import TableauAsset, TableauDatabase

logger = logging.getLogger(__name__)
router = APIRouter()


class QueryRequest(BaseModel):
    """POST /api/search/query 请求体（PRD §6.2）"""

    question: str
    datasource_luid: Optional[str] = None
    connection_id: Optional[int] = None
    options: Optional[dict] = None


def _require_role(user, min_role: str) -> None:
    """权限拦截：analyst+"""
    role_rank = {"user": 0, "analyst": 1, "data_admin": 2, "admin": 3}
    user_rank = role_rank.get(user.get("role", "user"), 0)
    min_rank = role_rank.get(min_role, 0)
    if user_rank < min_rank:
        raise HTTPException(status_code=403, detail="权限不足")


def _build_fields_with_types(fields: list) -> str:
    """将已 sanitized 的字段列表格式化为 LLM 上下文字符串（Spec 14 v1.1 §5.1 Token 预算管理）。

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


def _get_asset_by_luid(datasource_luid: str):
    """通过 datasource_luid 查找 TableauAsset"""
    db = TableauDatabase()
    session = db.session
    asset = session.query(TableauAsset).filter(
        TableauAsset.datasource_luid == datasource_luid,
        TableauAsset.is_deleted == False,
    ).first()
    session.close()
    return asset


# === API 端点 ===
@router.post("/query")
async def query(
    body: QueryRequest,
    db: Session = Depends(get_db),
):
    """自然语言查询（PRD §6.2）POST /api/search/query — analyst+
    将用户自然语言问题转换为数据查询并返回结果。
    """
    user = get_current_user(request=None, db=db)
    _require_role(user, "analyst")

    question = body.question
    datasource_luid = body.datasource_luid
    connection_id = body.connection_id
    options = body.options or {}
    response_type = options.get("response_type", "auto")
    limit = options.get("limit", 1000)
    timeout = options.get("timeout", 30)

    # === PRD §10.1 审计日志：提前创建，确保 HTTPException 路径也被记录 ===
    user_id = user.get("id") or 0
    audit_record = InvocationRecord(
        trace_id=new_trace_id(),
        principal_id=user.get("id") or 0,
        principal_role=user.get("role") or "user",
        capability="query_metric",
        params_jsonb={
            "question_length": len(question or ""),
            "datasource_luid": datasource_luid,
            "connection_id": connection_id,
        },
    )

    import time
    t0 = time.time()

    # === PRD §10.2 参数校验（顺序：限速 → 长度 → 敏感度）===
    # 1. 限速检查（单用户 20 次/分钟）
    if not check_rate_limit(user_id):
        raise _nlq_error_response("NLQ_010", "查询过于频繁，请稍后再试")

    # 2. 问题长度校验
    if not question or not question.strip():
        raise _nlq_error_response("NLQ_001", "查询问题不合法")
    if len(question) > MAX_QUERY_LENGTH:
        raise _nlq_error_response("NLQ_001", f"查询问题不能超过 {MAX_QUERY_LENGTH} 字符")

    # 3. PRD §10.3：用户显式指定 luid 时，校验敏感度
    if datasource_luid and is_datasource_sensitivity_blocked(datasource_luid):
        raise _nlq_error_response("NLQ_009", "该数据源不允许被查询（敏感度级别过高）")

    # === PRD §10.1 审计日志：外层 try/except/finally ===
    _log_intent: str = None
    _log_ds_luid: str = None
    _log_vizql: dict = None
    _log_response_type: str = None
    _log_exec_ms: int = 0
    _log_error: str = None
    _log_question: str = question
    _log_user_id: int = user_id

    try:
        # === 阶段1：意图分类 + 查询构建（One-Pass LLM）===
        # 1a. 规则快速路径
        rule_result = classify_intent(question)
        intent_hint = rule_result.type if rule_result else None

        # 1b. 确定数据源
        if datasource_luid:
            asset = _get_asset_by_luid(datasource_luid)
            if not asset:
                raise _nlq_error_response("NLQ_009", "指定的数据源不存在")
            chosen_ds = {
                "datasource_luid": asset.datasource_luid,
                "datasource_name": asset.name,
            }
        else:
            chosen_ds = route_datasource(question, connection_id)
            if not chosen_ds:
                raise _nlq_error_response("NLQ_005", "无法匹配到合适的数据源")

        ds_luid = chosen_ds["datasource_luid"]
        ds_name = chosen_ds["datasource_name"]

        # 1c. 获取数据源字段
        db = TableauDatabase()
        session = db.session
        asset = session.query(TableauAsset).filter(
            TableauAsset.datasource_luid == ds_luid,
            TableauAsset.is_deleted == False,
        ).first()
        session.close()

        if not asset:
            raise _nlq_error_response("NLQ_009", "数据源不存在或已删除")

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

        # Step 1: 敏感字段过滤（Spec 12 §9.2 + Spec 14 v1.1 §5.1 Token 熔断）
        # sanitize_fields_for_llm 会过滤 HIGH/CONFIDENTIAL 字段，
        # 截断 enum_values（≤20条，每条≤50字符），仅保留字段元数据
        sanitized_fields = sanitize_fields_for_llm(fields)

        # Step 1b: 基于 embedding 语义召回字段，提升相关字段优先级（P3 T6）
        try:
            recalled = await recall_fields(
                question,
                datasource_ids=[asset.connection_id],
                top_k=20,
            )
            if recalled:
                # Build similarity map keyed by field_caption
                recalled_map: dict[str, float] = {
                    r["semantic_name_zh"] or r["semantic_name"]: r["similarity"]
                    for r in recalled
                }
                # Re-sort sanitized_fields: recalled fields first (by similarity desc), then rest
                recalled_captions = set(recalled_map.keys())
                recalled_fields = [f for f in sanitized_fields if f.get("field_caption") in recalled_captions]
                other_fields = [f for f in sanitized_fields if f.get("field_caption") not in recalled_captions]
                recalled_fields.sort(key=lambda f: recalled_map.get(f.get("field_caption") or "", 0), reverse=True)
                sanitized_fields = recalled_fields + other_fields
        except Exception as e:
            logger.warning("语义召回失败，使用原始字段顺序: %s", e)

        # _build_fields_with_types 内部再次使用 ContextAssembler 做 P0-P5 截断（2500 tokens）
        fields_with_types = _build_fields_with_types(sanitized_fields)

        # 1d. 获取业务术语映射（知识库术语 + 同义词）
        term_mappings = ""
        try:
            matched_terms = glossary_service.match_terms(db, question, limit=10)
            if matched_terms:
                term_lines = [
                    f"{t.get('canonical_term', t.get('term', ''))}: {t.get('definition', '')}"
                    for t in matched_terms
                ]
                term_mappings = "\n".join(term_lines)
        except Exception as e:
            logger.warning("术语匹配失败: %s", e)

        # 1e. One-Pass LLM 调用（temperature=0.1 硬编码）
        try:
            one_pass_result = await one_pass_llm(
                question=question,
                datasource_luid=ds_luid,
                datasource_name=ds_name,
                fields_with_types=fields_with_types,
                term_mappings=term_mappings,
                intent_hint=intent_hint,
            )
        except NLQError as e:
            raise _nlq_error_response(e.code, e.message, e.details)

        intent = one_pass_result.get("intent", "aggregate")
        confidence = one_pass_result.get("confidence", 0.0)
        vizql_json = one_pass_result.get("vizql_json", {})

        # 置信度检查
        if confidence < 0.5:
            raise _nlq_error_response("NLQ_002", "无法理解查询意图")

        # === 阶段2：字段解析（使用已 sanitized 的字段列表，防止敏感字段泄露）===
        resolved_fields = await resolve_fields(question, sanitized_fields, intent)

        # === 阶段3：查询执行（PRD §5.5）===
        # 约束 A：环境变量从 TableauConnection 解密注入（mcp_client 内部处理）
        # 约束 B：MCP Session 长连接复用（TableauMCPClient 单例）
        # 约束 C：VizQL JSON fieldCaption 与 resolved_fields 对齐（已在 one_pass_llm 生成时保证）
        query_result = {"fields": [], "rows": []}
        try:
            query_result = execute_query(
                datasource_luid=ds_luid,
                vizql_json=vizql_json,
                limit=limit,
                timeout=timeout,
            )
        except NLQError:
            raise

        # === 阶段4：结果格式化（PRD §8）===
        # MCP 返回 {"fields": [...], "rows": [[...]]}，
        # 需按响应类型做数据转换后传入 format_response。
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
            # columns.name = fieldCaption（与 vizql_json.fieldCaption 对齐）
            columns = [
                {
                    "Name": f.get("fieldCaption", ""),
                    "label": f.get("fieldCaption", ""),
                    "type": f.get("dataType", "string"),
                }
                for f in mcp_fields
            ]
            rows_as_dicts = []
            for row in mcp_rows:
                row_dict = {}
                for i, f in enumerate(mcp_fields):
                    if i < len(row):
                        row_dict[f.get("fieldCaption", f"col_{i}")] = row[i]
                rows_as_dicts.append(row_dict)
            total_rows = len(rows_as_dicts)
            api_data = {
                "columns": columns,
                "rows": rows_as_dicts,
                "total_rows": total_rows,
                "truncated": total_rows > limit,
            }

        # 记录审计日志所需的变量（成功路径）
        _log_intent = intent
        _log_ds_luid = ds_luid
        _log_vizql = vizql_json
        _log_response_type = api_data.get("response_type", "table" if mcp_rows else "text")
        _log_exec_ms = round((time.time() - t0) * 1000)

        audit_record.status = "ok"
        audit_record.latency_ms = _log_exec_ms

        return {
            "success": True,
            "response_type": api_data.get("response_type", "table" if mcp_rows else "text"),
            "data": api_data if isinstance(api_data, dict) and "columns" in api_data else api_data,
            "query": {
                "datasource_luid": ds_luid,
                "datasource_name": ds_name,
                "vizql_json": vizql_json,
            },
            "metadata": {
                "intent": intent,
                "intent_confidence": confidence,
                "field_mappings": [
                    {
                        "user_term": rf.user_term,
                        "field_caption": rf.field_caption,
                        "match_source": rf.match_source,
                    }
                    for rf in resolved_fields
                ],
                "execution_time_ms": _log_exec_ms,
                "cached": False,
            },
        }

    except HTTPException as exc:
        # HTTPException 继续上抛，不吞掉
        _log_error = "NLQ_FAILED"
        _log_exec_ms = round((time.time() - t0) * 1000)
        detail = exc.detail if isinstance(exc.detail, dict) else {"message": str(exc.detail)}
        audit_record.status = "denied" if exc.status_code in (401, 403) else "failed"
        audit_record.error_code = detail.get("code")
        audit_record.error_detail = detail.get("message")
        audit_record.latency_ms = _log_exec_ms
        raise

    except Exception as exc:
        _log_error = "INTERNAL"
        _log_exec_ms = round((time.time() - t0) * 1000)
        audit_record.status = "failed"
        audit_record.error_code = "INTERNAL"
        audit_record.error_detail = str(exc)[:1000]
        audit_record.latency_ms = _log_exec_ms
        raise

    finally:
        # Capability audit: Append-Only（写入失败不阻塞主链路）
        write_audit(audit_record)
        # PRD §10.1：fire-and-forget 审计日志（无论成功/失败均记录）
        log_nlq_query(
            user_id=_log_user_id,
            question=_log_question,
            intent=_log_intent,
            datasource_luid=_log_ds_luid,
            vizql_json=_log_vizql,
            response_type=_log_response_type,
            execution_time_ms=_log_exec_ms,
            error_code=_log_error,
        )


@router.get("/suggestions")
async def suggestions(
    q: str,
    connection_id: int = None,
    db: Session = Depends(get_db),
):
    """查询建议（自动补全，PRD §6.3）GET /api/search/suggestions — analyst+
    """
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
    """查询历史（PRD §6.4）GET /api/search/history — analyst+
    """
    user = get_current_user(request=None, db=db)
    _require_role(user, "analyst")

    return {"items": [], "total": 0, "page": 1, "page_size": 20}

"""
QueryTool — Phase 1 tool wrapping NLQ Service + SQL Agent

Spec: docs/specs/36-data-agent-architecture-spec.md §3.1 ToolRegistry + §9.2 downstream
Spec: docs/specs/14-nl-to-query-pipeline-spec.md — NLQ Service
Spec: docs/specs/29-sql-agent-spec.md — SQL Agent
"""

import logging
import inspect
import re
import time
from typing import Any, Dict, List, Optional, Tuple

from services.data_agent.tool_base import BaseTool, ToolResult, ToolContext, ToolMetadata
from services.llm.nlq_service import one_pass_llm, execute_query, route_datasource, get_datasource_fields_cached, NLQError

logger = logging.getLogger(__name__)

# ── Direct VizQL builder (no-LLM fast path) ────────────────────────────────

_CHINESE_NUMS = {'一': 1, '二': 2, '三': 3, '四': 4, '五': 5,
                 '六': 6, '七': 7, '八': 8, '九': 9, '十': 10}

# Fields containing these substrings → SUM aggregation
_MEASURE_KEYWORDS = frozenset(['利润', '销售', '收入', '数量', '金额', '成本', '折扣', '额', '率'])

# Fields containing these substrings → date dimension (used for time filter)
_DATE_KEYWORDS = frozenset(['日期', '时间'])
_PREFERRED_DATE_KEYWORDS = ('订单日期', '日期', '时间')


def _cn_to_int(s: str) -> int:
    try:
        return int(s)
    except ValueError:
        return _CHINESE_NUMS.get(s, 1)


def _extract_time_filter(question: str, date_caption: str) -> Optional[dict]:
    """Return a Tableau DATE filter dict for the time expression in question, or None."""
    # 过去N年
    m = re.search(r'过去\s*(\d+|[一二三四五六七八九十]+)\s*年', question)
    if m:
        n = _cn_to_int(m.group(1))
        return {"field": {"fieldCaption": date_caption},
                "filterType": "DATE", "dateRangeType": "LASTN",
                "periodType": "YEARS", "rangeN": n}
    # 过去N个季度
    m = re.search(r'过去\s*(\d+|[一二三四五六七八九十]+)\s*(个季度|季度)', question)
    if m:
        n = _cn_to_int(m.group(1))
        return {"field": {"fieldCaption": date_caption},
                "filterType": "DATE", "dateRangeType": "LASTN",
                "periodType": "QUARTERS", "rangeN": n}
    # 过去N个月
    m = re.search(r'过去\s*(\d+|[一二三四五六七八九十]+)\s*(个月|月)', question)
    if m:
        n = _cn_to_int(m.group(1))
        return {"field": {"fieldCaption": date_caption},
                "filterType": "DATE", "dateRangeType": "LASTN",
                "periodType": "MONTHS", "rangeN": n}
    # 今年
    if '今年' in question:
        return {"field": {"fieldCaption": date_caption},
                "filterType": "DATE", "dateRangeType": "TODATE", "periodType": "YEARS"}
    # 去年
    if '去年' in question:
        return {"field": {"fieldCaption": date_caption},
                "filterType": "DATE", "dateRangeType": "LAST", "periodType": "YEARS"}
    # YYYY年
    m = re.search(r'(\d{4})\s*年', question)
    if m:
        year = int(m.group(1))
        return {"field": {"fieldCaption": date_caption},
                "filterType": "SET",
                "values": [str(year)]}
    return None


_TIME_PATTERNS = [
    r'过去\s*(\d+|[一二三四五六七八九十]+)\s*(年|个月|月|个季度|季度)',
    r'今年|去年|上季度|上月',
    r'\d{4}\s*年',
]


def _build_direct_vizql(question: str, field_captions: List[str]) -> Optional[Dict]:
    """
    Build VizQL JSON from question without any LLM call.

    Matches field captions found in the question text, classifies them as
    measure (→ SUM) or dimension, then extracts time filter from time patterns.
    Returns None if fewer than 1 non-date field matched.
    """
    q_norm = question.lower().replace('　', ' ')
    q_compact = q_norm.replace(' ', '').replace(' ', '')

    # Find mentioned field captions (case-insensitive, space-insensitive)
    mentioned: List[str] = []
    for cap in field_captions:
        cap_compact = cap.strip().lower().replace(' ', '').replace(' ', '')
        if cap_compact and cap_compact in q_compact:
            mentioned.append(cap)

    date_mentioned = [c for c in mentioned if any(kw in c for kw in _DATE_KEYWORDS)]
    other_fields = [c for c in mentioned if c not in date_mentioned]

    if not other_fields:
        return None

    # Classify non-date fields
    fields: List[Dict] = []
    for cap in other_fields:
        cap_clean = cap.replace(' ', '')
        if any(kw in cap_clean for kw in _MEASURE_KEYWORDS):
            fields.append({"fieldCaption": cap, "function": "SUM"})
        else:
            fields.append({"fieldCaption": cap})

    # Build time filter if a time pattern appears in the question
    filters: List[Dict] = []
    has_time = any(re.search(p, question) for p in _TIME_PATTERNS)
    if has_time:
        all_date_caps = [c for c in field_captions if any(kw in c for kw in _DATE_KEYWORDS)]
        preferred_date_cap = next(
            (
                cap for preferred in _PREFERRED_DATE_KEYWORDS
                for cap in all_date_caps
                if preferred in cap
            ),
            None,
        )
        date_cap = date_mentioned[0] if date_mentioned else (preferred_date_cap or (all_date_caps[0] if all_date_caps else None))
        if date_cap:
            tf = _extract_time_filter(question, date_cap)
            if tf:
                filters.append(tf)

    return {"fields": fields, "filters": filters}


def _lookup_datasource_by_name(datasource_name: str, connection_id: Optional[int]) -> Optional[Dict[str, Any]]:
    """Resolve an explicitly named Tableau datasource within the current connection."""
    if not datasource_name:
        return None

    from services.tableau.models import TableauAsset, TableauDatabase

    db = TableauDatabase()
    session = db.session
    try:
        query = session.query(TableauAsset).filter(
            TableauAsset.is_deleted == False,  # noqa: E712
            TableauAsset.asset_type == "datasource",
            TableauAsset.name == datasource_name,
        )
        if connection_id is not None:
            query = query.filter(TableauAsset.connection_id == connection_id)
        ds = query.order_by(TableauAsset.id.asc()).first()
        if not ds:
            return None
        return {
            "datasource_luid": ds.tableau_id,
            "luid": ds.tableau_id,
            "datasource_name": ds.name,
            "name": ds.name,
            "asset_id": ds.id,
            "connection_id": ds.connection_id,
            "score": 1.0,
        }
    finally:
        session.close()


class QueryTool(BaseTool):
    """
    Phase 1 Data Agent Tool: Natural Language Query Tool.

    Fast path: if caller supplies vizql_json + datasource_luid, bypass
    route_datasource and one_pass_llm entirely — direct execute_query.

    Slow path: route_datasource → one_pass_llm → execute_query.

    Tool name: "query"
    """

    name = "query"
    description = "执行自然语言数据查询。将用户问题转换为 Tableau VizQL 查询并返回结构化数据结果。适用于询问销售额、数量、统计数据等。若已有 vizql_json 和 datasource_luid，可直接传入跳过 NL→VizQL 转换（更快）。"
    metadata = ToolMetadata(
        category="query",
        version="1.1.0",
        dependencies=["requires_database", "requires_tableau"],
        tags=["nlq", "vizql", "data-query"],
    )
    parameters_schema = {
        "type": "object",
        "properties": {
            "question": {
                "type": "string",
                "description": "用户的自然语言问题，如 'Q4销售额是多少'",
            },
            "connection_id": {
                "type": "integer",
                "description": "数据源连接 ID（可选，默认使用系统默认连接）",
            },
            "vizql_json": {
                "type": "object",
                "description": "已生成的 VizQL JSON 查询（可选）。若提供则直接执行，跳过 NL→VizQL 转换。须同时提供 datasource_luid。",
            },
            "datasource_luid": {
                "type": "string",
                "description": "数据源 LUID（与 vizql_json 配合使用）",
            },
            "datasource_name": {
                "type": "string",
                "description": "数据源名称（与 vizql_json 配合使用，用于结果展示）",
            },
        },
        "required": ["question"],
    }

    async def execute(self, params: dict, context: ToolContext) -> ToolResult:
        """
        Execute a data query.

        Fast path: vizql_json + datasource_luid provided → direct execute_query.
        Slow path: route_datasource → one_pass_llm → execute_query.
        """
        start_time = time.time()
        question = params.get("question", "")
        connection_id = params.get("connection_id") or context.connection_id

        # ── Fast path: caller already has VizQL JSON ────────────────────────
        vizql_json = params.get("vizql_json")
        direct_luid = params.get("datasource_luid")
        if vizql_json and direct_luid:
            return await self._execute_direct(
                vizql_json=vizql_json,
                datasource_luid=direct_luid,
                datasource_name=params.get("datasource_name", direct_luid),
                connection_id=connection_id,
                start_time=start_time,
                context=context,
            )

        if not question:
            return ToolResult(
                success=False,
                data=None,
                error="question cannot be empty",
                execution_time_ms=int((time.time() - start_time) * 1000),
            )

        try:
            logger.info(
                "QueryTool.execute: question=%s, connection_id=%s, trace=%s",
                question,
                connection_id,
                context.trace_id,
            )

            # ── Stage 1: Route to datasource ──────────────────────────────────
            ds_info = _lookup_datasource_by_name(
                params.get("datasource_name", ""),
                connection_id=connection_id,
            ) or route_datasource(question, connection_id=connection_id)
            if not ds_info:
                return ToolResult(
                    success=False,
                    data=None,
                    error="无法找到匹配的数据源，请明确指定数据源或使用正确的术语",
                    execution_time_ms=int((time.time() - start_time) * 1000),
                )

            datasource_luid = ds_info["luid"]
            datasource_name = ds_info["name"]

            # Field captions from Redis cache (warmed by route_datasource scoring)
            asset_id = ds_info.get("asset_id")
            field_captions = get_datasource_fields_cached(asset_id) if asset_id else []
            fields_with_types = "\n".join(f"- {cap}" for cap in field_captions) if field_captions else ""

            # ── Stage 2a: Direct VizQL fast path (no LLM) ────────────────────
            if field_captions:
                direct = _build_direct_vizql(question, field_captions)
                if direct:
                    logger.info(
                        "QueryTool: direct VizQL path (no LLM), fields=%d, filters=%d, trace=%s",
                        len(direct["fields"]), len(direct["filters"]), context.trace_id,
                    )
                    return await self._execute_direct(
                        vizql_json=direct,
                        datasource_luid=datasource_luid,
                        datasource_name=datasource_name,
                        connection_id=connection_id,
                        start_time=start_time,
                        context=context,
                        intent="aggregate",
                        confidence=0.95,
                    )

            # ── Stage 2b: NL → VizQL via one_pass_llm (fallback) ─────────────
            try:
                parsed = await one_pass_llm(
                    question=question,
                    datasource_luid=datasource_luid,
                    datasource_name=datasource_name,
                    fields_with_types=fields_with_types,
                    term_mappings="",
                )
            except NLQError as e:
                logger.warning("QueryTool NLQ failed: code=%s, message=%s", e.code, e.message)
                return ToolResult(
                    success=False,
                    data=None,
                    error=f"[{e.code}] {e.message}",
                    execution_time_ms=int((time.time() - start_time) * 1000),
                )

            vizql_json = parsed.get("vizql_json", {})
            if not vizql_json:
                return ToolResult(
                    success=False,
                    data=None,
                    error="NLQ 返回的 VizQL JSON 为空",
                    execution_time_ms=int((time.time() - start_time) * 1000),
                )

            # ── Stage 3: Execute query ────────────────────────────────────────
            return await self._execute_direct(
                vizql_json=vizql_json,
                datasource_luid=datasource_luid,
                datasource_name=datasource_name,
                connection_id=connection_id,
                start_time=start_time,
                context=context,
                intent=parsed.get("intent"),
                confidence=parsed.get("confidence"),
            )

        except Exception as e:
            logger.exception("QueryTool unexpected error: %s", e)
            return ToolResult(
                success=False,
                data=None,
                error="数据查询服务暂时不可用，请稍后重试",
                execution_time_ms=int((time.time() - start_time) * 1000),
            )

    async def _execute_direct(
        self,
        vizql_json: dict,
        datasource_luid: str,
        datasource_name: str,
        connection_id: Optional[int],
        start_time: float,
        context: ToolContext,
        intent: Optional[str] = None,
        confidence: Optional[float] = None,
    ) -> ToolResult:
        """Execute a pre-built VizQL query directly against Tableau MCP."""
        try:
            result = execute_query(
                datasource_luid=datasource_luid,
                vizql_json=vizql_json,
                limit=1000,
                connection_id=connection_id,
            )
            if inspect.isawaitable(result):
                result = await result
        except NLQError as e:
            logger.warning("QueryTool execute_query failed: code=%s, message=%s", e.code, e.message)
            return ToolResult(
                success=False,
                data=None,
                error=f"[{e.code}] {e.message}",
                execution_time_ms=int((time.time() - start_time) * 1000),
            )

        execution_time_ms = int((time.time() - start_time) * 1000)

        # Normalize: Tableau MCP may return {"data": [{field: val, ...}, ...]} instead of
        # {"fields": [...], "rows": [[...]]}. Convert to the tabular format for downstream use.
        logger.debug("execute_query result keys=%s sample=%s", list(result.keys()), str(result)[:200])
        if "rows" not in result and "data" in result and isinstance(result.get("data"), list):
            data_list: list = result["data"]
            if data_list and isinstance(data_list[0], dict):
                field_names = list(data_list[0].keys())
                result_fields = field_names
                result_rows = [[r.get(f) for f in field_names] for r in data_list]
            else:
                result_fields, result_rows = [], []
        else:
            result_fields = result.get("fields", [])
            result_rows = result.get("rows", [])

        logger.info(
            "QueryTool success: datasource=%s, rows=%d, time=%dms",
            datasource_luid,
            len(result_rows),
            execution_time_ms,
        )

        return ToolResult(
            success=True,
            data={
                "fields": result_fields,
                "rows": result_rows,
                "intent": intent,
                "confidence": confidence,
                "datasource_name": datasource_name,
            },
            execution_time_ms=execution_time_ms,
        )

"""NL-to-Query 流水线服务（PRD §14）
四阶段流水线：意图分类+查询构建(One-Pass) → 字段解析 → 查询执行 → 结果格式化
"""
import json
import logging
import re
import tiktoken
from dataclasses import dataclass
from typing import List, Dict, Any, Optional, Tuple
from contextvars import ContextVar

from sqlalchemy.orm import Session

from services.capability.audit import get_trace_id, get_principal
from services.llm.service import llm_service
from services.llm.prompts import ONE_PASS_NL_TO_QUERY_TEMPLATE, ONE_PASS_RETRY_TEMPLATE
from services.tableau.models import TableauDatabase, TableauAsset


def _mcp_query_datasource_direct(
    mcp_server_url: str,
    site: str,
    token_name: str,
    token_value: str,
    datasource_luid: str,
    query: Dict[str, Any],
    limit: int = 1000,
    timeout: int = 30,
) -> Dict[str, Any]:
    """
    直接通过 MCP JSON-RPC 调用 query-datasource 工具（不依赖 TableauConnection 表）。

    用于：当 connection_id=None 且有活跃 MCP server config credentials 时。
    """
    import httpx

    protocol_ver = "2025-06-18"
    session_id = f"nlq-direct-{datasource_luid[:8]}"

    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json, text/event-stream",
        "MCP-Protocol-Version": protocol_ver,
        "MCP-Session-ID": session_id,
    }

    try:
        with httpx.Client(timeout=float(timeout)) as client:
            # initialize
            client.post(
                mcp_server_url,
                json={
                    "jsonrpc": "2.0", "id": 1, "method": "initialize",
                    "params": {
                        "protocolVersion": protocol_ver,
                        "clientInfo": {"name": "nlq-direct", "version": "1.0"},
                        "serverInfo": {"name": "tableau-mcp", "version": "1.0"},
                    }
                },
                headers=headers,
            )
            # notifications/initialized
            client.post(
                mcp_server_url,
                json={"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}},
                headers=headers,
            )
            # tools/call: query-datasource
            resp = client.post(
                mcp_server_url,
                json={
                    "jsonrpc": "2.0", "id": 2, "method": "tools/call",
                    "params": {
                        "name": "query-datasource",
                        "arguments": {
                            "datasourceLuid": datasource_luid,
                            "query": query,
                            "limit": limit,
                        }
                    }
                },
                headers=headers,
            )
            data = resp.json()
            result = data.get("result", {})
            content = result.get("content", [])
            text = "".join(c.get("text", "") for c in content if c.get("type") == "text")
            if text:
                return json.loads(text)
            return {}
    except httpx.HTTPError as e:
        logger.error("MCP direct query HTTP error: %s", e)
        raise NLQError("NLQ_006", message=f"MCP 查询失败: {e}")
    except json.JSONDecodeError as e:
        logger.error("MCP direct query JSON decode error: %s", e)
        raise NLQError("NLQ_006", message=f"MCP 返回格式错误: {e}")
    except Exception as e:
        logger.error("MCP direct query failed: %s", e)
        raise NLQError("NLQ_006", message=f"MCP 查询失败: {e}")


def execute_query(
    datasource_luid: str,
    vizql_json: Dict[str, Any],
    limit: int = 1000,
    timeout: int = 30,
    connection_id: Optional[int] = None,
    wrapper=None,
) -> Dict[str, Any]:
    """
    Stage 3：查询执行。

    通过 Tableau MCP query-datasource 执行 VizQL JSON，
    返回符合 PRD §5.5.3 格式的原始查询结果。

    约束 A：环境变量（PAT）从 TableauConnection 解密注入
    约束 B：MCP Session 长连接复用（单例 TableauMCPClient）
    约束 C：VizQL JSON 的 fieldCaption 须与阶段2 resolved_fields 对齐

    参数：
        datasource_luid: Tableau 数据源 LUID
        vizql_json: One-Pass LLM 生成的 VizQL JSON
        limit: 最大返回行数（默认 1000）
        timeout: 查询超时秒数
        connection_id: 租户连接 ID（必填，用于 MCP 路由到正确的 Tableau Site）
        wrapper: CapabilityWrapper 实例（可选，用于包装 query_metric capability）

    返回：
        {"fields": [...], "rows": [[...], ...]}

    异常：
        NLQError: NLQ_006（执行失败）/ NLQ_007（超时）/ NLQ_009（无权限）
    """
    from services.tableau.mcp_client import get_tableau_mcp_client, TableauMCPError

    # T1.3 入口2：优先通过 wrapper.invoke("query_metric") 包装 MCP 调用
    # 先从 context var 获取（被 run() 设置），再从参数获取（直接传入优先）
    _ctx_wrapper = get_wrapper()
    effective_wrapper = wrapper if wrapper is not None else _ctx_wrapper

    if effective_wrapper is not None:
        principal = get_principal() or {"id": 0, "role": "analyst"}
        cap_result = effective_wrapper.invoke(
            principal=principal,
            capability_name="query_metric",
            params={
                "datasource_luid": datasource_luid,
                "vizql_json": vizql_json,
                "limit": limit,
                "timeout": timeout,
                "connection_id": connection_id,
            },
        )
        return cap_result.data if hasattr(cap_result, "data") else cap_result

    if connection_id is None:
        # Fallback：当 connection_id=None 时，从活跃 MCP server config 获取 credentials
        # 用于无预同步 TableauConnection 但有 MCP server 配置的场景（如首页问答 MCP fallback）
        from app.core.database import SessionLocal
        from services.mcp.models import McpServer
        from app.core.crypto import get_tableau_crypto

        db = SessionLocal()
        try:
            mcp_record = db.query(McpServer).filter(
                McpServer.is_active == True,
                McpServer.type == "tableau",
            ).order_by(McpServer.id.asc()).first()

            if not mcp_record or not mcp_record.credentials:
                raise NLQError("NLQ_005", message="无可用的 Tableau 连接配置")

            creds = mcp_record.credentials
            pat_value = creds.get("pat_value", "")
            if not pat_value:
                raise NLQError("NLQ_005", message="Tableau PAT 未配置")

            # 解密 PAT（PAT 在 MCP config 中是明文存储，MCP server 进程持有）
            # 注意：这里 pat_value 是明文，直接传给 MCP
            result = _mcp_query_datasource_direct(
                mcp_server_url=mcp_record.server_url,
                site=creds.get("site_name", ""),
                token_name=creds.get("pat_name", ""),
                token_value=pat_value,
                datasource_luid=datasource_luid,
                query=vizql_json,
                limit=limit,
                timeout=timeout,
            )
            return result
        finally:
            db.close()

    client = get_tableau_mcp_client(connection_id=connection_id)
    try:
        result = client.query_datasource(
            datasource_luid=datasource_luid,
            query=vizql_json,
            limit=limit,
            timeout=timeout,
            connection_id=connection_id,
        )
        return result
    except TableauMCPError as e:
        # TableauMCPError → NLQError 统一映射
        code_map = {
            "NLQ_006": "NLQ_006",
            "NLQ_007": "NLQ_007",
            "NLQ_009": "NLQ_009",
        }
        nlq_code = code_map.get(e.code, "NLQ_006")
        raise NLQError(nlq_code, message=e.message, details=e.details)

logger = logging.getLogger(__name__)

# === T1.3 入口1+2 共享：CapabilityWrapper context var ===
# 供 execute_query（入口2）和内部 LLM 调用（入口1）从 context 获取 wrapper 实例
_wrapper_ctx: ContextVar[Optional[Any]] = ContextVar("nlq_wrapper", default=None)


def set_wrapper(wrapper: Any) -> None:
    """设置当前请求的 CapabilityWrapper 到 context（供 execute_query 等获取）"""
    _wrapper_ctx.set(wrapper)


def get_wrapper() -> Any:
    """获取当前请求的 CapabilityWrapper（可能为 None）"""
    return _wrapper_ctx.get()


# === T1.3 入口3：NLQ 完整流水线入口（供 search.py /api/search/query 委派）===
async def run(
    question: str,
    datasource_luid: Optional[str] = None,
    connection_id: Optional[int] = None,
    conversation_id: Optional[str] = None,
    options: Optional[dict] = None,
    use_conversation_context: bool = False,
    target_sites: Optional[list] = None,
    request=None,  # FastAPI Request（可选，用于提取 trace_id）
    response=None,  # FastAPI Response（可选）
    user: Optional[dict] = None,  # 用户 principal dict
    db: Optional[Any] = None,  # SQLAlchemy Session
    wrapper=None,  # CapabilityWrapper 实例（T1.3 入口3 由 search.py 传入）
) -> Dict[str, Any]:
    """
    NLQ 完整流水线入口（Entry 3）。

    供 search.py /api/search/query 委派使用：
      result = await wrapper.invoke(principal, "nlq_search", params)  # 计量层
      result = await nlq_service.run(**params)                       # 执行层

    参数（与 QueryRequest 对齐）：
        question: 用户自然语言问题
        datasource_luid: 指定数据源 LUID
        connection_id: 指定连接 ID
        conversation_id: 对话 ID（追问用）
        options: 查询选项（如 limit）
        use_conversation_context: 是否使用追问上下文
        target_sites: 多站点并发目标
        request: FastAPI Request（用于 trace_id）
        response: FastAPI Response（用于 trace_id 透传）
        user: 用户 principal dict（id, role, tenant_id）
        db: SQLAlchemy Session
        wrapper: CapabilityWrapper 实例（由 search.py 传入）

    返回：
        NLQ 查询结果 dict（与 search.py /api/search/query 响应格式一致）
    """
    from services.capability.audit import set_principal, set_trace_id
    import uuid

    # ── 1. 初始化上下文 ───────────────────────────────────────
    if request is not None:
        incoming_trace = request.headers.get("X-Trace-ID") if hasattr(request, "headers") else None
        trace_id = incoming_trace or str(uuid.uuid4())
    else:
        trace_id = str(uuid.uuid4())

    # 设置 audit context
    set_trace_id(trace_id)
    if user:
        set_principal(user)

    # ── 2. 设置 wrapper 到 context var（供 execute_query 等获取）──
    if wrapper is not None:
        set_wrapper(wrapper)

    # ── 3. 委派给 search.py 的核心查询逻辑执行 ──────────────────
    from app.api.search import _execute_nlq_pipeline
    result = await _execute_nlq_pipeline(
        question=question,
        datasource_luid=datasource_luid,
        connection_id=connection_id,
        conversation_id=conversation_id,
        options=options,
        use_conversation_context=use_conversation_context,
        target_sites=target_sites,
        request=request,
        response=response,
        user=user,
        db=db,
        trace_id=trace_id,
    )
    return result


# === PRD §10.2 数据量限制常量 ===
MAX_QUERY_LENGTH = 500
MAX_RESULT_ROWS = 1000
RATE_LIMIT_PER_MINUTE = 20

# === PRD §10.3 敏感数据源过滤 ===
BLOCKED_SENSITIVITY = {"high", "confidential"}


def is_datasource_sensitivity_blocked(datasource_luid: str) -> bool:
    """
    检查数据源敏感度是否被禁止（PRD §10.3）。
    HIGH / CONFIDENTIAL 级别的数据源不允许通过 NL-to-Query 查询。

    通过 datasource_luid 查找对应的 TableauDatasourceSemantics，
    判断其 sensitivity_level 是否在 BLOCKED_SENSITIVITY 集合中。
    若无对应语义记录，默认允许查询（LOW）。
    """
    from services.semantic_maintenance.models import TableauDatasourceSemantics
    from services.tableau.models import TableauDatabase

    db = TableauDatabase()
    session = db.session
    try:
        # 通过 datasource_luid 查找对应的语义记录
        semantics = session.query(TableauDatasourceSemantics).filter(
            TableauDatasourceSemantics.tableau_datasource_id == datasource_luid,
        ).first()

        if semantics is None:
            # 无语义记录，默认 LOW → 允许
            return False

        return semantics.sensitivity_level.lower() in BLOCKED_SENSITIVITY
    finally:
        session.close()


# === 错误码常量 ===
NLQ_ERROR_CODES = {
    "NLQ_001": "查询问题不合法",
    "NLQ_002": "无法理解查询意图",
    "NLQ_003": "查询构建失败",
    "NLQ_004": "未找到匹配字段",
    "NLQ_005": "无法匹配数据源",
    "NLQ_006": "数据查询执行失败",
    "NLQ_007": "查询超时",
    "NLQ_008": "LLM 服务不可用",
    "NLQ_009": "数据源访问被拒绝",
    "NLQ_010": "查询过于频繁",
    "NLQ_011": "敏感数据不支持查询",
    "NLQ_012": "暂无可用数据源",
}


class NLQError(Exception):
    """NL-to-Query 流水线异常"""

    def __init__(self, code: str, message: str = None, details: dict = None):
        self.code = code
        self.message = message or NLQ_ERROR_CODES.get(code, "未知错误")
        self.details = details or {}
        super().__init__(f"[{code}] {self.message}")


# === One-Pass 输出 Schema ===
ONE_PASS_OUTPUT_SCHEMA = {
    "type": "object",
    "required": ["intent", "confidence", "vizql_json"],
    "properties": {
        "intent": {
            "type": "string",
            "enum": ["aggregate", "filter", "ranking", "trend", "comparison"],
        },
        "confidence": {"type": "number", "minimum": 0.0, "maximum": 1.0},
        "vizql_json": {
            "type": "object",
            "required": ["fields"],
            "properties": {
                "fields": {
                    "type": "array",
                    "minItems": 1,
                    "items": {
                        "type": "object",
                        "required": ["fieldCaption"],
                        "properties": {
                            "fieldCaption": {"type": "string"},
                            "function": {
                                "type": "string",
                                "enum": [
                                    "SUM", "AVG", "MEDIAN", "COUNT", "COUNTD",
                                    "MIN", "MAX", "STDEV", "VAR",
                                    "YEAR", "QUARTER", "MONTH", "WEEK", "DAY",
                                    "TRUNC_YEAR", "TRUNC_QUARTER", "TRUNC_MONTH",
                                    "TRUNC_WEEK", "TRUNC_DAY",
                                ],
                            },
                            "fieldAlias": {"type": "string"},
                            "sortDirection": {"type": "string", "enum": ["ASC", "DESC"]},
                            "sortPriority": {"type": "integer", "minimum": 1},
                            "maxDecimalPlaces": {"type": "integer", "minimum": 0},
                        },
                    },
                },
                "filters": {"type": "array", "items": {"type": "object"}},
            },
        },
    },
}

# === 意图分类关键词 ===
INTENT_KEYWORDS = {
    "ranking": ["前N", "排名", "最高", "最低", "最多", "最少", "排行", "top", "bottom", "rank", "highest", "lowest"],
    "trend": ["趋势", "走势", "变化", "同比", "环比", "月度", "季度", "trend", "over time", "monthly", "quarterly"],
    "comparison": ["对比", "vs", "比较", "各...的", "分别", "compare", "versus", "each", "by"],
    "filter": ["...的", "哪些", "筛选", "包含", "不包含", "where", "which", "filter", "include"],
    "aggregate": ["总", "合计", "总共", "一共", "平均", "数量", "total", "sum", "average", "count", "how many"],
}

# === META 查询意图关键词（Q1-Q10 业务口径，不走 VizQL 流水线）===
# 注意事项：
# 1. 字典的遍历顺序即优先级，精确意图放在前面
# 2. 避免在高优先级意图中使用"哪些数据源"等宽泛关键词（会误匹配其他问题）
# 3. meta_datasource_list 放在最后兜底，且只保留精确短语
META_INTENT_KEYWORDS = {
    # Q9：数据源描述/备注不完整（精确，优先匹配）
    "meta_datasource_incomplete_metadata": [
        "备注没写", "定义没写", "没写全", "描述不完整", "备注不完整",
        "缺少描述", "没有描述", "缺少备注", "没有备注",
        "语义信息不完整", "元数据不完整",
    ],
    # Q10：重名/重复数据源
    "meta_datasource_duplicate": [
        "重名的数据源", "重复的数据源", "数据源重名", "数据源重复",
        "同名数据源", "有没有重名", "是否重名", "名称冲突",
        "是重名的", "数据源是重名",
    ],
    # Q6：近期新增数据源
    "meta_datasource_new_in_period": [
        "新增了哪些数据源", "新增加了哪些数据源", "新增的数据源",
        "最近新增数据源", "这个月新增数据源", "本月新增数据源",
        "一个月新增", "30天新增",
    ],
    # Q7：近期更新的数据源
    "meta_datasource_recently_updated": [
        "哪些数据源被改过", "数据源被修改", "数据源被更新",
        "最近改过的数据源", "最近动过的数据源", "过去一周数据源",
        "这一周哪些数据源", "最近更新的数据源", "最近修改的数据源",
    ],
    # Q8：按大小排列数据源
    "meta_datasource_top_by_size": [
        "占用空间最大", "数据源大小", "存储空间最大", "最大的数据源",
        "占用最多空间", "空间占用", "数据量最大", "体积最大",
    ],
    # Q3：字段列表
    "meta_field_list": [
        "有什么字段", "有哪些字段", "包含哪些字段", "字段列表", "字段有哪些",
        "哪些字段", "什么字段", "包含什么字段", "都有哪些字段", "有几个字段",
    ],
    # Q4：物理表溯源
    "meta_datasource_physical_table": [
        "物理表", "底层表", "对应的表", "后台的表", "原始表",
        "数据库表", "源表", "上游表", "对应后台",
    ],
    # Q5：下游报表（引用数据源的工作簿）
    "meta_datasource_downstream": [
        "用了这个数据源", "引用了这个数据源", "哪些看板用了", "哪些报表用了",
        "哪些工作簿用了", "看板和报表是用了", "依赖这个数据源",
        "下游报表", "下游工作簿", "报表是用了",
    ],
    # Q2：报表/工作簿计数
    "meta_workbook_count": [
        "有多少个报表", "有几个报表", "报表数量", "多少个工作簿",
        "有几个工作簿", "工作簿数量", "有多少报表", "几个报表",
        "平台上有多少报表", "平台上有几个报表",
    ],
    # 原有：看板计数（dashboard）
    "meta_asset_count": [
        "你有几个看板", "有几个看板", "看板数量", "有多少看板",
        "几个dashboard", "几个workbook", "多少个看板", "看板总数",
    ],
    # 语义质量
    "meta_semantic_quality": [
        "语义配置有哪些不完善", "语义配置不完善", "语义缺失",
        "哪些语义没配置", "语义配置问题", "语义不完善", "语义配置哪些问题",
    ],
    # Q1：数据源列表与计数（放最后兜底，关键词仅保留精确短语）
    "meta_datasource_list": [
        "你有哪些数据源", "有哪些数据源", "数据源列表", "list datasource",
        "数据源有哪些", "几个数据源", "多少个数据源", "有几个数据源",
        "多少数据源", "接了多少个数据源", "接了几个数据源", "共有几个数据源",
        "一共接了多少", "现在有多少数据源", "数据源一共有多少",
    ],
}


def classify_meta_intent(question: str) -> Optional[str]:
    """
    规则检测 META 查询意图，返回 intent key 或 None。

    META 查询不走 VizQL One-Pass LLM 流水线，直接查本地 DB 返回结构化文本。
    优先级高于 VizQL 意图分类（在 search.py 中优先执行）。
    """
    q = question.lower()
    for intent, keywords in META_INTENT_KEYWORDS.items():
        for kw in keywords:
            if kw.lower() in q:
                return intent
    return None


# === Tableau 动作意图关键词 ===
TABLEAU_ACTION_INTENT_KEYWORDS = {
    "tableau_field_match": [
        "字段叫什么", "找字段", "匹配字段", "这个字段叫", "字段名是",
        "resolve field", "find field", "match field",
        "那个维度", "那个指标", "哪个字段",
    ],
    "tableau_view_filter": [
        "改过滤器", "设置筛选", "筛选为", "过滤为", "显示哪个区域",
        "只看", "只显示", "filter to", "filter by", "set filter",
        "视图只显示", "看板显示",
    ],
    "tableau_write_semantic": [
        "修改字段名", "改字段描述", "更新字段", "字段重命名",
        "update field", "rename field", "change caption",
        "发布语义", "把语义发布", "publish semantic",
    ],
    "tableau_parameter": [
        "改参数", "设置参数", "参数值", "parameter 值",
        "set parameter", "change parameter",
    ],
}

# === Tableau 动作意图 -> 建议工具映射 ===
TABLEAU_ACTION_TOOL_MAP = {
    "tableau_field_match": ["resolve-field-name", "get-field-schema"],
    "tableau_view_filter": ["get-view-filter-url", "create-custom-view"],
    "tableau_write_semantic": ["update-field-caption", "update-field-description", "publish-field-semantic"],
    "tableau_parameter": ["get-workbook-parameters", "set-parameter-via-url", "run-vizql-command"],
}


def classify_tableau_action_intent(question: str) -> Optional[str]:
    """
    检测是否为 Tableau 动作意图（字段匹配/视图控制/写操作/参数控制）。
    返回 intent key 或 None（交由现有 VizQL 流水线处理）。
    规则匹配优先，无匹配时返回 None。
    """
    q_lower = question.lower()
    for intent, keywords in TABLEAU_ACTION_INTENT_KEYWORDS.items():
        for kw in keywords:
            if kw.lower() in q_lower:
                return intent
    return None


MIN_ROUTING_SCORE = 0.3


# === 数据类 ===
@dataclass
class IntentResult:
    type: str
    confidence: float
    source: str  # "rule" | "llm"


@dataclass
class ResolvedField:
    field_caption: str
    field_name: str
    role: str  # "dimension" | "measure"
    data_type: str
    match_source: str  # "exact" | "synonym" | "semantic" | "fuzzy" | "llm"
    match_confidence: float
    user_term: str


@dataclass
class TableauActionIntentResult:
    type: str          # tableau_field_match / tableau_view_filter / tableau_write_semantic / tableau_parameter
    confidence: float
    source: str        # "rule"
    suggested_tools: list  # 建议调用的 MCP tool 名称列表


# === 意图分类器（规则快速路径）===
def classify_intent(question: str) -> Optional[IntentResult]:
    """返回 None 表示需走 One-Pass LLM；返回 IntentResult 表示规则命中"""
    q = question.lower()
    for intent, keywords in INTENT_KEYWORDS.items():
        for kw in keywords:
            if kw.lower() in q:
                return IntentResult(type=intent, confidence=0.90, source="rule")
    return None


# === 阶段 2/1 一致性校验（Spec 14 v1.1 §6 — 防止 LLM hallucinate fieldCaption）===

_FIELD_CONSISTENCY_RETRY_TEMPLATE = """你生成的 VizQL JSON 中以下 fieldCaption 在数据源中不存在：

不存在的字段：{missing_fields}

数据源可用字段：
{available_fields}

请重新生成 JSON，确保 vizql_json.fields 中的所有 fieldCaption 都必须来自上述可用字段列表。
如果需要使用的度量字段没有对应的可用字段，请使用 SUM(某字段) 格式或选择最接近的字段。
不要虚构任何不在可用列表中的 fieldCaption。

直接输出 JSON，不要包含任何解释文字："""


def validate_field_captions_consistency(
    parsed: dict,
    datasource_luid: str,
) -> tuple:
    """
    校验 One-Pass LLM 输出的 fieldCaption 是否在真实数据源中存在（阶段 2/1 契约）。

    Spec 14 v1.1 §6 P1 问题：
    LLM 可能 hallucinate 不存在的 fieldCaption，导致 Stage 3 MCP 查询失败（NLQ_006）。
    此校验在 JSON Schema 校验后、MCP 执行前拦截。

    策略：
    - 获取数据源真实 fieldCaption 列表（Redis 缓存，1h TTL）
    - 若 LLM 输出的任意 fieldCaption 不在真实列表中 → 校验失败
    - 缺失严重（>50% 或关键字段）时触发带可用字段列表的重试

    Returns:
        (is_valid: bool, missing_fields: list, available_fields: list)

    Raises:
        NLQError(NLQ_004): 校验失败且重试后仍不通过
    """
    vizql = parsed.get("vizql_json", {})
    llm_fields: list = vizql.get("fields", [])

    if not llm_fields:
        return True, [], []  # schema 校验已拦截空字段

    # 获取数据源真实字段（强制走 Redis 缓存）
    from services.tableau.models import TableauDatabase, TableauAsset

    db = TableauDatabase()
    session = db.session
    asset = session.query(TableauAsset).filter(
        TableauAsset.tableau_id == datasource_luid
    ).first()
    session.close()

    if not asset:
        # 无法获取资产信息时跳过校验（fail-open，不阻断查询）
        logger.warning("无法获取 datasource_luid=%s 对应的 asset，跳过 fieldCaption 一致性校验, trace=%s",
                       datasource_luid, get_trace_id())
        return True, [], []

    actual_captions = get_datasource_fields_cached(asset.id)
    available_fields_str = "\n".join(
        f"- {fc}" for fc in actual_captions
    )

    # 检查每个 LLM 输出的 fieldCaption
    missing_fields = []
    for f in llm_fields:
        caption = f.get("fieldCaption", "")
        if caption and caption not in actual_captions:
            missing_fields.append(caption)

    if missing_fields:
        logger.warning(
            "Stage 2/1 fieldCaption 一致性校验失败: datasource_luid=%s, missing=%s, trace=%s",
            datasource_luid, missing_fields, get_trace_id(),
        )

    return False, missing_fields, actual_captions


async def _retry_field_consistency(
    parsed: dict,
    missing_fields: list,
    available_fields: list,
    prompt: str,
    system_prompt: str,
    ds_luid: str = "",
) -> tuple:
    """
    带可用字段列表的 fieldCaption 一致性重试。

    将缺失字段 + 可用字段列表注入 Prompt，引导 LLM 重新生成合法的 fieldCaption。
    """
    available_fields_str = "\n".join(f"- {fc}" for fc in available_fields)
    retry_prompt = _FIELD_CONSISTENCY_RETRY_TEMPLATE.format(
        missing_fields=", ".join(f"'{f}'" for f in missing_fields),
        available_fields=available_fields_str,
    ) + "\n\n原始问题：\n" + prompt

    # T1.3 入口1：一致性重试时也通过 wrapper.invoke("llm_complete") 包装
    wrapper = get_wrapper()
    if wrapper is not None:
        principal = get_principal() or {"id": 0, "role": "analyst"}
        cap_result = await wrapper.invoke(
            principal=principal,
            capability_name="llm_complete",
            params={
                "prompt": retry_prompt,
                "system": system_prompt,
                "timeout": 30,
                "purpose": "nlq",
            },
        )
        result = cap_result.data if hasattr(cap_result, "data") else cap_result
    else:
        result = await llm_service.complete_for_semantic(
            prompt=retry_prompt,
            system=system_prompt,
            timeout=30,
            purpose="nlq",
        )

    if "error" in result:
        return None, f"一致性重试 LLM 调用失败：{result['error']}"

    content = result["content"]
    parsed_retry, parse_err = parse_json_from_response(content)
    if parse_err:
        return None, f"一致性重试 JSON 解析失败：{parse_err}"

    is_valid, validation_err = validate_one_pass_output(parsed_retry)
    if not is_valid:
        return None, f"一致性重试 JSON 校验仍失败：{validation_err}"

    # 再次校验一致性
    is_ok, still_missing, _ = validate_field_captions_consistency(
        parsed_retry,
        ds_luid,
    )
    if not is_ok:
        return None, (
            f"重试后 fieldCaption 仍存在未知字段：{still_missing}。"
            f"无法生成合法的 VizQL JSON。"
        )

    return parsed_retry, None


# === JSON Schema 校验 ===
def validate_one_pass_output(raw: Any) -> Tuple[bool, Optional[str]]:
    """
    校验 One-Pass LLM 输出是否符合 Schema。
    返回 (is_valid, error_message)
    """
    if not isinstance(raw, dict):
        return False, f"输出不是 JSON 对象：{type(raw)}"

    # 校验 required 字段
    for field in ONE_PASS_OUTPUT_SCHEMA.get("required", []):
        if field not in raw:
            return False, f"缺少必填字段：{field}"

    # 校验 intent
    intent_enum = ONE_PASS_OUTPUT_SCHEMA["properties"]["intent"]["enum"]
    if raw.get("intent") not in intent_enum:
        return False, f"intent 值不合法：{raw.get('intent')}，必须在 {intent_enum} 中"

    # 校验 confidence
    conf = raw.get("confidence")
    if not isinstance(conf, (int, float)) or conf < 0.0 or conf > 1.0:
        return False, f"confidence 值不合法：{conf}，必须在 0.0~1.0 之间"

    # 校验 vizql_json.fields
    vizql = raw.get("vizql_json", {})
    fields = vizql.get("fields", [])
    if not isinstance(fields, list) or len(fields) == 0:
        return False, "vizql_json.fields 不能为空"
    for i, f in enumerate(fields):
        if not isinstance(f, dict) or "fieldCaption" not in f:
            return False, f"fields[{i}] 缺少 fieldCaption"
        if "function" in f:
            func_enum = ONE_PASS_OUTPUT_SCHEMA["properties"]["vizql_json"]["properties"]["fields"]["items"]["properties"]["function"]["enum"]
            if f["function"] not in func_enum:
                return False, f"fields[{i}].function 值不合法：{f['function']}"

    return True, None


def parse_json_from_response(content: str) -> Tuple[Optional[Dict], Optional[str]]:
    """
    从 LLM 响应文本中提取 JSON。
    尝试 json.loads 或从 ```json 代码块中提取。
    """
    # 去掉 markdown 代码块包裹
    content = content.strip()
    if content.startswith("```"):
        # 提取 ```json ... ``` 中的内容
        match = re.search(r"```(?:json)?\s*([\s\S]+?)```", content)
        if match:
            content = match.group(1).strip()
    try:
        return json.loads(content), None
    except json.JSONDecodeError as e:
        return None, f"JSON 解析失败：{e}"


# === One-Pass LLM 调用 ===
async def one_pass_llm(
    question: str,
    datasource_luid: str,
    datasource_name: str,
    fields_with_types: str,
    term_mappings: str,
    intent_hint: Optional[str] = None,
) -> Dict[str, Any]:
    """
    One-Pass LLM 调用（意图分类 + VizQL JSON 生成）。
    temperature 硬编码为 0.1（PRD §5.1 强制约束）。

    流程：
    1. 组装 Prompt
    2. 调用 LLM（temperature=0.1）
    3. 解析 JSON 响应
    4. Schema 校验
    5. 校验失败 → 带反馈重试（最多 1 次）
    6. 返回 {intent, confidence, vizql_json}
    """
    # ── Token 预算检查（P1 修复：防止宽表字段过多导致 prompt 爆炸）────────
    MAX_FIELDS_WITH_TYPES_TOKENS = 2000
    enc = tiktoken.get_encoding("cl100k_base")
    fields_tokens = enc.encode(fields_with_types)
    if len(fields_tokens) > MAX_FIELDS_WITH_TYPES_TOKENS:
        # 按行截断（保留前 N 行）
        lines = fields_with_types.split("\n")
        truncated_lines = []
        token_count = 0
        for line in lines:
            line_tokens = enc.encode(line)
            if token_count + len(line_tokens) > MAX_FIELDS_WITH_TYPES_TOKENS:
                break
            truncated_lines.append(line)
            token_count += len(line_tokens)
        fields_with_types = "\n".join(truncated_lines)
        logger.warning("宽表字段过多，已触发 Token 截断（原始 > %d tokens, trace=%s）",
                       len(fields_tokens), get_trace_id())

    # 组装 Prompt
    prompt = ONE_PASS_NL_TO_QUERY_TEMPLATE.format(
        datasource_luid=datasource_luid,
        datasource_name=datasource_name,
        fields_with_types=fields_with_types,
        term_mappings=term_mappings or "无",
        question=question,
    )

    system_prompt = "你是一个 Tableau 数据查询专家。"

    # T1.3 入口1：优先通过 wrapper.invoke("llm_complete") 包装 LLM 调用
    wrapper = get_wrapper()
    if wrapper is not None:
        principal = get_principal() or {"id": 0, "role": "analyst"}
        cap_result = await wrapper.invoke(
            principal=principal,
            capability_name="llm_complete",
            params={
                "prompt": prompt,
                "system": system_prompt,
                "timeout": 30,
                "purpose": "nlq",
            },
        )
        result = cap_result.data if hasattr(cap_result, "data") else cap_result
    else:
        # 首次调用：使用 complete_for_semantic（Spec 14 v1.1 §5.1 + Spec 12 v1.2 §4.2）
        # - temperature=0.1
        # - OpenAI: response_format={"type": "json_object"}
        # - Anthropic: 仅 temperature=0.1（不支持 response_format）
        result = await llm_service.complete_for_semantic(
            prompt=prompt,
            system=system_prompt,
            timeout=30,
            purpose="nlq",
        )

    if "error" in result:
        raise NLQError("NLQ_008", details={"llm_error": result["error"]})

    content = result["content"]
    parsed, parse_err = parse_json_from_response(content)
    if parse_err:
        # JSON 解析失败，尝试带反馈重试
        parsed, parse_err = _retry_with_feedback(
            prompt=prompt,
            system_prompt=system_prompt,
            error_details=parse_err,
        )
        if parse_err:
            raise NLQError("NLQ_003", message=f"JSON 解析失败：{parse_err}")

    # Schema 校验
    is_valid, validation_err = validate_one_pass_output(parsed)
    if not is_valid:
        # 校验失败，带反馈重试
        parsed, validation_err = await _retry_with_feedback(
            prompt=prompt,
            system_prompt=system_prompt,
            error_details=validation_err,
        )
        if validation_err:
            raise NLQError("NLQ_003", message=f"JSON 校验失败：{validation_err}")

    # ── 阶段 2/1 一致性校验（Spec 14 v1.1 §6 P1 修复）──────────────
    # Schema 校验通过后，检查 fieldCaption 是否在真实数据源中存在
    is_consistent, missing_fields, available_fields = validate_field_captions_consistency(
        parsed, datasource_luid
    )
    if not is_consistent:
        logger.info(
            "Stage 2/1 fieldCaption 不一致触发重试: datasource_luid=%s, missing=%s, trace=%s",
            datasource_luid, missing_fields, get_trace_id(),
        )
        # 带可用字段列表重试
        parsed, consistency_err = await _retry_field_consistency(
            parsed=parsed,
            missing_fields=missing_fields,
            available_fields=available_fields,
            prompt=prompt,
            system_prompt=system_prompt,
            ds_luid=datasource_luid,
        )
        if consistency_err:
            raise NLQError("NLQ_004", message=f"fieldCaption 一致性重试失败：{consistency_err}")

    return parsed


async def _retry_with_feedback(
    prompt: str,
    system_prompt: str,
    error_details: str,
) -> Tuple[Optional[Dict], Optional[str]]:
    """
    带反馈的 JSON 重试（PRD §5.4）。
    将具体报错信息追加到 Prompt 末尾，重新调用 LLM。
    """
    retry_prompt = ONE_PASS_RETRY_TEMPLATE.format(error_details=error_details) + "\n\n原始 Prompt：\n" + prompt

    # T1.3 入口1：重试时也通过 wrapper.invoke("llm_complete") 包装
    wrapper = get_wrapper()
    if wrapper is not None:
        principal = get_principal() or {"id": 0, "role": "analyst"}
        cap_result = await wrapper.invoke(
            principal=principal,
            capability_name="llm_complete",
            params={
                "prompt": retry_prompt,
                "system": system_prompt,
                "timeout": 30,
                "purpose": "nlq",
            },
        )
        result = cap_result.data if hasattr(cap_result, "data") else cap_result
    else:
        result = await llm_service.complete_for_semantic(
            prompt=retry_prompt,
            system=system_prompt,
            timeout=30,
            purpose="nlq",
        )

    if "error" in result:
        return None, f"重试失败：{result['error']}"

    content = result["content"]
    parsed, parse_err = parse_json_from_response(content)
    if parse_err:
        return None, f"重试 JSON 解析失败：{parse_err}"

    is_valid, validation_err = validate_one_pass_output(parsed)
    if not is_valid:
        return None, f"重试 JSON 校验仍失败：{validation_err}"

    return parsed, None


# === 字段解析 ===
async def resolve_fields(
    question: str,
    fields: List[Dict[str, str]],
    intent: str,
) -> List[ResolvedField]:
    """
    字段解析（阶段2）：将用户问题中的字段映射到 Tableau fieldCaption。
    按优先级：精确匹配 → 同义词匹配 → 语义标注匹配 → 模糊匹配 → LLM 兜底。
    """
    resolved = []
    # 简化实现：基于关键词的模糊匹配
    # 完整实现应包括同义词表、语义标注、编辑距离、拼音匹配
    q_lower = question.lower()

    for f in fields:
        caption_lower = f.get("field_caption", "").lower()
        name_lower = f.get("field_name", "").lower()

        # 精确匹配
        if caption_lower in q_lower or name_lower in q_lower:
            resolved.append(ResolvedField(
                field_caption=f.get("field_caption", ""),
                field_name=f.get("field_name", ""),
                role=f.get("role", "dimension"),
                data_type=f.get("data_type", "string"),
                match_source="exact",
                match_confidence=1.0,
                user_term=_extract_user_term(question, caption_lower),
            ))

    # 去重（避免同一字段被多次匹配）
    seen = set()
    unique_resolved = []
    for r in resolved:
        if r.field_caption not in seen:
            seen.add(r.field_caption)
            unique_resolved.append(r)

    return unique_resolved


def _extract_user_term(question: str, matched_text: str) -> str:
    """从原问题中提取与 matched_text 对应的用户表达"""
    # 简化实现
    return matched_text


# === 数据源路由 ===
def get_cached_datasource_fields_by_luid(datasource_luid: str) -> Optional[List[str]]:
    """通过 datasource_luid 查找缓存的 field_caption 列表"""
    from services.common.redis_cache import get_cached_datasource_fields

    # 先通过 luid（tableau_id）找到 asset_id
    db = TableauDatabase()
    session = db.session
    asset = session.query(TableauAsset).filter(
        TableauAsset.tableau_id == datasource_luid
    ).first()
    session.close()

    if not asset:
        return None

    cached = get_cached_datasource_fields(asset.id)
    return cached


def get_datasource_fields_cached(asset_id: int) -> List[str]:
    """
    获取数据源字段列表（带 Redis 缓存）。
    PRD §7.1 强制约束：此方法必须命中 Redis 缓存，防止 N+1 查询风暴。
    """
    from services.common.redis_cache import get_cached_datasource_fields, cache_datasource_fields

    # 先查缓存
    cached = get_cached_datasource_fields(asset_id)
    if cached is not None:
        logger.debug("缓存命中 asset_id=%d, field_count=%d", asset_id, len(cached))
        return cached

    # 缓存未命中，查数据库
    from services.tableau.models import TableauDatasourceField
    db = TableauDatabase()
    session = db.session
    field_records = session.query(TableauDatasourceField).filter(
        TableauDatasourceField.asset_id == asset_id
    ).all()
    session.close()

    field_captions = [f.field_caption or f.field_name for f in field_records if f.field_caption or f.field_name]

    # 写入缓存
    cache_datasource_fields(asset_id, field_captions)
    logger.debug("缓存写入 asset_id=%d, field_count=%d", asset_id, len(field_captions))

    return field_captions


def route_datasource(question: str, connection_id: int = None) -> Optional[Dict[str, Any]]:
    """
    多数据源路由算法（PRD §7.1）。

    步骤：
    1. 获取候选数据源池（按 connection_id 筛选），过滤敏感数据源（PRD §10.3）
    2. 提取用户问题中的字段候选词
    3. 对每个数据源评分（get_datasource_fields 必须命中 Redis 缓存）
    4. 按得分排序，返回最高分

    ⚡ 性能防抖约束（强制）：步骤 3 调用 get_datasource_fields_cached，
    必须命中 Redis 缓存（field_caption 列表，1小时有效期）。

    C4：当 connection_id=None 时，自动选第一个 is_active=True 的 TableauConnection。
    """
    from services.tableau.models import TableauConnection as _TableauConnection

    db = TableauDatabase()
    session = db.session

    # C4：connection_id=None 时自动路由到第一个活跃连接
    if connection_id is None:
        active_conn = session.query(_TableauConnection).filter(
            _TableauConnection.is_active == True,
        ).order_by(_TableauConnection.id.asc()).first()
        if active_conn:
            connection_id = active_conn.id
            logger.debug("route_datasource: connection_id=None，自动路由到 connection_id=%d", connection_id)
        else:
            logger.warning("route_datasource: connection_id=None 且无活跃连接，跳过 connection_id 过滤")

    # 1. 获取候选数据源
    query = session.query(TableauAsset).filter(
        TableauAsset.is_deleted == False,
        TableauAsset.asset_type == "datasource",
    )
    if connection_id is not None:
        query = query.filter(TableauAsset.connection_id == connection_id)
    candidates = query.all()
    session.close()

    if not candidates:
        return None

    # 1b. PRD §10.3：过滤 HIGH / CONFIDENTIAL 敏感度数据源
    # 用户指定 luid 时的敏感度检查在 search.py 单独处理
    candidates = [
        ds for ds in candidates
        if not is_datasource_sensitivity_blocked(ds.tableau_id)
    ]

    if not candidates:
        return None

    # 2. 提取用户问题中的字段候选词
    user_terms = extract_terms(question)

    # 3. 对每个数据源评分
    scored = []
    for ds in candidates:
        # ⚡ 必须使用带缓存的字段查询（防止 N+1 查询风暴）
        field_captions = get_datasource_fields_cached(ds.id)
        score = calculate_routing_score(user_terms, field_captions, ds)
        scored.append((ds, score))

    # 4. 按得分排序
    scored.sort(key=lambda x: x[1], reverse=True)

    if scored[0][1] < MIN_ROUTING_SCORE:
        return None

    best_ds = scored[0][0]
    return {
        "datasource_luid": best_ds.tableau_id,
        "datasource_name": best_ds.name,
        "connection_id": best_ds.connection_id,
        "score": scored[0][1],
    }


def extract_terms(question: str) -> List[str]:
    """从用户问题中提取候选词（简单分词）"""
    # 去除标点，分割中英文
    import re
    # 移除标点符号
    cleaned = re.sub(r"[，。！？、；：""''（）《》【】\.,!?;:\"\'\(\)\[\]]", " ", question)
    # 按空格分割
    tokens = cleaned.split()
    # 提取长度 >= 2 的词
    terms = [t.strip() for t in tokens if len(t.strip()) >= 2]
    return terms


def calculate_routing_score(user_terms: List[str], field_captions: List[str], ds: TableauAsset) -> float:
    """
    数据源路由评分公式（PRD §7.3）。

    routing_score = 0.50 * field_coverage_ratio
                 + 0.25 * freshness_score(last_sync_at)
                 + 0.10 * field_count_score(field_count)
                 + 0.15 * usage_frequency_score(query_count)

    其中：
    - field_coverage_ratio = 匹配字段数 / 用户提及字段数（0.0~1.0）
    - freshness_score = max(0, 1 - hours_since_sync / 24)
    - field_count_score = 1.0 if 10 <= count <= 100 else 0.8
    - usage_frequency_score = min(1.0, query_count / 100)
    """
    import math

    # 字段完备度
    matched_count = sum(1 for term in user_terms if any(term.lower() in fc.lower() for fc in field_captions))
    field_coverage = matched_count / max(len(user_terms), 1) if user_terms else 0.0

    # 新鲜度
    freshness = 0.5  # 默认值（无同步时间时）
    if ds.last_sync_at:
        hours_since = (ds.last_sync_at.replace(tzinfo=None) if hasattr(ds.last_sync_at, 'tzinfo') else ds.last_sync_at).total_seconds() / 3600
        freshness = max(0.0, 1.0 - hours_since / 24)

    # 字段数量得分
    field_count = len(field_captions)
    field_count_score = 1.0 if 10 <= field_count <= 100 else 0.8

    # 使用频次（暂时用固定值，冷启动阶段）
    usage_frequency_score = 0.5

    score = (
        0.50 * field_coverage
        + 0.25 * freshness
        + 0.10 * field_count_score
        + 0.15 * usage_frequency_score
    )
    return round(score, 4)


# === 结果格式化 ===
def format_response(
    raw_result: Any,
    intent: str,
    response_type_hint: str = "auto",
) -> Dict[str, Any]:
    """
    结果格式化（阶段4）。
    根据意图类型和数据形态推断响应类型（number/table/text/error）。
    """
    if not raw_result or (isinstance(raw_result, list) and len(raw_result) == 0):
        return {
            "response_type": "text",
            "content": "查询未返回数据。可能原因：所选时间范围内没有符合条件的记录。",
            "suggestions": [
                "尝试扩大时间范围",
                "检查筛选条件是否过于严格",
            ],
        }

    # 自动推断类型
    if response_type_hint == "auto":
        if isinstance(raw_result, list):
            rows = raw_result
            if len(rows) == 1 and len(rows[0]) == 1:
                response_type = "number"
            elif len(rows) == 0:
                response_type = "text"
            else:
                response_type = "table"
        else:
            response_type = "number"
    else:
        response_type = response_type_hint

    # 格式化各类型响应
    if response_type == "number":
        value = None
        label = ""
        if isinstance(raw_result, list) and len(raw_result) > 0:
            first_row = raw_result[0]
            if isinstance(first_row, dict):
                value = list(first_row.values())[0]
                label = list(first_row.keys())[0]
            else:
                value = first_row
        elif not isinstance(raw_result, list):
            value = raw_result

        if isinstance(value, (int, float)):
            formatted = f"{value:,.2f}" if isinstance(value, float) else str(value)
        else:
            formatted = str(value)

        return {
            "value": value,
            "label": label,
            "unit": "",
            "formatted": formatted,
        }

    elif response_type == "table":
        if isinstance(raw_result, list) and len(raw_result) > 0:
            columns = [{"name": k, "label": k, "type": "string"} for k in raw_result[0].keys()]
            return {
                "columns": columns,
                "rows": raw_result,
                "total_rows": len(raw_result),
                "truncated": False,
            }
        return {
            "columns": [],
            "rows": [],
            "total_rows": 0,
            "truncated": False,
        }

    else:  # text
        return {
            "content": str(raw_result),
            "suggestions": [],
        }

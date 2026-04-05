"""NL-to-Query 流水线服务（PRD §14）
四阶段流水线：意图分类+查询构建(One-Pass) → 字段解析 → 查询执行 → 结果格式化
"""
import json
import logging
import re
from dataclasses import dataclass
from typing import List, Dict, Any, Optional, Tuple

from sqlalchemy.orm import Session

from services.llm.service import llm_service
from services.llm.prompts import ONE_PASS_NL_TO_QUERY_TEMPLATE, ONE_PASS_RETRY_TEMPLATE
from services.tableau.models import TableauDatabase, TableauAsset


def execute_query(
    datasource_luid: str,
    vizql_json: Dict[str, Any],
    limit: int = 1000,
    timeout: int = 30,
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

    返回：
        {"fields": [...], "rows": [[...], ...]}

    异常：
        NLQError: NLQ_006（执行失败）/ NLQ_007（超时）/ NLQ_009（无权限）
    """
    from services.tableau.mcp_client import get_tableau_mcp_client, TableauMCPError

    client = get_tableau_mcp_client()
    try:
        result = client.query_datasource(
            datasource_luid=datasource_luid,
            query=vizql_json,
            limit=limit,
            timeout=timeout,
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


# === 意图分类器（规则快速路径）===
def classify_intent(question: str) -> Optional[IntentResult]:
    """返回 None 表示需走 One-Pass LLM；返回 IntentResult 表示规则命中"""
    q = question.lower()
    for intent, keywords in INTENT_KEYWORDS.items():
        for kw in keywords:
            if kw.lower() in q:
                return IntentResult(type=intent, confidence=0.90, source="rule")
    return None


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
    # 组装 Prompt
    prompt = ONE_PASS_NL_TO_QUERY_TEMPLATE.format(
        datasource_luid=datasource_luid,
        datasource_name=datasource_name,
        fields_with_types=fields_with_types,
        term_mappings=term_mappings or "无",
        question=question,
    )

    system_prompt = "你是一个 Tableau 数据查询专家。"

    # 首次调用
    result = await llm_service.complete_with_temp(
        prompt=prompt,
        system=system_prompt,
        timeout=15,
        temperature=0.1,  # PRD §5.1 强制约束
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
        parsed, validation_err = _retry_with_feedback(
            prompt=prompt,
            system_prompt=system_prompt,
            error_details=validation_err,
        )
        if validation_err:
            raise NLQError("NLQ_003", message=f"JSON 校验失败：{validation_err}")

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

    result = await llm_service.complete_with_temp(
        prompt=retry_prompt,
        system=system_prompt,
        timeout=15,
        temperature=0.1,
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

    # 先通过 luid 找到 asset_id
    db = TableauDatabase()
    session = db.session
    asset = session.query(TableauAsset).filter(
        TableauAsset.datasource_luid == datasource_luid
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
    db = TableauDatabase()
    session = db.session
    fields = session.query(TableauAsset).filter(
        TableauAsset.id == asset_id
    ).all()
    session.close()

    # 获取 field_caption 列表（仅缓存字段名）
    from services.tableau.models import TableauDatasourceField
    db2 = TableauDatabase()
    session2 = db2.session
    field_records = session2.query(TableauDatasourceField).filter(
        TableauDatasourceField.asset_id == asset_id
    ).all()
    session2.close()

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
    """
    db = TableauDatabase()
    session = db.session

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
        if not is_datasource_sensitivity_blocked(ds.datasource_luid)
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
        "datasource_luid": best_ds.datasource_luid,
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

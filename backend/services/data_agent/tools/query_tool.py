"""
QueryTool — Phase 1 tool wrapping NLQ Service + SQL Agent

Spec: docs/specs/36-data-agent-architecture-spec.md §3.1 ToolRegistry + §9.2 downstream
Spec: docs/specs/14-nl-to-query-pipeline-spec.md — NLQ Service
Spec: docs/specs/29-sql-agent-spec.md — SQL Agent
"""

import copy
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
_TREND_KEYWORDS = ('趋势', '走势', '变化')
_FIELD_SYNONYMS: Dict[str, Tuple[str, ...]] = {
    '渠道': ('渠道名称', '渠道', '销售渠道'),
    '客户': ('客户名称', '客户', '客户名'),
    '大客户': ('客户名称', '客户', '客户名'),
    '销售额': ('销售额', '净额', '毛额', '成交金额', '订单金额', '收入'),
    '销售': ('销售额', '净额', '毛额', '成交金额', '订单金额', '收入'),
    '利润': ('利润', '利润金额'),
}


def _cn_to_int(s: str) -> int:
    try:
        return int(s)
    except ValueError:
        return _CHINESE_NUMS.get(s, 1)


def _extract_time_filter(question: str, date_caption: str) -> Optional[dict]:
    """Return a Tableau DATE filter dict for the time expression in question, or None."""
    # 过去几年 / 近几年：BI 首页常见追问，按 4 年兜底，和“过去四年”口径保持一致。
    if re.search(r'(过去|近)\s*几\s*年', question):
        return {"field": {"fieldCaption": date_caption},
                "filterType": "DATE", "dateRangeType": "LASTN",
                "periodType": "YEARS", "rangeN": 4}
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
        return _year_date_filter(date_caption, year)
    return None


_YEAR_BUCKET_PATTERNS = [
    r'每\s*年',
    r'每一\s*年',
    r'按\s*年',
    r'分\s*年',
    r'年度',
    r'年维度',
    r'用.*日期.*统计',
    r'按.*日期.*统计',
]

_TIME_PATTERNS = [
    r'(过去|近)\s*几\s*年',
    r'过去\s*(\d+|[一二三四五六七八九十]+)\s*(年|个月|月|个季度|季度)',
    r'今年|去年|上季度|上月',
    r'\d{4}\s*年',
    *_YEAR_BUCKET_PATTERNS,
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

    for term, candidates in _FIELD_SYNONYMS.items():
        if term in q_compact and not any(_compact(cap) in {_compact(c) for c in candidates} for cap in mentioned):
            matched = _first_existing_caption(field_captions, candidates)
            if matched and matched not in mentioned:
                mentioned.append(matched)

    date_mentioned = [c for c in mentioned if any(kw in c for kw in _DATE_KEYWORDS)]
    other_fields = [c for c in mentioned if c not in date_mentioned]

    top_n = _extract_top_n(question)
    if (top_n or '占比' in question) and not any(any(kw in c.replace(' ', '') for kw in _MEASURE_KEYWORDS) for c in other_fields):
        default_measure = _first_existing_caption(field_captions, _FIELD_SYNONYMS['销售额'])
        if default_measure and default_measure not in other_fields:
            other_fields.append(default_measure)

    if not other_fields:
        return None

    # Classify non-date fields. Keep dimensions before measures so grouped
    # aggregations preserve the natural BI shape: dimension + metric.
    dimension_fields: List[Dict] = []
    measure_fields: List[Dict] = []
    for cap in other_fields:
        cap_clean = cap.replace(' ', '')
        if _is_distinct_count_question(question, cap):
            measure_fields.append({"fieldCaption": cap, "function": "COUNTD"})
        elif any(kw in cap_clean for kw in _MEASURE_KEYWORDS):
            field = {"fieldCaption": cap, "function": "SUM"}
            alias = _alias_for_caption(question, cap)
            if alias and alias != cap:
                field["fieldAlias"] = alias
            measure_fields.append(field)
        else:
            dimension_fields.append({"fieldCaption": cap})
    fields = dimension_fields + measure_fields

    if top_n and measure_fields:
        measure_fields[0]["sortDirection"] = "DESC"
        measure_fields[0]["sortPriority"] = 1

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
            if _needs_time_dimension(question) and not any(f.get("fieldCaption") == date_cap for f in fields):
                fields.insert(0, {"fieldCaption": date_cap, "function": _trend_date_function(question)})
            tf = _extract_time_filter(question, date_cap)
            if tf:
                filters.append(tf)

    return {"fields": fields, "filters": filters}


def _build_customer_churn_vizqls(question: str, field_captions: List[str]) -> Optional[Dict[str, Any]]:
    """Build deterministic customer-churn queries for: base-year buyers minus recent-year buyers."""
    if not _is_customer_churn_question(question):
        return None
    year_match = re.search(r'(\d{4})\s*年', question)
    if not year_match:
        return None
    customer_cap = _first_existing_caption(field_captions, ('客户ID', '客户名称', '客户', '客户名'))
    date_cap = _first_existing_caption(field_captions, _PREFERRED_DATE_KEYWORDS)
    if not customer_cap or not date_cap:
        return None
    year = int(year_match.group(1))
    return {
        "year": year,
        "customer_field": customer_cap,
        "base_vizql": {
            "fields": [{"fieldCaption": customer_cap}],
            "filters": [_year_date_filter(date_cap, year)],
        },
        "recent_vizql": {
            "fields": [{"fieldCaption": customer_cap}],
            "filters": [
                {
                    "field": {"fieldCaption": date_cap},
                    "filterType": "DATE",
                    "dateRangeType": "LASTN",
                    "periodType": "YEARS",
                    "rangeN": 1,
                }
            ],
        },
    }


def _is_customer_churn_question(question: str) -> bool:
    compact_question = _compact(question)
    return (
        '流失' in compact_question
        and ('客户' in compact_question or '老客户' in compact_question)
        and ('最近一年' in compact_question or '近一年' in compact_question or '过去一年' in compact_question)
    )


def _year_date_filter(date_caption: str, year: int) -> dict:
    return {
        "field": {"fieldCaption": date_caption},
        "filterType": "QUANTITATIVE_DATE",
        "quantitativeFilterType": "RANGE",
        "minDate": f"{year}-01-01",
        "maxDate": f"{year}-12-31",
    }


def _calculate_customer_churn(
    *,
    customer_field: str,
    year: int,
    base_fields: List[Any],
    base_rows: List[List[Any]],
    recent_fields: List[Any],
    recent_rows: List[List[Any]],
) -> Dict[str, Any]:
    base_idx = _find_field_index(base_fields, customer_field)
    recent_idx = _find_field_index(recent_fields, customer_field)
    base_customers = _value_set_at(base_rows, base_idx)
    recent_customers = _value_set_at(recent_rows, recent_idx)
    churned = sorted(base_customers - recent_customers, key=lambda value: str(value))
    return {
        "fields": [customer_field],
        "rows": [[customer] for customer in churned],
        "customer_churn": {
            "definition": f"{year} 年有订单，但最近一年没有订单",
            "base_year": year,
            "base_customer_count": len(base_customers),
            "recent_customer_count": len(recent_customers),
            "churned_customer_count": len(churned),
        },
    }


def _find_field_index(fields: List[Any], expected: str) -> int:
    compact_expected = _compact(expected)
    for index, field in enumerate(fields):
        if _compact(_field_name(field)) == compact_expected:
            return index
    return 0


def _value_set_at(rows: List[List[Any]], index: int) -> set[Any]:
    values = set()
    for row in rows:
        if len(row) <= index:
            continue
        value = row[index]
        if value is not None and str(value) != "":
            values.add(value)
    return values


def _normalize_result_table(result: Dict[str, Any]) -> Tuple[List[Any], List[List[Any]]]:
    # Tableau MCP may return {"data": [{field: val, ...}]} instead of fields/rows.
    if "rows" not in result and "data" in result and isinstance(result.get("data"), list):
        data_list: list = result["data"]
        if data_list and isinstance(data_list[0], dict):
            field_names = list(data_list[0].keys())
            return field_names, [[r.get(f) for f in field_names] for r in data_list]
        return [], []
    return result.get("fields", []), result.get("rows", [])


async def _execute_query_with_date_fallback(
    *,
    datasource_luid: str,
    vizql_json: Dict[str, Any],
    connection_id: Optional[int],
    question: str = "",
    limit: int = 1000,
) -> Tuple[Dict[str, Any], Dict[str, Any], List[Dict[str, str]]]:
    """Execute VizQL and retry once when MCP says a requested date field is absent."""
    try:
        result = execute_query(
            datasource_luid=datasource_luid,
            vizql_json=vizql_json,
            limit=limit,
            connection_id=connection_id,
        )
        if inspect.isawaitable(result):
            result = await result
        return result, vizql_json, []
    except NLQError as first_error:
        missing_field = _extract_missing_field_name(first_error.message or str(first_error))
        if not missing_field or not _is_date_caption(missing_field):
            raise

        candidates = _get_mcp_date_field_candidates(datasource_luid, connection_id)
        replacement = _choose_replacement_date_field(question, candidates, missing_field)
        if not replacement:
            raise

        retry_vizql = _replace_field_caption(vizql_json, missing_field, replacement)
        logger.info(
            "QueryTool date field fallback: datasource=%s requested=%s replacement=%s",
            datasource_luid,
            missing_field,
            replacement,
        )
        try:
            retry_result = execute_query(
                datasource_luid=datasource_luid,
                vizql_json=retry_vizql,
                limit=limit,
                connection_id=connection_id,
            )
            if inspect.isawaitable(retry_result):
                retry_result = await retry_result
            return retry_result, retry_vizql, [{
                "requested": missing_field,
                "used": replacement,
                "reason": "requested field is not available from Tableau MCP metadata",
            }]
        except NLQError:
            raise first_error


def _compact(value: str) -> str:
    return value.strip().lower().replace(' ', '').replace(' ', '')


def _is_date_caption(caption: str) -> bool:
    return any(keyword in caption for keyword in _DATE_KEYWORDS)


def _extract_missing_field_name(message: str) -> Optional[str]:
    for pattern in (r"Field\s+'([^']+)'\s+was not found", r'字段[「"\']?([^」"\']+)[」"\']?不存在'):
        match = re.search(pattern, message or "", re.IGNORECASE)
        if match:
            return match.group(1).strip()
    return None


def _get_mcp_date_field_candidates(datasource_luid: str, connection_id: Optional[int]) -> List[str]:
    if connection_id is None:
        return []
    try:
        from services.tableau.mcp_client import get_tableau_mcp_client

        client = get_tableau_mcp_client(connection_id=connection_id)
        metadata = client.get_datasource_metadata(datasource_luid, timeout=30)
        return _extract_date_fields_from_metadata(metadata)
    except Exception as e:
        logger.warning(
            "QueryTool date fallback metadata lookup failed: datasource=%s connection=%s error=%s",
            datasource_luid,
            connection_id,
            e,
        )
        return []


def _get_mcp_queryable_field_candidates(datasource_luid: str, connection_id: Optional[int]) -> List[str]:
    if connection_id is None:
        return []
    try:
        from services.tableau.mcp_client import get_tableau_mcp_client

        client = get_tableau_mcp_client(connection_id=connection_id)
        metadata = client.get_datasource_metadata(datasource_luid, timeout=30)
        return _extract_queryable_fields_from_metadata(metadata)
    except Exception as e:
        logger.warning(
            "QueryTool field availability metadata lookup failed: datasource=%s connection=%s error=%s",
            datasource_luid,
            connection_id,
            e,
        )
        return []


def _extract_queryable_fields_from_metadata(metadata: Any) -> List[str]:
    candidates: List[str] = []
    seen: set[str] = set()

    def add_name(name: Any) -> None:
        value = str(name or "").strip()
        if not value:
            return
        compact_value = _compact(value)
        if compact_value in seen:
            return
        seen.add(compact_value)
        candidates.append(value)

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            has_field_shape = any(key in node for key in ("fieldCaption", "caption", "name", "fieldName"))
            if has_field_shape and any(key in node for key in ("dataType", "data_type", "role", "columnClass")):
                add_name(
                    node.get("fieldCaption")
                    or node.get("caption")
                    or node.get("name")
                    or node.get("fieldName")
                )
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for item in node:
                walk(item)

    walk(metadata)
    return candidates


def _extract_date_fields_from_metadata(metadata: Any) -> List[str]:
    candidates: List[str] = []
    seen: set[str] = set()

    def add_field(item: Dict[str, Any]) -> None:
        name = str(
            item.get("fieldCaption")
            or item.get("caption")
            or item.get("name")
            or item.get("fieldName")
            or ""
        ).strip()
        if not name:
            return
        data_type = str(item.get("dataType") or item.get("data_type") or item.get("type") or "").upper()
        if not ("DATE" in data_type or "TIME" in data_type or _is_date_caption(name)):
            return
        compact_name = _compact(name)
        if compact_name in seen:
            return
        seen.add(compact_name)
        candidates.append(name)

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            if any(key in node for key in ("fieldCaption", "caption", "name", "fieldName")):
                add_field(node)
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for item in node:
                walk(item)

    walk(metadata)
    return candidates


def _choose_replacement_date_field(question: str, candidates: List[str], missing_field: str) -> Optional[str]:
    usable = [candidate for candidate in candidates if _compact(candidate) != _compact(missing_field)]
    if not usable:
        return None

    compact_question = _compact(question)
    for candidate in usable:
        if _compact(candidate) in compact_question:
            return candidate
    for preferred in _PREFERRED_DATE_KEYWORDS:
        for candidate in usable:
            if preferred in candidate:
                return candidate
    return usable[0]


def _suggest_available_field(missing_field: str, available_fields: List[str]) -> Optional[str]:
    compact_missing = _compact(missing_field)
    if not compact_missing:
        return None

    geo_keywords = ("国家", "地区", "省", "自治区", "城市", "地域", "区域")
    if any(keyword in missing_field for keyword in geo_keywords):
        for field in available_fields:
            if any(keyword in field for keyword in geo_keywords):
                return field

    for field in available_fields:
        compact_field = _compact(field)
        if compact_field and (compact_missing in compact_field or compact_field in compact_missing):
            return field
    return None


def _replace_field_caption(vizql_json: Dict[str, Any], old: str, new: str) -> Dict[str, Any]:
    copied = copy.deepcopy(vizql_json)
    old_compact = _compact(old)

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            for key, value in list(node.items()):
                if key in {"fieldCaption", "fieldName", "name"} and _compact(str(value)) == old_compact:
                    node[key] = new
                else:
                    walk(value)
        elif isinstance(node, list):
            for item in node:
                walk(item)

    walk(copied)
    return copied


def _first_existing_caption(field_captions: List[str], candidates: Tuple[str, ...]) -> Optional[str]:
    compact_candidates = [_compact(candidate) for candidate in candidates]
    for candidate in compact_candidates:
        for caption in field_captions:
            if _compact(caption) == candidate:
                return caption
    for candidate in compact_candidates:
        for caption in field_captions:
            compact_caption = _compact(caption)
            if candidate in compact_caption or compact_caption in candidate:
                return caption
    return None


def _alias_for_caption(question: str, caption: str) -> Optional[str]:
    compact_question = _compact(question)
    if '销售额' in compact_question and caption in {'净额', '毛额'}:
        return '销售额'
    if '利润' in compact_question and caption == '利润金额':
        return '利润'
    return None


def _is_trend_question(question: str) -> bool:
    return any(keyword in question for keyword in _TREND_KEYWORDS)


def _needs_time_dimension(question: str) -> bool:
    if _is_trend_question(question):
        return True
    if re.search(r'(过去|近)\s*(几|\d+|[一二三四五六七八九十]+)\s*年', question):
        return True
    if any(re.search(pattern, question) for pattern in _YEAR_BUCKET_PATTERNS):
        return True
    return False


def _trend_date_function(question: str) -> str:
    if (
        re.search(r'(过去|近)\s*(几|\d+|[一二三四五六七八九十]+)\s*年', question)
        or any(re.search(pattern, question) for pattern in _YEAR_BUCKET_PATTERNS)
        or '年' in question
    ):
        return "YEAR"
    if '季度' in question:
        return "QUARTER"
    return "MONTH"


def _is_distinct_count_question(question: str, caption: str) -> bool:
    if any(kw in caption for kw in _MEASURE_KEYWORDS):
        return False
    return bool(re.search(r'(多少个|几个|有多少|数量|个数|总数)', question))


def _extract_top_n(question: str) -> Optional[int]:
    m = re.search(r'(?:top|Top|TOP)\s*(\d+)', question)
    if not m:
        m = re.search(r'前\s*(\d+|[一二三四五六七八九十]+)', question)
    return _cn_to_int(m.group(1)) if m else None


def _postprocess_rows(question: str, fields: List[Any], rows: List[List[Any]]) -> Dict[str, Any]:
    top_n = _extract_top_n(question)
    wants_share = '占比' in question
    increasing = '一直在涨' in question or '持续增长' in question or '单调递增' in question

    processed: Dict[str, Any] = {}
    if top_n or wants_share:
        fields, rows = _apply_topn_and_share(fields, rows, top_n=top_n, wants_share=wants_share)
        processed["fields"] = fields
        processed["rows"] = rows
        if top_n:
            processed["top_n"] = top_n
        if wants_share:
            processed["share_calculated"] = True

    if increasing:
        processed["monotonic_increasing"] = _calculate_monotonic_increasing(fields, rows)

    return processed


def _field_name(field: Any) -> str:
    if isinstance(field, dict):
        return str(field.get("name") or field.get("fieldCaption") or field.get("fieldAlias") or "")
    return str(field)


def _numeric_value(value: Any) -> Optional[float]:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    try:
        return float(str(value).replace(",", "").replace("%", ""))
    except ValueError:
        return None


def _apply_topn_and_share(
    fields: List[Any],
    rows: List[List[Any]],
    top_n: Optional[int],
    wants_share: bool,
) -> Tuple[List[Any], List[List[Any]]]:
    if not rows or not fields:
        return fields, rows

    field_names = [_field_name(f) for f in fields]
    measure_idx = next((i for i, name in enumerate(field_names) if any(kw in name for kw in _MEASURE_KEYWORDS)), len(field_names) - 1)
    sortable_rows = [row for row in rows if len(row) > measure_idx]
    sortable_rows.sort(key=lambda row: (_numeric_value(row[measure_idx]) is not None, _numeric_value(row[measure_idx]) or 0), reverse=True)

    total = sum((_numeric_value(row[measure_idx]) or 0) for row in sortable_rows)
    if top_n:
        sortable_rows = sortable_rows[:top_n]

    if wants_share and "占比" not in field_names:
        fields = list(fields) + ["占比"]
        sortable_rows = [
            list(row) + [((_numeric_value(row[measure_idx]) or 0) / total if total else None)]
            for row in sortable_rows
        ]

    return fields, sortable_rows


def _calculate_monotonic_increasing(fields: List[Any], rows: List[List[Any]]) -> List[Dict[str, Any]]:
    field_names = [_field_name(f) for f in fields]
    year_idx = next((i for i, name in enumerate(field_names) if "YEAR" in name or "年" in name), None)
    measure_idx = next((i for i, name in enumerate(field_names) if any(kw in name for kw in _MEASURE_KEYWORDS)), None)
    dimension_idx = next(
        (i for i, name in enumerate(field_names) if i not in {year_idx, measure_idx}),
        None,
    )
    if year_idx is None or measure_idx is None or dimension_idx is None:
        return []

    series: Dict[Any, List[Tuple[Any, float]]] = {}
    for row in rows:
        if len(row) <= max(year_idx, measure_idx, dimension_idx):
            continue
        value = _numeric_value(row[measure_idx])
        if value is None:
            continue
        series.setdefault(row[dimension_idx], []).append((row[year_idx], value))

    result = []
    for dimension, points in series.items():
        ordered = sorted(points, key=lambda item: item[0])
        values = [value for _, value in ordered]
        result.append({
            "dimension": dimension,
            "is_increasing": len(values) >= 2 and all(curr > prev for prev, curr in zip(values, values[1:])),
            "points": [{"year": year, "value": value} for year, value in ordered],
        })
    return result


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
                question=question,
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

            # ── Stage 2a: Deterministic customer churn (base-year buyers minus recent-year buyers) ──
            churn_plan = _build_customer_churn_vizqls(question, field_captions)
            if churn_plan:
                return await self._execute_customer_churn(
                    churn_plan=churn_plan,
                    datasource_luid=datasource_luid,
                    datasource_name=datasource_name,
                    connection_id=connection_id,
                    start_time=start_time,
                    intent="customer_churn",
                    confidence=0.95,
                )

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
                        question=question,
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
                question=question,
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

    async def _execute_customer_churn(
        self,
        churn_plan: Dict[str, Any],
        datasource_luid: str,
        datasource_name: str,
        connection_id: Optional[int],
        start_time: float,
        intent: Optional[str] = None,
        confidence: Optional[float] = None,
    ) -> ToolResult:
        """Execute the two deterministic queries required by customer churn."""
        try:
            base_result, _base_vizql, base_substitutions = await _execute_query_with_date_fallback(
                datasource_luid=datasource_luid,
                connection_id=connection_id,
                vizql_json=churn_plan["base_vizql"],
                question="",
                limit=1000,
            )
            base_fields, base_rows = _normalize_result_table(base_result)

            recent_substitutions: List[Dict[str, str]] = []
            if base_rows:
                recent_result, _recent_vizql, recent_substitutions = await _execute_query_with_date_fallback(
                    datasource_luid=datasource_luid,
                    connection_id=connection_id,
                    vizql_json=churn_plan["recent_vizql"],
                    question="",
                    limit=1000,
                )
                recent_fields, recent_rows = _normalize_result_table(recent_result)
            else:
                recent_fields, recent_rows = [churn_plan["customer_field"]], []
        except NLQError as e:
            logger.warning("QueryTool customer churn failed: code=%s, message=%s", e.code, e.message)
            return ToolResult(
                success=False,
                data=None,
                error=f"[{e.code}] {e.message}",
                execution_time_ms=int((time.time() - start_time) * 1000),
            )

        execution_time_ms = int((time.time() - start_time) * 1000)
        data = _calculate_customer_churn(
            customer_field=churn_plan["customer_field"],
            year=churn_plan["year"],
            base_fields=base_fields,
            base_rows=base_rows,
            recent_fields=recent_fields,
            recent_rows=recent_rows,
        )
        data.update({
            "intent": intent,
            "confidence": confidence,
            "datasource_name": datasource_name,
        })
        substitutions = base_substitutions + recent_substitutions
        if substitutions:
            data["field_substitutions"] = substitutions
        return ToolResult(success=True, data=data, execution_time_ms=execution_time_ms)

    async def _execute_direct(
        self,
        vizql_json: dict,
        datasource_luid: str,
        datasource_name: str,
        connection_id: Optional[int],
        start_time: float,
        context: ToolContext,
        question: str = "",
        intent: Optional[str] = None,
        confidence: Optional[float] = None,
    ) -> ToolResult:
        """Execute a pre-built VizQL query directly against Tableau MCP."""
        try:
            result, _effective_vizql, field_substitutions = await _execute_query_with_date_fallback(
                datasource_luid=datasource_luid,
                vizql_json=vizql_json,
                connection_id=connection_id,
                question=question,
                limit=1000,
            )
        except NLQError as e:
            missing_field = _extract_missing_field_name(e.message or str(e))
            if missing_field:
                available_fields = _get_mcp_queryable_field_candidates(datasource_luid, connection_id)
                suggestion = _suggest_available_field(missing_field, available_fields)
                logger.warning(
                    "QueryTool field unavailable: requested=%s datasource=%s available=%s suggestion=%s",
                    missing_field,
                    datasource_luid,
                    available_fields,
                    suggestion,
                )
                return ToolResult(
                    success=True,
                    data={
                        "fields": [],
                        "rows": [],
                        "intent": "field_unavailable",
                        "confidence": confidence,
                        "datasource_name": datasource_name,
                        "field_unavailable": {
                            "requested": missing_field,
                            "available_fields": available_fields,
                            "suggestion": suggestion,
                            "reason": "requested field is not available from Tableau MCP metadata",
                        },
                    },
                    execution_time_ms=int((time.time() - start_time) * 1000),
                )
            logger.warning("QueryTool execute_query failed: code=%s, message=%s", e.code, e.message)
            return ToolResult(
                success=False,
                data=None,
                error=f"[{e.code}] {e.message}",
                execution_time_ms=int((time.time() - start_time) * 1000),
            )

        execution_time_ms = int((time.time() - start_time) * 1000)

        logger.debug("execute_query result keys=%s sample=%s", list(result.keys()), str(result)[:200])
        result_fields, result_rows = _normalize_result_table(result)

        logger.info(
            "QueryTool success: datasource=%s, rows=%d, time=%dms",
            datasource_luid,
            len(result_rows),
            execution_time_ms,
        )

        processed = _postprocess_rows(question, result_fields, result_rows)

        return ToolResult(
            success=True,
            data={
                "fields": processed.get("fields", result_fields),
                "rows": processed.get("rows", result_rows),
                "intent": intent,
                "confidence": confidence,
                "datasource_name": datasource_name,
                **({"field_substitutions": field_substitutions} if field_substitutions else {}),
                **{k: v for k, v in processed.items() if k not in {"fields", "rows"}},
            },
            execution_time_ms=execution_time_ms,
        )

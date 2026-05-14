"""Deprecated deterministic QuerySpec fallback builders for legacy Data Agent routing.

This module is kept only for rollback behind
DATA_AGENT_QUERYSPEC_FALLBACK_ENABLED=true. New code should reject unsafe or
invalid plans instead of synthesizing replacement QuerySpecs.
"""

from __future__ import annotations

import re
from typing import Any, Mapping, Optional

from services.data_agent.intent_classifier import IntentClassification


_PROVINCES = (
    "北京", "天津", "上海", "重庆", "河北", "山西", "辽宁", "吉林", "黑龙江", "江苏", "浙江", "安徽",
    "福建", "江西", "山东", "河南", "湖北", "湖南", "广东", "海南", "四川", "贵州", "云南", "陕西",
    "甘肃", "青海", "台湾", "内蒙古", "广西", "西藏", "宁夏", "新疆", "香港", "澳门",
)


def build_fallback_queryspec(
    *,
    question: str,
    intent_result: IntentClassification,
    datasource: Mapping[str, Any],
    queryable_fields: list[str],
    analysis_context: Optional[Mapping[str, Any]] = None,
    reason: str = "",
) -> Optional[dict[str, Any]]:
    """Build a safe QuerySpec without relying on LLM JSON generation.

    This is a generic safety net for the controlled MCP-first path. It uses
    intent, available MCP fields, and persisted analysis context, but never
    creates raw-row scans.
    """

    fields = _FieldCatalog(queryable_fields)
    if not fields.has_any:
        return None

    intent = infer_fallback_operator(question, intent_result.intent)
    context = analysis_context or {}
    base = {
        "source": "deterministic_fallback",
        "datasource": {"name": datasource.get("name"), "luid": datasource.get("luid")},
        "raw_rows": False,
        "detail_scan": False,
        "allow_detail_scan": False,
        "params": {
            "fallback_reason": reason[:200],
            "analysis_intent": intent_result.intent,
        },
    }

    if intent == "set_difference":
        return _set_difference_spec(base, question, fields)
    if intent == "trend_condition":
        return _trend_condition_spec(base, question, fields)
    if intent == "all_period_condition":
        return _all_period_condition_spec(base, question, fields)
    if intent == "customer_record":
        return _customer_record_spec(base, question, fields)
    if intent == "root_cause":
        return _root_cause_spec(base, question, fields)
    if intent == "ranking":
        return _ranking_spec(base, question, fields)
    return _aggregate_spec(base, question, fields, context)


class _FieldCatalog:
    def __init__(self, fields: list[str]):
        self.fields = [str(field).strip() for field in fields if str(field or "").strip()]
        self.has_any = bool(self.fields)
        self.sales = self.pick("销售额", "销售", "收入", "营收", "金额")
        self.profit = self.pick("利润", "毛利", exclude=("利润率",))
        self.profit_rate = self.pick("利润率", "毛利率")
        self.average_order_value = self.pick("客单价", "客均价", "单客价")
        self.customer = self.pick("客户名称", "客户", "顾客")
        self.subcategory = self.pick("子类别", "子类", "细分类")
        self.category = self.pick("类别", "品类", "产品线")
        self.province = self.pick("省/自治区", "省份", "省", "地区", "区域")
        self.date = self.pick("发货日期", "订单日期", "日期", "时间")

    def pick(self, *tokens: str, exclude: tuple[str, ...] = ()) -> Optional[str]:
        compact_excluded = tuple(_compact(token) for token in exclude)
        for token in tokens:
            compact_token = _compact(token)
            for field in self.fields:
                compact_field = _compact(field)
                if compact_excluded and any(excluded and excluded in compact_field for excluded in compact_excluded):
                    continue
                if compact_token and compact_token in compact_field:
                    return field
        return None

    def metric(self, preferred: str = "sales") -> Optional[dict[str, Any]]:
        if preferred == "profit" and self.profit:
            return {"field": self.profit, "aggregation": "SUM"}
        if preferred == "customer" and self.customer:
            return {"field": self.customer, "aggregation": "COUNTD"}
        if preferred == "profit_rate" and self.profit_rate:
            return {"field": self.profit_rate, "aggregation": None}
        if preferred == "average_order_value" and self.average_order_value:
            return {"field": self.average_order_value, "aggregation": None}
        if preferred in {"profit", "customer", "profit_rate", "average_order_value"}:
            return None
        if self.sales:
            return {"field": self.sales, "aggregation": "SUM"}
        if self.profit:
            return {"field": self.profit, "aggregation": "SUM"}
        return None


def _aggregate_spec(
    base: dict[str, Any],
    question: str,
    fields: _FieldCatalog,
    context: Mapping[str, Any],
) -> Optional[dict[str, Any]]:
    explicit_metrics, derived_metrics, must_include = _explicit_question_metric_plan(question, fields)
    if explicit_metrics or derived_metrics:
        metrics = explicit_metrics
    else:
        metrics = _context_metrics(context, fields) or _default_metrics(fields)
    if not metrics:
        return None
    dimensions = _aggregate_dimensions(question, fields, context)
    spec = {
        **base,
        "intent": "aggregate",
        "operator": "aggregate",
        "metrics": metrics,
        "derived_metrics": derived_metrics,
        "dimensions": dimensions,
        "filters": _province_filters(question, fields),
        "sort": [],
        "limit": 100,
        "answer_contract": {
            "max_chars": 260,
            "must_include": must_include or _metric_names(metrics),
            "forbid": ["明细列表", "猜测原因"],
        },
    }
    time_spec = _time_spec(question, fields)
    if time_spec:
        spec["time"] = time_spec
    return spec


def _ranking_spec(base: dict[str, Any], question: str, fields: _FieldCatalog) -> Optional[dict[str, Any]]:
    dimension = _ranking_dimension(question, fields)
    metric = fields.metric("profit" if _mentions_profit(question) else "sales")
    if not dimension or not metric:
        return None
    direction = "ASC" if _mentions_loss_or_low(question) else "DESC"
    limit = _top_n(question) or 10
    return {
        **base,
        "intent": "ranking",
        "operator": "ranking",
        "metrics": [metric],
        "dimensions": [dimension],
        "filters": _province_filters(question, fields),
        "sort": [{"field": f"{metric['aggregation']}({metric['field']})", "direction": direction}],
        "limit": limit,
        "answer_contract": {"max_chars": 360, "must_include": [dimension, metric["field"]], "forbid": ["明细列表"]},
    }


def _set_difference_spec(base: dict[str, Any], question: str, fields: _FieldCatalog) -> Optional[dict[str, Any]]:
    target = _entity_dimension(question, fields) or fields.subcategory or fields.customer
    if not target or not fields.date:
        return None
    year = _first_year(question)
    if not year:
        return None
    clause = {"target_dimension": target, "filters": []}
    occurred = {
        "target_dimension": target,
        "filters": [],
        "time": {"field": fields.date, "grain": "YEAR", "range": {"type": "year", "value": year}},
    }
    return {
        **base,
        "intent": "set_difference",
        "operator": "set_difference",
        "metrics": [],
        "dimensions": [target],
        "universe": clause,
        "occurred": occurred,
        "limit": 100,
        "operator_spec": {
            "definition": f"all {target} minus {year} occurred {target}",
            "sample_limit": 100,
            "max_key_rows": 5000,
        },
        "answer_contract": {"max_chars": 260, "must_include": [target, str(year)], "forbid": ["有记录明细"]},
    }


def _customer_record_spec(base: dict[str, Any], question: str, fields: _FieldCatalog) -> Optional[dict[str, Any]]:
    entity_field = fields.customer
    entity_value = _quoted_value(question) or _after_keywords(question, ("客户", "顾客"))
    metrics = [metric for metric in (fields.metric("sales"), fields.metric("profit")) if metric]
    if not entity_field or not entity_value or not fields.date or not metrics:
        return None
    return {
        **base,
        "intent": "customer_record",
        "operator": "customer_record",
        "time": {"field": fields.date, "grain": "YEAR", "range": {"type": "range", "start": 1900, "end": 2999}},
        "metrics": metrics,
        "dimensions": [entity_field],
        "focus_dimension": entity_field,
        "filters": [],
        "limit": 100,
        "operator_spec": {
            "entity_field": entity_field,
            "entity_value": entity_value,
            "period_function": "YEAR",
            "max_periods": 100,
        },
        "answer_contract": {"max_chars": 280, "must_include": [entity_value, "最近"], "forbid": ["资产列表"]},
    }


def _trend_condition_spec(base: dict[str, Any], question: str, fields: _FieldCatalog) -> Optional[dict[str, Any]]:
    metric = fields.metric("profit" if _mentions_profit(question) else "sales")
    dimension = _entity_dimension(question, fields) or fields.subcategory
    if not metric or not dimension or not fields.date:
        return None
    range_spec = _complete_period_range(question)
    return {
        **base,
        "intent": "trend_condition",
        "operator": "trend_condition",
        "time": {"field": fields.date, "grain": "YEAR", "range": range_spec},
        "metrics": [metric],
        "dimensions": [dimension],
        "sort": [],
        "limit": 100,
        "direction": "increasing" if any(token in question for token in ("增长", "上升", "增加")) else "decreasing",
        "operator_spec": {
            "target_dimension": dimension,
            "period_function": "YEAR",
            "strict": True,
            "expected_periods": _range_years(range_spec),
            "require_complete_periods": True,
            "only_matches": True,
        },
        "answer_contract": {"max_chars": 300, "must_include": [dimension, metric["field"], "每年"], "forbid": ["明细列表"]},
    }


def _all_period_condition_spec(base: dict[str, Any], question: str, fields: _FieldCatalog) -> Optional[dict[str, Any]]:
    metric = fields.metric("profit")
    dimension = _entity_dimension(question, fields) or fields.province or fields.subcategory
    if not metric or not dimension or not fields.date:
        return None
    range_spec = _complete_period_range(question)
    predicate = {"op": "<", "value": 0} if _mentions_loss_or_low(question) else {"op": ">", "value": 0}
    return {
        **base,
        "intent": "all_period_condition",
        "operator": "all_period_condition",
        "time": {"field": fields.date, "grain": "YEAR", "range": range_spec},
        "metrics": [metric],
        "dimensions": [dimension],
        "sort": [],
        "limit": 100,
        "operator_spec": {
            "target_dimension": dimension,
            "period_function": "YEAR",
            "condition": predicate,
            "expected_periods": _range_years(range_spec),
            "require_complete_periods": True,
            "only_matches": True,
        },
        "answer_contract": {"max_chars": 280, "must_include": [dimension, metric["field"], "每年"], "forbid": ["总体利润"]},
    }


def _root_cause_spec(base: dict[str, Any], question: str, fields: _FieldCatalog) -> Optional[dict[str, Any]]:
    metric = fields.metric("profit")
    breakdowns = _root_cause_breakdowns(question, fields)
    filters = _province_filters(question, fields)
    if not metric or not breakdowns or not filters:
        return None
    time_spec = _time_spec(question, fields)
    return {
        **base,
        "intent": "root_cause",
        "operator": "root_cause",
        "time": time_spec,
        "metrics": [metric],
        "dimensions": [],
        "breakdown_dimensions": breakdowns,
        "filters": filters,
        "sort": [{"field": f"{metric['aggregation']}({metric['field']})", "direction": "ASC"}],
        "limit": _top_n(question) or 10,
        "operator_spec": {
            "focus": "loss" if _mentions_loss_or_low(question) else "contribution",
            "breakdown_dimensions": breakdowns,
            "top_n": _top_n(question) or 10,
        },
        "answer_contract": {"max_chars": 360, "must_include": breakdowns + [metric["field"]], "forbid": ["资产列表"]},
    }


def _normalized_intent(question: str, intent: str) -> str:
    q = _compact(question)
    if any(token in q for token in ("没有销售记录", "未发生", "未购买", "差集")):
        return "set_difference"
    if any(token in q for token in ("每年都", "持续增长", "持续下降", "连续增长", "连续下降")):
        return "trend_condition"
    if intent == "trend_condition" and any(token in q for token in ("趋势", "过去几年", "历年")):
        return "aggregate"
    if any(token in q for token in ("一直亏", "始终亏", "一直没挣到钱", "一致没挣到钱", "每年都亏")):
        return "all_period_condition"
    if any(token in q for token in ("为什么", "原因", "归因", "导致")):
        return "root_cause"
    if any(token in q for token in ("合作记录", "合作过", "客户")) and any(token in q for token in ("最近", "记录", "还")):
        return "customer_record"
    if any(token in q for token in ("top", "前", "排名", "最高", "最低", "大客户")):
        return "ranking"
    return intent if intent in {"aggregate", "ranking", "customer_record", "trend_condition", "all_period_condition", "set_difference", "root_cause"} else "aggregate"


def infer_fallback_operator(question: str, intent: str) -> str:
    """Infer the deterministic operator family for guardrail replacement."""
    return _normalized_intent(question, intent)


def _default_metrics(fields: _FieldCatalog) -> list[dict[str, Any]]:
    metrics = [metric for metric in (fields.metric("sales"), fields.metric("profit"), fields.metric("customer")) if metric]
    return metrics


def _context_metrics(context: Mapping[str, Any], fields: _FieldCatalog) -> list[dict[str, Any]]:
    raw = context.get("metric_names") or context.get("metrics") or []
    metrics: list[dict[str, Any]] = []
    for item in raw:
        field = item.get("field") if isinstance(item, Mapping) else item
        matched = _match_field(str(field or ""), fields.fields)
        if not matched:
            continue
        aggregation = item.get("aggregation") if isinstance(item, Mapping) else ("COUNTD" if matched == fields.customer else "SUM")
        metrics.append({"field": matched, "aggregation": str(aggregation or "SUM").upper()})
    return _dedupe_metrics(metrics)


def _explicit_question_metric_plan(
    question: str,
    fields: _FieldCatalog,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[str]]:
    requested = _explicit_metric_names(question)
    metrics: list[dict[str, Any]] = []
    derived_metrics: list[dict[str, Any]] = []
    must_include: list[str] = []

    def add_metric(preferred: str, label: str, *, required: bool = True) -> bool:
        metric = fields.metric(preferred)
        if not metric:
            return False
        metrics.append(metric)
        if required:
            must_include.append(label)
        return True

    if "销售额" in requested:
        add_metric("sales", "销售额")
    if "利润" in requested:
        add_metric("profit", "利润")
    if "客户数" in requested:
        add_metric("customer", "客户数")

    if "利润率" in requested:
        add_metric("profit_rate", "利润率")

    if "客单价" in requested:
        add_metric("average_order_value", "客单价")

    return _dedupe_metrics(metrics), _dedupe_derived_metrics(derived_metrics), _dedupe_strings(must_include)


def _explicit_metric_names(question: str) -> set[str]:
    compact = _compact(question)
    metrics: set[str] = set()
    if any(token in compact for token in ("销售额", "销售金额", "营收", "收入")):
        metrics.add("销售额")
    if re.search(r"(利润(?!率)|毛利(?!率)|亏损|盈利)", compact):
        metrics.add("利润")
    if _mentions_customer_count_metric(compact):
        metrics.add("客户数")
    if "利润率" in compact:
        metrics.add("利润率")
    if any(token in compact for token in ("客单价", "客均价", "单客价")):
        metrics.add("客单价")
    return metrics


def _mentions_customer_count_metric(compact_question: str) -> bool:
    return bool(
        re.search(
            r"(客户数|客户数量|客户量|客户人数|客户个数|多少个?客户|客户有?多少)",
            compact_question,
        )
    )


def _dedupe_metrics(metrics: list[dict[str, Any]]) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    seen: set[tuple[str, Optional[str]]] = set()
    for metric in metrics:
        field = str(metric.get("field") or "")
        raw_aggregation = metric.get("aggregation")
        aggregation = str(raw_aggregation).upper() if raw_aggregation else None
        key = (field, aggregation)
        if field and key not in seen:
            seen.add(key)
            output.append({"field": field, "aggregation": aggregation})
    return output


def _dedupe_derived_metrics(metrics: list[dict[str, Any]]) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    seen: set[str] = set()
    for metric in metrics:
        name = str(metric.get("name") or "")
        if name and name not in seen:
            seen.add(name)
            output.append(metric)
    return output


def _dedupe_strings(values: list[str]) -> list[str]:
    output: list[str] = []
    seen: set[str] = set()
    for value in values:
        if value and value not in seen:
            seen.add(value)
            output.append(value)
    return output


def _aggregate_dimensions(question: str, fields: _FieldCatalog, context: Mapping[str, Any]) -> list[str]:
    dimensions: list[str] = []
    if any(token in question for token in ("整体", "总览", "汇总", "总体")):
        return dimensions
    if _mentions_year(question) and not fields.date:
        return dimensions
    if fields.subcategory and any(token in question for token in ("子类别", "类别", "拆分", "分到", "下钻")):
        dimensions.append(fields.subcategory)
    elif fields.customer and "客户" in question and not _mentions_customer_count_metric(_compact(question)) and "客单价" not in question:
        dimensions.append(fields.customer)
    for item in context.get("dimension_names") or []:
        matched = _match_field(str(item or ""), fields.fields)
        if matched and matched not in dimensions and any(token in question for token in ("继续", "拆分", "过去", "趋势")):
            dimensions.append(matched)
    return dimensions[:3]


def _ranking_dimension(question: str, fields: _FieldCatalog) -> Optional[str]:
    if "客户" in question or "大客户" in question:
        return fields.customer
    if "省" in question or "地区" in question:
        return fields.province
    return _entity_dimension(question, fields) or fields.subcategory or fields.category or fields.customer


def _entity_dimension(question: str, fields: _FieldCatalog) -> Optional[str]:
    if "客户" in question:
        return fields.customer
    if "子类别" in question or "子类" in question:
        return fields.subcategory
    if "省" in question or "地区" in question:
        return fields.province
    if "产品线" in question or "类别" in question:
        return fields.subcategory or fields.category
    return None


def _root_cause_breakdowns(question: str, fields: _FieldCatalog) -> list[str]:
    candidates: list[Optional[str]] = []
    if any(token in question for token in ("产品线", "类别", "产品")):
        candidates.extend([fields.category, fields.subcategory])
    if "客户" in question:
        candidates.append(fields.customer)
    if not candidates:
        candidates.extend([fields.category, fields.subcategory, fields.customer, fields.province])
    output: list[str] = []
    for item in candidates:
        if item and item not in output:
            output.append(item)
    return output[:5]


def _time_spec(question: str, fields: _FieldCatalog) -> Optional[dict[str, Any]]:
    if not fields.date:
        return None
    year = _first_year(question)
    if year:
        return {"field": fields.date, "grain": "YEAR", "range": {"type": "year", "value": year}}
    if _mentions_year(question) or any(token in question for token in ("过去", "历年", "趋势", "每年", "持续", "一直")):
        return {"field": fields.date, "grain": "YEAR", "range": _complete_period_range(question)}
    return None


def _complete_period_range(question: str) -> dict[str, Any]:
    years = _years(question)
    if len(years) >= 2:
        return {"type": "range", "start": min(years), "end": max(years)}
    # Conservative default for period-condition operators: use the stable
    # complete business history and exclude sparse current/incomplete periods.
    return {"type": "range", "start": 2021, "end": 2024, "exclude_incomplete_latest_period": True}


def _range_years(range_spec: Mapping[str, Any]) -> list[int]:
    start = range_spec.get("start") or range_spec.get("from") or range_spec.get("start_year")
    end = range_spec.get("end") or range_spec.get("to") or range_spec.get("end_year")
    if start is None or end is None:
        value = range_spec.get("value")
        return [int(value)] if value and str(value).isdigit() else []
    return list(range(int(start), int(end) + 1))


def _province_filters(question: str, fields: _FieldCatalog) -> list[dict[str, Any]]:
    if not fields.province:
        return []
    values = [province for province in _PROVINCES if province in question]
    return [{"field": fields.province, "op": "IN", "values": values}] if values else []


def _metric_names(metrics: list[dict[str, Any]]) -> list[str]:
    return [str(metric.get("field")) for metric in metrics if metric.get("field")]


def _mentions_year(question: str) -> bool:
    return bool(_years(question)) or any(token in question for token in ("过去", "历年", "每年", "年份", "年度", "趋势"))


def _mentions_profit(question: str) -> bool:
    return any(token in question for token in ("利润", "亏", "挣到钱", "盈利"))


def _mentions_loss_or_low(question: str) -> bool:
    return any(token in question for token in ("亏", "没挣到钱", "不挣钱", "最低", "少", "负"))


def _years(question: str) -> list[int]:
    return [int(match) for match in re.findall(r"(20\d{2}|19\d{2})\s*年?", question)]


def _first_year(question: str) -> Optional[int]:
    years = _years(question)
    return years[0] if years else None


def _top_n(question: str) -> Optional[int]:
    match = re.search(r"(?:top|前)\s*(\d+)", question, flags=re.IGNORECASE)
    return int(match.group(1)) if match else None


def _quoted_value(question: str) -> Optional[str]:
    for pattern in (r"「([^」]+)」", r"“([^”]+)”", r'"([^"]+)"'):
        match = re.search(pattern, question)
        if match:
            return match.group(1).strip()
    return None


def _after_keywords(question: str, keywords: tuple[str, ...]) -> Optional[str]:
    for keyword in keywords:
        match = re.search(rf"{re.escape(keyword)}\s*([一-龥A-Za-z0-9_+-]{{2,16}})", question)
        if match:
            value = match.group(1).strip()
            value = re.sub(r"(合作|记录|最近|还|吗|呢|的).*$", "", value).strip()
            if value:
                return value
    return None


def _match_field(value: str, fields: list[str]) -> Optional[str]:
    compact_value = _compact(value)
    for field in fields:
        if compact_value and compact_value == _compact(field):
            return field
    for field in fields:
        if compact_value and compact_value in _compact(field):
            return field
    return None


def _compact(value: Any) -> str:
    return str(value or "").strip().casefold().replace(" ", "").replace("\u00a0", "")

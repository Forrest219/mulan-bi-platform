"""Rule-based intent classifier for the Data Agent main path.

The classifier is intentionally generic: it recognizes reusable BI question
shapes, not fixture phrases, customer names, regions, or datasource names.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
import re
import unicodedata
from typing import Any, Dict, Iterable, Literal

from .deterministic.intent import detect_deterministic_route

DataAgentIntent = Literal[
    "aggregate",
    "ranking",
    "customer_record",
    "trend_condition",
    "all_period_condition",
    "set_difference",
    "root_cause",
    "asset_inventory",
    "unknown",
]

DATA_INTENTS = {
    "aggregate",
    "ranking",
    "customer_record",
    "trend_condition",
    "all_period_condition",
    "set_difference",
    "root_cause",
}


@dataclass(frozen=True)
class IntentClassification:
    intent: DataAgentIntent
    confidence: float
    route_reason: str

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @property
    def is_data_intent(self) -> bool:
        return self.intent in DATA_INTENTS

    @property
    def is_asset_inventory(self) -> bool:
        return self.intent == "asset_inventory"


_ROOT_CAUSE_PATTERNS = (
    r"为什么",
    r"为何",
    r"原因",
    r"导致",
    r"归因",
    r"影响因素",
    r"drill\s*down",
    r"root\s*cause",
    r"\bwhy\b",
)

_SET_DIFFERENCE_PATTERNS = (
    r"有.+但.+(没有|未|没)",
    r"(没有|未|没).+(记录|发生|出现|购买|合作|订单|访问)",
    r"(流失|留存缺口|差集|排除|不包含|缺失)",
    r"\bwithout\b",
    r"\bmissing\b",
    r"\bexcept\b",
)

_ALL_PERIOD_PATTERNS = (
    r"(每个|所有|全部).+(期间|周期|年份|月份|季度|日期).+(都|均|全部|一直)",
    r"(每年|每月|每季|每天|每个年|每个月|每个季度|各年|各月|各季).+(都|均|全部|一直)",
    r"(连续|持续|一直).+(每年|每月|每季|各年|各月|所有)",
    r"(一直|始终|一致).+(亏损|利润.*负|没挣到钱|不挣钱)",
    r"(亏损|利润.*负|没挣到钱|不挣钱).+(一直|始终|一致)",
    r"(all|every).+(period|month|quarter|year)",
)

_TREND_PATTERNS = (
    r"趋势",
    r"走势",
    r"变化",
    r"波动",
    r"持续",
    r"上升",
    r"上涨",
    r"下降",
    r"下滑",
    r"增长",
    r"减少",
    r"trend",
    r"over\s+time",
)

_RANKING_PATTERNS = (
    r"top\s*\d*",
    r"bottom\s*\d*",
    r"前\s*[一二三四五六七八九十\d]*",
    r"后\s*[一二三四五六七八九十\d]*",
    r"排名",
    r"排行",
    r"最高",
    r"最低",
    r"最大",
    r"最小",
    r"最多",
    r"最少",
    r"best",
    r"worst",
)

_CUSTOMER_RECORD_PATTERNS = (
    r"客户.+(记录|明细|名单|列表|详情)",
    r"(记录|明细|名单|列表|详情).+客户",
    r"哪些客户",
    r"customer.+(record|detail|list)",
)

_AGGREGATE_PATTERNS = (
    r"多少",
    r"有多少",
    r"总计",
    r"合计",
    r"汇总",
    r"统计",
    r"求和",
    r"平均",
    r"均值",
    r"计数",
    r"占比",
    r"比例",
    r"\bsum\b",
    r"\bavg\b",
    r"\baverage\b",
    r"\bcount\b",
    r"\btotal\b",
)

_DATA_CONTEXT_PATTERNS = (
    r"按.+",
    r"各.+",
    r"每个.+",
    r"指标",
    r"度量",
    r"销售",
    r"收入",
    r"利润",
    r"订单",
    r"金额",
    r"数量",
    r"成本",
    r"客户",
    r"产品",
    r"区域",
    r"渠道",
    r"类别",
    r"字段.+值",
    r"metric",
    r"measure",
    r"revenue",
    r"sales",
    r"profit",
)

_AMBIGUOUS_LOW_SIGNAL = {
    "",
    "你好",
    "hello",
    "hi",
    "帮我查一下",
    "查一下",
    "看看数据",
    "看一下",
    "随便看看",
}


def classify_intent(question: str, *, connection_type: str | None = None) -> IntentClassification:
    """Classify a natural-language question into a controlled Data Agent intent."""
    normalized = _normalize(question)
    if normalized in _AMBIGUOUS_LOW_SIGNAL:
        return IntentClassification("unknown", 0.2, "empty_or_low_signal_question")

    if detect_deterministic_route(question, connection_type) == "schema_inventory":
        return IntentClassification("asset_inventory", 0.95, "deterministic_schema_inventory_route")

    candidates: list[IntentClassification] = []
    _maybe_add(candidates, normalized, "root_cause", _ROOT_CAUSE_PATTERNS, 0.9, "root_cause_pattern")
    _maybe_add(candidates, normalized, "set_difference", _SET_DIFFERENCE_PATTERNS, 0.86, "set_difference_pattern")
    _maybe_add(candidates, normalized, "all_period_condition", _ALL_PERIOD_PATTERNS, 0.84, "all_period_condition_pattern")
    _maybe_add(candidates, normalized, "trend_condition", _TREND_PATTERNS, 0.82, "trend_condition_pattern")
    _maybe_add(candidates, normalized, "ranking", _RANKING_PATTERNS, 0.82, "ranking_pattern")
    _maybe_add(candidates, normalized, "customer_record", _CUSTOMER_RECORD_PATTERNS, 0.8, "customer_record_pattern")
    _maybe_add(candidates, normalized, "aggregate", _AGGREGATE_PATTERNS, 0.78, "aggregate_pattern")

    if candidates:
        return candidates[0]

    if _matches_any(normalized, _DATA_CONTEXT_PATTERNS):
        return IntentClassification("aggregate", 0.62, "generic_business_data_context")

    return IntentClassification("unknown", 0.35, "no_supported_intent_pattern")


def _maybe_add(
    candidates: list[IntentClassification],
    normalized: str,
    intent: DataAgentIntent,
    patterns: Iterable[str],
    confidence: float,
    reason: str,
) -> None:
    if _matches_any(normalized, patterns):
        candidates.append(IntentClassification(intent, confidence, reason))


def _matches_any(normalized: str, patterns: Iterable[str]) -> bool:
    return any(re.search(pattern, normalized, flags=re.IGNORECASE) for pattern in patterns)


def _normalize(text: str) -> str:
    normalized = unicodedata.normalize("NFKC", text or "").casefold()
    return re.sub(r"\s+", " ", normalized).strip()

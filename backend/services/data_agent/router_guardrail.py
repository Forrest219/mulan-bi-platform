"""Homepage Data Agent router guardrail.

The router classifies a user question before the ReAct loop sees any tools.
Its output is a hard execution policy, not just prompt guidance.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
import re
import unicodedata
from typing import Any, Dict, Iterable, Literal, Optional

QuestionType = Literal["asset_question", "data_question", "ambiguous"]
RouteName = Literal["schema_inventory", "data_query", "clarify"]
FallbackPolicy = Literal["schema_only", "data_only", "clarify_only"]
GuardrailMode = Literal["shadow", "enforce"]


@dataclass(frozen=True)
class RouteDecision:
    question_type: QuestionType
    confidence: float
    route: RouteName
    allowed_tools: list[str]
    forbidden_tools: list[str]
    fallback_policy: FallbackPolicy
    reason: str
    mode: GuardrailMode = "enforce"

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @property
    def is_data_question(self) -> bool:
        return self.question_type == "data_question"

    @property
    def is_asset_question(self) -> bool:
        return self.question_type == "asset_question"

    @property
    def needs_clarification(self) -> bool:
        return self.question_type == "ambiguous"


ASSET_METADATA_PATTERNS = (
    r"有哪些字段",
    r"有什么字段",
    r"字段有哪些",
    r"字段是什么",
    r"字段列表",
    r"包含哪些字段",
    r"有哪些列",
    r"列有哪些",
    r"表结构",
    r"数据结构",
    r"介绍数据源",
    r"介绍.+数据源",
    r"介绍.+数据资产",
    r"介绍.+表",
    r"schema",
    r"\bfields?\b",
    r"\bcolumns?\b",
)

ASSET_INVENTORY_KEYWORDS = (
    "有哪些数据源",
    "有什么数据源",
    "数据源列表",
    "可用数据源",
    "当前连接",
    "有哪些表",
    "表列表",
    "有哪些资产",
    "数据资产清单",
    "有哪些视图",
    "视图列表",
    "有哪些 workbook",
    "有哪些工作簿",
    "workbook",
    "工作簿",
    "workbooks",
    "views",
    "tables",
    "datasets",
    "data sources",
)

GOVERNANCE_KEYWORDS = (
    "所有者",
    "owner",
    "项目",
    "project",
    "链接",
    "url",
    "更新时间",
    "更新频率",
    "认证",
    "权限",
    "血缘",
    "元数据",
    "metadata",
)

DATA_METRIC_KEYWORDS = (
    "销售额",
    "销售",
    "利润",
    "收入",
    "订单数",
    "客户数",
    "数量",
    "金额",
    "成本",
    "折扣",
    "gmv",
    "率",
    "毛利",
    "净额",
)

DATA_ACTION_PATTERNS = (
    r"多少",
    r"有多少",
    r"总计",
    r"合计",
    r"汇总",
    r"统计",
    r"求和",
    r"平均",
    r"最大",
    r"最小",
    r"按.+",
    r"各.+",
    r"每个.+",
    r"分布",
    r"趋势",
    r"走势",
    r"变化",
    r"top\s*\d+",
    r"前\s*[一二三四五六七八九十\d]+",
    r"排名",
    r"占比",
    r"同比",
    r"环比",
    r"增长",
    r"下降",
    r"持续",
    r"一直",
    r"亏损",
    r"巨亏",
    r"原因",
    r"归因",
    r"合作记录",
    r"合作",
    r"最近",
    r"记录",
    r"画图",
    r"趋势图",
    r"柱状图",
    r"饼图",
    r"可视化",
)

TIME_PATTERNS = (
    r"\d{4}\s*年",
    r"今年",
    r"去年",
    r"上月",
    r"本月",
    r"过去\s*[一二三四五六七八九十\d几]+\s*(年|月|周|季度)",
    r"近\s*[一二三四五六七八九十\d几]+\s*(年|月|周|季度)",
)

BUSINESS_DIMENSION_KEYWORDS = (
    "客户",
    "渠道",
    "类别",
    "子类别",
    "省份",
    "省",
    "城市",
    "区域",
    "地区",
    "产品",
    "门店",
    "部门",
    "业务线",
    "销售员",
)

AMBIGUOUS_EXACT = (
    "帮我查一下",
    "看看数据",
    "有哪些",
    "查一下",
    "看一下",
    "介绍一下这个数据源",
    "这个表怎么样",
    "列出客户",
)


def classify_homepage_question(
    question: str,
    *,
    context_hints: Optional[Dict[str, Any]] = None,
    mode: GuardrailMode = "enforce",
) -> RouteDecision:
    """Classify a homepage question and return an executable guardrail policy."""

    normalized = _normalize(question)
    context_hints = context_hints or {}

    if not normalized or normalized in AMBIGUOUS_EXACT:
        return _ambiguous("empty_or_low_signal_question", mode=mode)

    asset_score, asset_reason = _score_asset_question(normalized)
    data_score, data_reason = _score_data_question(normalized, context_hints=context_hints)

    # Conflict resolution: explicit field/schema requests are assets unless the
    # user also asks for business values from the asset.
    if _has_asset_metadata_pattern(normalized) and not _has_business_value_request(normalized):
        return _asset(0.95, asset_reason or "explicit_asset_metadata_request", mode=mode)

    if _has_business_value_request(normalized):
        data_score += 2
        data_reason = data_reason or "business_value_request"

    if data_score >= 2 and data_score >= asset_score:
        confidence = min(0.95, 0.55 + data_score * 0.1)
        return _data(confidence, data_reason or "data_question_rules", mode=mode)

    if asset_score >= 2 and asset_score > data_score:
        confidence = min(0.95, 0.55 + asset_score * 0.1)
        return _asset(confidence, asset_reason or "asset_question_rules", mode=mode)

    return _ambiguous(
        f"low_confidence_route asset_score={asset_score} data_score={data_score}",
        mode=mode,
    )


def validate_tool_allowed(tool_name: str, decision: Optional[RouteDecision]) -> tuple[bool, Optional[str]]:
    """Return whether a tool can execute under the route decision."""
    if decision is None:
        return True, None
    if decision.mode != "enforce":
        return True, None
    if tool_name in decision.forbidden_tools:
        return False, "tool_forbidden_by_route"
    if decision.allowed_tools and tool_name not in decision.allowed_tools:
        return False, "tool_not_in_allowed_tools"
    return True, None


def filter_tool_descriptions(
    tool_descriptions: Iterable[Dict[str, Any]],
    decision: Optional[RouteDecision],
) -> list[Dict[str, Any]]:
    """Filter tool descriptions before building the LLM system prompt."""
    descriptions = list(tool_descriptions)
    if decision is None or decision.mode != "enforce":
        return descriptions
    allowed = set(decision.allowed_tools)
    forbidden = set(decision.forbidden_tools)
    return [
        desc
        for desc in descriptions
        if desc.get("name") not in forbidden and (not allowed or desc.get("name") in allowed)
    ]


def _asset(confidence: float, reason: str, *, mode: GuardrailMode) -> RouteDecision:
    return RouteDecision(
        question_type="asset_question",
        confidence=confidence,
        route="schema_inventory",
        allowed_tools=["schema"],
        forbidden_tools=["query"],
        fallback_policy="schema_only",
        reason=reason,
        mode=mode,
    )


def _data(confidence: float, reason: str, *, mode: GuardrailMode) -> RouteDecision:
    return RouteDecision(
        question_type="data_question",
        confidence=confidence,
        route="data_query",
        allowed_tools=["query"],
        forbidden_tools=["schema"],
        fallback_policy="data_only",
        reason=reason,
        mode=mode,
    )


def _ambiguous(reason: str, *, mode: GuardrailMode) -> RouteDecision:
    return RouteDecision(
        question_type="ambiguous",
        confidence=0.35,
        route="clarify",
        allowed_tools=[],
        forbidden_tools=["schema", "query"],
        fallback_policy="clarify_only",
        reason=reason,
        mode=mode,
    )


def _score_asset_question(normalized: str) -> tuple[int, str]:
    score = 0
    reason = ""
    if _has_asset_metadata_pattern(normalized):
        score += 3
        reason = "asset_metadata_pattern"
    if any(keyword in normalized for keyword in ASSET_INVENTORY_KEYWORDS):
        score += 2
        reason = reason or "asset_inventory_keyword"
    asset_object_requested = any(
        keyword in normalized
        for keyword in (
            "数据资产",
            "数据源",
            "视图",
            "view",
            "workbook",
            "工作簿",
            "表",
        )
    )
    if asset_object_requested and any(keyword in normalized for keyword in GOVERNANCE_KEYWORDS):
        score += 2
        reason = reason or "asset_governance_keyword"
    return score, reason


def _score_data_question(normalized: str, *, context_hints: Dict[str, Any]) -> tuple[int, str]:
    score = 0
    reason = ""
    if any(keyword in normalized for keyword in DATA_METRIC_KEYWORDS):
        score += 2
        reason = "metric_keyword"
    if any(re.search(pattern, normalized, flags=re.IGNORECASE) for pattern in DATA_ACTION_PATTERNS):
        score += 2
        reason = reason or "data_action_pattern"
    if any(re.search(pattern, normalized, flags=re.IGNORECASE) for pattern in TIME_PATTERNS):
        score += 1
        reason = reason or "time_filter_pattern"
    if any(keyword in normalized for keyword in BUSINESS_DIMENSION_KEYWORDS):
        score += 1
        reason = reason or "business_dimension_keyword"
    if context_hints.get("last_query_datasource") and re.search(r"(这个|这些|上述|继续|再按|拆分)", normalized):
        score += 2
        reason = reason or "query_followup_context"
    return score, reason


def _has_asset_metadata_pattern(normalized: str) -> bool:
    return any(re.search(pattern, normalized, flags=re.IGNORECASE) for pattern in ASSET_METADATA_PATTERNS)


def _has_business_value_request(normalized: str) -> bool:
    metric = any(keyword in normalized for keyword in DATA_METRIC_KEYWORDS)
    time_filter = any(re.search(pattern, normalized, flags=re.IGNORECASE) for pattern in TIME_PATTERNS)
    action = any(re.search(pattern, normalized, flags=re.IGNORECASE) for pattern in DATA_ACTION_PATTERNS)
    business_dimension = any(keyword in normalized for keyword in BUSINESS_DIMENSION_KEYWORDS)
    return metric or (business_dimension and (time_filter or action))


def _normalize(text: str) -> str:
    normalized = unicodedata.normalize("NFKC", text or "").casefold()
    return re.sub(r"\s+", " ", normalized).strip()

"""
Spec 36 §15: 意图识别 — keyword_match 策略

基于关键词规则快速识别意图。
适用于高频意图词匹配（查询、分析、报表等）。
无法识别时抛出异常，fallback 到 llm_classify。
"""
import logging
import re
from typing import Any, Dict, List, Optional, Tuple

from .strategy import IntentResult, IntentStrategy

logger = logging.getLogger(__name__)


# 直接查询模式：可被单次 QueryTool 调用回答的问题特征
DIRECT_QUERY_PATTERNS = [
    r'(过去|近)\s*几\s*年',                    # 过去几年 / 近几年
    r'过去\s*\d+\s*(年|季度|个月|周)',          # 过去四年 / 过去3个月
    r'\d{4}\s*年',                              # 2021年 / 2024年
    r'(今年|去年|上季度|上月|最近\d)',
    r'(每个?|各)\s*(产品|类别|子类别|区域|城市|客户|省)',
    r'(走势|趋势|变化).{0,20}(销售|利润|收入)|(销售|利润|收入).{0,20}(走势|趋势|变化)',  # 时序+指标，双向
    r'趋势分析',                     # 趋势分析本身是快通场景（优先于黑名单的"分析"）
    # 简单聚合问法
    r'有多少|多少笔|总计|汇总|统计',
    r'是.*多少|多少.*是',
]

SUPPORTED_TOPN_DIRECT_PATTERNS = [
    # 已由 QueryTool deterministic planner 覆盖：年度 TopN 大客户 + 销售额/利润/收入/金额。
    r'\d{4}\s*年.{0,20}(top\s*\d+|前\s*\d+).{0,20}(大?客户).{0,30}(销售|销售额|收入|利润|金额)',
    r'(销售|销售额|收入|利润|金额).{0,20}\d{4}\s*年.{0,20}(top\s*\d+|前\s*\d+).{0,20}(大?客户)',
]

SUPPORTED_CHURN_DIRECT_PATTERNS = [
    r'\d{4}\s*年.{0,30}(老客户|客户).{0,20}流失.{0,40}(最近一年|近一年|过去一年)',
    r'(老客户|客户).{0,20}流失.{0,40}\d{4}\s*年.{0,40}(最近一年|近一年|过去一年)',
]

# 复杂分析模式：即使匹配到上面的模式，也应走完整 ReAct
# 优先级：黑名单高于白名单，命中任意一条即判定为复杂
COMPLEX_ANALYSIS_PATTERNS = [
    # 因果/归因 — 强分析意图
    r'为什么|原因|归因|导致|影响了|为何',
    # 分析/解读 — 直接触发分析意图（排除"趋势分析"，它是快通场景）
    r'(?<!趋势)分析',
    r'解读|洞察|拆解',
    # 对比/差异 — 多维度分析
    r'对比|差异|比较|区别',
    # 预测/建议 — 生成性分析
    r'预测|建议|改善|提升|优化',
    # 异常/发现问题
    r'异常|问题|故障|发现|流失|留存|定义',
    # 报表生成 — 复杂输出
    r'生成报表|生成报告|做个报表|输出一张报表',
    # 特定分析短语
    r'分析.*原因|原因.*分析|如何改善|如何提升',
    r'相关性|关联|影响因素',
    # 占比/同比/环比/top/排名 — 需二次计算或排序
    r'占比|同比|环比|增长率|增幅',
    r'\btop\s*\d+|排名|排序|第.\d?名',
]

# Schema / metadata questions must not use the direct query fast path.
# Asset names may contain metric-looking words such as "summary" / "汇总",
# but questions about fields or table structure should route through schema.
SCHEMA_METADATA_PATTERNS = [
    r'字段|栏位|列名|列\b|表结构|结构信息|schema|元数据|数据资产',
    r'有哪些.{0,12}(字段|列)',
    r'(字段|列).{0,12}有哪些',
    r'(查看|查询|展示|列出).{0,20}(字段|列|表结构|schema|元数据)',
]


# 图表类型关键词映射（精确词先于通用词）
CHART_TYPE_KEYWORDS = {
    'line': ['趋势图', '折线图', '走势图', '时序图'],
    'pie': ['饼图', '占比图', '饼状图', '环形图'],
    'bar': ['柱状图', '柱形图', '条形图', '直方图'],
}


def is_chart_request(question: str) -> Tuple[bool, str]:
    """判断问题是否包含图表请求，返回 (is_chart, chart_type)。

    Returns:
        tuple: (is_chart, chart_type) where chart_type is 'line' | 'bar' | 'pie'
    """
    normalized = _normalize(question)
    for chart_type, keywords in CHART_TYPE_KEYWORDS.items():
        for kw in keywords:
            if kw in normalized:
                return True, chart_type
    for kw in ['图表', '可视化', '做图', '画图', '生成图']:
        if kw in normalized:
            return True, 'bar'
    if '图' in normalized and any(k in normalized for k in ['做个', '画个', '生成', '展示成']):
        return True, 'bar'
    return False, 'bar'


def is_direct_query(question: str) -> bool:
    """判断问题是否可走直接查询快速路径（跳过 LLM Think 首步）。

    匹配"时间区间 + 指标/维度聚合"特征，执行耗时 <1ms，无 LLM 调用。
    复杂分析关键词（为什么/原因/归因）优先级更高，命中则返回 False。
    """
    normalized = _normalize(question)
    for pattern in SCHEMA_METADATA_PATTERNS:
        if re.search(pattern, normalized):
            return False
    for pattern in SUPPORTED_TOPN_DIRECT_PATTERNS:
        if re.search(pattern, normalized):
            return True
    for pattern in SUPPORTED_CHURN_DIRECT_PATTERNS:
        if re.search(pattern, normalized):
            return True
    for pattern in COMPLEX_ANALYSIS_PATTERNS:
        if re.search(pattern, normalized):
            return False
    for pattern in DIRECT_QUERY_PATTERNS:
        if re.search(pattern, normalized):
            return True
    return False


SCHEMA_INVENTORY_PATTERNS = [
    r'有哪些\s*(数据源|数据来源|表|表格|资产)',
    r'(数据源|数据来源|表|表格|资产)\s*有哪些',
    r'(列出|展示|显示|查看|查询).{0,8}(数据源|数据来源|表|表格|资产)',
    r'(数据源|数据来源).{0,8}(列表|清单|目录)',
]


def is_schema_inventory_request(question: str) -> bool:
    """判断是否为连接级元数据枚举问题。

    这类问题需要列出当前连接下的 Tableau 资产/数据源，而不是预选一个
    route_datasource 候选注入 prompt，否则 LLM 会把单一候选误当成全集。
    """
    normalized = _normalize(question)
    return any(re.search(pattern, normalized) for pattern in SCHEMA_INVENTORY_PATTERNS)


# 意图关键词定义（优先级从高到低）
INTENT_KEYWORDS = {
    "report": [
        "报表", "报告", "生成报表", "生成报告", "做张报表",
        "画报表", "输出报表", "导出报表",
    ],
    "analysis": [
        "分析", "分析一下", "拆解", "解读", "洞察",
        "原因", "为什么", "归因", "趋势", "对比",
        "对比", "差异", "排名", "排序",
    ],
    "query": [
        "查一下", "查查", "看看", "有多少", "是哪些",
        "显示", "展示", "列出", "给我看", "统计",
        "汇总", "求和", "计数", "最大值", "最小值",
    ],
    "chart": [
        "图", "图表", "柱状图", "折线图", "饼图", "散点图",
        "可视化", "画个图", "生成图表",
    ],
    "chat": [
        "你好", "您好", "谢谢", "感谢", "再见", "拜拜",
        "早上好", "下午好", "晚上好", "嗨",
    ],
}


def _normalize(text: str) -> str:
    """规范化文本：小写化、全角转半角、去除多余空格"""
    import unicodedata
    text = text.lower()
    # 全角转半角
    text = unicodedata.normalize("NFKC", text)
    # 去除多余空格
    text = re.sub(r"\s+", " ", text).strip()
    return text


class KeywordMatchStrategy(IntentStrategy):
    """
    基于关键词规则的意图识别。

    规则：
    - 按优先级（report > analysis > query > chart > chat）依次匹配
    - 匹配到第一个即返回，不继续匹配
    - 无法识别时抛出异常
    """

    name = "keyword_match"

    def __init__(self):
        self._patterns: Dict[str, List[re.Pattern]] = {}
        for intent, keywords in INTENT_KEYWORDS.items():
            self._patterns[intent] = [
                re.compile(re.escape(kw)) for kw in keywords
            ]

    async def classify(
        self,
        question: str,
        context: Optional[Dict[str, Any]] = None,
    ) -> IntentResult:
        """
        基于关键词匹配意图。

        优先级顺序：report > analysis > query > chart > chat（默认）
        """
        normalized = _normalize(question)

        priority_order = ["report", "analysis", "query", "chart", "chat"]

        for intent in priority_order:
            patterns = self._patterns.get(intent, [])
            for pattern in patterns:
                if pattern.search(normalized):
                    return IntentResult(
                        intent=intent,
                        confidence=0.90,
                        strategy=self.name,
                        params={"matched_keyword": pattern.pattern},
                    )

        # 无法从关键词识别，默认 chat
        raise ValueError(f"keyword_match: no keyword matched for '{question}'")

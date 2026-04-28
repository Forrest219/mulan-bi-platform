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
    "chat": [],  # 默认意图，无关键词
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
        # 预编译正则（匹配完整词或词边界）
        self._patterns: Dict[str, List[re.Pattern]] = {}
        for intent, keywords in INTENT_KEYWORDS.items():
            self._patterns[intent] = [
                re.compile(rf"(^|\s){re.escape(kw)}(\s|$)") for kw in keywords
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

        priority_order = ["report", "analysis", "query", "chart"]

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
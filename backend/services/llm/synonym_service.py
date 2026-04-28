"""
同义词服务（Spec 14 §4.4）

提供 NL-to-Query 场景的同义词表查询功能。
初始版本使用硬编码 DEFAULT_SYNONYMS，
后续可迁移到 nlq_synonym_mappings 表。
"""
import logging
from typing import Dict, List, Optional, Set, Tuple

logger = logging.getLogger(__name__)

# 硬编码同义词表（Spec 14 §4.4）
DEFAULT_SYNONYMS: Dict[str, List[str]] = {
    # 常见财务指标
    "销售额": ["sales", "营业额", "销售金额", "收入", "营收"],
    "利润": ["profit", "净利润", "毛利", "利润额"],
    "成本": ["cost", "费用", "支出"],
    "订单数": ["order count", "订单量", "订单总数"],
    "折扣": ["discount", "折扣率", "优惠"],

    # 常见维度
    "区域": ["region", "地区", "大区"],
    "产品": ["product", "商品", "产品名称", "货品"],
    "类别": ["category", "分类", "品类", "产品类别"],
    "客户": ["customer", "顾客", "客户名称"],
    "日期": ["date", "时间", "订单日期", "下单时间"],

    # 时间表达
    "上个月": ["last month", "上月"],
    "本月": ["this month", "当月"],
    "今年": ["this year", "本年度"],
    "去年": ["last year", "上年"],
}


def levenshtein_distance(s1: str, s2: str) -> int:
    """
    计算两个字符串之间的编辑距离（Levenshtein Distance）。

    算法：动态规划
    时间复杂度：O(m*n)
    空间复杂度：O(m*n)

    Args:
        s1: 第一个字符串
        s2: 第二个字符串

    Returns:
        编辑距离（整数）
    """
    if len(s1) < len(s2):
        return levenshtein_distance(s2, s1)

    if len(s2) == 0:
        return len(s1)

    previous_row = range(len(s2) + 1)
    for i, c1 in enumerate(s1):
        current_row = [i + 1]
        for j, c2 in enumerate(s2):
            insertions = previous_row[j + 1] + 1
            deletions = current_row[j] + 1
            substitutions = previous_row[j] + (c1 != c2)
            current_row.append(min(insertions, deletions, substitutions))
        previous_row = current_row

    return previous_row[-1]


def is_fuzzy_match(
    term1: str,
    term2: str,
    max_distance: int = 2,
    min_length_ratio: float = 0.6,
) -> bool:
    """
    判断两个词是否模糊匹配（Spec 14 §4.3）。

    条件：
    1. 编辑距离 <= max_distance（默认 2）
    2. 长度比 >= min_length_ratio（默认 0.6）

    Args:
        term1: 第一个词
        term2: 第二个词
        max_distance: 最大编辑距离
        min_length_ratio: 最小长度比

    Returns:
        True 表示匹配，False 表示不匹配
    """
    if not term1 or not term2:
        return False

    # 长度检查
    min_len = min(len(term1), len(term2))
    max_len = max(len(term1), len(term2))
    length_ratio = min_len / max_len if max_len > 0 else 0

    if length_ratio < min_length_ratio:
        return False

    # 编辑距离检查
    distance = levenshtein_distance(term1.lower(), term2.lower())
    return distance <= max_distance


class SynonymService:
    """
    同义词服务。

    提供：
    - 同义词查询（精确匹配 + 反向匹配）
    - 模糊匹配（编辑距离）
    - 同义词表注册
    """

    def __init__(self, synonyms: Dict[str, List[str]] = None):
        """
        Args:
            synonyms: 同义词表，默认为 DEFAULT_SYNONYMS
        """
        self.synonyms = synonyms or DEFAULT_SYNONYMS
        # 构建反向索引：synonym -> canonical term
        self._reverse_index: Dict[str, str] = {}
        self._build_reverse_index()

    def _build_reverse_index(self):
        """构建反向索引"""
        for canonical, synonyms in self.synonyms.items():
            for syn in synonyms:
                self._reverse_index[syn.lower()] = canonical
            # 也将 canonical term 本身加入索引
            self._reverse_index[canonical.lower()] = canonical

    def lookup(self, term: str) -> Optional[str]:
        """
        查询术语的规范形式。

        查找顺序：
        1. 精确匹配 canonical term
        2. 精确匹配 synonym
        3. 大小写不敏感匹配

        Args:
            term: 用户输入的术语

        Returns:
            规范术语，如果未找到返回 None
        """
        if not term:
            return None

        term_lower = term.lower()

        # 直接查找
        if term_lower in self._reverse_index:
            return self._reverse_index[term_lower]

        return None

    def find_synonyms(self, term: str) -> List[str]:
        """
        查找术语的所有同义词（包括自身）。

        Args:
            term: 规范术语或同义词

        Returns:
            同义词列表
        """
        # 先找到 canonical term
        canonical = self.lookup(term)
        if canonical and canonical in self.synonyms:
            result = [canonical] + self.synonyms[canonical]
            return list(dict.fromkeys(result))  # 去重保持顺序
        return [term] if term else []

    def fuzzy_match(
        self,
        term: str,
        candidates: List[str],
        max_distance: int = 2,
        min_length_ratio: float = 0.6,
    ) -> List[Tuple[str, int, float]]:
        """
        模糊匹配：找到与 term 模糊匹配的所有候选词。

        Args:
            term: 用户输入的术语
            candidates: 候选词列表（通常是字段 caption 列表）
            max_distance: 最大编辑距离
            min_length_ratio: 最小长度比

        Returns:
            匹配结果列表，每项为 (候选词, 编辑距离, 长度比)，
            按编辑距离升序排列
        """
        if not term or not candidates:
            return []

        results = []
        for candidate in candidates:
            if is_fuzzy_match(term, candidate, max_distance, min_length_ratio):
                distance = levenshtein_distance(term.lower(), candidate.lower())
                min_len = min(len(term), len(candidate))
                max_len = max(len(term), len(candidate))
                ratio = min_len / max_len if max_len > 0 else 0
                results.append((candidate, distance, ratio))

        # 按编辑距离升序排列
        results.sort(key=lambda x: (x[1], -x[2]))
        return results

    def register_synonym(self, canonical: str, synonyms: List[str]):
        """
        注册新的同义词组。

        Args:
            canonical: 规范术语
            synonyms: 同义词列表
        """
        if canonical in self.synonyms:
            # 合并同义词
            existing = set(self.synonyms[canonical])
            existing.update(synonyms)
            self.synonyms[canonical] = list(existing)
        else:
            self.synonyms[canonical] = synonyms

        # 重建反向索引
        self._build_reverse_index()


# 全局单例
_synonym_service: Optional[SynonymService] = None


def get_synonym_service() -> SynonymService:
    """获取同义词服务单例"""
    global _synonym_service
    if _synonym_service is None:
        _synonym_service = SynonymService()
    return _synonym_service

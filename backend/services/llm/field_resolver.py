"""
字段解析器（Spec 14 §4）

将用户问题中的字段名映射到 Tableau fieldCaption。
支持多种匹配策略，按优先级：
1. 精确匹配
2. 同义词匹配
3. 语义标注匹配
4. 模糊匹配
5. LLM 兜底
"""
import logging
from dataclasses import dataclass
from typing import Dict, List, Optional, Any, Tuple

from .synonym_service import SynonymService, get_synonym_service

logger = logging.getLogger(__name__)


@dataclass
class ResolvedField:
    """解析后的字段（Spec 14 §4.5）"""
    field_caption: str        # 匹配到的 Tableau 字段显示名
    field_name: str          # Tableau 内部字段名
    role: str                 # "dimension" | "measure"
    data_type: str           # 数据类型
    match_source: str         # "exact" | "synonym" | "semantic" | "fuzzy" | "llm"
    match_confidence: float   # 0.0 ~ 1.0
    user_term: str            # 用户原始表达


class FieldResolver:
    """
    字段解析器。

    将用户问题中的字段名映射到 Tableau fieldCaption。
    """

    def __init__(self, synonym_service: SynonymService = None):
        """
        Args:
            synonym_service: 同义词服务，默认为全局单例
        """
        self.synonym_service = synonym_service or get_synonym_service()

    def resolve(
        self,
        user_term: str,
        fields: List[Dict[str, str]],
        intent: str = None,
    ) -> Optional[ResolvedField]:
        """
        解析单个用户术语到字段。

        匹配策略（按优先级）：
        1. 精确匹配 field_caption 或 field_name（不区分大小写）
        2. 同义词匹配（查 synonym_service）
        3. 模糊匹配（编辑距离 <= 2）

        Args:
            user_term: 用户问题中的字段术语
            fields: 数据源字段列表，每项包含 field_caption, field_name, role, data_type
            intent: 意图类型（用于上下文）

        Returns:
            ResolvedField 如果找到匹配，否则 None
        """
        if not user_term or not fields:
            return None

        user_term_lower = user_term.lower()

        # 1. 精确匹配
        for f in fields:
            caption_lower = (f.get("field_caption") or "").lower()
            name_lower = (f.get("field_name") or "").lower()
            if caption_lower == user_term_lower or name_lower == user_term_lower:
                return ResolvedField(
                    field_caption=f.get("field_caption", ""),
                    field_name=f.get("field_name", ""),
                    role=f.get("role", "dimension"),
                    data_type=f.get("data_type", "string"),
                    match_source="exact",
                    match_confidence=1.0,
                    user_term=user_term,
                )

        # 2. 同义词匹配
        canonical = self.synonym_service.lookup(user_term)
        if canonical:
            # 在字段列表中找 canonical term
            for f in fields:
                caption_lower = (f.get("field_caption") or "").lower()
                name_lower = (f.get("field_name") or "").lower()
                if caption_lower == canonical.lower() or name_lower == canonical.lower():
                    return ResolvedField(
                        field_caption=f.get("field_caption", ""),
                        field_name=f.get("field_name", ""),
                        role=f.get("role", "dimension"),
                        data_type=f.get("data_type", "string"),
                        match_source="synonym",
                        match_confidence=0.95,
                        user_term=user_term,
                    )

        # 3. 模糊匹配（编辑距离）
        field_captions = [
            f.get("field_caption", "") or f.get("field_name", "")
            for f in fields
        ]
        matches = self.synonym_service.fuzzy_match(user_term, field_captions)
        if matches:
            best_match, distance, ratio = matches[0]
            # 找到最佳匹配的字段
            for f in fields:
                caption = f.get("field_caption", "") or f.get("field_name", "")
                if caption == best_match:
                    return ResolvedField(
                        field_caption=f.get("field_caption", ""),
                        field_name=f.get("field_name", ""),
                        role=f.get("role", "dimension"),
                        data_type=f.get("data_type", "string"),
                        match_source="fuzzy",
                        match_confidence=max(0.5, 1.0 - distance * 0.2),
                        user_term=user_term,
                    )

        return None

    def resolve_all(
        self,
        user_terms: List[str],
        fields: List[Dict[str, str]],
        intent: str = None,
    ) -> List[ResolvedField]:
        """
        解析多个用户术语。

        Args:
            user_terms: 用户问题中的所有术语
            fields: 数据源字段列表
            intent: 意图类型

        Returns:
            ResolvedField 列表（去重）
        """
        results = []
        seen_captions = set()

        for term in user_terms:
            resolved = self.resolve(term, fields, intent)
            if resolved and resolved.field_caption not in seen_captions:
                results.append(resolved)
                seen_captions.add(resolved.field_caption)

        return results

    def resolve_from_question(
        self,
        question: str,
        fields: List[Dict[str, str]],
        intent: str = None,
    ) -> List[ResolvedField]:
        """
        从用户问题中提取并解析字段术语。

        Args:
            question: 用户问题
            fields: 数据源字段列表
            intent: 意图类型

        Returns:
            ResolvedField 列表
        """
        import re

        # 简单分词：提取长度 >= 2 的词
        cleaned = re.sub(
            r"[，。！？、；：""''（）《》【】\.,!?;:\"\'\(\)\[\]]",
            " ",
            question,
        )
        tokens = cleaned.split()
        terms = [t.strip() for t in tokens if len(t.strip()) >= 2]

        return self.resolve_all(terms, fields, intent)


def extract_field_terms(question: str) -> List[str]:
    """
    从用户问题中提取可能的字段术语。

    使用简单分词 + 停用词过滤。

    Args:
        question: 用户问题

    Returns:
        术语列表
    """
    import re

    # 停用词
    STOPWORDS = {
        "的", "是", "在", "有", "和", "与", "或", "各", "每",
        "多少", "几个", "什么", "哪些", "如何", "怎么",
        "最近", "过去", "今年", "去年", "上月", "本月",
        "所有", "全部", "总", "合计", "总共",
    }

    cleaned = re.sub(
        r"[，。！？、；：""''（）《》【】\.,!?;:\"\'\(\)\[\]]",
        " ",
        question,
    )
    tokens = cleaned.split()
    terms = [
        t.strip()
        for t in tokens
        if len(t.strip()) >= 2 and t.strip() not in STOPWORDS
    ]
    return terms


class FieldResolverWithSemantic(FieldResolver):
    """
    支持语义标注的字段解析器。

    在基本解析基础上，额外支持语义标注匹配：
    - semantic_name_zh 匹配
    - semantic_definition 关键词匹配
    """

    def __init__(self, synonym_service: SynonymService = None, semantic_fields: Dict[str, Dict] = None):
        """
        Args:
            synonym_service: 同义词服务
            semantic_fields: 语义标注字段映射 {field_caption: {semantic_name_zh, semantic_definition, ...}}
        """
        super().__init__(synonym_service)
        self.semantic_fields = semantic_fields or {}

    def resolve_with_semantic(
        self,
        user_term: str,
        fields: List[Dict[str, str]],
        intent: str = None,
    ) -> Optional[ResolvedField]:
        """
        解析时优先检查语义标注。

        Args:
            user_term: 用户术语
            fields: 数据源字段列表
            intent: 意图类型

        Returns:
            ResolvedField 如果找到
        """
        # 先检查语义标注
        user_term_lower = user_term.lower()
        for f in fields:
            caption = f.get("field_caption", "") or f.get("field_name", "")
            semantic_info = self.semantic_fields.get(caption, {})
            semantic_name_zh = (semantic_info.get("semantic_name_zh") or "").lower()
            semantic_definition = (semantic_info.get("semantic_definition") or "").lower()

            if (semantic_name_zh == user_term_lower or
                    user_term_lower in semantic_name_zh or
                    user_term_lower in semantic_definition):
                return ResolvedField(
                    field_caption=caption,
                    field_name=f.get("field_name", ""),
                    role=f.get("role", "dimension"),
                    data_type=f.get("data_type", "string"),
                    match_source="semantic",
                    match_confidence=0.9,
                    user_term=user_term,
                )

        # 回退到基本解析
        return self.resolve(user_term, fields, intent)


# 全局单例（无语义标注）
_field_resolver: Optional[FieldResolver] = None


def get_field_resolver() -> FieldResolver:
    """获取字段解析器单例"""
    global _field_resolver
    if _field_resolver is None:
        _field_resolver = FieldResolver()
    return _field_resolver

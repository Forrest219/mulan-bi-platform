"""
敏感字段净化器（Spec 12 §9.2 — 独立模块）

将上下文净化逻辑从 context_assembler.py 抽取为独立模块，
符合 Spec 12 §2.2 模块职责边界规范。

净化规则：
1. 移除 sensitivity_level 为 HIGH/CONFIDENTIAL 的字段
2. enum_values 最多保留 20 个示例值，单个值最大 50 字符
3. 仅保留字段元数据（名称、类型、公式），不包含实际数据值
"""
import logging
from typing import List, Dict, Any, Optional, Set

logger = logging.getLogger(__name__)

# Blocked sensitivity levels for AI processing (Spec 12 §9.1)
BLOCKED_FOR_LLM: Set[str] = {"high", "confidential"}

# 枚举值截断常量（Spec 12 §5.1 + §8.2）
MAX_ENUM_VALUES: int = 20
MAX_ENUM_VALUE_LENGTH: int = 50


def sanitize_fields_for_llm(
    fields: List[Dict[str, Any]],
    blocked_levels: Optional[Set[str]] = None,
) -> List[Dict[str, Any]]:
    """
    上下文净化（Spec 12 §9.2）：过滤 HIGH/CONFIDENTIAL 敏感级别字段。

    净化规则：
    1. 移除 sensitivity_level 为 HIGH/CONFIDENTIAL 的字段
    2. enum_values 最多保留 20 个示例值，单个值最大 50 字符
    3. 仅保留字段元数据（名称、类型、公式），不包含实际数据值

    Args:
        fields: 原始字段列表
        blocked_levels: 封锁的敏感级别集合，默认为 BLOCKED_FOR_LLM

    Returns:
        净化后的字段列表
    """
    if blocked_levels is None:
        blocked_levels = BLOCKED_FOR_LLM

    sanitized = []
    for f in fields:
        sensitivity = (f.get("sensitivity_level") or "").lower()
        if sensitivity in blocked_levels:
            continue  # 敏感字段不进入 LLM 上下文

        safe_field = _build_safe_field(f)
        sanitized.append(safe_field)

    return sanitized


def _build_safe_field(field: Dict[str, Any]) -> Dict[str, Any]:
    """
    构建单个安全字段（仅包含 LLM 所需的元数据）。

    包含字段：
    - field_name: Tableau 内部字段名
    - field_caption: 字段显示名
    - data_type: 数据类型
    - role: 维度/度量
    - formula: 计算字段公式（元数据，允许）
    - enum_values: 脱敏后的枚举值（最多 20 个，单个最大 50 字符）
    """
    safe_field = {
        "field_name": field.get("field_name"),
        "field_caption": field.get("field_caption"),
        "data_type": field.get("data_type"),
        "role": field.get("role"),
        "formula": field.get("formula"),  # 公式是元数据，允许
    }

    # 枚举值截断（Spec 12 §5.1 + §8.2：最多 20 个，单个值最大 50 字符）
    enum_values = field.get("enum_values")
    if enum_values:
        safe_field["enum_values"] = _truncate_enum_values(enum_values)

    return safe_field


def _truncate_enum_values(enum_values: List[str]) -> List[str]:
    """
    截断枚举值列表。

    规则：
    - 最多保留 MAX_ENUM_VALUES (20) 个
    - 单个值最大 MAX_ENUM_VALUE_LENGTH (50) 字符，超出用 ... 截断

    Args:
        enum_values: 原始枚举值列表

    Returns:
        截断后的枚举值列表
    """
    truncated = []
    for v in enum_values[:MAX_ENUM_VALUES]:
        if len(v) > MAX_ENUM_VALUE_LENGTH:
            truncated.append(v[:MAX_ENUM_VALUE_LENGTH] + "...")
        else:
            truncated.append(v)
    return truncated


def is_field_blocked(field: Dict[str, Any]) -> bool:
    """
    检查字段是否被封锁（不适合进入 LLM 上下文）。

    Args:
        field: 字段元数据字典

    Returns:
        True 表示封锁，False 表示可以通过
    """
    sensitivity = (field.get("sensitivity_level") or "").lower()
    return sensitivity in BLOCKED_FOR_LLM


def filter_blocked_fields(
    fields: List[Dict[str, Any]],
) -> tuple:
    """
    分离封锁字段和非封锁字段。

    Args:
        fields: 原始字段列表

    Returns:
        (allowed_fields, blocked_fields) 元组
    """
    allowed = []
    blocked = []
    for f in fields:
        if is_field_blocked(f):
            blocked.append(f)
        else:
            allowed.append(_build_safe_field(f))
    return allowed, blocked


class FieldSanitizer:
    """
    字段净化器（面向对象接口）。

    适用于需要维护状态的场景（如多次调用间共享配置）。
    """

    def __init__(
        self,
        blocked_levels: Optional[Set[str]] = None,
        max_enum_values: int = MAX_ENUM_VALUES,
        max_enum_value_length: int = MAX_ENUM_VALUE_LENGTH,
    ):
        """
        Args:
            blocked_levels: 封锁的敏感级别集合
            max_enum_values: 最多保留的枚举值数量
            max_enum_value_length: 单个枚举值的最大字符数
        """
        self.blocked_levels = blocked_levels or BLOCKED_FOR_LLM
        self.max_enum_values = max_enum_values
        self.max_enum_value_length = max_enum_value_length

    def sanitize(self, fields: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """净化字段列表"""
        return sanitize_fields_for_llm(fields, self.blocked_levels)

    def is_blocked(self, field: Dict[str, Any]) -> bool:
        """检查字段是否封锁"""
        sensitivity = (field.get("sensitivity_level") or "").lower()
        return sensitivity in self.blocked_levels

    def filter(self, fields: List[Dict[str, Any]]) -> tuple:
        """分离封锁和非封锁字段"""
        allowed = []
        blocked = []
        for f in fields:
            if self.is_blocked(f):
                blocked.append(f)
            else:
                allowed.append(_build_safe_field(f))
        return allowed, blocked

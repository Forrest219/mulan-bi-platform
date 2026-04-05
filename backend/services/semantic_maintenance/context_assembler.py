"""上下文组装器（Spec 12 §3 — P0 前置实现）

将 Token 计算、字段序列化、优先级截断、敏感度过滤等上下文组装逻辑
从 service.py 抽取为独立类，符合 Spec 12 §2.2 模块职责边界规范。

Priority Levels（Spec 12 §3.4）：
    P0: 核心度量字段（is_core_field=True 且 role=measure）
    P1: 核心维度字段（is_core_field=True 且 role=dimension）
    P2: 普通度量字段（role=measure）
    P3: 普通维度字段（role=dimension）
    P4: 计算字段（有 formula）
    P5: 其他字段
"""
import logging
from typing import List, Dict, Any, Optional

logger = logging.getLogger(__name__)

# Token 预算常量（Spec 12 §3.2）
SYSTEM_PROMPT_TOKENS = 200   # System Prompt 预留
USER_INSTRUCTION_TOKENS = 300  # User Instruction 预留
MAX_CONTEXT_TOKENS = 3000     # 单次调用上下文上限

# Blocked sensitivity levels for AI processing (Spec 12 §9.1)
BLOCKED_FOR_LLM = {"high", "confidential"}

# Priority rank (lower = higher priority)
_PRIORITY_RANK = {
    "P0": 0,  # 核心度量
    "P1": 1,  # 核心维度
    "P2": 2,  # 普通度量
    "P3": 3,  # 普通维度
    "P4": 4,  # 计算字段
    "P5": 5,  # 其他
}


def _get_token_estimator():
    """
    获取 Token 估算器。

    优先使用 tiktoken（OpenAI 官方），若无则回退到保守字符截断。
    Spec 12 §3.2 OI-02 要求精确估算，此处引入 tiktoken。
    """
    try:
        import tiktoken
        # 默认使用 cl100k_base（GPT-4/3.5 同款）
        enc = tiktoken.get_encoding("cl100k_base")
        return enc
    except ImportError:
        logger.warning(
            "tiktoken 未安装，Token 估算将使用保守字符截断策略（可能比实际 token 多估算约 20%%）。"
            "建议安装：pip install tiktoken"
        )
        return None


def estimate_tokens(text: str, encoder=None) -> int:
    """
    估算文本的 token 数量。

    - 有 tiktoken 时：用 encoder.encode() 长度（精确）
    - 无 tiktoken 时：按 Spec 12 §3.2 规则估算
      - 中文字符：约 1.5 token/字
      - 英文单词：约 1.3 token/word
      - JSON 结构符号：按字符数 * 1.0
    """
    if not text:
        return 0

    if encoder is not None:
        return len(encoder.encode(text))

    # 保守估算：无 tiktoken 时的回退方案
    chinese_chars = sum(1 for c in text if ord(c) > 127)
    english_chars = len(text) - chinese_chars
    # 估算：中文 1.5 token/字，英文 1.3 token/字
    return int(chinese_chars * 1.5 + english_chars * 1.3)


def _classify_priority(field: Dict[str, Any]) -> str:
    """
    根据字段属性返回优先级标签。

    Priority Levels（Spec 12 §3.4）：
        P0: 核心度量字段（is_core_field=True 且 role=measure）
        P1: 核心维度字段（is_core_field=True 且 role=dimension）
        P2: 普通度量字段（role=measure）
        P3: 普通维度字段（role=dimension）
        P4: 计算字段（有 formula）
        P5: 其他字段
    """
    is_core = field.get("is_core_field", False)
    role = field.get("role", "")
    has_formula = bool(field.get("formula"))

    if is_core and role == "measure":
        return "P0"
    elif is_core and role == "dimension":
        return "P1"
    elif role == "measure":
        return "P2"
    elif role == "dimension":
        return "P3"
    elif has_formula:
        return "P4"
    else:
        return "P5"


def serialize_field(field: Dict[str, Any], truncate_formula: bool = False) -> str:
    """
    将字段序列化为 Prompt 上下文字符串（Spec 12 §3.3）。

    格式：- {field_name} ({field_caption}) [{data_type}] [{role}] 公式: {formula}

    Args:
        field: 字段元数据字典
        truncate_formula: True 时截断公式（用于 P2/P3 级别截断）
    """
    field_name = field.get("field_name", "")
    field_caption = field.get("field_caption", "")
    data_type = field.get("data_type", "")
    role = field.get("role", "")
    formula = field.get("formula") or ""

    line = f"- {field_name}"
    if field_caption:
        line += f" ({field_caption})"
    line += f" [{data_type}] [{role}]"

    if formula:
        if truncate_formula:
            # P2/P3 截断：仅保留公式类型标识，不保留全文
            line += " [公式已截断]"
        else:
            line += f" 公式: {formula}"

    return line


def sanitize_fields_for_llm(
    fields: List[Dict[str, Any]],
    blocked_levels: Optional[set] = None,
) -> List[Dict[str, Any]]:
    """
    上下文净化（Spec 12 §9.2）：过滤 HIGH/CONFIDENTIAL 敏感级别字段。

    净化规则：
    1. 移除 sensitivity_level 为 HIGH/CONFIDENTIAL 的字段
    2. enum_values 最多保留 20 个示例值
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

        safe_field = {
            "field_name": f.get("field_name"),
            "field_caption": f.get("field_caption"),
            "data_type": f.get("data_type"),
            "role": f.get("role"),
            "formula": f.get("formula"),  # 公式是元数据，允许
        }

        # 枚举值截断（Spec 12 §9.2：最多 20 个示例值）
        enum_values = f.get("enum_values")
        if enum_values:
            safe_field["enum_values"] = enum_values[:20]

        sanitized.append(safe_field)

    return sanitized


def truncate_context(
    fields: List[Dict[str, Any]],
    budget_tokens: int,
    encoder=None,
) -> List[Dict[str, Any]]:
    """
    按优先级截断字段元数据，确保序列化后不超过 Token 预算（Spec 12 §3.4）。

    截断算法（伪代码来自 Spec 12 §3.4）：
    1. 按优先级分组
    2. 从 P0 开始逐级添加字段
    3. 添加前检查 Token 预算，超出则停止

    Args:
        fields: 字段元数据列表
        budget_tokens: 最大可用 Token 数
        encoder: tiktoken 编码器（可选）

    Returns:
        截断后的字段列表（保留原始字段结构，非序列化字符串）
    """
    if not fields:
        return []

    # 按优先级分类
    from collections import defaultdict
    groups = defaultdict(list)
    for f in fields:
        priority = _classify_priority(f)
        groups[priority].append(f)

    result = []
    used_tokens = 0

    for priority_label in ["P0", "P1", "P2", "P3", "P4", "P5"]:
        group = groups.get(priority_label, [])
        # P2 及以上截断公式，P3 及以下保留公式
        truncate_formula = priority_label in ("P2", "P3", "P4")

        for field in group:
            line = serialize_field(field, truncate_formula=truncate_formula)
            line_tokens = estimate_tokens(line, encoder)

            if used_tokens + line_tokens > budget_tokens:
                # 预算用尽，停止添加
                return result

            result.append(field)
            used_tokens += line_tokens

    return result


class ContextAssembler:
    """
    上下文组装器（Spec 12 §2.1/§3）。

    职责：
    - Token 预算管理（3000 上限，Spec 12 §3.2）
    - 字段序列化（Spec 12 §3.3）
    - 优先级截断（Spec 12 §3.4 P0-P5）
    - 敏感度过滤（Spec 12 §9.2 sanitize_fields_for_llm）

    不涉及：
    - 直接操作数据库
    - LLM 调用
    """

    # System Prompt 模板（Spec 12 §4.2）
    SYSTEM_PROMPT_FIELD = "你是一个专业的 BI 字段语义专家。"
    SYSTEM_PROMPT_DS = "你是一个专业的 BI 数据语义专家。"

    def __init__(self, encoder=None):
        """
        Args:
            encoder: tiktoken 编码器实例（可选，用于精确 Token 估算）
        """
        self.encoder = encoder or _get_token_estimator()

    def estimate_tokens(self, text: str) -> int:
        """对外暴露的 Token 估算接口"""
        return estimate_tokens(text, self.encoder)

    def serialize_field(self, field: Dict[str, Any], truncate_formula: bool = False) -> str:
        """对外暴露的字段序列化接口"""
        return serialize_field(field, truncate_formula)

    def sanitize_fields(self, fields: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        净化字段列表，移除敏感字段（Spec 12 §9.2）。

        Args:
            fields: 原始字段列表

        Returns:
            净化后的字段列表
        """
        return sanitize_fields_for_llm(fields)

    def build_field_context(
        self,
        fields: List[Dict[str, Any]],
        max_tokens: int = None,
    ) -> str:
        """
        构建字段元数据上下文字符串（含截断）。

        在 max_tokens 预算内尽可能多地包含字段，优先保留高优先级字段。

        Args:
            fields: 字段元数据列表（应先调用 sanitize_fields 净化）
            max_tokens: 最大 Token 预算，默认 DATA_CONTEXT_TOKENS

        Returns:
            序列化的字段上下文字符串
        """
        if max_tokens is None:
            max_tokens = MAX_CONTEXT_TOKENS - SYSTEM_PROMPT_TOKENS - USER_INSTRUCTION_TOKENS

        # 先截断
        truncated = truncate_context(fields, max_tokens, self.encoder)

        # 序列化
        lines = [serialize_field(f) for f in truncated]
        return "\n".join(lines) if lines else "无字段信息"

    def build_datasource_context(
        self,
        ds_name: str,
        description: str,
        existing_semantic_name: str,
        existing_semantic_name_zh: str,
        fields: List[Dict[str, Any]],
    ) -> str:
        """
        构建数据源语义生成的 Data Context Block（Spec 12 §4.3 模板格式）。

        Args:
            ds_name: 数据源名称
            description: 数据源描述
            existing_semantic_name: 现有英文语义名
            existing_semantic_name_zh: 现有中文语义名
            fields: 字段元数据列表

        Returns:
            完整的 Data Context Block 字符串
        """
        field_text = self.build_field_context(fields)
        return f"""## 数据源信息
名称：{ds_name}
描述：{description or '无'}
现有语义名：{existing_semantic_name or '无'}
现有中文名：{existing_semantic_name_zh or '无'}

## 字段列表
{field_text}"""

    def build_field_context_for_ds(
        self,
        field_context: List[Dict[str, Any]],
    ) -> str:
        """
        构建数据源 AI 生成中的字段上下文字符串。

        此方法用于已有 field_context 传入的场景（如 generate_ai_draft_datasource）。

        Args:
            field_context: 字段上下文列表（来自 API 调用方）

        Returns:
            序列化后的字段列表字符串
        """
        # 对 field_context 进行净化和截断
        sanitized = self.sanitize_fields(field_context)
        max_tokens = MAX_CONTEXT_TOKENS - SYSTEM_PROMPT_TOKENS - USER_INSTRUCTION_TOKENS
        return self.build_field_context(sanitized, max_tokens)

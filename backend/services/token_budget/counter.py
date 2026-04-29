"""Token 计数器 — tiktoken 封装 + 模型 → 编码器映射（Spec 12 §18.3）

全局编码器缓存（Spec 12 §18.12 架构红线：tiktoken 必须全局缓存）。
"""
import logging
from typing import Dict, Optional

logger = logging.getLogger(__name__)

# 全局编码器缓存（Spec 12 §18.12 红线：必须全局缓存，不要每次 get_encoding）
_ENCODER_CACHE: Dict[str, "tiktoken.Encoding"] = {}

# 已知的 cl100k_base 兼容模型（GPT-4/3.5/DeepSeek 等均用同款编码器）
# 用于 model → encoding_name 映射
_ENCODER_MODEL_MAP: Dict[str, str] = {
    # OpenAI
    "gpt-4o": "cl100k_base",
    "gpt-4o-mini": "cl100k_base",
    "gpt-4-turbo": "cl100k_base",
    "gpt-4": "cl100k_base",
    "gpt-3.5-turbo": "cl100k_base",
    # Anthropic
    "claude-sonnet-4": "cl100k_base",
    "claude-3-5-sonnet": "cl100k_base",
    "claude-3-opus": "cl100k_base",
    "claude-3-sonnet": "cl100k_base",
    # DeepSeek
    "deepseek-v3": "cl100k_base",
    "deepseek-coder": "cl100k_base",
    # 兼容接口
    "cl100k_base": "cl100k_base",
}


def _get_encoder(encoding_name: str = "cl100k_base") -> Optional["tiktoken.Encoding"]:
    """
    获取 tiktoken 编码器实例（带缓存）。

    Args:
        encoding_name: 编码器名称，默认 cl100k_base

    Returns:
        tiktoken.Encoding 实例，或 None（tiktoken 未安装）
    """
    if encoding_name not in _ENCODER_CACHE:
        try:
            import tiktoken
            _ENCODER_CACHE[encoding_name] = tiktoken.get_encoding(encoding_name)
            logger.debug("tiktoken 编码器 '%s' 已缓存", encoding_name)
        except ImportError:
            logger.warning(
                "tiktoken 未安装，Token 计数将使用字符估算（不精确）。"
                "建议安装：pip install tiktoken"
            )
            return None
        except Exception as e:
            logger.error("tiktoken 初始化失败: %s", e)
            return None
    return _ENCODER_CACHE.get(encoding_name)


def clear_encoder_cache() -> None:
    """清除编码器缓存（用于测试或 key rotation 场景）"""
    global _ENCODER_CACHE
    _ENCODER_CACHE.clear()


class TokenCounter:
    """
    Token 计数器（Spec 12 §18.3）。

    使用全局缓存的 tiktoken 编码器，支持 model → encoding 映射。
    """

    def __init__(self, encoding_name: str = "cl100k_base"):
        """
        Args:
            encoding_name: 编码器名称，默认 cl100k_base
        """
        self.encoding_name = encoding_name
        self._encoder = _get_encoder(encoding_name)

    @classmethod
    def for_model(cls, model: str) -> "TokenCounter":
        """
        根据模型名推断编码器并创建计数器。

        Args:
            model: 模型名（如 "gpt-4o"、"claude-sonnet-4"）

        Returns:
            TokenCounter 实例
        """
        encoding_name = _ENCODER_MODEL_MAP.get(model, "cl100k_base")
        return cls(encoding_name=encoding_name)

    def count(self, text: str) -> int:
        """
        计算文本的 token 数量。

        - 有 tiktoken 时：用 encoder.encode() 长度（精确）
        - 无 tiktoken 时：回退到保守字符估算（中文字符 2.0 token/字）

        Args:
            text: 待计数文本

        Returns:
            token 数量
        """
        if not text:
            return 0

        if self._encoder is not None:
            return len(self._encoder.encode(text))

        # 保守估算（无 tiktoken 时）
        chinese_chars = sum(1 for c in text if ord(c) > 127)
        english_chars = len(text) - chinese_chars
        return int(chinese_chars * 2.0 + english_chars * 1.3)

    def count_batch(self, texts: list[str]) -> list[int]:
        """批量计数"""
        return [self.count(t) for t in texts]

"""Payload 脱敏模块（移除 PII / Token 等敏感信息）"""
import re
from typing import Dict, Any


# 敏感字段名模式（大小写不敏感）
SENSITIVE_FIELD_PATTERNS = [
    re.compile(r"password", re.IGNORECASE),
    re.compile(r"secret", re.IGNORECASE),
    re.compile(r"token", re.IGNORECASE),
    re.compile(r"api_key", re.IGNORECASE),
    re.compile(r"apikey", re.IGNORECASE),
    re.compile(r"auth", re.IGNORECASE),
    re.compile(r"credential", re.IGNORECASE),
    re.compile(r"private_key", re.IGNORECASE),
    re.compile(r"bearer", re.IGNORECASE),
]

# 脱敏占位符
REDACTED = "[REDACTED]"


def redact_payload(payload: Dict[str, Any]) -> Dict[str, Any]:
    """
    对 payload 进行脱敏处理，返回新 dict（不修改原对象）。
    规则：
    - 字段名匹配 SENSITIVE_FIELD_PATTERNS → 值替换为 [REDACTED]
    - 值中出现的 Token/Key 格式（如 sk-xxx, Bearer xxx）→ 替换为 [REDACTED]
    """
    result = {}

    for key, value in payload.items():
        # 检查字段名是否敏感
        is_sensitive = any(p.search(key) for p in SENSITIVE_FIELD_PATTERNS)

        if is_sensitive:
            result[key] = REDACTED
        elif isinstance(value, dict):
            result[key] = redact_payload(value)
        elif isinstance(value, str):
            result[key] = _redact_string(value)
        else:
            result[key] = value

    return result


def _redact_string(s: str) -> str:
    """对字符串中可能存在的 token 进行脱敏"""
    # 脱敏常见的 token 格式
    # OpenAI key: sk-... 或 sk-prod-...
    s = re.sub(r'sk-[A-Za-z0-9_-]{20,}', REDACTED, s)
    # Generic Bearer token
    s = re.sub(r'Bearer [A-Za-z0-9_-]{20,}', f'Bearer {REDACTED}', s)
    # Generic API key patterns
    s = re.sub(r'[A-Za-z0-9_-]{40,}', REDACTED, s)
    return s
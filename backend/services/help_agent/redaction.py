"""Sensitive data redaction helpers for Help Agent diagnostics."""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from typing import Any


REDACTED = "******"

_SECRET_KEY_MARKERS = (
    "password",
    "passwd",
    "pwd",
    "secret",
    "private_key",
    "private key",
)
_SECRET_EXACT_KEYS = {"pat", "pat_secret"}
_TOKEN_KEY_MARKERS = ("token", "access_token", "refresh_token", "api_key", "apikey")
_DROP_VALUE_KEY_MARKERS = ("authorization", "cookie", "set-cookie")

_PRIVATE_KEY_BLOCK_RE = re.compile(
    r"-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----[\s\S]*?-----END [A-Z0-9 ]*PRIVATE KEY-----"
)
_KEY_VALUE_RE = re.compile(
    r"(?i)\b(password|passwd|pwd|pat_secret|pat|secret|access_token|refresh_token|api_key|apikey|token)\b"
    r"(\s*[:=]\s*)"
    r"([^\s,;&\"']+)"
)
_HEADER_RE = re.compile(r"(?im)\b(authorization|cookie|set-cookie)\b(\s*[:=]\s*)[^\r\n]*")
_MEMORY_ADDRESS_RE = re.compile(r"0x[0-9a-fA-F]{6,16}")


def redact_value(value: Any) -> Any:
    """Return a copy of value with known secret-bearing fields redacted."""
    if isinstance(value, Mapping):
        return {key: _redact_mapping_value(str(key), item) for key, item in value.items()}
    if isinstance(value, tuple):
        return tuple(redact_value(item) for item in value)
    if isinstance(value, list):
        return [redact_value(item) for item in value]
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [redact_value(item) for item in value]
    if isinstance(value, bytes):
        return redact_text(value.decode("utf-8", errors="replace"))
    if isinstance(value, str):
        return redact_text(value)
    return value


def redact(value: Any) -> Any:
    """Compatibility entry point used by Help Agent tools."""
    return redact_value(value)


def redact_text(text: str) -> str:
    """Redact sensitive tokens from free-form text without returning original secrets."""
    if not text:
        return text

    redacted = _PRIVATE_KEY_BLOCK_RE.sub(REDACTED, text)
    redacted = _HEADER_RE.sub(lambda match: f"{match.group(1)}{match.group(2)}{REDACTED}", redacted)
    redacted = _KEY_VALUE_RE.sub(_redact_key_value_match, redacted)
    return _MEMORY_ADDRESS_RE.sub("0x******", redacted)


def _redact_mapping_value(key: str, value: Any) -> Any:
    normalized = key.lower().replace("-", "_")
    if any(marker in normalized for marker in _DROP_VALUE_KEY_MARKERS):
        return REDACTED
    if normalized in _SECRET_EXACT_KEYS or any(marker in normalized for marker in _SECRET_KEY_MARKERS):
        return REDACTED
    if any(marker in normalized for marker in _TOKEN_KEY_MARKERS):
        if isinstance(value, str):
            return _mask_token(value)
        return REDACTED
    return redact_value(value)


def _redact_key_value_match(match: re.Match[str]) -> str:
    key = match.group(1)
    sep = match.group(2)
    raw_value = match.group(3)
    normalized = key.lower()
    if "token" in normalized or normalized in {"api_key", "apikey"}:
        return f"{key}{sep}{_mask_token(raw_value)}"
    return f"{key}{sep}{REDACTED}"


def _mask_token(token: str) -> str:
    if len(token) <= 8:
        return REDACTED
    return f"{token[:4]}{REDACTED}{token[-4:]}"

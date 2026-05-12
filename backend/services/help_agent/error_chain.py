"""Read structured error chains for Help Agent tools."""

from __future__ import annotations

import re
from typing import Any, Mapping

from services.help_agent.redaction import redact_text, redact_value


LEGACY_MAX_CHARS = 5000

_EXCEPTION_LINE_RE = re.compile(r"^\s*([A-Za-z_][\w.]*?(?:Error|Exception|Timeout|Failure))\s*:\s*(.{0,1000})\s*$")
_ERROR_CODE_RE = re.compile(r"\b([A-Z][A-Z0-9_]{2,}_[0-9]{3,}|[A-Z]{2,}[0-9]{3,})\b")
_FRAME_RE = re.compile(r"File \"([^\"]{0,500})\", line \d+, in ([A-Za-z_][\w]*)")


def read_structured_error(
    *,
    structured_error: Mapping[str, Any] | None = None,
    legacy_error_text: str | None = None,
    source: str | None = None,
) -> dict:
    """Prefer stored StructuredBIError JSON, fallback to bounded legacy parsing."""
    if structured_error:
        payload = dict(redact_value(structured_error))
        payload.setdefault("source", "structured_error")
        payload["redaction_applied"] = True
        return payload

    return _read_legacy_error(legacy_error_text or "", source=source)


def _read_legacy_error(error_text: str, *, source: str | None = None) -> dict:
    bounded = redact_text(str(error_text)[:LEGACY_MAX_CHARS])
    lines = [line.strip() for line in bounded.splitlines() if line.strip()]

    match = None
    for line in reversed(lines[-80:]):
        match = _EXCEPTION_LINE_RE.match(line)
        if match:
            break

    if not match:
        return {
            "error_type": "Unknown",
            "message": "无法从 legacy 字符串提取结构化错误链，已保留脱敏后的错误摘要。",
            "source": "legacy_fallback_failed",
            "legacy_source": source,
            "summary": bounded[:500],
            "redaction_applied": True,
        }

    error_type = match.group(1).rsplit(".", 1)[-1]
    message = match.group(2)[:1000]
    code_match = _ERROR_CODE_RE.search(bounded)
    frames = _extract_business_frames(lines)
    return {
        "error_type": error_type,
        "error_code": code_match.group(1) if code_match else None,
        "message": message,
        "caused_by": [{"type": error_type, "message": message}],
        "sql_error": None,
        "timeout_target": error_type if "timeout" in error_type.lower() else None,
        "business_frames": frames,
        "source": "legacy_fallback",
        "legacy_source": source,
        "redaction_applied": True,
    }


def _extract_business_frames(lines: list[str]) -> list[str] | None:
    frames: list[str] = []
    for line in lines:
        match = _FRAME_RE.search(line)
        if not match:
            continue
        path, func = match.groups()
        normalized = path.replace("\\", "/")
        marker = "/services/"
        if marker not in normalized:
            continue
        module_path = normalized.split(marker, 1)[1].rsplit(".", 1)[0].replace("/", ".")
        frames.append(redact_text(f"services.{module_path}.{func}"))
    return frames[-5:] or None

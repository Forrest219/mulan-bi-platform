"""Preview result redaction for Data Explorer."""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from copy import deepcopy
from typing import Any


MASK = "******"

_PASSWORD_NAMES = {"password", "passwd", "pwd", "mima", "密码"}
_SECRET_NAMES = {"token", "secret", "api_key"}
_PHONE_NAMES = {
    "phone",
    "mobile",
    "tel",
    "telephone",
    "shouji",
    "dianhua",
    "手机",
    "电话",
}
_EMAIL_NAMES = {"email"}
_ID_NAMES = {"id_card", "idcard", "ssn", "shenfenzheng", "身份证", "证件号"}

_SHORT_EXACT_NAMES = {"pwd", "tel", "ssn"}
_TOKEN_SPLIT_RE = re.compile(r"[^0-9A-Za-z\u4e00-\u9fff]+")


def redact_preview(columns: Sequence[Any], rows: Sequence[Any]) -> dict[str, Any]:
    """Return copied columns and rows with sensitive preview values masked."""

    column_names = [_column_name(column) for column in columns]
    column_kinds = [_sensitive_kind(name) for name in column_names]
    redaction_applied = any(kind is not None for kind in column_kinds)

    return {
        "columns": deepcopy(list(columns)),
        "rows": [_redact_row(row, column_names, column_kinds) for row in rows],
        "redaction_applied": redaction_applied,
    }


def redact_preview_rows(columns: Sequence[Any], rows: Sequence[Any]) -> list[Any]:
    """Return only redacted rows for callers that already own response metadata."""

    return redact_preview(columns, rows)["rows"]


def _column_name(column: Any) -> str:
    if isinstance(column, Mapping):
        name = column.get("name", "")
    else:
        name = column
    return name if isinstance(name, str) else str(name)


def _sensitive_kind(column_name: str) -> str | None:
    normalized = column_name.casefold()
    normalized_compact = _compact_name(normalized)
    tokens = {
        token
        for token in _TOKEN_SPLIT_RE.split(normalized)
        if token
    }

    for names, kind in (
        (_PASSWORD_NAMES, "mask"),
        (_SECRET_NAMES, "mask"),
        (_PHONE_NAMES, "phone"),
        (_EMAIL_NAMES, "email"),
        (_ID_NAMES, "mask"),
    ):
        if _matches_any(normalized, normalized_compact, tokens, names):
            return kind
    return None


def _matches_any(
    normalized: str,
    normalized_compact: str,
    tokens: set[str],
    names: set[str],
) -> bool:
    for name in names:
        folded = name.casefold()
        compact = _compact_name(folded)
        if normalized == folded or normalized_compact == compact or folded in tokens:
            return True
        if folded not in _SHORT_EXACT_NAMES and compact in normalized_compact:
            return True
        if any("\u4e00" <= char <= "\u9fff" for char in folded) and folded in normalized:
            return True
    return False


def _compact_name(name: str) -> str:
    return re.sub(r"[^0-9a-z\u4e00-\u9fff]+", "", name.casefold())


def _redact_row(row: Any, column_names: Sequence[str], column_kinds: Sequence[str | None]) -> Any:
    if isinstance(row, Mapping):
        redacted = dict(row)
        lower_to_key = {str(key).casefold(): key for key in row}
        for name, kind in zip(column_names, column_kinds):
            if kind is None:
                continue
            key = name if name in row else lower_to_key.get(name.casefold())
            if key is not None:
                redacted[key] = _redact_value(row[key], kind)
        return redacted

    if isinstance(row, tuple):
        redacted_values = _redact_sequence(row, column_kinds)
        return tuple(redacted_values)

    if isinstance(row, Sequence) and not isinstance(row, (str, bytes, bytearray)):
        return _redact_sequence(row, column_kinds)

    return row


def _redact_sequence(row: Sequence[Any], column_kinds: Sequence[str | None]) -> list[Any]:
    redacted = list(row)
    for index, kind in enumerate(column_kinds):
        if kind is not None and index < len(redacted):
            redacted[index] = _redact_value(redacted[index], kind)
    return redacted


def _redact_value(value: Any, kind: str) -> Any:
    if value is None:
        return None
    if kind == "phone":
        return _mask_phone(value)
    if kind == "email":
        return _mask_email(value)
    return MASK


def _mask_phone(value: Any) -> str:
    text = str(value)
    if len(text) <= 4:
        return MASK
    return f"{'*' * (len(text) - 4)}{text[-4:]}"


def _mask_email(value: Any) -> str:
    text = str(value)
    if "@" not in text:
        return MASK

    local, domain = text.rsplit("@", 1)
    if local == "":
        masked_local = "*"
    elif len(local) == 1:
        masked_local = "*"
    else:
        masked_local = f"{local[0]}{'*' * (len(local) - 1)}"
    return f"{masked_local}@{domain}"

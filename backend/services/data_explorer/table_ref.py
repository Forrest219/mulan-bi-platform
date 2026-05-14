"""Deterministic table reference encoding for Data Explorer routes."""

from __future__ import annotations

import base64
import binascii
import re


TABLE_REF_ERROR_CODE = "DEX_001"

_TABLE_REF_ALLOWED_RE = re.compile(r"^[A-Za-z0-9_-]+$")


class TableRefError(ValueError):
    """Raised when a Data Explorer table_ref cannot be decoded safely."""

    def __init__(self, reason: str) -> None:
        self.code = TABLE_REF_ERROR_CODE
        self.reason = reason
        super().__init__(f"{self.code}: invalid table_ref: {reason}")


def encode_table_ref(schema: str, table: str) -> str:
    """Encode schema/table as base64url(utf8(schema + NUL + table)), no padding."""

    if not isinstance(schema, str) or not isinstance(table, str):
        raise TableRefError("schema and table must be strings")
    if schema == "":
        raise TableRefError("schema must not be empty")
    if table == "":
        raise TableRefError("table must not be empty")
    if "\x00" in schema or "\x00" in table:
        raise TableRefError("schema and table must not contain NUL")

    raw = f"{schema}\x00{table}".encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def decode_table_ref(table_ref: str) -> tuple[str, str]:
    """Strictly decode a table_ref into ``(schema, table)``.

    The accepted wire format is unpadded base64url only. Decoded payload must
    contain exactly one NUL separator and two non-empty UTF-8 string parts.
    """

    if not isinstance(table_ref, str):
        raise TableRefError("table_ref must be a string")
    if table_ref == "":
        raise TableRefError("table_ref must not be empty")
    if "=" in table_ref:
        raise TableRefError("padding is not allowed")
    if not _TABLE_REF_ALLOWED_RE.fullmatch(table_ref):
        raise TableRefError("table_ref must be unpadded base64url")
    if len(table_ref) % 4 == 1:
        raise TableRefError("invalid base64url length")

    padded = table_ref + ("=" * (-len(table_ref) % 4))
    try:
        raw = base64.b64decode(
            padded.encode("ascii").translate(bytes.maketrans(b"-_", b"+/")),
            validate=True,
        )
        decoded = raw.decode("utf-8")
    except (binascii.Error, UnicodeDecodeError) as exc:
        raise TableRefError("table_ref is not valid UTF-8 base64url") from exc

    parts = decoded.split("\x00")
    if len(parts) != 2:
        raise TableRefError("table_ref must contain exactly one NUL separator")

    schema, table = parts
    if schema == "":
        raise TableRefError("schema must not be empty")
    if table == "":
        raise TableRefError("table must not be empty")

    return schema, table

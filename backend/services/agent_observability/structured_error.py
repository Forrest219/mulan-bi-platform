"""Structured error representation shared by BI agent observability paths."""

from __future__ import annotations

import traceback
from dataclasses import dataclass
from typing import Any

from sqlalchemy import bindparam, text
from sqlalchemy.dialects.postgresql import JSONB

from services.help_agent.redaction import redact_text, redact_value

MAX_MESSAGE_CHARS = 1000
MAX_BUSINESS_FRAMES = 5
STRUCTURED_ERROR_TABLES = {"bi_agent_steps", "bi_task_runs", "help_agent_runs", "help_agent_steps"}


@dataclass
class StructuredBIError:
    """Redacted, serializable error shape stored in structured_error JSONB."""

    error_type: str
    message: str
    error_code: str | None = None
    caused_by: list[dict[str, Any]] | None = None
    sql_error: dict[str, Any] | None = None
    timeout_target: str | None = None
    business_frames: list[str] | None = None
    retryable: bool | None = None
    redaction_applied: bool = True

    @classmethod
    def from_exception(
        cls,
        exc: BaseException,
        *,
        error_code: str | None = None,
        retryable: bool | None = None,
        timeout_target: str | None = None,
    ) -> "StructuredBIError":
        chain = _exception_chain(exc)
        return cls(
            error_type=type(exc).__name__,
            message=_clean_message(str(exc) or type(exc).__name__),
            error_code=error_code or getattr(exc, "error_code", None),
            caused_by=chain[1:] or None,
            sql_error=_extract_sql_error(exc),
            timeout_target=timeout_target or _infer_timeout_target(exc),
            business_frames=_extract_business_frames(exc.__traceback__),
            retryable=retryable,
            redaction_applied=True,
        )

    @classmethod
    def from_message(
        cls,
        message: Any,
        *,
        error_type: str = "Error",
        error_code: str | None = None,
        retryable: bool | None = None,
    ) -> "StructuredBIError":
        return cls(
            error_type=_clean_message(error_type)[:120] or "Error",
            message=_clean_message(str(message) if message is not None else error_type),
            error_code=error_code,
            retryable=retryable,
            redaction_applied=True,
        )

    def to_dict(self) -> dict[str, Any]:
        data = {
            "error_type": self.error_type or "Unknown",
            "message": self.message or "",
            "error_code": self.error_code,
            "caused_by": self.caused_by,
            "sql_error": self.sql_error,
            "timeout_target": self.timeout_target,
            "business_frames": self.business_frames,
            "retryable": self.retryable,
            "redaction_applied": True,
        }
        return redact_value(data)


def best_effort_structured_error(value: Any, *, error_code: str | None = None) -> dict[str, Any]:
    if isinstance(value, StructuredBIError):
        return value.to_dict()
    if isinstance(value, dict):
        return redact_value(value)
    if isinstance(value, BaseException):
        return StructuredBIError.from_exception(value, error_code=error_code).to_dict()
    return StructuredBIError.from_message(value, error_code=error_code).to_dict()


def persist_structured_error(db: Any, table_name: str, row_id: Any, structured_error: Any) -> bool:
    """Best-effort JSONB update that tolerates missing migrations or ORM fields."""
    if not db or table_name not in STRUCTURED_ERROR_TABLES or row_id is None:
        return False
    if not hasattr(db, "execute"):
        return False

    payload = best_effort_structured_error(structured_error)
    try:
        stmt = text(f"UPDATE {table_name} SET structured_error = :payload WHERE id = :row_id").bindparams(
            bindparam("payload", type_=JSONB)
        )
        db.execute(
            stmt,
            {"payload": payload, "row_id": row_id},
        )
        db.commit()
        return True
    except Exception:
        try:
            db.rollback()
        except Exception:
            pass
        return False


def _exception_chain(exc: BaseException) -> list[dict[str, str]]:
    chain: list[dict[str, str]] = []
    seen: set[int] = set()
    current: BaseException | None = exc
    while current is not None and id(current) not in seen and len(chain) < 8:
        seen.add(id(current))
        chain.append({"type": type(current).__name__, "message": _clean_message(str(current))})
        current = current.__cause__ or current.__context__
    return chain


def _clean_message(message: str) -> str:
    return redact_text((message or "").replace("\x00", "")[:MAX_MESSAGE_CHARS])


def _extract_sql_error(exc: BaseException) -> dict[str, Any] | None:
    sql_error: dict[str, Any] = {}
    for attr in ("line", "column", "position"):
        value = getattr(exc, attr, None)
        if value is not None:
            sql_error[attr] = value
    return sql_error or None


def _infer_timeout_target(exc: BaseException) -> str | None:
    name = type(exc).__name__.lower()
    message = str(exc).lower()
    if "timeout" not in name and "timeout" not in message and "timed out" not in message:
        return None
    return _clean_message(getattr(exc, "timeout_target", None) or type(exc).__name__)


def _extract_business_frames(tb: Any) -> list[str] | None:
    if tb is None:
        return None
    frames: list[str] = []
    for frame in traceback.extract_tb(tb):
        filename = frame.filename.replace("\\", "/")
        marker = "/services/"
        if marker not in filename:
            continue
        module_path = filename.split(marker, 1)[1].rsplit(".", 1)[0].replace("/", ".")
        frames.append(redact_text(f"services.{module_path}.{frame.name}"))
    return frames[-MAX_BUSINESS_FRAMES:] or None

"""Capability 调用审计（Append-Only）

不会阻塞主链路：写入失败只记日志不抛。
"""
import json
import logging
import uuid
from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import Optional

from sqlalchemy import text

from app.core.database import SessionLocal

logger = logging.getLogger(__name__)

_trace_id_var: ContextVar[Optional[str]] = ContextVar("capability_trace_id", default=None)
_principal_var: ContextVar[Optional[dict]] = ContextVar("capability_principal", default=None)


def new_trace_id() -> str:
    """生成新 trace_id 并设置到 context"""
    tid = uuid.uuid4().hex[:16]
    _trace_id_var.set(tid)
    return tid


def get_trace_id() -> Optional[str]:
    """获取当前 context 的 trace_id"""
    return _trace_id_var.get()


def set_principal(principal: dict) -> None:
    """设置当前请求的 principal 到 context（供下游调用链路获取）"""
    _principal_var.set(principal)


def get_principal() -> Optional[dict]:
    """获取当前 context 的 principal"""
    return _principal_var.get()


@dataclass
class InvocationRecord:
    trace_id: str
    principal_id: int
    principal_role: str
    capability: str
    params_jsonb: dict = field(default_factory=dict)
    status: str = "ok"  # allowed | denied | failed | ok
    error_code: Optional[str] = None
    error_detail: Optional[str] = None
    latency_ms: Optional[int] = None
    mcp_call_id: Optional[int] = None
    llm_tokens_in: Optional[int] = None
    llm_tokens_out: Optional[int] = None
    redacted_fields: Optional[list[str]] = None


def write_audit(rec: InvocationRecord) -> None:
    """Append-Only 写入审计记录。

    失败只记日志不抛，避免审计路径阻塞主链路。
    """
    db = SessionLocal()
    try:
        db.execute(
            text("""
                INSERT INTO bi_capability_invocations
                (trace_id, principal_id, principal_role, capability, params_jsonb,
                 status, error_code, error_detail, latency_ms, mcp_call_id,
                 llm_tokens_in, llm_tokens_out, redacted_fields)
                VALUES
                (:trace_id, :principal_id, :principal_role, :capability,
                 CAST(:params_jsonb AS JSONB),
                 :status, :error_code, :error_detail, :latency_ms, :mcp_call_id,
                 :llm_tokens_in, :llm_tokens_out, CAST(:redacted_fields AS JSONB))
            """),
            {
                "trace_id": rec.trace_id,
                "principal_id": rec.principal_id,
                "principal_role": rec.principal_role,
                "capability": rec.capability,
                "params_jsonb": json.dumps(rec.params_jsonb, ensure_ascii=False, default=str),
                "status": rec.status,
                "error_code": rec.error_code,
                "error_detail": (rec.error_detail or "")[:2000],
                "latency_ms": rec.latency_ms,
                "mcp_call_id": rec.mcp_call_id,
                "llm_tokens_in": rec.llm_tokens_in,
                "llm_tokens_out": rec.llm_tokens_out,
                "redacted_fields": json.dumps(rec.redacted_fields) if rec.redacted_fields else None,
            },
        )
        db.commit()
    except Exception as e:
        logger.error("审计写入失败 trace_id=%s: %s", rec.trace_id, e)
    finally:
        db.close()

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping, Optional


DETAIL_SCAN_BLOCKED = "DETAIL_SCAN_BLOCKED"
RESULT_FIELD_MISSING = "RESULT_FIELD_MISSING"
RESULT_GRAIN_MISMATCH = "RESULT_GRAIN_MISMATCH"
SEMANTIC_QA_FAILED = "SEMANTIC_QA_FAILED"


def _norm(value: Any) -> str:
    return str(value or "").strip().casefold()


def _field_name(field: Any) -> str:
    if isinstance(field, Mapping):
        return str(field.get("name") or field.get("fieldCaption") or "")
    return str(field or "")


def _row_count(result: Mapping[str, Any]) -> int:
    rows = result.get("rows")
    return len(rows) if isinstance(rows, list) else 0


def _is_aggregate_like(operator: str) -> bool:
    return operator in {
        "aggregate",
        "ranking",
        "trend_condition",
        "set_difference",
        "consecutive_growth",
        "all_period_condition",
        "customer_record",
        "root_cause",
    }


@dataclass
class GuardrailCheck:
    name: str
    status: str
    detail: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {"name": self.name, "status": self.status, "detail": self.detail}


@dataclass
class ResultGuardrailOutput:
    decision: str
    semantic_status: str
    error_code: Optional[str]
    message: str
    checks: list[GuardrailCheck]

    def to_dict(self) -> dict[str, Any]:
        return {
            "decision": self.decision,
            "semantic_status": self.semantic_status,
            "error_code": self.error_code,
            "message": self.message,
            "checks": [check.to_dict() for check in self.checks],
        }


@dataclass
class ResultGuardrailInput:
    question: str
    chain_mode: str
    fallback_triggered: bool
    fallback_reason: Optional[str]
    semantic_operator: str
    context_snapshot: Mapping[str, Any]
    tool_name: str
    safe_args: Mapping[str, Any]
    result: Mapping[str, Any]
    thresholds: Mapping[str, Any]


def evaluate_result_guardrail(payload: ResultGuardrailInput) -> ResultGuardrailOutput:
    checks: list[GuardrailCheck] = []
    thresholds = dict(payload.thresholds or {})
    max_detail_rows = int(thresholds.get("max_detail_rows") or 200)
    row_count = _row_count(payload.result)
    metadata = payload.result.get("metadata") if isinstance(payload.result.get("metadata"), Mapping) else {}
    truncated = bool(metadata.get("truncated_by_guardrail"))

    semantic_operator = _norm(payload.semantic_operator)
    if payload.tool_name == "query-datasource" and _is_aggregate_like(semantic_operator):
        if truncated:
            checks.append(GuardrailCheck("detail_scan", "fail", {"truncated_by_guardrail": True}))
            return ResultGuardrailOutput(
                decision="block",
                semantic_status="semantic_fail",
                error_code=DETAIL_SCAN_BLOCKED,
                message="结果触发资源闸口截断，已阻断明细扫描型回答。",
                checks=checks,
            )
        if row_count > max_detail_rows:
            checks.append(GuardrailCheck("detail_scan", "fail", {"row_count": row_count, "max_detail_rows": max_detail_rows}))
            return ResultGuardrailOutput(
                decision="block",
                semantic_status="semantic_fail",
                error_code=DETAIL_SCAN_BLOCKED,
                message="结果行数超过首页问数阈值，已阻断明细扫描型回答。",
                checks=checks,
            )
    checks.append(GuardrailCheck("detail_scan", "pass", {"row_count": row_count, "max_detail_rows": max_detail_rows}))

    required_fields = payload.thresholds.get("required_fields") if isinstance(payload.thresholds.get("required_fields"), list) else []
    if required_fields:
        actual_fields = {_norm(_field_name(field)) for field in list(payload.result.get("fields") or [])}
        missing = [field for field in required_fields if _norm(field) not in actual_fields]
        if missing:
            checks.append(GuardrailCheck("required_fields", "fail", {"missing": missing}))
            return ResultGuardrailOutput(
                decision="review",
                semantic_status="semantic_fail",
                error_code=RESULT_FIELD_MISSING,
                message="结果缺少核心字段，需要复核。",
                checks=checks,
            )
        checks.append(GuardrailCheck("required_fields", "pass", {"required": required_fields}))

    if payload.fallback_triggered:
        checks.append(GuardrailCheck("fallback_default_review", "review", {"fallback_reason": payload.fallback_reason}))
        return ResultGuardrailOutput(
            decision="review",
            semantic_status="needs_review",
            error_code=None,
            message="Fallback 结果默认需要人工复核。",
            checks=checks,
        )

    return ResultGuardrailOutput(
        decision="allow",
        semantic_status="semantic_pass",
        error_code=None,
        message="结果通过 Result Guardrail。",
        checks=checks,
    )

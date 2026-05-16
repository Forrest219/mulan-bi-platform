"""Data QA drift alert evaluation."""

from __future__ import annotations

from dataclasses import dataclass


SCHEMA_DRIFT_ALERT = "SCHEMA_DRIFT_ALERT"


@dataclass(frozen=True)
class SchemaDriftEvaluation:
    alert: bool
    code: str | None
    ci_passed: bool
    nightly_total: int
    nightly_failed: int
    failure_rate: float
    failure_threshold: float
    min_cases: int
    freeze_golden_pass: bool
    reason: str

    def to_dict(self) -> dict:
        return {
            "alert": self.alert,
            "code": self.code,
            "ci_passed": self.ci_passed,
            "nightly_total": self.nightly_total,
            "nightly_failed": self.nightly_failed,
            "failure_rate": self.failure_rate,
            "failure_threshold": self.failure_threshold,
            "min_cases": self.min_cases,
            "freeze_golden_pass": self.freeze_golden_pass,
            "reason": self.reason,
        }


def evaluate_schema_drift_alert(
    *,
    ci_passed: bool,
    nightly_total: int,
    nightly_failed: int,
    failure_threshold: float = 0.3,
    min_cases: int = 5,
) -> SchemaDriftEvaluation:
    """Trigger drift only when mocked CI is green and nightly real-chain failures are broad."""

    if nightly_total < 0 or nightly_failed < 0:
        raise ValueError("nightly_total and nightly_failed must be non-negative")
    if nightly_failed > nightly_total:
        raise ValueError("nightly_failed cannot exceed nightly_total")
    if not 0 < failure_threshold <= 1:
        raise ValueError("failure_threshold must be in (0, 1]")
    if min_cases < 1:
        raise ValueError("min_cases must be positive")

    failure_rate = nightly_failed / nightly_total if nightly_total else 0.0
    alert = ci_passed and nightly_total >= min_cases and failure_rate >= failure_threshold

    if not ci_passed:
        reason = "ci_not_green"
    elif nightly_total < min_cases:
        reason = "insufficient_nightly_cases"
    elif failure_rate < failure_threshold:
        reason = "nightly_failure_rate_below_threshold"
    else:
        reason = "ci_green_nightly_broad_failure"

    return SchemaDriftEvaluation(
        alert=alert,
        code=SCHEMA_DRIFT_ALERT if alert else None,
        ci_passed=ci_passed,
        nightly_total=nightly_total,
        nightly_failed=nightly_failed,
        failure_rate=failure_rate,
        failure_threshold=failure_threshold,
        min_cases=min_cases,
        freeze_golden_pass=alert,
        reason=reason,
    )

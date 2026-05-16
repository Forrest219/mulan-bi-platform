"""Governance checks for temporary virtual metrics.

This module validates the escape-hatch metadata only. It does not execute
business formulas or add another calculation authority.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import Any


VIRTUAL_METRICS_REGISTRY = "Virtual Metrics Registry"

REQUIRED_FIELDS = (
    "name",
    "owner",
    "formula",
    "formula_version",
    "formula_source",
    "approver",
    "expires_at",
    "migration_plan",
    "test_refs",
)


@dataclass(frozen=True)
class VirtualMetricValidation:
    ok: bool
    errors: tuple[str, ...]
    metadata: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "errors": list(self.errors),
            "metadata": self.metadata,
        }


def validate_virtual_metric_entry(entry: dict[str, Any], *, now: datetime | None = None) -> VirtualMetricValidation:
    """Validate approval, TTL, formula provenance, migration plan and test coverage."""

    current = now or datetime.now(timezone.utc)
    errors: list[str] = []

    for field in REQUIRED_FIELDS:
        value = entry.get(field)
        if value is None or value == "" or value == []:
            errors.append(f"missing_{field}")

    expires_at = _parse_expires_at(entry.get("expires_at"))
    if entry.get("expires_at") and expires_at is None:
        errors.append("invalid_expires_at")
    elif expires_at is not None and expires_at <= current:
        errors.append("expired_ttl")

    if entry.get("formula_source") not in {"tableau", "business_approved_spec", "legacy_metric_contract"}:
        errors.append("invalid_formula_source")

    test_refs = entry.get("test_refs")
    if test_refs is not None and not isinstance(test_refs, list):
        errors.append("invalid_test_refs")

    metadata = {
        "metric_registry": VIRTUAL_METRICS_REGISTRY,
        "metric_name": entry.get("name"),
        "formula_version": entry.get("formula_version"),
        "formula_source": entry.get("formula_source"),
        "owner": entry.get("owner"),
        "approver": entry.get("approver"),
        "expires_at": entry.get("expires_at"),
        "temporary_escape_hatch": True,
    }

    return VirtualMetricValidation(ok=not errors, errors=tuple(errors), metadata=metadata)


def _parse_expires_at(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if isinstance(value, date):
        return datetime(value.year, value.month, value.day, tzinfo=timezone.utc)
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)

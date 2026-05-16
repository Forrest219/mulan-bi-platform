"""Tests for Virtual Metrics Registry governance."""

from datetime import datetime, timezone

import pytest

from services.data_agent.virtual_metrics_registry import (
    VIRTUAL_METRICS_REGISTRY,
    validate_virtual_metric_entry,
)


pytestmark = pytest.mark.skip_db


def _entry() -> dict:
    return {
        "name": "temporary_margin_rate",
        "owner": "finance-bi",
        "formula": "SUM(利润) / SUM(销售额)",
        "formula_version": "v2026.05.16",
        "formula_source": "business_approved_spec",
        "approver": "tl@example.com",
        "expires_at": "2026-06-30T00:00:00Z",
        "migration_plan": "Move to Metrics Registry metric_id=margin_rate.",
        "test_refs": ["tests/services/data_agent/test_virtual_metrics_registry.py"],
    }


def test_virtual_metric_entry_requires_governance_metadata():
    validation = validate_virtual_metric_entry(
        _entry(),
        now=datetime(2026, 5, 16, tzinfo=timezone.utc),
    )

    assert validation.ok is True
    assert validation.errors == ()
    assert validation.metadata["metric_registry"] == VIRTUAL_METRICS_REGISTRY
    assert validation.metadata["temporary_escape_hatch"] is True


def test_virtual_metric_entry_rejects_expired_ttl_and_missing_tests():
    entry = _entry()
    entry["expires_at"] = "2026-05-01T00:00:00Z"
    entry["test_refs"] = []

    validation = validate_virtual_metric_entry(
        entry,
        now=datetime(2026, 5, 16, tzinfo=timezone.utc),
    )

    assert validation.ok is False
    assert "expired_ttl" in validation.errors
    assert "missing_test_refs" in validation.errors


def test_virtual_metric_entry_rejects_unknown_formula_source():
    entry = _entry()
    entry["formula_source"] = "llm_generated"

    validation = validate_virtual_metric_entry(
        entry,
        now=datetime(2026, 5, 16, tzinfo=timezone.utc),
    )

    assert validation.ok is False
    assert "invalid_formula_source" in validation.errors

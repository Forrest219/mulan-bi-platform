"""Tests for Data QA schema drift alerting."""

import pytest

from services.data_agent.data_qa_drift import SCHEMA_DRIFT_ALERT, evaluate_schema_drift_alert


pytestmark = pytest.mark.skip_db


def test_schema_drift_alert_triggers_when_ci_green_and_nightly_broadly_fails():
    evaluation = evaluate_schema_drift_alert(ci_passed=True, nightly_total=10, nightly_failed=4)

    assert evaluation.alert is True
    assert evaluation.code == SCHEMA_DRIFT_ALERT
    assert evaluation.freeze_golden_pass is True
    assert evaluation.reason == "ci_green_nightly_broad_failure"


def test_schema_drift_alert_does_not_trigger_when_ci_is_already_red():
    evaluation = evaluate_schema_drift_alert(ci_passed=False, nightly_total=10, nightly_failed=10)

    assert evaluation.alert is False
    assert evaluation.code is None
    assert evaluation.reason == "ci_not_green"


def test_schema_drift_alert_requires_minimum_case_volume():
    evaluation = evaluate_schema_drift_alert(ci_passed=True, nightly_total=3, nightly_failed=3, min_cases=5)

    assert evaluation.alert is False
    assert evaluation.reason == "insufficient_nightly_cases"


def test_schema_drift_alert_rejects_invalid_counts():
    with pytest.raises(ValueError, match="cannot exceed"):
        evaluate_schema_drift_alert(ci_passed=True, nightly_total=2, nightly_failed=3)

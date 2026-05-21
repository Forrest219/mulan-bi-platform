"""Schema parity tests for shared agent observability fields."""

from __future__ import annotations

import pytest
from sqlalchemy.dialects import postgresql

from services.agent_observability import AgentRunTelemetryMixin, AgentStepTelemetryMixin
from services.data_agent.models import BiAgentRun, BiAgentStep
from services.help_agent.models import HelpAgentRun, HelpAgentStep


pytestmark = pytest.mark.skip_db

RUN_TELEMETRY_FIELDS = [
    "status",
    "steps_count",
    "tools_used",
    "response_type",
    "execution_time_ms",
    "created_at",
    "completed_at",
]

STEP_TELEMETRY_FIELDS = [
    "step_number",
    "step_type",
    "tool_name",
    "tool_params",
    "tool_result_summary",
    "content",
    "structured_error",
    "execution_time_ms",
    "created_at",
]


def _column_signature(model, field_name: str) -> tuple[str, bool, str | None]:
    column = model.__table__.columns[field_name]
    compiled_type = column.type.compile(dialect=postgresql.dialect())
    server_default = str(column.server_default.arg) if column.server_default is not None else None
    return compiled_type, column.nullable, server_default


def _assert_parity(left_model, right_model, fields: list[str]) -> None:
    for field_name in fields:
        assert _column_signature(left_model, field_name) == _column_signature(right_model, field_name)


def test_run_observability_fields_come_from_shared_mixin() -> None:
    assert issubclass(BiAgentRun, AgentRunTelemetryMixin)
    assert issubclass(HelpAgentRun, AgentRunTelemetryMixin)


def test_step_observability_fields_come_from_shared_mixin() -> None:
    assert issubclass(BiAgentStep, AgentStepTelemetryMixin)
    assert issubclass(HelpAgentStep, AgentStepTelemetryMixin)


def test_run_observability_schema_parity() -> None:
    _assert_parity(BiAgentRun, HelpAgentRun, RUN_TELEMETRY_FIELDS)


def test_data_agent_error_code_is_wider_than_help_agent_contract() -> None:
    assert BiAgentRun.__table__.columns["error_code"].type.length == 128
    assert HelpAgentRun.__table__.columns["error_code"].type.length == 16


def test_step_observability_schema_parity() -> None:
    _assert_parity(BiAgentStep, HelpAgentStep, STEP_TELEMETRY_FIELDS)

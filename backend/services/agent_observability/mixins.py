"""Shared ORM mixins for agent observability tables."""

from sqlalchemy import ARRAY, Column, DateTime, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB

from app.core.database import sa_func, sa_text


class AgentRunTelemetryMixin:
    """Common run telemetry fields shared by Data Agent and Help Agent."""

    status = Column(String(16), nullable=False, server_default=sa_text("'running'"))
    error_code = Column(String(16), nullable=True)
    steps_count = Column(Integer, nullable=False, server_default=sa_text("0"))
    tools_used = Column(ARRAY(Text), nullable=True)
    response_type = Column(String(16), nullable=True)
    execution_time_ms = Column(Integer, nullable=True)
    created_at = Column(DateTime, server_default=sa_func.now(), nullable=False)
    completed_at = Column(DateTime, nullable=True)


class AgentStepTelemetryMixin:
    """Common step telemetry fields shared by Data Agent and Help Agent."""

    step_number = Column(Integer, nullable=False)
    step_type = Column(String(16), nullable=False)
    tool_name = Column(String(64), nullable=True)
    tool_params = Column(JSONB, nullable=True)
    tool_result_summary = Column(Text, nullable=True)
    content = Column(Text, nullable=True)
    structured_error = Column(JSONB, nullable=True)
    execution_time_ms = Column(Integer, nullable=True)
    created_at = Column(DateTime, server_default=sa_func.now(), nullable=False)

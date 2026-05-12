"""Help Agent ORM models.

Help Agent uses independent help_agent_* tables and must not write to Data
Agent observability tables.
"""

import uuid

from sqlalchemy import ARRAY, Column, DateTime, ForeignKey, Index, Integer, BigInteger, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID

from app.core.database import Base, sa_func, sa_text
from services.agent_observability import AgentRunTelemetryMixin, AgentStepTelemetryMixin


class HelpAgentConversation(Base):
    """Help Agent conversation."""

    __tablename__ = "help_agent_conversations"
    __table_args__ = (
        Index("ix_hac_user_status_updated", "user_id", "status", sa_text("updated_at DESC")),
        {"extend_existing": True},
    )

    id = Column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=sa_text("gen_random_uuid()"),
    )
    user_id = Column(Integer, nullable=False, index=True)
    title = Column(String(256), nullable=True)
    status = Column(String(16), nullable=False, server_default=sa_text("'active'"))
    last_page_path = Column(String(256), nullable=True)
    created_at = Column(DateTime, server_default=sa_func.now(), nullable=False)
    updated_at = Column(DateTime, server_default=sa_func.now(), onupdate=sa_func.now(), nullable=False)

    def to_dict(self) -> dict:
        return {
            "id": str(self.id),
            "user_id": self.user_id,
            "title": self.title,
            "status": self.status,
            "last_page_path": self.last_page_path,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


class HelpAgentMessage(Base):
    """Help Agent message."""

    __tablename__ = "help_agent_messages"
    __table_args__ = (
        Index("ix_ham_conv_created", "conversation_id", "created_at"),
        {"extend_existing": True},
    )

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    conversation_id = Column(
        UUID(as_uuid=True),
        ForeignKey("help_agent_conversations.id", ondelete="CASCADE"),
        nullable=False,
    )
    role = Column(String(16), nullable=False)
    content = Column(Text, nullable=False)
    response_type = Column(String(16), nullable=True)
    response_data = Column(JSONB, nullable=True)
    tools_used = Column(ARRAY(Text), nullable=True)
    trace_id = Column(UUID(as_uuid=True), nullable=True)
    steps_count = Column(Integer, nullable=True)
    execution_time_ms = Column(Integer, nullable=True)
    sources_count = Column(Integer, nullable=True)
    top_sources = Column(JSONB, nullable=True)
    created_at = Column(DateTime, server_default=sa_func.now(), nullable=False)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "conversation_id": str(self.conversation_id),
            "role": self.role,
            "content": self.content,
            "response_type": self.response_type,
            "response_data": self.response_data,
            "tools_used": self.tools_used,
            "trace_id": str(self.trace_id) if self.trace_id else None,
            "steps_count": self.steps_count,
            "execution_time_ms": self.execution_time_ms,
            "sources_count": self.sources_count,
            "top_sources": self.top_sources,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


class HelpAgentRun(AgentRunTelemetryMixin, Base):
    """Help Agent diagnostic run."""

    __tablename__ = "help_agent_runs"
    __table_args__ = (
        Index("ix_har_user_created", "user_id", sa_text("created_at DESC")),
        Index("ix_har_status_created", "status", sa_text("created_at DESC")),
        Index("ix_har_conversation_created", "conversation_id", "created_at"),
        {"extend_existing": True},
    )

    id = Column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=sa_text("gen_random_uuid()"),
    )
    conversation_id = Column(
        UUID(as_uuid=True),
        ForeignKey("help_agent_conversations.id", ondelete="CASCADE"),
        nullable=False,
    )
    user_id = Column(Integer, nullable=False, index=True)
    question = Column(Text, nullable=False)
    page_context = Column(JSONB, nullable=True)
    structured_error = Column(JSONB, nullable=True)
    snapshot_started_at = Column(DateTime, nullable=False)
    snapshot_completed_at = Column(DateTime, nullable=True)

    def to_dict(self) -> dict:
        return {
            "id": str(self.id),
            "conversation_id": str(self.conversation_id),
            "user_id": self.user_id,
            "question": self.question,
            "page_context": self.page_context,
            "status": self.status,
            "error_code": self.error_code,
            "structured_error": self.structured_error,
            "steps_count": self.steps_count,
            "tools_used": self.tools_used,
            "response_type": self.response_type,
            "execution_time_ms": self.execution_time_ms,
            "snapshot_started_at": self.snapshot_started_at.isoformat() if self.snapshot_started_at else None,
            "snapshot_completed_at": self.snapshot_completed_at.isoformat() if self.snapshot_completed_at else None,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
        }


class HelpAgentStep(AgentStepTelemetryMixin, Base):
    """Help Agent diagnostic step."""

    __tablename__ = "help_agent_steps"
    __table_args__ = (
        Index("ix_has_run_step", "run_id", "step_number"),
        {"extend_existing": True},
    )

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    run_id = Column(
        UUID(as_uuid=True),
        ForeignKey("help_agent_runs.id", ondelete="CASCADE"),
        nullable=False,
    )
    diagnostic_payload = Column(JSONB, nullable=True)
    related_entities = Column(JSONB, nullable=True)
    snapshot_at = Column(DateTime, nullable=True)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "run_id": str(self.run_id),
            "step_number": self.step_number,
            "step_type": self.step_type,
            "tool_name": self.tool_name,
            "tool_params": self.tool_params,
            "tool_result_summary": self.tool_result_summary,
            "content": self.content,
            "diagnostic_payload": self.diagnostic_payload,
            "structured_error": self.structured_error,
            "related_entities": self.related_entities,
            "snapshot_at": self.snapshot_at.isoformat() if self.snapshot_at else None,
            "execution_time_ms": self.execution_time_ms,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }

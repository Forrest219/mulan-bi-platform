"""
Data Agent ORM Models — agent_conversations, agent_conversation_messages,
bi_agent_runs, bi_agent_steps, bi_agent_feedback tables

Spec: docs/specs/36-data-agent-architecture-spec.md §4.1 + §Phase 3
"""

import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import Column, String, Text, DateTime, Integer, BigInteger, Index, ARRAY, ForeignKey, UniqueConstraint, text as sa_text
from sqlalchemy.dialects.postgresql import UUID, JSONB

from app.core.database import Base, sa_func


class AgentConversation(Base):
    """会话表 — 管理用户与 Data Agent 的对话会话"""

    __tablename__ = "agent_conversations"
    __table_args__ = (
        Index("ix_ac_user", "user_id", "status", sa_text("updated_at DESC")),
        {"extend_existing": True},
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(Integer, nullable=False, index=True)
    title = Column(String(256), nullable=True)
    connection_id = Column(Integer, nullable=True)
    status = Column(String(16), nullable=False, default="active")
    created_at = Column(DateTime, server_default=sa_func.now(), nullable=False)
    updated_at = Column(DateTime, server_default=sa_func.now(), onupdate=sa_func.now(), nullable=False)

    def to_dict(self) -> dict:
        return {
            "id": str(self.id),
            "user_id": self.user_id,
            "title": self.title,
            "connection_id": self.connection_id,
            "status": self.status,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


class AgentConversationMessage(Base):
    """消息表 — 存储会话中的每条消息"""

    __tablename__ = "agent_conversation_messages"
    __table_args__ = (
        Index("ix_acm_conv", "conversation_id", "created_at"),
        {"extend_existing": True},
    )

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    conversation_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    role = Column(String(16), nullable=False)  # 'user' | 'assistant'
    content = Column(Text, nullable=False)
    response_type = Column(String(16), nullable=True)  # text | table | number | chart_spec | error
    response_data = Column(JSONB, nullable=True)
    tools_used = Column(ARRAY(Text), nullable=True)
    trace_id = Column(String(64), nullable=True)
    steps_count = Column(Integer, nullable=True)
    execution_time_ms = Column(Integer, nullable=True)
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
            "trace_id": self.trace_id,
            "steps_count": self.steps_count,
            "execution_time_ms": self.execution_time_ms,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


# ---------------------------------------------------------------------------
# Phase 3 — Observability tables (Spec 36 §Phase 3)
# ---------------------------------------------------------------------------


class BiAgentRun(Base):
    """Agent 运行记录 — 每次 POST /api/agent/stream 调用产生一行"""

    __tablename__ = "bi_agent_runs"
    __table_args__ = (
        Index("ix_bar_user_created", "user_id", sa_text("created_at DESC")),
        Index("ix_bar_status", "status"),
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
        ForeignKey("agent_conversations.id", ondelete="CASCADE"),
        nullable=False,
    )
    user_id = Column(Integer, nullable=False)
    question = Column(Text, nullable=False)
    connection_id = Column(Integer, nullable=True)
    status = Column(String(16), nullable=False, server_default=sa_text("'running'"))
    error_code = Column(String(16), nullable=True)
    steps_count = Column(Integer, server_default=sa_text("0"))
    tools_used = Column(ARRAY(Text), nullable=True)
    response_type = Column(String(16), nullable=True)
    execution_time_ms = Column(Integer, nullable=True)
    created_at = Column(DateTime, server_default=sa_func.now(), nullable=False)
    completed_at = Column(DateTime, nullable=True)

    def to_dict(self) -> dict:
        return {
            "id": str(self.id),
            "conversation_id": str(self.conversation_id),
            "user_id": self.user_id,
            "question": self.question,
            "connection_id": self.connection_id,
            "status": self.status,
            "error_code": self.error_code,
            "steps_count": self.steps_count,
            "tools_used": self.tools_used,
            "response_type": self.response_type,
            "execution_time_ms": self.execution_time_ms,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
        }


class BiAgentStep(Base):
    """Agent 步骤记录 — 每个 ReAct step 产生一行"""

    __tablename__ = "bi_agent_steps"
    __table_args__ = (
        Index("ix_bas_run_step", "run_id", "step_number"),
        {"extend_existing": True},
    )

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    run_id = Column(
        UUID(as_uuid=True),
        ForeignKey("bi_agent_runs.id", ondelete="CASCADE"),
        nullable=False,
    )
    step_number = Column(Integer, nullable=False)
    step_type = Column(String(16), nullable=False)  # thinking | tool_call | tool_result | answer | error
    tool_name = Column(String(64), nullable=True)
    tool_params = Column(JSONB, nullable=True)
    tool_result_summary = Column(Text, nullable=True)  # first 500 chars
    content = Column(Text, nullable=True)
    execution_time_ms = Column(Integer, nullable=True)
    created_at = Column(DateTime, server_default=sa_func.now(), nullable=False)

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
            "execution_time_ms": self.execution_time_ms,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


class BiAgentFeedback(Base):
    """用户反馈 — 每个 run 每个用户最多一条（thumbs up/down）"""

    __tablename__ = "bi_agent_feedback"
    __table_args__ = (
        UniqueConstraint("run_id", "user_id", name="uq_baf_run_user"),
        {"extend_existing": True},
    )

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    run_id = Column(
        UUID(as_uuid=True),
        ForeignKey("bi_agent_runs.id", ondelete="CASCADE"),
        nullable=False,
    )
    user_id = Column(Integer, nullable=False)
    rating = Column(String(8), nullable=False)  # up | down
    comment = Column(Text, nullable=True)
    created_at = Column(DateTime, server_default=sa_func.now(), nullable=False)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "run_id": str(self.run_id),
            "user_id": self.user_id,
            "rating": self.rating,
            "comment": self.comment,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }
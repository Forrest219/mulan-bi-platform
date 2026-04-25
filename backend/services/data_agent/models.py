"""
Data Agent ORM Models — agent_conversations, agent_conversation_messages,
bi_agent_runs, bi_agent_steps, bi_agent_feedback tables

Spec: docs/specs/36-data-agent-architecture-spec.md §4.1 + §Phase 3
"""

import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import Column, String, Text, DateTime, Integer, BigInteger, Index, ARRAY, ForeignKey, UniqueConstraint, text as sa_text
import sqlalchemy as sa
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


# ============================================================================
# Spec 28 — Data Agent 分析表（归因分析、报告生成、主动洞察存储）
# ============================================================================


class BiAnalysisSession(Base):
    """分析会话状态表（可变）— 仅存储当前最新状态，每步执行后 UPDATE"""

    __tablename__ = "bi_analysis_sessions"
    __table_args__ = (
        Index("ix_as_tenant_status", "tenant_id", "status"),
        Index("ix_as_user_status", "tenant_id", "created_by", "status"),
        Index("ix_as_task_type", "task_type"),
        Index("ix_as_created", sa_text("created_at DESC")),
        {"extend_existing": True},
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    agent_type = Column(String(32), nullable=False, server_default=sa_text("'data_agent'"))
    task_type = Column(String(16), nullable=False)  # causation / report / insight
    status = Column(
        String(16),
        nullable=False,
        server_default=sa_text("'created'"),
    )  # created/running/paused/completed/failed/expired/archived/deleted
    expiration_reason = Column(String(32), nullable=True)  # paused_timeout/retention/admin_delete
    hypothesis_tree = Column(JSONB, nullable=True)  # 假设节点树
    current_step = Column(Integer, nullable=False, server_default=sa_text("0"))
    context_snapshot = Column(JSONB, nullable=True)  # 中间推理结果快照
    session_metadata = Column(JSONB, nullable=True)  # 任务元数据（不含 user_id）
    created_by = Column(Integer, nullable=False)
    created_at = Column(DateTime, server_default=sa_func.now(), nullable=False)
    updated_at = Column(DateTime, server_default=sa_func.now(), onupdate=sa_func.now(), nullable=False)
    completed_at = Column(DateTime, nullable=True)
    expired_at = Column(DateTime, nullable=True)

    def to_dict(self) -> dict:
        return {
            "id": str(self.id),
            "tenant_id": str(self.tenant_id),
            "agent_type": self.agent_type,
            "task_type": self.task_type,
            "status": self.status,
            "expiration_reason": self.expiration_reason,
            "hypothesis_tree": self.hypothesis_tree,
            "current_step": self.current_step,
            "context_snapshot": self.context_snapshot,
            "metadata": self.session_metadata,
            "created_by": self.created_by,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "expired_at": self.expired_at.isoformat() if self.expired_at else None,
        }


class BiAnalysisSessionStep(Base):
    """分析会话步骤历史（不可变 Append-Only）"""

    __tablename__ = "bi_analysis_session_steps"
    __table_args__ = (
        Index("ix_ass_tenant", "tenant_id", "session_id"),
        Index("ix_ass_session_step", "tenant_id", "session_id", sa_text("step_no DESC")),
        Index("ix_ass_sequence", "session_id", "sequence_no"),
        UniqueConstraint("session_id", "step_no", "branch_id", name="uq_ass_step_branch"),
        UniqueConstraint(
            "session_id", "idempotency_key",
            name="uq_ass_idem_key",
        ),
        {"extend_existing": True},
    )

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    tenant_id = Column(UUID(as_uuid=True), nullable=False)
    session_id = Column(
        UUID(as_uuid=True),
        ForeignKey("bi_analysis_sessions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    sequence_no = Column(BigInteger, nullable=False, server_default=sa_text("nextval('bi_analysis_session_steps_seq'::regclass)"))
    step_no = Column(Integer, nullable=False)
    branch_id = Column(String(32), nullable=False, server_default=sa_text("'main'"))
    parent_sequence_no = Column(BigInteger, nullable=True)
    idempotency_key = Column(String(128), nullable=True)
    reasoning_trace = Column(JSONB, nullable=False)  # Thought-Action-Observation 三元组
    query_log = Column(JSONB, nullable=True)
    context_delta = Column(JSONB, nullable=True)  # hypothesis_tree 增量变更
    created_at = Column(DateTime, server_default=sa_func.now(), nullable=False)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "tenant_id": str(self.tenant_id),
            "session_id": str(self.session_id),
            "sequence_no": self.sequence_no,
            "step_no": self.step_no,
            "branch_id": self.branch_id,
            "parent_sequence_no": self.parent_sequence_no,
            "idempotency_key": self.idempotency_key,
            "reasoning_trace": self.reasoning_trace,
            "query_log": self.query_log,
            "context_delta": self.context_delta,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


class BiAnalysisInsight(Base):
    """已发布洞察表"""

    __tablename__ = "bi_analysis_insights"
    __table_args__ = (
        Index("ix_ai_session", "session_id"),
        Index("ix_ai_type_status", "insight_type", "status"),
        Index("ix_ai_published", sa_text("published_at DESC")),
        Index("ix_ai_ds", "datasource_ids", postgresql_using="gin"),
        Index("ix_ai_roles", "allowed_roles", postgresql_using="gin"),
        Index("ix_ai_vis_pub", "visibility", "status", sa_text("published_at DESC")),
        {"extend_existing": True},
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    session_id = Column(
        UUID(as_uuid=True),
        ForeignKey("bi_analysis_sessions.id", ondelete="SET NULL"),
        nullable=True,
    )
    insight_type = Column(String(16), nullable=False)  # anomaly/trend/correlation/causation
    title = Column(String(256), nullable=False)
    summary = Column(Text, nullable=False)
    detail_json = Column(JSONB, nullable=False)
    confidence = Column(sa.Float(), nullable=False)
    impact_scope = Column(String(128), nullable=True)
    push_targets = Column(JSONB, nullable=True)
    status = Column(String(16), nullable=False, server_default=sa_text("'draft'"))  # draft/published/dismissed
    created_by = Column(Integer, nullable=False)
    lineage_status = Column(
        String(16),
        nullable=False,
        server_default=sa_text("'resolved'"),
    )  # resolved/unknown/non_data_derived
    datasource_ids = Column(ARRAY(Integer), nullable=False, server_default=sa_text("'{}'"))
    metric_names = Column(ARRAY(Text), nullable=True)
    visibility = Column(String(16), nullable=False, server_default=sa_text("'private'"))  # private/team/public
    allowed_roles = Column(JSONB, nullable=True)
    published_at = Column(DateTime, nullable=True)
    provenance_info = Column(JSONB, nullable=True)
    created_at = Column(DateTime, server_default=sa_func.now(), nullable=False)

    def to_dict(self) -> dict:
        return {
            "id": str(self.id),
            "tenant_id": str(self.tenant_id),
            "session_id": str(self.session_id) if self.session_id else None,
            "insight_type": self.insight_type,
            "title": self.title,
            "summary": self.summary,
            "detail_json": self.detail_json,
            "confidence": self.confidence,
            "impact_scope": self.impact_scope,
            "push_targets": self.push_targets,
            "status": self.status,
            "created_by": self.created_by,
            "lineage_status": self.lineage_status,
            "datasource_ids": self.datasource_ids,
            "metric_names": self.metric_names,
            "visibility": self.visibility,
            "allowed_roles": self.allowed_roles,
            "published_at": self.published_at.isoformat() if self.published_at else None,
            "provenance_info": self.provenance_info,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


class BiAnalysisReport(Base):
    """分析报告表"""

    __tablename__ = "bi_analysis_reports"
    __table_args__ = (
        Index("ix_ar_session", "session_id"),
        Index("ix_ar_author", "author"),
        Index("ix_ar_ds", "datasource_ids", postgresql_using="gin"),
        Index("ix_ar_roles", "allowed_roles", postgresql_using="gin"),
        Index("ix_ar_groups", "allowed_user_groups", postgresql_using="gin"),
        Index("ix_ar_vis_pub", "visibility", "status", sa_text("published_at DESC")),
        {"extend_existing": True},
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    session_id = Column(
        UUID(as_uuid=True),
        ForeignKey("bi_analysis_sessions.id", ondelete="SET NULL"),
        nullable=True,
    )
    subject = Column(String(256), nullable=False)
    time_range = Column(String(64), nullable=True)
    content_json = Column(JSONB, nullable=False)  # 报告内容（规范层）
    content_md = Column(Text, nullable=True)  # 渲染后的 Markdown
    author = Column(Integer, nullable=False)
    lineage_status = Column(
        String(16),
        nullable=False,
        server_default=sa_text("'resolved'"),
    )  # resolved/unknown/non_data_derived
    datasource_ids = Column(ARRAY(Integer), nullable=False, server_default=sa_text("'{}'"))
    visibility = Column(String(16), nullable=False, server_default=sa_text("'private'"))
    allowed_roles = Column(ARRAY(Text), nullable=True)
    allowed_user_groups = Column(ARRAY(Text), nullable=True)
    status = Column(String(16), nullable=False, server_default=sa_text("'draft'"))  # draft/published
    published_at = Column(DateTime, nullable=True)
    provenance_info = Column(JSONB, nullable=True)
    created_at = Column(DateTime, server_default=sa_func.now(), nullable=False)
    updated_at = Column(DateTime, server_default=sa_func.now(), onupdate=sa_func.now(), nullable=False)

    def to_dict(self) -> dict:
        return {
            "id": str(self.id),
            "tenant_id": str(self.tenant_id),
            "session_id": str(self.session_id) if self.session_id else None,
            "subject": self.subject,
            "time_range": self.time_range,
            "content_json": self.content_json,
            "content_md": self.content_md,
            "author": self.author,
            "lineage_status": self.lineage_status,
            "datasource_ids": self.datasource_ids,
            "visibility": self.visibility,
            "allowed_roles": self.allowed_roles,
            "allowed_user_groups": self.allowed_user_groups,
            "status": self.status,
            "published_at": self.published_at.isoformat() if self.published_at else None,
            "provenance_info": self.provenance_info,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }
"""
Agent Skills ORM Models — agent_skills, agent_skill_versions tables

Spec: docs/specs/agents_skills.md §3.1 / §3.2
"""

import uuid
from datetime import datetime

from sqlalchemy import (
    Column,
    String,
    Text,
    Boolean,
    Integer,
    DateTime,
    Index,
    ForeignKey,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.sql import text as sa_text

from app.core.database import Base, sa_func


class AgentSkill(Base):
    """技能主表 — 存储技能的不可变基础标识信息。

    Spec §3.1: description 仅供管理界面展示，不进入 LLM Prompt。
    """

    __tablename__ = "agent_skills"
    __table_args__ = (
        Index("idx_agent_skills_skill_key", "skill_key"),
        Index("idx_agent_skills_category", "category"),
        {"extend_existing": True},
    )

    id = Column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=sa_text("gen_random_uuid()"),
    )
    skill_key = Column(String(128), nullable=False, unique=True)
    name = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)  # 管理界面简介，不进入 LLM Prompt
    category = Column(String(64), nullable=False, server_default=sa_text("'general'"))
    is_enabled = Column(Boolean, nullable=False, server_default=sa_text("true"))
    created_at = Column(DateTime, server_default=sa_func.now(), nullable=False)
    updated_at = Column(
        DateTime,
        server_default=sa_func.now(),
        onupdate=datetime.utcnow,
        nullable=False,
    )
    created_by = Column(
        Integer,
        ForeignKey("auth_users.id", ondelete="SET NULL"),
        nullable=True,
    )

    def to_dict(self) -> dict:
        return {
            "id": str(self.id),
            "skill_key": self.skill_key,
            "name": self.name,
            "description": self.description,
            "category": self.category,
            "is_enabled": self.is_enabled,
            "created_by": self.created_by,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


class AgentSkillVersion(Base):
    """技能版本表 — 每个技能的变更历史。

    Spec §3.2: DB 约束强制每个 skill 同时只有一个 is_active=True 版本
    （partial unique index uq_skill_versions_one_active 在 Alembic 迁移中创建）。
    """

    __tablename__ = "agent_skill_versions"
    __table_args__ = (
        UniqueConstraint("skill_id", "version_number", name="uq_skill_version_number"),
        Index("idx_skill_versions_skill_id", "skill_id"),
        {"extend_existing": True},
    )

    id = Column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=sa_text("gen_random_uuid()"),
    )
    skill_id = Column(
        UUID(as_uuid=True),
        ForeignKey("agent_skills.id", ondelete="CASCADE"),
        nullable=False,
    )
    version_number = Column(String(16), nullable=False)  # "v1", "v2", ...
    description = Column(Text, nullable=False)  # 注入 LLM System Prompt 的工具描述
    input_schema = Column(JSONB, nullable=False)  # JSON Schema (OpenAI function calling 格式)
    endpoint_type = Column(
        String(32), nullable=False, server_default=sa_text("'static'")
    )
    code_ref = Column(Text, nullable=True)  # 人读注释：Python class 名
    change_notes = Column(Text, nullable=True)
    is_active = Column(Boolean, nullable=False, server_default=sa_text("false"))
    created_at = Column(DateTime, server_default=sa_func.now(), nullable=False)
    created_by = Column(
        Integer,
        ForeignKey("auth_users.id", ondelete="SET NULL"),
        nullable=True,
    )

    def to_dict(self) -> dict:
        return {
            "id": str(self.id),
            "skill_id": str(self.skill_id),
            "version_number": self.version_number,
            "description": self.description,
            "input_schema": self.input_schema,  # already a dict (JSONB), no json.loads needed
            "endpoint_type": self.endpoint_type,
            "code_ref": self.code_ref,
            "change_notes": self.change_notes,
            "is_active": self.is_active,
            "created_by": self.created_by,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }

"""
Session Manager for Data Agent — create / resume / persist conversations

Spec: docs/specs/36-data-agent-architecture-spec.md §3.3 Session Manager
"""

import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

from sqlalchemy.orm import Session as DBSession

from services.data_agent.models import AgentConversation, AgentConversationMessage

logger = logging.getLogger(__name__)


@dataclass
class ConversationStep:
    """A single step in the ReAct loop"""
    step_number: int
    thought: str
    tool_name: Optional[str] = None
    tool_params: Optional[dict] = None
    tool_result: Optional[dict] = None
    timestamp: datetime = field(default_factory=datetime.utcnow)


@dataclass
class AgentSession:
    """
    In-memory agent session, persisted via AgentConversation + AgentConversationMessage.
    
    Attributes:
        conversation_id: UUID of the conversation
        user_id: User who owns this session
        history: List of conversation steps (in-memory only, not persisted separately)
    """
    conversation_id: uuid.UUID
    user_id: int
    title: Optional[str] = None
    connection_id: Optional[int] = None
    status: str = "active"
    history: list[ConversationStep] = field(default_factory=list)
    created_at: datetime = field(default_factory=datetime.utcnow)
    updated_at: datetime = field(default_factory=datetime.utcnow)

    def add_step(self, step: ConversationStep) -> None:
        self.history.append(step)
        self.updated_at = datetime.utcnow()

    def to_conversation_dict(self) -> dict:
        return {
            "id": str(self.conversation_id),
            "user_id": self.user_id,
            "title": self.title,
            "connection_id": self.connection_id,
            "status": self.status,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
        }


class SessionManager:
    """
    Manages agent conversation lifecycle.
    
    Usage:
        manager = SessionManager(db)
        session = manager.create_session(user_id=1, connection_id=1)
        session = manager.resume_session(conversation_id, user_id=1)
        manager.persist_message(session, role="user", content="...")
    """

    def __init__(self, db: DBSession):
        self.db = db

    def create_session(
        self,
        user_id: int,
        connection_id: Optional[int] = None,
        title: Optional[str] = None,
    ) -> AgentSession:
        """
        Create a new conversation session.
        
        Args:
            user_id: User ID
            connection_id: Optional data source connection
            title: Optional conversation title
            
        Returns:
            AgentSession instance
        """
        conversation = AgentConversation(
            id=uuid.uuid4(),
            user_id=user_id,
            connection_id=connection_id,
            title=title,
            status="active",
        )
        self.db.add(conversation)
        self.db.commit()
        self.db.refresh(conversation)

        logger.info(f"Created new session: {conversation.id} for user {user_id}")

        return AgentSession(
            conversation_id=conversation.id,
            user_id=user_id,
            connection_id=connection_id,
            title=title,
        )

    def resume_session(self, conversation_id: uuid.UUID, user_id: int) -> Optional[AgentSession]:
        """
        Resume an existing session from database.

        Args:
            conversation_id: UUID of the conversation
            user_id: Owner user ID (enforces ownership check)

        Returns:
            AgentSession or None if not found or not owned by user
        """
        conversation = self.db.query(AgentConversation).filter(
            AgentConversation.id == conversation_id,
            AgentConversation.user_id == user_id,
        ).first()

        if not conversation:
            return None

        return AgentSession(
            conversation_id=conversation.id,
            user_id=conversation.user_id,
            connection_id=conversation.connection_id,
            title=conversation.title,
            status=conversation.status,
        )

    def update_title(self, conversation_id: uuid.UUID, title: str, user_id: int) -> None:
        """Update conversation title (ownership-enforced)"""
        conversation = self.db.query(AgentConversation).filter(
            AgentConversation.id == conversation_id,
            AgentConversation.user_id == user_id,
        ).first()
        if conversation:
            conversation.title = title
            self.db.commit()

    def archive_session(self, conversation_id: uuid.UUID, user_id: int) -> None:
        """Archive a session (soft delete, ownership-enforced)"""
        conversation = self.db.query(AgentConversation).filter(
            AgentConversation.id == conversation_id,
            AgentConversation.user_id == user_id,
        ).first()
        if conversation:
            conversation.status = "archived"
            self.db.commit()

    def persist_message(
        self,
        session: AgentSession,
        role: str,
        content: str,
        response_type: Optional[str] = None,
        response_data: Optional[dict] = None,
        tools_used: Optional[list[str]] = None,
        trace_id: Optional[str] = None,
        steps_count: Optional[int] = None,
        execution_time_ms: Optional[int] = None,
    ) -> AgentConversationMessage:
        """
        Persist a message to the database.
        
        Args:
            session: AgentSession
            role: 'user' or 'assistant'
            content: Message content
            response_type: Response type (text/table/number/chart_spec/error)
            response_data: Structured response data
            tools_used: List of tools used in this response
            trace_id: Trace ID for debugging
            steps_count: Number of ReAct steps taken
            execution_time_ms: Total execution time
            
        Returns:
            Created AgentConversationMessage
        """
        message = AgentConversationMessage(
            conversation_id=session.conversation_id,
            role=role,
            content=content,
            response_type=response_type,
            response_data=response_data,
            tools_used=tools_used,
            trace_id=trace_id,
            steps_count=steps_count,
            execution_time_ms=execution_time_ms,
        )
        self.db.add(message)

        # Update conversation updated_at
        conversation = self.db.query(AgentConversation).filter(
            AgentConversation.id == session.conversation_id
        ).first()
        if conversation:
            conversation.updated_at = datetime.utcnow()

        self.db.commit()
        self.db.refresh(message)
        return message

    def get_conversation_messages(
        self,
        conversation_id: uuid.UUID,
        user_id: int,
        limit: int = 50,
        offset: int = 0,
    ) -> list[AgentConversationMessage]:
        """Get messages for a conversation (ownership-enforced)"""
        ownership = self.db.query(AgentConversation).filter(
            AgentConversation.id == conversation_id,
            AgentConversation.user_id == user_id,
        ).first()
        if not ownership:
            return []
        return (
            self.db.query(AgentConversationMessage)
            .filter(AgentConversationMessage.conversation_id == conversation_id)
            .order_by(AgentConversationMessage.created_at)
            .offset(offset)
            .limit(limit)
            .all()
        )

    def get_user_conversations(
        self,
        user_id: int,
        status: Optional[str] = "active",
        limit: int = 20,
    ) -> list[AgentConversation]:
        """Get all conversations for a user"""
        query = self.db.query(AgentConversation).filter(
            AgentConversation.user_id == user_id
        )
        if status:
            query = query.filter(AgentConversation.status == status)
        return query.order_by(AgentConversation.updated_at.desc()).limit(limit).all()
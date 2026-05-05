"""对话历史 Service — 纯业务逻辑层，不依赖 FastAPI"""

import uuid
from datetime import datetime, timezone
from typing import Optional, List, Tuple

from sqlalchemy import func, text
from sqlalchemy.orm import Session

from models.conversations import Conversation, ConversationMessage


class ConversationService:
    """对话历史服务"""

    def __init__(self, db: Session):
        self.db = db

    # ========== Conversation ==========

    def list_conversations(self, user_id: int, limit: int = 100) -> List[dict]:
        """返回当前用户对话列表（按 updated_at DESC，最多 limit 条）"""
        rows = (
            self.db.query(
                Conversation.id,
                Conversation.title,
                Conversation.updated_at,
                func.count(ConversationMessage.id).label("message_count"),
            )
            .outerjoin(ConversationMessage, ConversationMessage.conversation_id == Conversation.id)
            .filter(Conversation.user_id == user_id)
            .group_by(Conversation.id, Conversation.title, Conversation.updated_at)
            .having(func.count(ConversationMessage.id) > 0)
            .order_by(Conversation.updated_at.desc())
            .limit(limit)
            .all()
        )
        return [
            {
                "id": r.id,
                "title": r.title,
                "updated_at": r.updated_at.isoformat() if r.updated_at else None,
                "message_count": r.message_count,
            }
            for r in rows
        ]

    def get_conversation(self, conversation_id: str, user_id: int) -> Optional[Conversation]:
        """获取对话详情（需验证归属）"""
        return (
            self.db.query(Conversation)
            .filter(Conversation.id == conversation_id, Conversation.user_id == user_id)
            .first()
        )

    def create_conversation(self, user_id: int, title: Optional[str] = None) -> Conversation:
        """创建新对话"""
        now = datetime.now(timezone.utc)
        conv = Conversation(
            id=str(uuid.uuid4()),
            user_id=user_id,
            title=title or "新对话",
            created_at=now,
            updated_at=now,
        )
        self.db.add(conv)
        self.db.commit()
        self.db.refresh(conv)
        return conv

    def update_conversation(
        self, conversation_id: str, user_id: int, title: str
    ) -> Optional[Conversation]:
        """更新对话标题"""
        conv = self.get_conversation(conversation_id, user_id)
        if not conv:
            return None
        conv.title = title
        conv.updated_at = datetime.now(timezone.utc)
        self.db.commit()
        self.db.refresh(conv)
        return conv

    def delete_conversation(self, conversation_id: str, user_id: int) -> bool:
        """删除对话（需验证归属）"""
        conv = self.get_conversation(conversation_id, user_id)
        if not conv:
            return False
        self.db.delete(conv)
        self.db.commit()
        return True

    # ========== ConversationMessage ==========

    def list_messages(self, conversation_id: str, user_id: int) -> Tuple[Optional[Conversation], List[ConversationMessage]]:
        """获取对话消息列表（需验证归属）"""
        conv = self.get_conversation(conversation_id, user_id)
        if not conv:
            return None, []
        messages = (
            self.db.query(ConversationMessage)
            .filter(ConversationMessage.conversation_id == conversation_id)
            .order_by(ConversationMessage.created_at.asc())
            .all()
        )
        return conv, messages

    def create_message(
        self,
        conversation_id: str,
        user_id: int,
        role: str,
        content: str,
        query_context: Optional[dict] = None,
    ) -> Optional[ConversationMessage]:
        """发送消息（需验证对话归属）"""
        # 验证对话归属
        conv = self.get_conversation(conversation_id, user_id)
        if not conv:
            return None

        # 校验 role
        if role not in ("user", "assistant"):
            raise ValueError("role must be 'user' or 'assistant'")

        now = datetime.now(timezone.utc)
        msg = ConversationMessage(
            id=str(uuid.uuid4()),
            conversation_id=conversation_id,
            role=role,
            content=content,
            query_context=query_context,
            created_at=now,
        )
        self.db.add(msg)

        # 更新对话 updated_at
        conv.updated_at = now
        self.db.commit()
        self.db.refresh(msg)
        return msg

    def get_conversation_context(self, conversation_id: str, user_id: int) -> Optional[dict]:
        """获取对话最近一条 assistant 消息的 query_context（用于追问上下文继承）"""
        # 验证归属
        conv = self.get_conversation(conversation_id, user_id)
        if not conv:
            return None

        msg = (
            self.db.query(ConversationMessage)
            .filter(
                ConversationMessage.conversation_id == conversation_id,
                ConversationMessage.role == "assistant",
                ConversationMessage.query_context.isnot(None),
            )
            .order_by(ConversationMessage.created_at.desc())
            .first()
        )
        return msg.query_context if msg else None

    # ========== 搜索 ==========

    def search_conversations(
        self, user_id: int, query: str, limit: int = 20
    ) -> List[dict]:
        """搜索对话标题或消息内容"""
        like = f"%{query}%"
        rows = (
            self.db.query(
                Conversation.id,
                Conversation.title,
                Conversation.updated_at,
                func.count(ConversationMessage.id).label("message_count"),
            )
            .outerjoin(ConversationMessage, ConversationMessage.conversation_id == Conversation.id)
            .filter(
                Conversation.user_id == user_id,
                (Conversation.title.ilike(like) | ConversationMessage.content.ilike(like)),
            )
            .group_by(Conversation.id, Conversation.title, Conversation.updated_at)
            .having(func.count(ConversationMessage.id) > 0)
            .order_by(Conversation.updated_at.desc())
            .limit(limit)
            .all()
        )
        return [
            {
                "id": r.id,
                "title": r.title,
                "updated_at": r.updated_at.isoformat() if r.updated_at else None,
                "message_count": r.message_count,
            }
            for r in rows
        ]

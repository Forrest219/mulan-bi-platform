"""消息反馈 API — POST /api/feedback

用户对 AI 回答点赞（up）或踩（down），写入 message_feedback 表。
user_id 和 username 从 JWT 解析，不接受前端传入。
"""
import logging
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, field_validator
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.dependencies import get_current_user

logger = logging.getLogger(__name__)
router = APIRouter()


class FeedbackRequest(BaseModel):
    conversation_id: Optional[str] = None
    message_index: Optional[int] = None
    question: Optional[str] = None
    answer_summary: Optional[str] = None
    rating: str  # 'up' | 'down'

    @field_validator('rating')
    @classmethod
    def validate_rating(cls, v: str) -> str:
        if v not in ('up', 'down'):
            raise ValueError("rating 必须为 'up' 或 'down'")
        return v


@router.post("")
async def submit_feedback(
    body: FeedbackRequest,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """
    POST /api/feedback — 提交消息反馈

    user_id 和 username 从 JWT 解析，不接受前端传入。
    """
    user_id = current_user["id"]
    username = current_user.get("username") or ""

    try:
        db.execute(
            text(
                "INSERT INTO message_feedback "
                "(user_id, username, conversation_id, message_index, question, answer_summary, rating, created_at) "
                "VALUES (:user_id, :username, :conversation_id, :message_index, :question, :answer_summary, :rating, :created_at)"
            ),
            {
                "user_id": user_id,
                "username": username,
                "conversation_id": body.conversation_id,
                "message_index": body.message_index,
                "question": body.question,
                "answer_summary": body.answer_summary[:100] if body.answer_summary else None,
                "rating": body.rating,
                "created_at": datetime.now(timezone.utc),
            },
        )
        db.commit()
        logger.info(
            "反馈已记录 user_id=%s rating=%s conversation_id=%s",
            user_id, body.rating, body.conversation_id,
        )
        return {"ok": True}
    except Exception as exc:
        db.rollback()
        logger.error("写入反馈失败: %s", exc, exc_info=True)
        raise

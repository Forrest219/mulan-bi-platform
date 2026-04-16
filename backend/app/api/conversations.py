"""对话历史 API"""
import uuid
from datetime import datetime, timezone
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session
from sqlalchemy import text

from app.core.database import get_db
from app.core.dependencies import get_current_user

router = APIRouter()


class ConversationCreate(BaseModel):
    title: Optional[str] = "新对话"


class ConversationUpdate(BaseModel):
    title: str


# GET /api/conversations
@router.get("")
def list_conversations(
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    """返回当前用户对话列表（按 updated_at DESC，最多 100 条）"""
    rows = db.execute(text("""
        SELECT c.id, c.title, c.updated_at,
               COUNT(m.id) AS message_count
        FROM conversations c
        LEFT JOIN conversation_messages m ON m.conversation_id = c.id
        WHERE c.user_id = :user_id
        GROUP BY c.id, c.title, c.updated_at
        ORDER BY c.updated_at DESC
        LIMIT 100
    """), {"user_id": user["id"]}).fetchall()
    return [dict(r._mapping) for r in rows]


# POST /api/conversations
@router.post("", status_code=201)
def create_conversation(
    body: ConversationCreate,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    conv_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc)
    db.execute(text("""
        INSERT INTO conversations (id, user_id, title, created_at, updated_at)
        VALUES (:id, :user_id, :title, :now, :now)
    """), {"id": conv_id, "user_id": user["id"], "title": body.title or "新对话", "now": now})
    db.commit()
    return {"id": conv_id, "title": body.title, "created_at": now.isoformat(), "updated_at": now.isoformat()}


# GET /api/conversations/search — 必须在 /{conversation_id} 之前注册
@router.get("/search")
def search_conversations(
    q: str,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    """搜索对话标题或消息内容（最多 20 条）"""
    like = f"%{q}%"
    rows = db.execute(text("""
        SELECT DISTINCT c.id, c.title, c.updated_at,
               COUNT(m.id) AS message_count
        FROM conversations c
        LEFT JOIN conversation_messages m ON m.conversation_id = c.id
        WHERE c.user_id = :user_id
          AND (c.title ILIKE :q OR m.content ILIKE :q)
        GROUP BY c.id, c.title, c.updated_at
        ORDER BY c.updated_at DESC
        LIMIT 20
    """), {"user_id": user["id"], "q": like}).fetchall()
    return [dict(r._mapping) for r in rows]


# GET /api/conversations/{conversation_id}/context — P2-1 追问上下文
@router.get("/{conversation_id}/context")
def get_conversation_context(
    conversation_id: str,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    """获取对话最近一条 assistant 消息的 query_context（用于追问上下文继承）"""
    import json as _json

    conv = db.execute(
        text("SELECT id FROM conversations WHERE id=:id AND user_id=:user_id"),
        {"id": conversation_id, "user_id": user["id"]},
    ).fetchone()
    if not conv:
        raise HTTPException(status_code=404, detail="对话不存在")

    msg = db.execute(
        text("""
            SELECT query_context FROM conversation_messages
            WHERE conversation_id=:cid AND role='assistant' AND query_context IS NOT NULL
            ORDER BY created_at DESC LIMIT 1
        """),
        {"cid": conversation_id},
    ).fetchone()

    if not msg:
        return {"context": None}

    ctx = msg._mapping["query_context"]
    if isinstance(ctx, str):
        ctx = _json.loads(ctx)
    return {"context": ctx}


# GET /api/conversations/{conversation_id}
@router.get("/{conversation_id}")
def get_conversation(
    conversation_id: str,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    conv = db.execute(text("""
        SELECT id, title, updated_at FROM conversations
        WHERE id = :id AND user_id = :user_id
    """), {"id": conversation_id, "user_id": user["id"]}).fetchone()
    if not conv:
        raise HTTPException(status_code=404, detail="对话不存在")
    messages = db.execute(text("""
        SELECT id, role, content, query_context, created_at FROM conversation_messages
        WHERE conversation_id = :cid ORDER BY created_at ASC
    """), {"cid": conversation_id}).fetchall()
    return {
        **dict(conv._mapping),
        "messages": [dict(m._mapping) for m in messages],
    }


# PATCH /api/conversations/{conversation_id}
@router.patch("/{conversation_id}")
def update_conversation(
    conversation_id: str,
    body: ConversationUpdate,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    result = db.execute(text("""
        UPDATE conversations SET title = :title, updated_at = now()
        WHERE id = :id AND user_id = :user_id
    """), {"title": body.title, "id": conversation_id, "user_id": user["id"]})
    db.commit()
    if result.rowcount == 0:
        raise HTTPException(status_code=404, detail="对话不存在")
    return {"id": conversation_id, "title": body.title}


# DELETE /api/conversations/{conversation_id}
@router.delete("/{conversation_id}", status_code=204)
def delete_conversation(
    conversation_id: str,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    result = db.execute(text("""
        DELETE FROM conversations WHERE id = :id AND user_id = :user_id
    """), {"id": conversation_id, "user_id": user["id"]})
    db.commit()
    if result.rowcount == 0:
        raise HTTPException(status_code=404, detail="对话不存在")

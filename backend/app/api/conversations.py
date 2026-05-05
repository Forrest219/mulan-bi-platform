"""对话历史 API"""
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.dependencies import get_current_user
from services.conversation_service import ConversationService

router = APIRouter()


class ConversationCreate(BaseModel):
    title: Optional[str] = "新对话"


class ConversationUpdate(BaseModel):
    title: str


class MessageCreate(BaseModel):
    role: str
    content: str
    query_context: Optional[dict] = None


# GET /api/conversations
@router.get("")
def list_conversations(
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    """返回当前用户对话列表（按 updated_at DESC，最多 100 条）"""
    service = ConversationService(db)
    return service.list_conversations(user["id"])


# POST /api/conversations
@router.post("", status_code=201)
def create_conversation(
    body: ConversationCreate,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    """创建新对话"""
    service = ConversationService(db)
    conv = service.create_conversation(user["id"], body.title)
    return {
        "id": conv.id,
        "title": conv.title,
        "created_at": conv.created_at.isoformat() if conv.created_at else None,
        "updated_at": conv.updated_at.isoformat() if conv.updated_at else None,
    }


# GET /api/conversations/search — 必须在 /{conversation_id} 之前注册
@router.get("/search")
def search_conversations(
    q: str,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    """搜索对话标题或消息内容（最多 20 条）"""
    service = ConversationService(db)
    return service.search_conversations(user["id"], q)


# GET /api/conversations/{conversation_id}/context — P2-1 追问上下文
@router.get("/{conversation_id}/context")
def get_conversation_context(
    conversation_id: str,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    """获取对话最近一条 assistant 消息的 query_context（用于追问上下文继承）"""
    service = ConversationService(db)
    ctx = service.get_conversation_context(conversation_id, user["id"])
    if ctx is None:
        # 可能没有上下文，也可能是对话不存在
        return {"context": None}
    return {"context": ctx}


# GET /api/conversations/{conversation_id}
@router.get("/{conversation_id}")
def get_conversation(
    conversation_id: str,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    """获取对话详情（含消息列表）"""
    service = ConversationService(db)
    conv = service.get_conversation(conversation_id, user["id"])
    if not conv:
        raise HTTPException(status_code=404, detail="对话不存在")
    _, messages = service.list_messages(conversation_id, user["id"])
    return {
        "id": conv.id,
        "title": conv.title,
        "updated_at": conv.updated_at.isoformat() if conv.updated_at else None,
        "messages": [m.to_dict() for m in messages],
    }


# PATCH /api/conversations/{conversation_id}
@router.patch("/{conversation_id}")
def update_conversation(
    conversation_id: str,
    body: ConversationUpdate,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    """更新对话标题"""
    service = ConversationService(db)
    conv = service.update_conversation(conversation_id, user["id"], body.title)
    if not conv:
        raise HTTPException(status_code=404, detail="对话不存在")
    return {"id": conv.id, "title": conv.title}


# DELETE /api/conversations/{conversation_id}
@router.delete("/{conversation_id}", status_code=204)
def delete_conversation(
    conversation_id: str,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    """删除对话"""
    service = ConversationService(db)
    ok = service.delete_conversation(conversation_id, user["id"])
    if not ok:
        raise HTTPException(status_code=404, detail="对话不存在")


# GET /api/conversations/{conversation_id}/messages
@router.get("/{conversation_id}/messages")
def list_messages(
    conversation_id: str,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    """获取对话消息列表"""
    service = ConversationService(db)
    conv, messages = service.list_messages(conversation_id, user["id"])
    if not conv:
        raise HTTPException(status_code=404, detail="对话不存在")
    return [m.to_dict() for m in messages]


# POST /api/conversations/{conversation_id}/messages
@router.post("/{conversation_id}/messages", status_code=201)
def create_message(
    conversation_id: str,
    body: MessageCreate,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    """发送消息"""
    if body.role not in ("user", "assistant"):
        raise HTTPException(status_code=400, detail="role must be 'user' or 'assistant'")
    service = ConversationService(db)
    msg = service.create_message(
        conversation_id=conversation_id,
        user_id=user["id"],
        role=body.role,
        content=body.content,
        query_context=body.query_context,
    )
    if not msg:
        raise HTTPException(status_code=404, detail="对话不存在")
    return msg.to_dict()

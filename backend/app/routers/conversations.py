from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.deps import get_db
from app.models import VALID_ROLES, Conversation, Message
from app.recall_index_service import sync_recall
from app.schemas import MessageCreate, MessageRead

router = APIRouter(tags=["conversations"])


def _get_conversation_or_404(db: Session, conversation_id: str) -> Conversation:
    conversation = db.get(Conversation, conversation_id)
    if conversation is None:
        raise HTTPException(status_code=404, detail="Conversation not found")
    return conversation


@router.get(
    "/api/conversations/{conversation_id}/messages",
    response_model=list[MessageRead],
)
def list_messages(conversation_id: str, db: Session = Depends(get_db)) -> list[Message]:
    _get_conversation_or_404(db, conversation_id)
    stmt = (
        select(Message)
        .where(Message.conversation_id == conversation_id)
        .order_by(Message.created_at)
    )
    return list(db.execute(stmt).scalars().all())


@router.post(
    "/api/conversations/{conversation_id}/messages",
    response_model=MessageRead,
    status_code=201,
)
def create_message(
    conversation_id: str, payload: MessageCreate, db: Session = Depends(get_db)
) -> Message:
    _get_conversation_or_404(db, conversation_id)

    if payload.role not in VALID_ROLES:
        raise HTTPException(status_code=422, detail=f"role must be one of {VALID_ROLES}")

    if not payload.content.strip():
        raise HTTPException(status_code=422, detail="content must not be empty")

    message = Message(conversation_id=conversation_id, role=payload.role, content=payload.content)
    db.add(message)
    db.flush()
    sync_recall(db, "message", message.id)
    db.commit()
    db.refresh(message)
    return message

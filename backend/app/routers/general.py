"""Phase 6: general Jarvis conversation scope — a real, explicit,
persisted conversation shape with no fixed domain, not a seventh domain
and not an arbitrary assignment to one of the six existing ones. See
migration 0011 and docs/DECISIONS.md.

Messages/turns for a general conversation reuse the existing
domain-agnostic `/api/conversations/{id}/messages` and
`/api/conversations/{id}/turns` endpoints unchanged — only creation and
listing need a home that isn't scoped under a domain slug.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.deps import get_db
from app.models import Conversation
from app.recall_index_service import sync_recall
from app.schemas import ConversationCreate, ConversationRead

router = APIRouter(tags=["general"])


@router.post(
    "/api/general/conversations",
    response_model=ConversationRead,
    status_code=201,
)
def create_general_conversation(payload: ConversationCreate, db: Session = Depends(get_db)) -> Conversation:
    conversation = Conversation(domain_id=None, title=payload.title)
    db.add(conversation)
    db.flush()
    sync_recall(db, "conversation", conversation.id)
    db.commit()
    db.refresh(conversation)
    return conversation


@router.get(
    "/api/general/conversations",
    response_model=list[ConversationRead],
)
def list_general_conversations(db: Session = Depends(get_db)) -> list[Conversation]:
    stmt = (
        select(Conversation)
        .where(Conversation.domain_id.is_(None))
        .order_by(Conversation.created_at.desc())
    )
    return list(db.execute(stmt).scalars().all())

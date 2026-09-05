from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.deps import get_db
from app.models import Conversation, Domain
from app.recall_index_service import sync_recall
from app.schemas import ConversationCreate, ConversationRead, DomainRead

router = APIRouter(tags=["domains"])


def _get_domain_or_404(db: Session, slug: str) -> Domain:
    domain = db.execute(select(Domain).where(Domain.slug == slug)).scalar_one_or_none()
    if domain is None:
        raise HTTPException(status_code=404, detail="Domain not found")
    return domain


@router.get("/api/domains", response_model=list[DomainRead])
def list_domains(db: Session = Depends(get_db)) -> list[Domain]:
    return list(db.execute(select(Domain).order_by(Domain.slug)).scalars().all())


@router.post(
    "/api/domains/{slug}/conversations",
    response_model=ConversationRead,
    status_code=201,
)
def create_conversation(
    slug: str, payload: ConversationCreate, db: Session = Depends(get_db)
) -> Conversation:
    domain = _get_domain_or_404(db, slug)
    conversation = Conversation(domain_id=domain.id, title=payload.title)
    db.add(conversation)
    db.flush()
    sync_recall(db, "conversation", conversation.id)
    db.commit()
    db.refresh(conversation)
    return conversation


@router.get(
    "/api/domains/{slug}/conversations",
    response_model=list[ConversationRead],
)
def list_conversations(slug: str, db: Session = Depends(get_db)) -> list[Conversation]:
    domain = _get_domain_or_404(db, slug)
    stmt = (
        select(Conversation)
        .where(Conversation.domain_id == domain.id)
        .order_by(Conversation.created_at.desc())
    )
    return list(db.execute(stmt).scalars().all())

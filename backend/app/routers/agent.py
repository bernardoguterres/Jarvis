from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.deps import get_db, get_provider
from app.providers.base import AgentProvider
from app.schemas import (
    AgentStatusRead,
    MessageRead,
    TurnCreate,
    TurnErrorRead,
    TurnRead,
    UsageRead,
)
from app.models_memory import ContextSnapshot
from app.turn_service import ConversationNotFoundError, TurnOutcome, send_turn

router = APIRouter(tags=["agent"])


def _turn_response(db: Session, outcome: TurnOutcome) -> TurnRead:
    run = outcome.run
    usage = None
    if run.status == "succeeded":
        usage = UsageRead(
            input_tokens=run.input_tokens,
            output_tokens=run.output_tokens,
            total_tokens=run.total_tokens,
        )
    error = None
    if run.status == "failed":
        error = TurnErrorRead(code=run.error_code or "unknown", summary=run.error_summary or "")

    snapshot = (
        db.query(ContextSnapshot).filter_by(agent_run_id=run.id).one_or_none()
    )

    return TurnRead(
        run_id=run.id,
        status=run.status,
        user_message=MessageRead.model_validate(outcome.user_message),
        assistant_message=(
            MessageRead.model_validate(outcome.assistant_message)
            if outcome.assistant_message
            else None
        ),
        provider=run.provider,
        model=run.model,
        latency_ms=run.latency_ms,
        usage=usage,
        context_snapshot_id=snapshot.id if snapshot else None,
        error=error,
    )


@router.post(
    "/api/conversations/{conversation_id}/turns",
    response_model=TurnRead,
    status_code=201,
)
def create_turn(
    conversation_id: str,
    payload: TurnCreate,
    db: Session = Depends(get_db),
    provider: AgentProvider = Depends(get_provider),
    settings: Settings = Depends(get_settings),
) -> TurnRead:
    try:
        outcome = send_turn(
            db,
            provider,
            settings,
            conversation_id,
            payload.content,
            payload.idempotency_key,
            additional_domain_ids=payload.additional_domain_ids,
        )
    except ConversationNotFoundError:
        raise HTTPException(status_code=404, detail="Conversation not found")

    return _turn_response(db, outcome)


@router.get("/api/agent/status", response_model=AgentStatusRead)
def agent_status(
    provider: AgentProvider = Depends(get_provider),
    settings: Settings = Depends(get_settings),
) -> AgentStatusRead:
    health = provider.health(timeout=5.0)
    if not health.available:
        return AgentStatusRead(
            hermes_available=False,
            model_configured=False,
            model=None,
            provider=provider.name,
        )

    info = provider.model_info(timeout=5.0)
    return AgentStatusRead(
        hermes_available=True,
        model_configured=info.configured,
        model=info.model,
        provider=provider.name,
    )

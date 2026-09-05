"""Phase 8: the Jarvis-initiated action proposal/approval/execution API."""

from __future__ import annotations

import json

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app import action_service
from app.capabilities import CAPABILITY_REGISTRY, CapabilityError
from app.credential_store import CredentialStore
from app.deps import get_credential_store, get_db, get_http_client
from app.models_actions import ActionProposal
from app.schemas_actions import (
    ActionApproveRequest,
    ActionAuditEventRead,
    ActionDenyRequest,
    ActionExecuteRequest,
    ActionProposalRead,
    ActionProposalWithHistory,
    ActionProposeRequest,
)

router = APIRouter(tags=["actions"])


def proposal_to_read(proposal: ActionProposal) -> ActionProposalRead:
    return ActionProposalRead(
        id=proposal.id,
        capability_id=proposal.capability_id,
        domain_id=proposal.domain_id,
        permission_level=proposal.permission_level,
        arguments=json.loads(proposal.arguments_json),
        reason=proposal.reason,
        expected_effect=proposal.expected_effect,
        payload_digest=proposal.payload_digest,
        status=proposal.status,
        source=proposal.source,
        confirmation_token=proposal.confirmation_token,
        confirmation_expires_at=proposal.confirmation_expires_at,
        result=json.loads(proposal.result_json) if proposal.result_json else None,
        error_summary=proposal.error_summary,
        created_at=proposal.created_at,
        updated_at=proposal.updated_at,
    )


@router.get("/api/capabilities")
def list_capabilities() -> list[dict]:
    return [
        {"capability_id": spec.capability_id, "permission_level": spec.permission_level}
        for spec in CAPABILITY_REGISTRY.values()
    ]


@router.post("/api/actions", response_model=ActionProposalRead, status_code=201)
def create_action_proposal(payload: ActionProposeRequest, db: Session = Depends(get_db)) -> ActionProposalRead:
    try:
        proposal = action_service.propose_action(
            db,
            capability_id=payload.capability_id,
            domain_id=payload.domain_id,
            arguments=payload.arguments,
            reason=payload.reason,
        )
    except CapabilityError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return proposal_to_read(proposal)


@router.get("/api/actions", response_model=list[ActionProposalRead])
def list_action_proposals(
    status: str | None = Query(default=None),
    domain_id: str | None = Query(default=None),
    limit: int = Query(default=50),
    db: Session = Depends(get_db),
) -> list[ActionProposalRead]:
    proposals = action_service.list_proposals(db, status=status, domain_id=domain_id, limit=limit)
    return [proposal_to_read(p) for p in proposals]


@router.get("/api/actions/{proposal_id}", response_model=ActionProposalWithHistory)
def get_action_proposal(proposal_id: str, db: Session = Depends(get_db)) -> ActionProposalWithHistory:
    try:
        proposal = action_service.get_proposal_or_404(db, proposal_id)
    except action_service.ActionNotFoundError:
        raise HTTPException(status_code=404, detail="Action proposal not found")
    events = [ActionAuditEventRead.model_validate(e) for e in proposal.audit_events]
    return ActionProposalWithHistory(proposal=proposal_to_read(proposal), audit_events=events)


@router.post("/api/actions/{proposal_id}/approve", response_model=ActionProposalRead)
def approve_action_proposal(
    proposal_id: str, payload: ActionApproveRequest, db: Session = Depends(get_db)
) -> ActionProposalRead:
    try:
        proposal = action_service.approve_action(db, proposal_id, payload_digest=payload.payload_digest)
    except action_service.ActionNotFoundError:
        raise HTTPException(status_code=404, detail="Action proposal not found")
    except action_service.ActionError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return proposal_to_read(proposal)


@router.post("/api/actions/{proposal_id}/deny", response_model=ActionProposalRead)
def deny_action_proposal(
    proposal_id: str, payload: ActionDenyRequest, db: Session = Depends(get_db)
) -> ActionProposalRead:
    try:
        proposal = action_service.deny_action(db, proposal_id, reason=payload.reason)
    except action_service.ActionNotFoundError:
        raise HTTPException(status_code=404, detail="Action proposal not found")
    except action_service.ActionError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return proposal_to_read(proposal)


@router.post("/api/actions/{proposal_id}/execute", response_model=ActionProposalRead)
def execute_action_proposal(
    proposal_id: str,
    payload: ActionExecuteRequest,
    db: Session = Depends(get_db),
    credential_store: CredentialStore = Depends(get_credential_store),
    http_client=Depends(get_http_client),
) -> ActionProposalRead:
    try:
        proposal = action_service.execute_action(
            db,
            proposal_id,
            confirmation_token=payload.confirmation_token,
            http_client=http_client,
            credential_store=credential_store,
        )
    except action_service.ActionNotFoundError:
        raise HTTPException(status_code=404, detail="Action proposal not found")
    except action_service.ActionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    return proposal_to_read(proposal)

"""Phase 8: the Jarvis-initiated action lifecycle.

propose -> approve (bound to the exact payload digest) -> execute (bound to
a short-lived, single-use confirmation token) -> succeeded/failed, with an
append-only audit trail at every transition. See CLAUDE.md §12 and
docs/ARCHITECTURE.md §8c for the full contract this implements.

Direct actions a user takes through existing UI controls (saving a note,
editing a memory by hand, etc.) never go through this module — only
Jarvis-initiated proposals do.
"""

from __future__ import annotations

import hashlib
import json
import secrets
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app import hooks
from app.capabilities import get_capability, validate_domain_for_capability
from app.models_actions import ActionAuditEvent, ActionProposal
from app.recall_index_service import sync_recall

CONFIRMATION_TTL = timedelta(minutes=5)


class ActionError(Exception):
    pass


class ActionNotFoundError(Exception):
    pass


def compute_payload_digest(capability_id: str, domain_id: str | None, arguments: dict) -> str:
    canonical = json.dumps(
        {"capability_id": capability_id, "domain_id": domain_id, "arguments": arguments},
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _as_aware_utc(dt: datetime) -> datetime:
    """SQLite round-trips DateTime(timezone=True) values as naive datetimes
    (no offset survives storage) — every timestamp this module writes is
    already UTC, so a naive value read back is safely reinterpreted as UTC
    rather than compared incorrectly against an aware `datetime.now(utc)`."""
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=timezone.utc)


def _record_event(session: Session, proposal: ActionProposal, event_type: str, detail: str | None = None) -> None:
    session.add(ActionAuditEvent(action_proposal_id=proposal.id, event_type=event_type, detail=detail))
    session.flush()


def propose_action(
    session: Session,
    *,
    capability_id: str,
    domain_id: str | None,
    arguments: dict,
    reason: str,
    expected_effect: str | None = None,
    source: str = "manual_proposal",
) -> ActionProposal:
    spec = get_capability(capability_id)
    spec.validate(arguments)
    validate_domain_for_capability(session, spec, domain_id, arguments)

    digest = compute_payload_digest(capability_id, domain_id, arguments)
    effect = expected_effect or spec.describe_effect(arguments)

    proposal = ActionProposal(
        capability_id=capability_id,
        domain_id=domain_id,
        permission_level=spec.permission_level,
        arguments_json=json.dumps(arguments, sort_keys=True),
        reason=reason,
        expected_effect=effect,
        payload_digest=digest,
        status="proposed",
        source=source,
    )
    session.add(proposal)
    session.flush()
    sync_recall(session, "action_proposal", proposal.id)
    _record_event(session, proposal, "proposed", detail=reason)
    session.commit()
    session.refresh(proposal)
    return proposal


def get_proposal_or_404(session: Session, proposal_id: str) -> ActionProposal:
    proposal = session.get(ActionProposal, proposal_id)
    if proposal is None:
        raise ActionNotFoundError(proposal_id)
    return proposal


def _expire_if_needed(session: Session, proposal: ActionProposal) -> None:
    if proposal.status != "approved":
        return
    if proposal.confirmation_expires_at is None:
        return
    if _as_aware_utc(proposal.confirmation_expires_at) < datetime.now(timezone.utc):
        proposal.status = "expired"
        session.flush()
        _record_event(session, proposal, "expired", detail="Confirmation window elapsed before execution.")
        session.commit()
        session.refresh(proposal)


def expire_interrupted_executions(session: Session) -> int:
    """Recovers any proposal left stuck in `executing` by a backend crash or
    kill (power loss, OOM, `kill -9`, a laptop sleep interrupting a network
    call) between the two commits inside `execute_action` — the window where
    a proposal is marked "executing" but `spec.execute(...)` has not yet
    returned. Nothing else in this codebase ever moves a proposal out of
    `executing` except a normal completion of that same call; the identical
    situation during a restore is already handled by
    `import_service._expire_stale_action_proposals`, but an ordinary backend
    restart (no restore involved) previously left such a row permanently
    stuck — `list_proposals`'s lazy `_expire_if_needed` only ever resolves a
    time-based `approved`-window expiry, never an `executing` row, and
    `_recursion_guard_hook` correctly refuses to ever re-execute or
    otherwise resolve one.

    Marked `failed`, not a fabricated `succeeded` — but the error summary is
    explicit that the underlying capability's real-world effect is unknown
    (it may have already completed, e.g. a Google Calendar event may already
    exist) rather than implying a normal, understood failure. Called once at
    backend startup, before anything else can observe these proposals."""
    stuck = session.execute(select(ActionProposal).where(ActionProposal.status == "executing")).scalars().all()
    for proposal in stuck:
        proposal.status = "failed"
        proposal.error_summary = (
            "Interrupted by a backend restart while executing — the real-world outcome is "
            "unknown. If this proposed an external change (e.g. a Google Calendar write), "
            "verify the target system directly before retrying."
        )
        session.flush()
        _record_event(
            session,
            proposal,
            "failed",
            detail="Recovered at startup: proposal was left in 'executing' by an interrupted backend process.",
        )
    if stuck:
        session.commit()
    return len(stuck)


def list_proposals(
    session: Session,
    *,
    status: str | None = None,
    domain_id: str | None = None,
    limit: int = 50,
) -> list[ActionProposal]:
    limit = max(1, min(limit, 200))
    stmt = select(ActionProposal)
    if status is not None:
        stmt = stmt.where(ActionProposal.status == status)
    if domain_id is not None:
        stmt = stmt.where(ActionProposal.domain_id == domain_id)
    stmt = stmt.order_by(ActionProposal.created_at.desc()).limit(limit)
    proposals = list(session.execute(stmt).scalars().all())
    for proposal in proposals:
        _expire_if_needed(session, proposal)
    return proposals


def approve_action(session: Session, proposal_id: str, *, payload_digest: str) -> ActionProposal:
    proposal = get_proposal_or_404(session, proposal_id)
    _expire_if_needed(session, proposal)

    if proposal.status != "proposed":
        raise ActionError(f"Cannot approve a proposal in status {proposal.status!r}.")
    if payload_digest != proposal.payload_digest:
        raise ActionError("Payload digest does not match this proposal's exact content — refusing to approve.")

    proposal.status = "approved"
    proposal.confirmation_token = secrets.token_hex(32)
    proposal.confirmation_expires_at = datetime.now(timezone.utc) + CONFIRMATION_TTL
    proposal.confirmation_used_at = None
    session.flush()
    _record_event(session, proposal, "approved")
    session.commit()
    session.refresh(proposal)
    return proposal


def deny_action(session: Session, proposal_id: str, *, reason: str | None = None) -> ActionProposal:
    proposal = get_proposal_or_404(session, proposal_id)
    _expire_if_needed(session, proposal)

    if proposal.status not in ("proposed", "approved"):
        raise ActionError(f"Cannot deny a proposal in status {proposal.status!r}.")

    proposal.status = "denied"
    session.flush()
    _record_event(session, proposal, "denied", detail=reason)
    session.commit()
    session.refresh(proposal)
    return proposal


def execute_action(
    session: Session, proposal_id: str, *, confirmation_token: str, http_client=None, credential_store=None
) -> ActionProposal:
    proposal = get_proposal_or_404(session, proposal_id)
    _expire_if_needed(session, proposal)

    context = hooks.HookContext(
        phase="before_action",
        db=session,
        action_proposal=proposal,
        domain_id=proposal.domain_id,
        extra={"confirmation_token": confirmation_token},
    )
    outcomes = hooks.run_hooks("before_action", context)
    session.commit()
    blocked = next((o for o in outcomes if not o.allowed), None)
    if blocked is not None:
        raise ActionError(blocked.detail)

    # Single-use: consumed on the attempt, not on success, so a failing
    # handler cannot be retried indefinitely with the same token.
    proposal.status = "executing"
    proposal.confirmation_used_at = datetime.now(timezone.utc)
    session.flush()
    _record_event(session, proposal, "executing")
    session.commit()
    session.refresh(proposal)

    try:
        spec = get_capability(proposal.capability_id)
        arguments = json.loads(proposal.arguments_json)
        result = spec.execute(
            session, proposal.domain_id, arguments, http_client=http_client, credential_store=credential_store
        )
    except Exception as exc:
        session.rollback()
        session.refresh(proposal)
        proposal.status = "failed"
        proposal.error_summary = str(exc)[:500]
        session.flush()
        sync_recall(session, "action_proposal", proposal.id)
        _record_event(session, proposal, "failed", detail=proposal.error_summary)
        session.commit()
        session.refresh(proposal)

        failure_context = hooks.HookContext(
            phase="on_failure",
            db=session,
            action_proposal=proposal,
            domain_id=proposal.domain_id,
            extra={"error_summary": proposal.error_summary},
        )
        hooks.run_hooks("on_failure", failure_context)
        session.commit()
        return proposal

    proposal.status = "succeeded"
    proposal.result_json = json.dumps(result)
    session.flush()
    _record_event(session, proposal, "succeeded")
    session.commit()
    session.refresh(proposal)

    after_context = hooks.HookContext(
        phase="after_action", db=session, action_proposal=proposal, domain_id=proposal.domain_id
    )
    hooks.run_hooks("after_action", after_context)
    session.commit()
    return proposal

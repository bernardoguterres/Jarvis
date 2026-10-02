"""The Jarvis-initiated action lifecycle: propose, approve (bound to the
exact payload digest), execute (bound to a short-lived, single-use
confirmation token), then succeeded/failed, with an append-only audit
trail. Direct user actions through the UI never go through here.
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
from app.capability_errors import CapabilityNeedsReviewError
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
    (no offset survives storage). Every timestamp this module writes is
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


def _reenable_for_retry(session: Session, proposal: ActionProposal, *, detail: str) -> None:
    """Puts a proposal back into `approved` with a fresh single-use
    confirmation token, so it can be retried through the ordinary
    execute_action path. Used only when the external system's absence of
    effect has been positively confirmed (never merely assumed)."""
    proposal.status = "approved"
    proposal.confirmation_token = secrets.token_hex(32)
    proposal.confirmation_expires_at = datetime.now(timezone.utc) + CONFIRMATION_TTL
    proposal.confirmation_used_at = None
    proposal.error_summary = None
    session.flush()
    _record_event(session, proposal, "approved", detail=detail)


def _mark_needs_review(session: Session, proposal: ActionProposal, *, detail: str) -> None:
    proposal.status = "needs_review"
    proposal.error_summary = detail[:500]
    session.flush()
    _record_event(session, proposal, "needs_review", detail=detail)


def _mark_confirmed_succeeded(
    session: Session, proposal: ActionProposal, *, result: dict, detail: str
) -> None:
    proposal.status = "succeeded"
    proposal.result_json = json.dumps(result)
    proposal.error_summary = None
    session.flush()
    _record_event(session, proposal, "succeeded", detail=detail)


def _cache_event_if_missing(session: Session, calendar, external_id: str, arguments: dict) -> None:
    from app.models_integrations import CalendarEventCache

    existing_cache = session.execute(
        select(CalendarEventCache).where(
            CalendarEventCache.calendar_id == calendar.id, CalendarEventCache.external_event_id == external_id
        )
    ).scalar_one_or_none()
    if existing_cache is None:
        session.add(
            CalendarEventCache(
                calendar_id=calendar.id,
                external_event_id=external_id,
                title=arguments.get("title", "(untitled)"),
                description=arguments.get("description"),
                location=arguments.get("location"),
                all_day=bool(arguments.get("all_day", False)),
            )
        )
        session.flush()


def _reconcile_calendar_create(
    session: Session, proposal: ActionProposal, arguments: dict, http_client, credential_store
) -> None:
    from app import integration_service
    from app.models_integrations import CalendarCalendar
    from app.providers import google_calendar as gcal_provider

    calendar = session.get(CalendarCalendar, arguments.get("calendar_id"))
    if calendar is None:
        _mark_needs_review(session, proposal, detail="Recovery could not find the target calendar locally.")
        return

    deterministic_id = gcal_provider.deterministic_event_id(proposal.id)
    try:
        access_token = integration_service.ensure_fresh_access_token(
            session, credential_store, http_client, "google_calendar"
        )
        # Prefer a direct lookup by this action's own deterministic event
        # ID: the exact ID the interrupted create attempt would have sent,
        # so this is a precise single-event fetch rather than a search.
        live = gcal_provider.get_event(
            client=http_client,
            access_token=access_token,
            calendar_id=calendar.external_calendar_id,
            event_id=deterministic_id,
        )
    except Exception as exc:
        _mark_needs_review(
            session,
            proposal,
            detail=(
                "Interrupted while creating a Google Calendar event, and recovery could not reach "
                f"Google to confirm the outcome: {exc}. Verify the calendar directly before retrying."
            ),
        )
        return

    if live is not None:
        tagged_id = ((live.get("extendedProperties") or {}).get("private", {})).get("jarvis_action_id")
        if tagged_id != proposal.id:
            # An event occupies this action's deterministic ID but its own
            # metadata doesn't confirm it belongs to this action. Never
            # guess either way.
            _mark_needs_review(
                session,
                proposal,
                detail=(
                    "Recovered at startup: an event exists at this action's deterministic ID, but its "
                    "metadata does not confirm it belongs to this action. Verify the calendar directly."
                ),
            )
            return
        _cache_event_if_missing(session, calendar, deterministic_id, arguments)
        _mark_confirmed_succeeded(
            session,
            proposal,
            result={"external_event_id": deterministic_id, "calendar_id": calendar.id},
            detail=(
                "Recovered at startup: Google Calendar confirmed an event at this action's own "
                "deterministic ID, tagged with this action's ID — the interrupted create had actually "
                "succeeded."
            ),
        )
        return

    # Not found at the deterministic ID: either the create never took
    # effect, or (an event created before this deterministic-ID scheme
    # existed) it was tagged only via the private extended property, never
    # given this ID. Fall back to that legacy lookup path before concluding
    # absence, preserving compatibility with events created before this
    # change.
    try:
        matches = gcal_provider.find_events_by_private_property(
            client=http_client,
            access_token=access_token,
            calendar_id=calendar.external_calendar_id,
            key="jarvis_action_id",
            value=proposal.id,
        )
    except Exception as exc:
        _mark_needs_review(
            session,
            proposal,
            detail=(
                "Interrupted while creating a Google Calendar event, and recovery could not reach "
                f"Google to confirm the outcome: {exc}. Verify the calendar directly before retrying."
            ),
        )
        return

    if matches:
        external_id = matches[0]
        _cache_event_if_missing(session, calendar, external_id, arguments)
        _mark_confirmed_succeeded(
            session,
            proposal,
            result={"external_event_id": external_id, "calendar_id": calendar.id},
            detail=(
                "Recovered at startup: Google Calendar confirmed a (legacy, private-property-tagged) "
                "event for this action already exists — the interrupted create had actually succeeded."
            ),
        )
    else:
        _reenable_for_retry(
            session,
            proposal,
            detail=(
                "Recovered at startup: Google Calendar confirmed no event for this action exists — "
                "the interrupted create never took effect. Safe to retry."
            ),
        )


def _reconcile_calendar_mutation(
    session: Session, proposal: ActionProposal, arguments: dict, http_client, credential_store, *, is_delete: bool
) -> None:
    from app import integration_service
    from app.models_integrations import CalendarCalendar, CalendarEventCache
    from app.providers import google_calendar as gcal_provider

    calendar = session.get(CalendarCalendar, arguments.get("calendar_id"))
    cached_event = session.get(CalendarEventCache, arguments.get("event_id"))
    if calendar is None or cached_event is None:
        _mark_needs_review(
            session, proposal, detail="Recovery could not find the target calendar/event locally."
        )
        return
    try:
        access_token = integration_service.ensure_fresh_access_token(
            session, credential_store, http_client, "google_calendar"
        )
        live = gcal_provider.get_event(
            client=http_client,
            access_token=access_token,
            calendar_id=calendar.external_calendar_id,
            event_id=cached_event.external_event_id,
        )
    except Exception as exc:
        _mark_needs_review(
            session,
            proposal,
            detail=(
                f"Interrupted while modifying a Google Calendar event, and recovery could not reach "
                f"Google to confirm the outcome: {exc}. Verify the calendar directly before retrying."
            ),
        )
        return

    if is_delete:
        if live is None:
            session.delete(cached_event)
            session.flush()
            _mark_confirmed_succeeded(
                session,
                proposal,
                result={"deleted_event_id": arguments.get("event_id")},
                detail="Recovered at startup: Google confirmed the event no longer exists.",
            )
        else:
            # A delete is naturally idempotent (repeat DELETE calls are
            # harmless, since the provider already treats a 410 as success), so
            # retrying carries no duplication risk once we know the event
            # is still present.
            _reenable_for_retry(
                session,
                proposal,
                detail="Recovered at startup: Google confirmed the event still exists. Safe to retry.",
            )
        return

    # Update: a PATCH is naturally idempotent (reapplying the same field
    # values twice never creates a duplicate), so as long as the event
    # still exists it is always safe to retry, whether or not the earlier
    # attempt's patch had already landed.
    if live is None:
        _mark_needs_review(
            session,
            proposal,
            detail="Recovered at startup: the target event no longer exists on Google Calendar.",
        )
    else:
        _reenable_for_retry(
            session,
            proposal,
            detail="Recovered at startup: the target event still exists on Google Calendar. Safe to retry.",
        )


def expire_interrupted_executions(session: Session, *, http_client=None, credential_store=None) -> int:
    """Recovers proposals left in `executing` by a crash or kill between
    the two commits in `execute_action`. Runs once at startup.

    A local capability's change shares the transaction with the status
    commit, so an interrupted one never took effect and `failed` is
    accurate. A Google Calendar change happens outside that transaction,
    so it is reconciled against Google: confirmed succeeded, safe to
    retry, or `needs_review` when Google can't tell us. Without a client
    or credentials, every stuck Calendar proposal becomes `needs_review`
    rather than a guess."""
    stuck = session.execute(select(ActionProposal).where(ActionProposal.status == "executing")).scalars().all()
    for proposal in stuck:
        if proposal.capability_id.startswith("google_calendar.event."):
            if http_client is None or credential_store is None:
                _mark_needs_review(
                    session,
                    proposal,
                    detail=(
                        "Interrupted while executing a Google Calendar write, and recovery had no "
                        "way to reach Google to confirm the outcome. Verify the calendar directly."
                    ),
                )
                continue
            arguments = json.loads(proposal.arguments_json)
            try:
                if proposal.capability_id == "google_calendar.event.create":
                    _reconcile_calendar_create(session, proposal, arguments, http_client, credential_store)
                elif proposal.capability_id == "google_calendar.event.delete":
                    _reconcile_calendar_mutation(
                        session, proposal, arguments, http_client, credential_store, is_delete=True
                    )
                else:
                    _reconcile_calendar_mutation(
                        session, proposal, arguments, http_client, credential_store, is_delete=False
                    )
            except Exception as exc:
                session.rollback()
                session.refresh(proposal)
                _mark_needs_review(
                    session, proposal, detail=f"Recovery failed unexpectedly and made no changes: {exc}"
                )
        else:
            proposal.status = "failed"
            proposal.error_summary = (
                "Interrupted by a backend restart while executing a local-only capability with no "
                "external effect — the database transaction never committed, so it did not happen."
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
            session,
            proposal.domain_id,
            arguments,
            http_client=http_client,
            credential_store=credential_store,
            action_proposal_id=proposal.id,
        )
    except CapabilityNeedsReviewError as exc:
        # A capability determined its own real-world outcome is genuinely
        # unverifiable (e.g. a Google Calendar create conflicted with an
        # existing event whose metadata didn't match this action). Never
        # collapse that honest uncertainty into a false "failed".
        session.rollback()
        session.refresh(proposal)
        proposal.status = "needs_review"
        proposal.error_summary = str(exc.detail)[:500]
        session.flush()
        sync_recall(session, "action_proposal", proposal.id)
        _record_event(session, proposal, "needs_review", detail=proposal.error_summary)
        session.commit()
        session.refresh(proposal)
        return proposal
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

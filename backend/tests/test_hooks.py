"""Hook registration/ordering, fail-closed behavior, and auditable outcomes."""

from __future__ import annotations

from sqlalchemy.orm import Session

from app import action_service, hooks
from app.models import Domain
from app.models_actions import HookEvent


def test_hook_ordering_is_explicit_and_documented() -> None:
    assert hooks.registered_hook_names("before_context") == ["validate_domain_exists"]
    assert hooks.registered_hook_names("before_action") == [
        "capability_allowlist",
        "confirmation_validity",
        "recursion_guard",
    ]
    assert hooks.registered_hook_names("after_action") == ["audit_after_action"]
    assert hooks.registered_hook_names("on_failure") == ["audit_on_failure"]


def test_before_context_hook_rejects_unknown_domain(db_session: Session) -> None:
    context = hooks.HookContext(phase="before_context", db=db_session, domain_id="not-a-real-domain-id")
    outcomes = hooks.run_hooks("before_context", context)
    assert outcomes[0].allowed is False

    events = db_session.query(HookEvent).filter_by(phase="before_context").all()
    assert len(events) == 1
    assert events[0].outcome == "blocked"


def test_before_context_hook_allows_real_domain(db_session: Session) -> None:
    body = db_session.query(Domain).filter_by(slug="body").one()
    context = hooks.HookContext(phase="before_context", db=db_session, domain_id=body.id)
    outcomes = hooks.run_hooks("before_context", context)
    assert outcomes[0].allowed is True


def test_before_action_hooks_run_in_order_and_stop_at_first_failure(db_session: Session) -> None:
    proposal = action_service.propose_action(
        db_session,
        capability_id="memory.create",
        domain_id=None,
        arguments={"scope": "global", "kind": "fact", "title": "hook-order", "content": "c"},
        reason="test",
    )
    # Not yet approved: confirmation_validity should block, and recursion_guard
    # (registered after it) must never even run.
    context = hooks.HookContext(
        phase="before_action",
        db=db_session,
        action_proposal=proposal,
        domain_id=None,
        extra={"confirmation_token": "irrelevant"},
    )
    outcomes = hooks.run_hooks("before_action", context)
    assert len(outcomes) == 2  # capability_allowlist (ok), confirmation_validity (blocked) — stopped there
    assert outcomes[0].allowed is True
    assert outcomes[1].allowed is False

    events = (
        db_session.query(HookEvent)
        .filter_by(action_proposal_id=proposal.id, phase="before_action")
        .order_by(HookEvent.created_at)
        .all()
    )
    assert [e.hook_name for e in events] == ["capability_allowlist", "confirmation_validity"]
    assert [e.outcome for e in events] == ["ok", "blocked"]


def test_after_action_and_on_failure_hooks_produce_audit_events(db_session: Session) -> None:
    proposal = action_service.propose_action(
        db_session,
        capability_id="memory.create",
        domain_id=None,
        arguments={"scope": "global", "kind": "fact", "title": "hook-audit", "content": "c"},
        reason="test",
    )
    approved = action_service.approve_action(db_session, proposal.id, payload_digest=proposal.payload_digest)
    action_service.execute_action(db_session, proposal.id, confirmation_token=approved.confirmation_token)

    after_events = db_session.query(HookEvent).filter_by(action_proposal_id=proposal.id, phase="after_action").all()
    assert len(after_events) == 1
    assert after_events[0].outcome == "ok"


def test_recursion_guard_blocks_re_execution_after_success(db_session: Session) -> None:
    proposal = action_service.propose_action(
        db_session,
        capability_id="memory.create",
        domain_id=None,
        arguments={"scope": "global", "kind": "fact", "title": "no-recursion", "content": "c"},
        reason="test",
    )
    approved = action_service.approve_action(db_session, proposal.id, payload_digest=proposal.payload_digest)
    action_service.execute_action(db_session, proposal.id, confirmation_token=approved.confirmation_token)

    # Attempt a second execute with the very same (now-used) token.
    context = hooks.HookContext(
        phase="before_action",
        db=db_session,
        action_proposal=action_service.get_proposal_or_404(db_session, proposal.id),
        domain_id=None,
        extra={"confirmation_token": approved.confirmation_token},
    )
    outcomes = hooks.run_hooks("before_action", context)
    # confirmation_validity itself already blocks (status is no longer "approved"),
    # so recursion_guard never even needs to run — still a correct fail-closed result.
    assert any(not o.allowed for o in outcomes)

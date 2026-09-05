"""Phase 8: deterministic, explicitly-registered controller lifecycle hooks.

Not to be confused with Claude Code's own development hooks — these are
Jarvis Controller runtime hooks, running inside this backend process only.

Ordering is explicit (registration order, listed at the bottom of this
file) and documented in docs/ARCHITECTURE.md §8c. Every hook receives a
typed HookContext and returns a typed HookOutcome; every invocation is
recorded as an auditable HookEvent row before its result is used. A hook
that returns allowed=False stops the phase immediately (fail closed) —
callers must not proceed to the risky operation the phase gates.

Hooks here are plain Python functions defined in this codebase. None of
them execute arbitrary user-provided shell commands or code, none rewrite
stored messages/memories, and none depend on which reasoning model/provider
is configured.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Callable

from sqlalchemy.orm import Session

from app.models import Domain
from app.models_actions import ActionProposal, HookEvent


@dataclass
class HookContext:
    phase: str
    db: Session
    action_proposal: ActionProposal | None = None
    domain_id: str | None = None
    extra: dict = field(default_factory=dict)


@dataclass
class HookOutcome:
    allowed: bool
    detail: str = ""


HookFn = Callable[[HookContext], HookOutcome]


class HookRegistrationError(Exception):
    pass


_REGISTRY: dict[str, list[tuple[str, HookFn]]] = {
    "before_context": [],
    "before_action": [],
    "after_action": [],
    "on_failure": [],
}


def register_hook(phase: str, name: str, fn: HookFn) -> None:
    if phase not in _REGISTRY:
        raise HookRegistrationError(f"Unknown hook phase: {phase!r}")
    _REGISTRY[phase].append((name, fn))


def registered_hook_names(phase: str) -> list[str]:
    """Documents the effective, in-order allowlist for a phase."""
    return [name for name, _ in _REGISTRY.get(phase, [])]


def run_hooks(phase: str, context: HookContext) -> list[HookOutcome]:
    """Runs every registered hook for `phase` in registration order,
    recording an auditable HookEvent per call. Stops (fail closed) at the
    first hook that returns allowed=False or raises."""
    outcomes: list[HookOutcome] = []
    action_proposal_id = context.action_proposal.id if context.action_proposal else None

    for name, fn in _REGISTRY.get(phase, []):
        raised = False
        try:
            outcome = fn(context)
        except Exception as exc:  # a hook must never crash the caller
            raised = True
            outcome = HookOutcome(allowed=False, detail=f"Hook {name} raised: {exc}")

        outcome_label = "error" if raised else ("ok" if outcome.allowed else "blocked")
        context.db.add(
            HookEvent(
                hook_name=name,
                phase=phase,
                action_proposal_id=action_proposal_id,
                outcome=outcome_label,
                detail=outcome.detail or None,
            )
        )
        context.db.flush()
        outcomes.append(outcome)
        if not outcome.allowed:
            break

    return outcomes


# --- Concrete hooks -------------------------------------------------------


def _validate_domain_exists_hook(context: HookContext) -> HookOutcome:
    """before_context: guards against a stale/deleted domain_id ever
    reaching context construction."""
    if context.domain_id is None:
        return HookOutcome(allowed=True)
    if context.db.get(Domain, context.domain_id) is None:
        return HookOutcome(allowed=False, detail=f"Unknown domain_id: {context.domain_id!r}")
    return HookOutcome(allowed=True)


def _capability_allowlist_hook(context: HookContext) -> HookOutcome:
    """before_action: re-verifies the proposal's capability is still in the
    fixed allowlist, even though it was already checked at proposal time —
    defense in depth against the registry changing between propose and
    execute (e.g. across a version upgrade)."""
    from app.capabilities import CAPABILITY_REGISTRY

    proposal = context.action_proposal
    assert proposal is not None
    if proposal.capability_id not in CAPABILITY_REGISTRY:
        return HookOutcome(allowed=False, detail=f"Capability no longer allowlisted: {proposal.capability_id!r}")
    return HookOutcome(allowed=True)


def _confirmation_validity_hook(context: HookContext) -> HookOutcome:
    """before_action: this IS the enforcement point for the exact-payload,
    short-lived, single-use confirmation binding (CLAUDE.md §12 items 5-7).
    Expects context.extra['confirmation_token'] to have been set by the
    caller (app/action_service.py)."""
    proposal = context.action_proposal
    assert proposal is not None
    token = context.extra.get("confirmation_token")

    if proposal.status != "approved":
        return HookOutcome(allowed=False, detail=f"Proposal status is {proposal.status!r}, not 'approved'")
    if not token or token != proposal.confirmation_token:
        return HookOutcome(allowed=False, detail="Confirmation token missing or does not match this proposal")
    if proposal.confirmation_used_at is not None:
        return HookOutcome(allowed=False, detail="Confirmation token already used (replay rejected)")
    expires_at = proposal.confirmation_expires_at
    if expires_at is not None and expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    if expires_at is None or expires_at < datetime.now(timezone.utc):
        return HookOutcome(allowed=False, detail="Confirmation token expired")
    return HookOutcome(allowed=True)


def _recursion_guard_hook(context: HookContext) -> HookOutcome:
    """before_action: prevents re-entrant/repeated execution of the same
    proposal — status must still be exactly 'approved' at the moment this
    runs (set to 'executing' immediately after, by the caller, inside the
    same transaction)."""
    proposal = context.action_proposal
    assert proposal is not None
    if proposal.status in ("executing", "succeeded", "failed"):
        return HookOutcome(allowed=False, detail=f"Proposal already {proposal.status}; refusing to re-execute")
    return HookOutcome(allowed=True)


def _audit_after_action_hook(context: HookContext) -> HookOutcome:
    return HookOutcome(allowed=True, detail="Action completed successfully.")


def _audit_on_failure_hook(context: HookContext) -> HookOutcome:
    detail = context.extra.get("error_summary", "")
    return HookOutcome(allowed=True, detail=f"Action failed: {detail}")


# Explicit, documented ordering — see docs/ARCHITECTURE.md §8c.
register_hook("before_context", "validate_domain_exists", _validate_domain_exists_hook)
register_hook("before_action", "capability_allowlist", _capability_allowlist_hook)
register_hook("before_action", "confirmation_validity", _confirmation_validity_hook)
register_hook("before_action", "recursion_guard", _recursion_guard_hook)
register_hook("after_action", "audit_after_action", _audit_after_action_hook)
register_hook("on_failure", "audit_on_failure", _audit_on_failure_hook)

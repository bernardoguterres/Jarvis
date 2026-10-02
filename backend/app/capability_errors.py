"""Shared base exception for capability validation/execution failures.

Kept in its own module (rather than defined in app/capabilities.py) so that
per-capability modules like app/calendar_capability.py can raise a subclass
of it without a circular import (capabilities.py imports calendar_capability
at module load time to register its capabilities)."""

from __future__ import annotations


class CapabilityError(Exception):
    """Raised for a malformed/invalid set of arguments for a capability,
    either at proposal time or (defense in depth) at execution time. Every
    capability-specific error (e.g. CalendarCapabilityError) must subclass
    this so routers/actions.py's single `except CapabilityError` handles
    all of them uniformly."""


class CapabilityNeedsReviewError(Exception):
    """Raised by a capability's execute() when it genuinely cannot tell
    whether its real-world effect succeeded or failed, e.g. Google
    Calendar returned a conflicting event ID whose own `jarvis_action_id`
    metadata doesn't match this action, so treating it as either success or
    failure would be a guess. Deliberately NOT a CapabilityError subclass:
    action_service.execute_action catches this separately and marks the
    proposal `needs_review` instead of `failed`, the same honest-uncertainty
    status startup crash recovery already uses."""

    def __init__(self, detail: str) -> None:
        super().__init__(detail)
        self.detail = detail

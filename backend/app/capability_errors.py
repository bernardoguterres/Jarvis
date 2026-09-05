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

"""The three Google Calendar write capabilities
(`google_calendar.event.create/update/delete`), registered into the fixed
the capability registry (app/capabilities.py).

Every write here still goes through the exact same propose -> approve ->
execute lifecycle as any other capability; nothing here bypasses that.
In scope: no attendees, no invitations, no recurring events, no
calendar-sharing changes, no calendar deletion. A timezone is required for
any timed (non-all-day) event, never silently inferred when ambiguous.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.capability_errors import CapabilityError, CapabilityNeedsReviewError, CapabilityRetryableError
from app.models_integrations import CalendarCalendar, CalendarEventCache
from app.providers import google_calendar as gcal_provider


class CalendarCapabilityError(CapabilityError):
    pass


WRITE_SCOPE = "https://www.googleapis.com/auth/calendar.events.owned"


def _require_write_scope_granted(session: Session) -> None:
    """Defense-in-depth re-check at execute time: never assume a requested
    scope was actually granted. `validate_domain_for_capability` in
    capabilities.py performs the same check at propose time; this repeats
    it immediately before any real mutation, since a connection can be
    disconnected or its scope narrowed between propose and execute."""
    from app import integration_service

    if not integration_service.has_scope(session, "google_calendar", WRITE_SCOPE):
        raise CalendarCapabilityError(
            "Google Calendar write access has not been granted (calendar.events.owned scope "
            "is missing from the connection's granted scopes). Enable Calendar writing and "
            "re-authorize before retrying."
        )


def _get_calendar_or_error(session: Session, calendar_id: str) -> CalendarCalendar:
    _require_write_scope_granted(session)
    calendar = session.get(CalendarCalendar, calendar_id)
    if calendar is None:
        raise CalendarCapabilityError(f"Unknown calendar_id: {calendar_id!r}")
    if not calendar.selected:
        raise CalendarCapabilityError("This calendar is not selected for Jarvis access.")
    if not calendar.is_owned:
        raise CalendarCapabilityError("Write access is only permitted for calendars you own.")
    return calendar


def _validate_common(arguments: dict) -> None:
    if not arguments.get("calendar_id"):
        raise CalendarCapabilityError("calendar_id is required")


def validate_event_create(arguments: dict) -> None:
    _validate_common(arguments)
    if not arguments.get("title"):
        raise CalendarCapabilityError("title is required")
    all_day = bool(arguments.get("all_day", False))
    if not arguments.get("start") or not arguments.get("end"):
        raise CalendarCapabilityError("start and end are required")
    if not all_day and not arguments.get("timezone"):
        raise CalendarCapabilityError(
            "timezone is required for a timed event — never silently inferred when ambiguity matters"
        )
    if not all_day:
        try:
            datetime.fromisoformat(arguments["start"])
            datetime.fromisoformat(arguments["end"])
        except ValueError as exc:
            raise CalendarCapabilityError(f"start/end must be ISO datetimes: {exc}") from exc


def describe_event_create(arguments: dict) -> str:
    kind = "all-day" if arguments.get("all_day") else "timed"
    return (
        f"Create a {kind} Google Calendar event titled {arguments.get('title')!r} "
        f"from {arguments.get('start')} to {arguments.get('end')}"
        f"{' (' + arguments['timezone'] + ')' if arguments.get('timezone') else ''}."
    )


def execute_event_create(
    session: Session,
    domain_id: str | None,
    arguments: dict,
    *,
    http_client=None,
    credential_store=None,
    action_proposal_id: str | None = None,
    **_kwargs: Any,
) -> dict:
    if http_client is None or credential_store is None:
        raise CalendarCapabilityError("Calendar execution requires an HTTP client and credential store.")
    calendar = _get_calendar_or_error(session, arguments["calendar_id"])

    from app import integration_service

    access_token = integration_service.ensure_fresh_access_token(session, credential_store, http_client, "google_calendar")
    try:
        return _create_event_with_reconciliation(
            session,
            calendar,
            arguments,
            http_client=http_client,
            access_token=access_token,
            action_proposal_id=action_proposal_id,
        )
    except gcal_provider.GoogleCalendarConflictError as exc:
        return _resolve_create_conflict(
            session, calendar, arguments, exc.event_id, http_client=http_client,
            access_token=access_token, action_proposal_id=action_proposal_id,
        )


def _cache_created_event(session: Session, calendar: CalendarCalendar, external_id: str, arguments: dict) -> None:
    existing_cache = session.execute(
        select(CalendarEventCache).where(
            CalendarEventCache.calendar_id == calendar.id,
            CalendarEventCache.external_event_id == external_id,
        )
    ).scalar_one_or_none()
    if existing_cache is None:
        session.add(
            CalendarEventCache(
                calendar_id=calendar.id,
                external_event_id=external_id,
                title=arguments["title"],
                description=arguments.get("description"),
                location=arguments.get("location"),
                all_day=bool(arguments.get("all_day", False)),
            )
        )
        session.flush()


def _is_cancelled(event: dict) -> bool:
    """Google keeps a deleted event readable with status "cancelled" instead
    of returning 404. A deleted event is never evidence that a create
    succeeded."""
    return event.get("status") == "cancelled"


def _is_uncertain_write_failure(exc: Exception) -> bool:
    """True when the insert may have reached Google even though no success
    response came back: the response was lost (read timeout, dropped
    connection) or Google answered 5xx, which it can do after storing the
    event. A connect failure means the request never left this machine."""
    if isinstance(exc, (httpx.ConnectError, httpx.ConnectTimeout)):
        return False
    if isinstance(exc, httpx.TransportError):
        return True
    if isinstance(exc, gcal_provider.GoogleCalendarError) and not isinstance(
        exc, gcal_provider.GoogleCalendarConflictError
    ):
        return exc.code.startswith("http_5")
    return False


def _create_event_with_reconciliation(
    session: Session,
    calendar: CalendarCalendar,
    arguments: dict,
    *,
    http_client,
    access_token: str,
    action_proposal_id: str | None,
) -> dict:
    """Sends the insert. If the outcome is uncertain, asks Google directly
    whether an event exists at this action's deterministic ID before
    deciding anything: found and tagged means it succeeded, confirmed
    absent means it is safe to retry the same proposal, and anything else
    is needs_review. Never reports a definite failure for a write Google
    may have accepted."""
    try:
        external_id = gcal_provider.create_event(
            client=http_client,
            access_token=access_token,
            calendar_id=calendar.external_calendar_id,
            title=arguments["title"],
            description=arguments.get("description"),
            location=arguments.get("location"),
            all_day=bool(arguments.get("all_day", False)),
            start=arguments["start"],
            end=arguments["end"],
            timezone_name=arguments.get("timezone"),
            # The action proposal's own stable ID is the natural idempotency
            # key: it is persisted (propose_action commits it) before this
            # capability is ever reached, so it survives a crash on either
            # side of this call. It seeds a deterministic, caller-supplied
            # Google event ID (Google's own documented duplicate-prevention
            # mechanism: retrying the same insert reuses the same ID and
            # gets 409 instead of a second event) and is retained as
            # secondary `jarvis_action_id` metadata for reconciliation
            # against legacy events created before this scheme existed.
            idempotency_key=action_proposal_id,
        )
    except gcal_provider.GoogleCalendarConflictError:
        raise
    except (httpx.ConnectError, httpx.ConnectTimeout) as exc:
        if action_proposal_id is None:
            raise
        raise CapabilityRetryableError(
            f"Could not connect to Google Calendar ({type(exc).__name__}); the request never left this "
            "machine, so no event was created. Safe to retry."
        ) from exc
    except Exception as exc:
        if action_proposal_id is None or not _is_uncertain_write_failure(exc):
            raise
        return _reconcile_uncertain_create(
            session, calendar, arguments, exc, http_client=http_client,
            access_token=access_token, action_proposal_id=action_proposal_id,
        )
    _cache_created_event(session, calendar, external_id, arguments)
    return {"external_event_id": external_id, "calendar_id": calendar.id}


def _reconcile_uncertain_create(
    session: Session,
    calendar: CalendarCalendar,
    arguments: dict,
    original: Exception,
    *,
    http_client,
    access_token: str,
    action_proposal_id: str,
) -> dict:
    deterministic_id = gcal_provider.deterministic_event_id(action_proposal_id)
    what = f"{type(original).__name__}: {original}"[:160]
    try:
        live = gcal_provider.get_event(
            client=http_client,
            access_token=access_token,
            calendar_id=calendar.external_calendar_id,
            event_id=deterministic_id,
        )
    except Exception as lookup_exc:
        raise CapabilityNeedsReviewError(
            f"Google Calendar did not confirm the create ({what}), and checking whether the event exists "
            f"also failed ({type(lookup_exc).__name__}). Check the calendar before doing anything else."
        ) from original
    if live is None:
        raise CapabilityRetryableError(
            f"Google Calendar did not confirm the create ({what}). A direct check found no event for this "
            "action right now. Safe to retry: a retry reuses the same event ID, so even if the first "
            "attempt lands late it cannot create a duplicate."
        ) from original
    if _is_cancelled(live):
        raise CapabilityNeedsReviewError(
            "Google Calendar did not confirm the create, and the event at this action's ID has been "
            "deleted. Check the calendar before doing anything else."
        ) from original
    tagged_id = ((live.get("extendedProperties") or {}).get("private", {})).get("jarvis_action_id")
    if tagged_id != action_proposal_id:
        raise CapabilityNeedsReviewError(
            "Google Calendar did not confirm the create, and an event at this action's deterministic ID "
            "is not tagged with this action. Check the calendar before doing anything else."
        ) from original
    _cache_created_event(session, calendar, deterministic_id, arguments)
    return {"external_event_id": deterministic_id, "calendar_id": calendar.id}


def _resolve_create_conflict(
    session: Session,
    calendar: CalendarCalendar,
    arguments: dict,
    event_id: str,
    *,
    http_client,
    access_token: str,
    action_proposal_id: str | None,
) -> dict:
        # Google already has an event at this action's deterministic ID:
        # the expected outcome of retrying an insert whose earlier success
        # response was lost. Confirm it before trusting it: only an event
        # actually tagged with *this* action's own ID may be treated as
        # this action having already succeeded.
    try:
        live = gcal_provider.get_event(
            client=http_client,
            access_token=access_token,
            calendar_id=calendar.external_calendar_id,
            event_id=event_id,
        )
    except Exception as exc:
        raise CapabilityNeedsReviewError(
            "Google Calendar reported an event already exists at this action's deterministic ID, and "
            f"fetching it to confirm failed ({type(exc).__name__}). Verify the calendar directly."
        ) from exc
    tagged_id = ((live or {}).get("extendedProperties") or {}).get("private", {}).get("jarvis_action_id")
    if live is not None and tagged_id == action_proposal_id and not _is_cancelled(live):
        _cache_created_event(session, calendar, event_id, arguments)
        return {"external_event_id": event_id, "calendar_id": calendar.id}
    # An event already occupies this deterministic ID but its metadata
    # doesn't confirm it belongs to this action. Never guess either way.
    raise CapabilityNeedsReviewError(
        "Google Calendar reported an event already exists at this action's deterministic ID, but its "
        "metadata could not be confirmed as belonging to this action. Verify the calendar directly "
        "before retrying."
    )


def validate_event_update(arguments: dict) -> None:
    _validate_common(arguments)
    if not arguments.get("event_id"):
        raise CalendarCapabilityError("event_id is required")
    if not any(arguments.get(k) is not None for k in ("title", "description", "location")):
        raise CalendarCapabilityError("At least one of title/description/location must be provided")


def describe_event_update(arguments: dict) -> str:
    return f"Update Google Calendar event {arguments.get('event_id')!r}."


def execute_event_update(
    session: Session, domain_id: str | None, arguments: dict, *, http_client=None, credential_store=None, **_kwargs: Any
) -> dict:
    if http_client is None or credential_store is None:
        raise CalendarCapabilityError("Calendar execution requires an HTTP client and credential store.")
    calendar = _get_calendar_or_error(session, arguments["calendar_id"])
    cached_event = session.get(CalendarEventCache, arguments["event_id"])
    if cached_event is None or cached_event.calendar_id != calendar.id:
        raise CalendarCapabilityError("Unknown event_id for this calendar.")

    from app import integration_service

    access_token = integration_service.ensure_fresh_access_token(session, credential_store, http_client, "google_calendar")
    gcal_provider.update_event(
        client=http_client,
        access_token=access_token,
        calendar_id=calendar.external_calendar_id,
        event_id=cached_event.external_event_id,
        title=arguments.get("title"),
        description=arguments.get("description"),
        location=arguments.get("location"),
    )
    if arguments.get("title") is not None:
        cached_event.title = arguments["title"]
    if arguments.get("description") is not None:
        cached_event.description = arguments["description"]
    if arguments.get("location") is not None:
        cached_event.location = arguments["location"]
    session.flush()
    return {"external_event_id": cached_event.external_event_id}


def validate_event_delete(arguments: dict) -> None:
    _validate_common(arguments)
    if not arguments.get("event_id"):
        raise CalendarCapabilityError("event_id is required")


def describe_event_delete(arguments: dict) -> str:
    return f"Delete Google Calendar event {arguments.get('event_id')!r}."


def execute_event_delete(
    session: Session, domain_id: str | None, arguments: dict, *, http_client=None, credential_store=None, **_kwargs: Any
) -> dict:
    if http_client is None or credential_store is None:
        raise CalendarCapabilityError("Calendar execution requires an HTTP client and credential store.")
    calendar = _get_calendar_or_error(session, arguments["calendar_id"])
    cached_event = session.get(CalendarEventCache, arguments["event_id"])
    if cached_event is None or cached_event.calendar_id != calendar.id:
        raise CalendarCapabilityError("Unknown event_id for this calendar.")

    from app import integration_service

    access_token = integration_service.ensure_fresh_access_token(session, credential_store, http_client, "google_calendar")
    gcal_provider.delete_event(
        client=http_client, access_token=access_token, calendar_id=calendar.external_calendar_id, event_id=cached_event.external_event_id
    )
    session.delete(cached_event)
    session.flush()
    return {"deleted_event_id": arguments["event_id"]}

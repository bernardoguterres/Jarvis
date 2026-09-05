"""Phase 8's fixed, code-owned capability registry — a default-deny
allowlist. A capability_id not in this dict cannot be proposed, approved,
or executed; nothing (not a skill, not a model, not an import) can add to
this set at runtime.

Every capability here is "Confirm" tier (CLAUDE.md §12): it only ever
proposes a controller-owned internal record — no external side effect.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable

from sqlalchemy.orm import Session

from app import calendar_capability, domain_summary_service, memory_service, structured_record_service
from app.capability_errors import CapabilityError
from app.models import Domain
from app.models_memory import MEMORY_SCOPES
from app.structured_records import RECORD_TYPE_DOMAIN_SLUG

__all__ = ["CapabilityError", "CapabilitySpec", "CAPABILITY_REGISTRY", "get_capability", "validate_domain_for_capability"]


@dataclass
class CapabilitySpec:
    capability_id: str
    permission_level: str
    domain_required: bool  # True if arguments must resolve to exactly one domain
    validate: Callable[[dict], None]
    describe_effect: Callable[[dict], str]
    # Every execute function accepts **kwargs so capabilities that need
    # external I/O (e.g. the Google Calendar write capabilities) can declare
    # `http_client`/`credential_store` keyword params while the majority of
    # purely-local capabilities simply ignore them.
    execute: Callable[..., dict]


def _validate_memory_create(arguments: dict) -> None:
    scope = arguments.get("scope")
    if scope not in MEMORY_SCOPES:
        raise CapabilityError(f"scope must be one of {MEMORY_SCOPES}")
    if not arguments.get("kind"):
        raise CapabilityError("kind is required")
    if not arguments.get("title"):
        raise CapabilityError("title is required")
    if not arguments.get("content"):
        raise CapabilityError("content is required")


def _describe_memory_create(arguments: dict) -> str:
    return f"Create a {arguments.get('scope')} memory titled {arguments.get('title')!r}."


def _execute_memory_create(session: Session, domain_id: str | None, arguments: dict, **_kwargs: Any) -> dict:
    item = memory_service.create_memory(
        session,
        scope=arguments["scope"],
        domain_id=domain_id,
        kind=arguments["kind"],
        title=arguments["title"],
        content=arguments["content"],
        importance=arguments.get("importance", 3),
        confidence=arguments.get("confidence", 1.0),
        sensitivity=arguments.get("sensitivity", "normal"),
        source_note=arguments.get("source_note"),
        source="action_proposal",
    )
    return {"memory_item_id": item.id}


def _validate_structured_record_create(arguments: dict) -> None:
    record_type = arguments.get("record_type")
    if record_type not in RECORD_TYPE_DOMAIN_SLUG:
        raise CapabilityError(f"record_type must be one of {sorted(RECORD_TYPE_DOMAIN_SLUG)}")
    if not isinstance(arguments.get("payload"), dict):
        raise CapabilityError("payload must be an object")


def _describe_structured_record_create(arguments: dict) -> str:
    return f"Create a {arguments.get('record_type')} record."


def _execute_structured_record_create(session: Session, domain_id: str | None, arguments: dict, **_kwargs: Any) -> dict:
    if domain_id is None:
        raise CapabilityError("structured_record.create requires a domain_id")
    occurred_at_raw = arguments.get("occurred_at")
    occurred_at = (
        datetime.fromisoformat(occurred_at_raw) if occurred_at_raw else datetime.now(timezone.utc)
    )
    try:
        record = structured_record_service.create_structured_record(
            session,
            domain_id=domain_id,
            record_type=arguments["record_type"],
            occurred_at=occurred_at,
            payload=arguments["payload"],
        )
    except structured_record_service.StructuredRecordError as exc:
        raise CapabilityError(str(exc)) from exc
    return {"structured_record_id": record.id}


def _validate_domain_summary_update(arguments: dict) -> None:
    if not arguments.get("content"):
        raise CapabilityError("content is required")


def _describe_domain_summary_update(arguments: dict) -> str:
    return "Update the domain summary."


def _execute_domain_summary_update(session: Session, domain_id: str | None, arguments: dict, **_kwargs: Any) -> dict:
    if domain_id is None:
        raise CapabilityError("domain_summary.update requires a domain_id")
    summary = domain_summary_service.set_domain_summary(
        session, domain_id, arguments["content"], source="action_proposal"
    )
    return {"domain_summary_id": summary.id}


CAPABILITY_REGISTRY: dict[str, CapabilitySpec] = {
    "memory.create": CapabilitySpec(
        capability_id="memory.create",
        permission_level="confirm",
        domain_required=False,
        validate=_validate_memory_create,
        describe_effect=_describe_memory_create,
        execute=_execute_memory_create,
    ),
    "structured_record.create": CapabilitySpec(
        capability_id="structured_record.create",
        permission_level="confirm",
        domain_required=True,
        validate=_validate_structured_record_create,
        describe_effect=_describe_structured_record_create,
        execute=_execute_structured_record_create,
    ),
    "domain_summary.update": CapabilitySpec(
        capability_id="domain_summary.update",
        permission_level="confirm",
        domain_required=True,
        validate=_validate_domain_summary_update,
        describe_effect=_describe_domain_summary_update,
        execute=_execute_domain_summary_update,
    ),
    "google_calendar.event.create": CapabilitySpec(
        capability_id="google_calendar.event.create",
        permission_level="confirm",
        domain_required=True,
        validate=calendar_capability.validate_event_create,
        describe_effect=calendar_capability.describe_event_create,
        execute=calendar_capability.execute_event_create,
    ),
    "google_calendar.event.update": CapabilitySpec(
        capability_id="google_calendar.event.update",
        permission_level="confirm",
        domain_required=True,
        validate=calendar_capability.validate_event_update,
        describe_effect=calendar_capability.describe_event_update,
        execute=calendar_capability.execute_event_update,
    ),
    "google_calendar.event.delete": CapabilitySpec(
        capability_id="google_calendar.event.delete",
        permission_level="confirm",
        domain_required=True,
        validate=calendar_capability.validate_event_delete,
        describe_effect=calendar_capability.describe_event_delete,
        execute=calendar_capability.execute_event_delete,
    ),
}


def get_capability(capability_id: str) -> CapabilitySpec:
    spec = CAPABILITY_REGISTRY.get(capability_id)
    if spec is None:
        raise CapabilityError(f"Unknown or disallowed capability: {capability_id!r}")
    return spec


def validate_domain_for_capability(
    session: Session, spec: CapabilitySpec, domain_id: str | None, arguments: dict[str, Any]
) -> None:
    if spec.domain_required and domain_id is None:
        raise CapabilityError(f"{spec.capability_id} requires a domain_id")
    if not spec.domain_required and domain_id is not None and spec.capability_id == "memory.create":
        if arguments.get("scope") == "global":
            raise CapabilityError("A global-scope memory proposal must not have a domain_id")
    if domain_id is not None and session.get(Domain, domain_id) is None:
        raise CapabilityError(f"Unknown domain_id: {domain_id!r}")
    if spec.capability_id == "structured_record.create" and domain_id is not None:
        record_type = arguments.get("record_type")
        expected_slug = RECORD_TYPE_DOMAIN_SLUG.get(record_type)
        domain = session.get(Domain, domain_id)
        if domain is not None and expected_slug is not None and domain.slug != expected_slug:
            raise CapabilityError(
                f"record_type {record_type!r} belongs to domain {expected_slug!r}, not {domain.slug!r}"
            )
    if spec.capability_id.startswith("google_calendar.event."):
        # Never assume a requested scope was granted — check what Google
        # actually returned, at propose time. calendar_capability.py
        # re-checks this again at execute time for defense in depth.
        from app import integration_service

        if not integration_service.has_scope(session, "google_calendar", calendar_capability.WRITE_SCOPE):
            raise CapabilityError(
                "Google Calendar write access has not been granted (calendar.events.owned scope "
                "is missing from the connection's granted scopes). Enable Calendar writing and "
                "re-authorize before proposing this action."
            )

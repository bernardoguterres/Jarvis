"""CRUD and versioning for MemoryItem/MemoryVersion.

Every content change creates a new immutable MemoryVersion; MemoryItem's own
mutable columns mirror the current version for convenient querying. Nothing
here depends on which reasoning model is active (CLAUDE.md model-independent
memory requirement).
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.backup_service import BackupError, create_backup
from app.config import Settings
from app.fts_service import remove_memory_fts, upsert_memory_fts
from app.models import Domain
from app.models_memory import MEMORY_KINDS, MEMORY_SCOPES, SENSITIVITY_LEVELS, MemoryItem, MemoryVersion


class MemoryValidationError(Exception):
    pass


class MemoryNotFoundError(Exception):
    pass


class PermanentDeletionError(Exception):
    pass


def _validate_scope_domain(scope: str, domain_id: str | None) -> None:
    if scope not in MEMORY_SCOPES:
        raise MemoryValidationError(f"scope must be one of {MEMORY_SCOPES}")
    if scope == "global" and domain_id is not None:
        raise MemoryValidationError("Global memories must not have a domain_id.")
    if scope == "domain" and domain_id is None:
        raise MemoryValidationError("Domain memories must have a domain_id.")


def create_memory(
    session: Session,
    *,
    scope: str,
    domain_id: str | None,
    kind: str,
    title: str,
    content: str,
    importance: int = 3,
    confidence: float = 1.0,
    sensitivity: str = "normal",
    event_date: datetime | None = None,
    source_message_id: str | None = None,
    source_conversation_id: str | None = None,
    source_note: str | None = None,
    change_reason: str | None = None,
    source: str = "explicit_remember",
) -> MemoryItem:
    _validate_scope_domain(scope, domain_id)
    if kind not in MEMORY_KINDS:
        raise MemoryValidationError(f"kind must be one of {MEMORY_KINDS}")
    if sensitivity not in SENSITIVITY_LEVELS:
        raise MemoryValidationError(f"sensitivity must be one of {SENSITIVITY_LEVELS}")
    if domain_id is not None and session.get(Domain, domain_id) is None:
        raise MemoryValidationError(f"Unknown domain_id: {domain_id!r}")
    if not (1 <= importance <= 5):
        raise MemoryValidationError("importance must be between 1 and 5")
    if not (0.0 <= confidence <= 1.0):
        raise MemoryValidationError("confidence must be between 0.0 and 1.0")

    item = MemoryItem(
        scope=scope,
        domain_id=domain_id,
        kind=kind,
        title=title,
        status="active",
        importance=importance,
        confidence=confidence,
        sensitivity=sensitivity,
        event_date=event_date,
        source_message_id=source_message_id,
        source_conversation_id=source_conversation_id,
        source_note=source_note,
    )
    session.add(item)
    session.flush()

    version = MemoryVersion(
        memory_item_id=item.id,
        version_number=1,
        title=title,
        kind=kind,
        content=content,
        importance=importance,
        confidence=confidence,
        sensitivity=sensitivity,
        event_date=event_date,
        change_reason=change_reason,
        source=source,
    )
    session.add(version)
    session.flush()

    item.current_version_id = version.id
    session.flush()

    upsert_memory_fts(session, item, title, content)
    session.commit()
    session.refresh(item)
    return item


def get_memory_or_404(session: Session, memory_item_id: str) -> MemoryItem:
    item = session.get(MemoryItem, memory_item_id)
    if item is None:
        raise MemoryNotFoundError(memory_item_id)
    return item


def edit_memory(
    session: Session,
    memory_item_id: str,
    *,
    title: str | None = None,
    content: str,
    kind: str | None = None,
    importance: int | None = None,
    confidence: float | None = None,
    sensitivity: str | None = None,
    event_date: datetime | None = None,
    change_reason: str | None = None,
    source: str = "edit",
) -> MemoryItem:
    """Creates a new immutable version. The previous version is never
    modified or removed."""
    item = get_memory_or_404(session, memory_item_id)

    new_title = title if title is not None else item.title
    new_kind = kind if kind is not None else item.kind
    new_importance = importance if importance is not None else item.importance
    new_confidence = confidence if confidence is not None else item.confidence
    new_sensitivity = sensitivity if sensitivity is not None else item.sensitivity

    if new_kind not in MEMORY_KINDS:
        raise MemoryValidationError(f"kind must be one of {MEMORY_KINDS}")
    if new_sensitivity not in SENSITIVITY_LEVELS:
        raise MemoryValidationError(f"sensitivity must be one of {SENSITIVITY_LEVELS}")
    if not (1 <= new_importance <= 5):
        raise MemoryValidationError("importance must be between 1 and 5")
    if not (0.0 <= new_confidence <= 1.0):
        raise MemoryValidationError("confidence must be between 0.0 and 1.0")

    latest_version_number = session.execute(
        select(MemoryVersion.version_number)
        .where(MemoryVersion.memory_item_id == item.id)
        .order_by(MemoryVersion.version_number.desc())
        .limit(1)
    ).scalar_one()

    version = MemoryVersion(
        memory_item_id=item.id,
        version_number=latest_version_number + 1,
        title=new_title,
        kind=new_kind,
        content=content,
        importance=new_importance,
        confidence=new_confidence,
        sensitivity=new_sensitivity,
        event_date=event_date if event_date is not None else item.event_date,
        change_reason=change_reason,
        source=source,
    )
    session.add(version)
    session.flush()

    item.title = new_title
    item.kind = new_kind
    item.importance = new_importance
    item.confidence = new_confidence
    item.sensitivity = new_sensitivity
    item.current_version_id = version.id
    session.flush()

    upsert_memory_fts(session, item, new_title, content)
    session.commit()
    session.refresh(item)
    return item


def supersede_memory(
    session: Session,
    old_memory_item_id: str,
    *,
    title: str,
    content: str,
    kind: str | None = None,
    importance: int | None = None,
    confidence: float | None = None,
    sensitivity: str | None = None,
    event_date: datetime | None = None,
    change_reason: str | None = None,
) -> MemoryItem:
    """Creates a brand-new MemoryItem that replaces `old_memory_item_id`.
    The old item is archived (its full version history is retained) and
    linked via supersedes_id/superseded_by_id."""
    old_item = get_memory_or_404(session, old_memory_item_id)

    new_item = create_memory(
        session,
        scope=old_item.scope,
        domain_id=old_item.domain_id,
        kind=kind or old_item.kind,
        title=title,
        content=content,
        importance=importance if importance is not None else old_item.importance,
        confidence=confidence if confidence is not None else old_item.confidence,
        sensitivity=sensitivity if sensitivity is not None else old_item.sensitivity,
        event_date=event_date,
        change_reason=change_reason,
        source="supersede",
    )

    new_item.supersedes_id = old_item.id
    old_item.superseded_by_id = new_item.id
    old_item.status = "archived"
    session.flush()

    remove_memory_fts(session, old_item.id)
    session.commit()
    session.refresh(new_item)
    return new_item


def archive_memory(session: Session, memory_item_id: str) -> MemoryItem:
    item = get_memory_or_404(session, memory_item_id)
    item.status = "archived"
    session.flush()
    remove_memory_fts(session, item.id)
    session.commit()
    session.refresh(item)
    return item


def unarchive_memory(session: Session, memory_item_id: str) -> MemoryItem:
    item = get_memory_or_404(session, memory_item_id)
    item.status = "active"
    session.flush()
    if item.current_version is not None:
        upsert_memory_fts(session, item, item.current_version.title, item.current_version.content)
    session.commit()
    session.refresh(item)
    return item


def permanently_delete_memory(
    session: Session,
    settings: Settings,
    memory_item_id: str,
    *,
    typed_confirmation: str,
) -> None:
    """Irreversibly removes a memory and all its versions. Requires the
    caller to have typed the memory's exact current title as confirmation,
    and creates a verified rollback backup first."""
    item = get_memory_or_404(session, memory_item_id)

    if typed_confirmation != item.title:
        raise PermanentDeletionError(
            "Typed confirmation does not match this memory's exact current title."
        )

    try:
        create_backup(settings, category="pre_delete")
    except BackupError as exc:
        raise PermanentDeletionError(f"Refusing to delete: rollback backup failed: {exc}") from exc

    remove_memory_fts(session, item.id)

    # Detach any items that pointed at this one so deletion doesn't cascade
    # into unrelated memories.
    for other in session.execute(
        select(MemoryItem).where(MemoryItem.supersedes_id == item.id)
    ).scalars():
        other.supersedes_id = None
    for other in session.execute(
        select(MemoryItem).where(MemoryItem.superseded_by_id == item.id)
    ).scalars():
        other.superseded_by_id = None
    session.flush()

    session.delete(item)
    session.commit()


def list_memories(
    session: Session,
    *,
    scope: str | None = None,
    domain_id: str | None = None,
    status: str | None = "active",
    kind: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> list[MemoryItem]:
    limit = max(1, min(limit, 200))
    stmt = select(MemoryItem)
    if scope is not None:
        stmt = stmt.where(MemoryItem.scope == scope)
    if domain_id is not None:
        stmt = stmt.where(MemoryItem.domain_id == domain_id)
    if status is not None:
        stmt = stmt.where(MemoryItem.status == status)
    if kind is not None:
        stmt = stmt.where(MemoryItem.kind == kind)
    stmt = stmt.order_by(MemoryItem.updated_at.desc()).limit(limit).offset(offset)
    return list(session.execute(stmt).scalars().all())

from __future__ import annotations

import pytest
from sqlalchemy.orm import Session

from app import memory_service
from app.config import Settings
from app.memory_service import MemoryNotFoundError, MemoryValidationError, PermanentDeletionError
from app.models import Domain
from app.models_memory import MemoryItem, MemoryVersion


def _body_id(session: Session) -> str:
    return session.query(Domain).filter_by(slug="body").one().id


def test_create_global_memory(db_session: Session) -> None:
    item = memory_service.create_memory(
        db_session,
        scope="global",
        domain_id=None,
        kind="preference",
        title="Preferred name",
        content="Call him Bernardo.",
    )
    assert item.scope == "global"
    assert item.domain_id is None
    assert item.current_version_id is not None
    assert item.current_version.version_number == 1


def test_create_domain_memory(db_session: Session) -> None:
    body_id = _body_id(db_session)
    item = memory_service.create_memory(
        db_session, scope="domain", domain_id=body_id, kind="health_context", title="Knee", content="Knee pain."
    )
    assert item.domain_id == body_id


def test_global_memory_must_not_have_domain(db_session: Session) -> None:
    body_id = _body_id(db_session)
    with pytest.raises(MemoryValidationError):
        memory_service.create_memory(
            db_session, scope="global", domain_id=body_id, kind="fact", title="x", content="y"
        )


def test_domain_memory_must_have_domain(db_session: Session) -> None:
    with pytest.raises(MemoryValidationError):
        memory_service.create_memory(
            db_session, scope="domain", domain_id=None, kind="fact", title="x", content="y"
        )


def test_invalid_kind_rejected(db_session: Session) -> None:
    with pytest.raises(MemoryValidationError):
        memory_service.create_memory(
            db_session, scope="global", domain_id=None, kind="not-a-real-kind", title="x", content="y"
        )


def test_invalid_domain_id_rejected(db_session: Session) -> None:
    with pytest.raises(MemoryValidationError):
        memory_service.create_memory(
            db_session,
            scope="domain",
            domain_id="00000000-0000-4000-8000-000000000000",
            kind="fact",
            title="x",
            content="y",
        )


def test_importance_and_confidence_range_validated(db_session: Session) -> None:
    with pytest.raises(MemoryValidationError):
        memory_service.create_memory(
            db_session, scope="global", domain_id=None, kind="fact", title="x", content="y", importance=6
        )
    with pytest.raises(MemoryValidationError):
        memory_service.create_memory(
            db_session, scope="global", domain_id=None, kind="fact", title="x", content="y", confidence=1.5
        )


def test_edit_creates_new_immutable_version(db_session: Session) -> None:
    item = memory_service.create_memory(
        db_session, scope="global", domain_id=None, kind="fact", title="T", content="v1"
    )
    v1_id = item.current_version_id

    edited = memory_service.edit_memory(db_session, item.id, content="v2", change_reason="update")

    assert edited.current_version_id != v1_id
    assert edited.current_version.version_number == 2
    assert edited.current_version.content == "v2"

    # Version 1 still exists and is unchanged.
    v1 = db_session.get(MemoryVersion, v1_id)
    assert v1 is not None
    assert v1.content == "v1"

    versions = db_session.query(MemoryVersion).filter_by(memory_item_id=item.id).all()
    assert len(versions) == 2


def test_edit_nonexistent_memory_raises(db_session: Session) -> None:
    with pytest.raises(MemoryNotFoundError):
        memory_service.edit_memory(db_session, "00000000-0000-4000-8000-000000000000", content="x")


def test_duplicate_version_numbers_prevented_by_unique_constraint(db_session: Session) -> None:
    item = memory_service.create_memory(
        db_session, scope="global", domain_id=None, kind="fact", title="T", content="v1"
    )
    # Attempting to insert a second version 1 directly must violate the
    # unique constraint (defends against a concurrent/duplicate update race).
    dup = MemoryVersion(
        memory_item_id=item.id,
        version_number=1,
        title="T",
        kind="fact",
        content="dup",
        importance=3,
        confidence=1.0,
        sensitivity="normal",
    )
    db_session.add(dup)
    with pytest.raises(Exception):
        db_session.commit()
    db_session.rollback()


def test_supersede_creates_new_item_and_archives_old(db_session: Session) -> None:
    old = memory_service.create_memory(
        db_session, scope="global", domain_id=None, kind="fact", title="Old", content="outdated fact"
    )
    new = memory_service.supersede_memory(
        db_session, old.id, title="New", content="corrected fact"
    )

    assert new.supersedes_id == old.id
    old_refreshed = db_session.get(MemoryItem, old.id)
    assert old_refreshed.superseded_by_id == new.id
    assert old_refreshed.status == "archived"
    assert new.status == "active"


def test_archive_excludes_from_active_listing(db_session: Session) -> None:
    item = memory_service.create_memory(
        db_session, scope="global", domain_id=None, kind="fact", title="T", content="c"
    )
    memory_service.archive_memory(db_session, item.id)

    active = memory_service.list_memories(db_session, status="active")
    assert item.id not in [m.id for m in active]

    archived = memory_service.list_memories(db_session, status="archived")
    assert item.id in [m.id for m in archived]


def test_permanent_deletion_requires_exact_typed_title(
    db_session: Session, memory_settings: Settings
) -> None:
    item = memory_service.create_memory(
        db_session, scope="global", domain_id=None, kind="fact", title="Delete me", content="c"
    )
    with pytest.raises(PermanentDeletionError):
        memory_service.permanently_delete_memory(
            db_session, memory_settings, item.id, typed_confirmation="wrong"
        )
    # Still exists.
    assert db_session.get(MemoryItem, item.id) is not None


def test_permanent_deletion_creates_rollback_backup_and_removes_memory(
    db_session: Session, memory_settings: Settings
) -> None:
    item = memory_service.create_memory(
        db_session, scope="global", domain_id=None, kind="fact", title="Delete me", content="c"
    )
    item_id = item.id

    backups_before = list((memory_settings.backups_dir / "pre_delete").glob("*.sqlite")) if (
        memory_settings.backups_dir / "pre_delete"
    ).exists() else []

    memory_service.permanently_delete_memory(
        db_session, memory_settings, item_id, typed_confirmation="Delete me"
    )

    backups_after = list((memory_settings.backups_dir / "pre_delete").glob("*.sqlite"))
    assert len(backups_after) == len(backups_before) + 1

    assert db_session.get(MemoryItem, item_id) is None
    assert db_session.query(MemoryVersion).filter_by(memory_item_id=item_id).count() == 0


def test_permanent_deletion_never_operates_on_wrong_target(db_session: Session) -> None:
    with pytest.raises(MemoryNotFoundError):
        memory_service.get_memory_or_404(db_session, "00000000-0000-4000-8000-000000000000")

"""Phase 8 round-trip: skills, skill versions, and completed action audit
history must survive export/restore — and a pending/approved action must
never become executable merely because it was restored (see D-series
decisions on the post-restore expiry safety measure)."""

from __future__ import annotations

from pathlib import Path

import pytest

from app import action_service, skill_service
from app.config import Settings
from app.database import build_engine, build_sessionmaker
from app.export_service import create_export
from app.import_service import restore_archive, validate_archive
from app.migration_info import upgrade_database_to_head
from app.models_actions import ActionProposal, Skill
from app.seed import seed_domains


def _make_installation(root: Path) -> Settings:
    settings = Settings(jarvis_data_dir=str(root))
    settings.ensure_directories()
    upgrade_database_to_head(settings.database_url)
    return settings


def test_phase8_data_survives_export_and_restore(tmp_path: Path) -> None:
    install_a = _make_installation(tmp_path / "installation-a")
    engine_a = build_engine(install_a.database_url)
    session_factory_a = build_sessionmaker(engine_a)

    with session_factory_a() as session:
        seed_domains(session)

        skill = skill_service.create_skill(
            session,
            slug="round-trip-skill",
            name="Round trip skill",
            description="d",
            domain_id=None,
            workflow_steps=[{"capability_id": "memory.create", "description": "log"}],
        )
        skill_service.activate_skill(session, skill.id)
        skill_service.edit_skill(
            session, skill.id, workflow_steps=[{"capability_id": "memory.create", "description": "log v2"}]
        )
        skill_id = skill.id

        # A completed action, whose full audit history must survive.
        completed = action_service.propose_action(
            session,
            capability_id="memory.create",
            domain_id=None,
            arguments={"scope": "global", "kind": "fact", "title": "Completed", "content": "c"},
            reason="will complete",
        )
        approved = action_service.approve_action(session, completed.id, payload_digest=completed.payload_digest)
        action_service.execute_action(session, completed.id, confirmation_token=approved.confirmation_token)
        completed_id = completed.id

        # A still-pending (never executed) proposal — must not become
        # executable just because it was restored.
        pending = action_service.propose_action(
            session,
            capability_id="memory.create",
            domain_id=None,
            arguments={"scope": "global", "kind": "fact", "title": "Pending", "content": "c"},
            reason="never gets executed before export",
        )
        pending_id = pending.id

        # An approved-but-not-executed proposal — same requirement.
        approved_only = action_service.propose_action(
            session,
            capability_id="memory.create",
            domain_id=None,
            arguments={"scope": "global", "kind": "fact", "title": "ApprovedOnly", "content": "c"},
            reason="approved but never executed before export",
        )
        approved_only_result = action_service.approve_action(
            session, approved_only.id, payload_digest=approved_only.payload_digest
        )
        approved_only_id = approved_only.id
        leaked_token = approved_only_result.confirmation_token
    engine_a.dispose()

    export_result = create_export(install_a)
    validation = validate_archive(export_result.path)
    assert validation.ok, validation.errors

    install_b = tmp_path / "installation-b"
    report = restore_archive(export_result.path, Settings(jarvis_data_dir=str(install_b)))
    assert report is not None

    settings_b = Settings(jarvis_data_dir=str(install_b))
    engine_b = build_engine(settings_b.database_url)
    with build_sessionmaker(engine_b)() as session:
        skill_after = session.get(Skill, skill_id)
        assert skill_after is not None
        # Editing after activation demotes to draft by design (skill_service
        # requires re-review after any modification) — this is unrelated to
        # restore itself, just the setup above editing post-activation.
        assert skill_after.status == "draft"
        assert len(skill_after.versions) == 2
        assert "log v2" in skill_after.current_version.workflow_steps_json

        completed_after = session.get(ActionProposal, completed_id)
        assert completed_after.status == "succeeded"
        assert [e.event_type for e in completed_after.audit_events] == [
            "proposed",
            "approved",
            "executing",
            "succeeded",
        ]

        # The safety measure: neither the pending nor the approved-only
        # proposal is executable after restore — both are expired.
        pending_after = session.get(ActionProposal, pending_id)
        assert pending_after.status == "expired"

        approved_only_after = session.get(ActionProposal, approved_only_id)
        assert approved_only_after.status == "expired"

        # Even with the (leaked, pre-restore) token, execute must fail.
        with pytest.raises(action_service.ActionError):
            action_service.execute_action(session, approved_only_id, confirmation_token=leaked_token)

        # The restored installation remains writable.
        new_proposal = action_service.propose_action(
            session,
            capability_id="memory.create",
            domain_id=None,
            arguments={"scope": "global", "kind": "fact", "title": "Post-restore", "content": "c"},
            reason="writability check",
        )
        assert new_proposal.id
    engine_b.dispose()

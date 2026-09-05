"""Skill schema validation, immutable versioning, draft/active/archive
lifecycle, invocation-through-the-action-system, and domain isolation."""

from __future__ import annotations

import pytest
from sqlalchemy.orm import Session

from app import skill_service
from app.models import Domain


def test_create_draft_skill(db_session: Session) -> None:
    body = db_session.query(Domain).filter_by(slug="body").one()
    skill = skill_service.create_skill(
        db_session,
        slug="test-body-checkin",
        name="Test BODY check-in",
        description="A test skill.",
        domain_id=body.id,
        invocation_phrases=["test checkin"],
        workflow_steps=[
            {"capability_id": "structured_record.create", "description": "Log a weight entry"}
        ],
    )
    assert skill.status == "draft"
    assert skill.current_version_id is not None


def test_create_rejects_unknown_capability(db_session: Session) -> None:
    with pytest.raises(skill_service.SkillError):
        skill_service.create_skill(
            db_session,
            slug="test-bad-skill",
            name="Bad",
            description="d",
            domain_id=None,
            workflow_steps=[{"capability_id": "filesystem.delete", "description": "nope"}],
        )


def test_create_rejects_duplicate_slug(db_session: Session) -> None:
    workflow = [{"capability_id": "memory.create", "description": "log something"}]
    skill_service.create_skill(
        db_session, slug="dup-slug", name="A", description="d", domain_id=None, workflow_steps=workflow
    )
    with pytest.raises(skill_service.SkillError):
        skill_service.create_skill(
            db_session, slug="dup-slug", name="B", description="d", domain_id=None, workflow_steps=workflow
        )


def test_cannot_invoke_a_draft_skill(db_session: Session) -> None:
    skill = skill_service.create_skill(
        db_session,
        slug="draft-only",
        name="Draft only",
        description="d",
        domain_id=None,
        workflow_steps=[{"capability_id": "memory.create", "description": "log"}],
    )
    with pytest.raises(skill_service.SkillError):
        skill_service.invoke_skill(
            db_session,
            skill.id,
            step_arguments=[{"scope": "global", "kind": "fact", "title": "x", "content": "y"}],
        )


def test_activate_then_invoke_creates_proposals(db_session: Session) -> None:
    body = db_session.query(Domain).filter_by(slug="body").one()
    skill = skill_service.create_skill(
        db_session,
        slug="activate-invoke",
        name="Activate then invoke",
        description="d",
        domain_id=body.id,
        workflow_steps=[
            {"capability_id": "structured_record.create", "description": "Log a weight entry"}
        ],
    )
    skill_service.activate_skill(db_session, skill.id)
    fresh = skill_service.get_skill_or_404(db_session, skill.id)
    assert fresh.status == "active"

    proposals = skill_service.invoke_skill(
        db_session,
        skill.id,
        step_arguments=[{"record_type": "body_weight", "payload": {"kilograms": 70}}],
    )
    assert len(proposals) == 1
    assert proposals[0].domain_id == body.id
    assert proposals[0].status == "proposed"
    assert proposals[0].source == f"skill:{skill.id}:v1"


def test_domain_scoped_skill_forces_its_own_domain_ignoring_invocation_input(db_session: Session) -> None:
    """A domain-scoped skill's proposals are always pinned to the skill's
    own domain — there is no per-invocation override, so a domain-scoped
    skill structurally cannot retrieve/write an unrelated domain."""
    body = db_session.query(Domain).filter_by(slug="body").one()
    skill = skill_service.create_skill(
        db_session,
        slug="body-forced-domain",
        name="Body forced domain",
        description="d",
        domain_id=body.id,
        workflow_steps=[{"capability_id": "domain_summary.update", "description": "update summary"}],
    )
    skill_service.activate_skill(db_session, skill.id)
    proposals = skill_service.invoke_skill(
        db_session, skill.id, step_arguments=[{"content": "new summary"}]
    )
    assert proposals[0].domain_id == body.id


def test_edit_creates_new_immutable_version_and_demotes_to_draft(db_session: Session) -> None:
    body = db_session.query(Domain).filter_by(slug="body").one()
    skill = skill_service.create_skill(
        db_session,
        slug="edit-demote",
        name="Edit demote",
        description="d",
        domain_id=body.id,
        workflow_steps=[{"capability_id": "structured_record.create", "description": "step 1"}],
    )
    skill_service.activate_skill(db_session, skill.id)
    assert skill_service.get_skill_or_404(db_session, skill.id).status == "active"

    edited = skill_service.edit_skill(
        db_session,
        skill.id,
        workflow_steps=[{"capability_id": "structured_record.create", "description": "step 1 revised"}],
        change_reason="revise",
    )
    assert edited.status == "draft"  # modification always requires re-review

    history = skill_service.get_skill_or_404(db_session, skill.id).versions
    assert len(history) == 2
    assert history[0].workflow_steps_json != history[1].workflow_steps_json
    # The first version is untouched — immutable history.
    assert "step 1" in history[0].workflow_steps_json and "revised" not in history[0].workflow_steps_json


def test_archive_then_cannot_invoke(db_session: Session) -> None:
    skill = skill_service.create_skill(
        db_session,
        slug="archive-me",
        name="Archive me",
        description="d",
        domain_id=None,
        workflow_steps=[{"capability_id": "memory.create", "description": "log"}],
    )
    skill_service.activate_skill(db_session, skill.id)
    skill_service.archive_skill(db_session, skill.id)
    fresh = skill_service.get_skill_or_404(db_session, skill.id)
    assert fresh.status == "archived"
    with pytest.raises(skill_service.SkillError):
        skill_service.invoke_skill(
            db_session, skill.id, step_arguments=[{"scope": "global", "kind": "fact", "title": "a", "content": "b"}]
        )


def test_invoke_step_count_mismatch_rejected(db_session: Session) -> None:
    skill = skill_service.create_skill(
        db_session,
        slug="two-steps",
        name="Two steps",
        description="d",
        domain_id=None,
        workflow_steps=[
            {"capability_id": "memory.create", "description": "step 1"},
            {"capability_id": "memory.create", "description": "step 2"},
        ],
    )
    skill_service.activate_skill(db_session, skill.id)
    with pytest.raises(skill_service.SkillError):
        skill_service.invoke_skill(
            db_session,
            skill.id,
            step_arguments=[{"scope": "global", "kind": "fact", "title": "a", "content": "b"}],  # only 1, need 2
        )

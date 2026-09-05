"""Phase 8: local, versioned, schema-validated declarative skills.

A skill is a named, reusable sequence of workflow steps, each naming one
allowlisted capability — never arbitrary executable code. Invoking a skill
only ever creates ActionProposals through the same propose/approve/execute
lifecycle as a manually-created proposal (app/action_service.py); a skill
cannot expand its own permissions because it can only reference capabilities
already in the fixed registry (app/capabilities.py).
"""

from __future__ import annotations

import json
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app import action_service
from app.capabilities import CAPABILITY_REGISTRY
from app.models import Domain
from app.models_actions import SKILL_STATUSES, ActionProposal, Skill, SkillVersion


class SkillError(Exception):
    pass


class SkillNotFoundError(Exception):
    pass


def validate_workflow_steps(steps: list[dict]) -> None:
    if not isinstance(steps, list) or not steps:
        raise SkillError("workflow_steps must be a non-empty list")
    for step in steps:
        if not isinstance(step, dict):
            raise SkillError("Each workflow step must be an object")
        capability_id = step.get("capability_id")
        if capability_id not in CAPABILITY_REGISTRY:
            raise SkillError(f"Unknown or disallowed capability in workflow step: {capability_id!r}")
        if not step.get("description"):
            raise SkillError("Each workflow step requires a description")


def create_skill(
    session: Session,
    *,
    slug: str,
    name: str,
    description: str,
    domain_id: str | None,
    invocation_phrases: list[str] | None = None,
    workflow_steps: list[dict],
    created_by: str = "user",
    change_reason: str | None = None,
) -> Skill:
    if domain_id is not None and session.get(Domain, domain_id) is None:
        raise SkillError(f"Unknown domain_id: {domain_id!r}")
    validate_workflow_steps(workflow_steps)

    existing = session.execute(select(Skill).where(Skill.slug == slug)).scalar_one_or_none()
    if existing is not None:
        raise SkillError(f"A skill with slug {slug!r} already exists.")

    skill = Skill(
        slug=slug,
        name=name,
        description=description,
        domain_id=domain_id,
        invocation_phrases_json=json.dumps(invocation_phrases or []),
        status="draft",
        created_by=created_by,
    )
    session.add(skill)
    session.flush()

    version = SkillVersion(
        skill_id=skill.id,
        version_number=1,
        name=name,
        description=description,
        workflow_steps_json=json.dumps(workflow_steps),
        change_reason=change_reason,
    )
    session.add(version)
    session.flush()

    skill.current_version_id = version.id
    session.commit()
    session.refresh(skill)
    return skill


def get_skill_or_404(session: Session, skill_id: str) -> Skill:
    skill = session.get(Skill, skill_id)
    if skill is None:
        raise SkillNotFoundError(skill_id)
    return skill


def list_skills(
    session: Session, *, status: str | None = None, domain_id: str | None = None
) -> list[Skill]:
    stmt = select(Skill)
    if status is not None:
        stmt = stmt.where(Skill.status == status)
    if domain_id is not None:
        stmt = stmt.where(Skill.domain_id == domain_id)
    stmt = stmt.order_by(Skill.updated_at.desc())
    return list(session.execute(stmt).scalars().all())


def edit_skill(
    session: Session,
    skill_id: str,
    *,
    name: str | None = None,
    description: str | None = None,
    workflow_steps: list[dict],
    change_reason: str | None = None,
) -> Skill:
    """Creates a new immutable version. Modifying a skill — active or not —
    always demotes it back to 'draft', requiring explicit re-activation
    review (CLAUDE.md §14: activation/modification require explicit review;
    Jarvis cannot silently update an active skill)."""
    skill = get_skill_or_404(session, skill_id)
    validate_workflow_steps(workflow_steps)

    new_name = name if name is not None else skill.name
    new_description = description if description is not None else skill.description

    latest_version_number = session.execute(
        select(SkillVersion.version_number)
        .where(SkillVersion.skill_id == skill.id)
        .order_by(SkillVersion.version_number.desc())
        .limit(1)
    ).scalar_one()

    version = SkillVersion(
        skill_id=skill.id,
        version_number=latest_version_number + 1,
        name=new_name,
        description=new_description,
        workflow_steps_json=json.dumps(workflow_steps),
        change_reason=change_reason,
    )
    session.add(version)
    session.flush()

    skill.name = new_name
    skill.description = new_description
    skill.current_version_id = version.id
    skill.status = "draft"
    session.commit()
    session.refresh(skill)
    return skill


def activate_skill(session: Session, skill_id: str) -> Skill:
    skill = get_skill_or_404(session, skill_id)
    if skill.status == "active":
        return skill
    if skill.current_version is None:
        raise SkillError("Skill has no version to activate.")

    # Validate before activation — required even for a skill restored from
    # an export/import, in case it references a capability that no longer
    # exists in this codebase's registry.
    steps = json.loads(skill.current_version.workflow_steps_json)
    validate_workflow_steps(steps)

    skill.status = "active"
    session.commit()
    session.refresh(skill)
    return skill


def archive_skill(session: Session, skill_id: str) -> Skill:
    skill = get_skill_or_404(session, skill_id)
    skill.status = "archived"
    session.commit()
    session.refresh(skill)
    return skill


def invoke_skill(
    session: Session,
    skill_id: str,
    *,
    step_arguments: list[dict],
    reason: str | None = None,
) -> list[ActionProposal]:
    """Only ever creates ActionProposals — the same propose/approve/execute
    lifecycle any other proposal goes through. Never mutates anything
    directly, and never expands a step's capability beyond what the
    skill's own (already-validated) definition names."""
    skill = get_skill_or_404(session, skill_id)
    if skill.status != "active":
        raise SkillError(f"Skill is not active (status={skill.status!r}); only active skills may be invoked.")
    if skill.current_version is None:
        raise SkillError("Skill has no current version.")

    steps = json.loads(skill.current_version.workflow_steps_json)
    if len(step_arguments) != len(steps):
        raise SkillError(f"Expected {len(steps)} step argument set(s), got {len(step_arguments)}.")

    proposals: list[ActionProposal] = []
    for step, arguments in zip(steps, step_arguments):
        step_reason = reason or step.get("description") or f"Invoked via skill {skill.slug!r}"
        proposal = action_service.propose_action(
            session,
            capability_id=step["capability_id"],
            domain_id=skill.domain_id,  # forced from the skill's own scope — never per-invocation
            arguments=arguments,
            reason=step_reason,
            source=f"skill:{skill.id}:v{skill.current_version.version_number}",
        )
        proposals.append(proposal)
    return proposals


assert set(SKILL_STATUSES) == {"draft", "active", "archived"}

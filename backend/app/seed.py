"""Idempotent seeding of the six fixed domains, and (Phase 8) a handful of
example skill templates."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import DOMAIN_SEEDS, Domain
from app.models_actions import Skill
from app.skill_service import SkillError, create_skill


def seed_domains(session: Session) -> None:
    existing_slugs = {slug for (slug,) in session.query(Domain.slug).all()}

    for seed in DOMAIN_SEEDS:
        if seed["slug"] in existing_slugs:
            continue
        session.add(
            Domain(
                id=seed["id"],
                slug=seed["slug"],
                name=seed["name"],
                description=seed["description"],
            )
        )

    session.commit()


# Fixed domain UUIDs from DOMAIN_SEEDS (app/models.py) — stable across
# reinstalls, same reasoning as seed_domains above.
_BODY_ID = "11111111-1111-4111-8111-111111111111"
_PATH_ID = "44444444-4444-4444-8444-444444444444"
_BUILD_ID = "55555555-5555-4555-8555-555555555555"
_LIFE_ID = "66666666-6666-4666-8666-666666666666"

# Clearly-labelled inactive example skill templates (CLAUDE.md §14). Seeded
# as drafts only — never activated automatically; Bernardo must explicitly
# review and activate each one before it can be invoked.
EXAMPLE_SKILL_SEEDS = [
    {
        "slug": "example-body-weekly-checkin",
        "name": "[Example] BODY weekly check-in",
        "description": "Log this week's weight and a short BODY summary note.",
        "domain_id": _BODY_ID,
        "invocation_phrases": ["weekly body check-in", "log my week"],
        "workflow_steps": [
            {
                "capability_id": "structured_record.create",
                "description": "Log this week's weight",
                "argument_hint": {"record_type": "body_weight", "payload": {"kilograms": 0}},
            },
            {
                "capability_id": "domain_summary.update",
                "description": "Update the BODY summary with this week's notes",
                "argument_hint": {"content": ""},
            },
        ],
    },
    {
        "slug": "example-build-project-checkpoint",
        "name": "[Example] BUILD project checkpoint",
        "description": "Log a project checkpoint: what shipped, what's next.",
        "domain_id": _BUILD_ID,
        "invocation_phrases": ["project checkpoint", "log a build checkpoint"],
        "workflow_steps": [
            {
                "capability_id": "structured_record.create",
                "description": "Log a BUILD checkpoint",
                "argument_hint": {"record_type": "build_checkpoint", "payload": {"project": "", "summary": ""}},
            }
        ],
    },
    {
        "slug": "example-path-deadline-review",
        "name": "[Example] PATH deadline review",
        "description": "Log an upcoming PATH deadline to review.",
        "domain_id": _PATH_ID,
        "invocation_phrases": ["review my deadlines", "log a path deadline"],
        "workflow_steps": [
            {
                "capability_id": "structured_record.create",
                "description": "Log an upcoming PATH deadline",
                "argument_hint": {"record_type": "path_deadline", "payload": {"title": "", "due_date": ""}},
            }
        ],
    },
    {
        "slug": "example-life-daily-planning",
        "name": "[Example] LIFE daily planning",
        "description": "Log a task for today's LIFE planning.",
        "domain_id": _LIFE_ID,
        "invocation_phrases": ["plan my day", "log a life task"],
        "workflow_steps": [
            {
                "capability_id": "structured_record.create",
                "description": "Log a LIFE task for today",
                "argument_hint": {"record_type": "life_task", "payload": {"title": ""}},
            }
        ],
    },
]


def seed_example_skills(session: Session) -> None:
    existing_slugs = {slug for (slug,) in session.execute(select(Skill.slug)).all()}
    for seed in EXAMPLE_SKILL_SEEDS:
        if seed["slug"] in existing_slugs:
            continue
        try:
            create_skill(
                session,
                slug=seed["slug"],
                name=seed["name"],
                description=seed["description"],
                domain_id=seed["domain_id"],
                invocation_phrases=seed["invocation_phrases"],
                workflow_steps=seed["workflow_steps"],
                created_by="jarvis",
                change_reason="Seeded example template.",
            )
        except SkillError:
            # Domain not seeded yet, or some other transient ordering issue —
            # never fatal to startup; the template just won't appear this run.
            session.rollback()

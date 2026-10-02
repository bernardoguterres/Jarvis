"""Fills a throwaway JARVIS_DATA_DIR with demo content for every panel,
for taking product screenshots. Refuses to run against ~/JarvisData.

Usage (from backend/):

    JARVIS_DEMO_DIR=~/JarvisDemoData
    JARVIS_DATA_DIR="$JARVIS_DEMO_DIR" uv run alembic upgrade head
    uv run python scripts/seed_demo_data.py --data-dir "$JARVIS_DEMO_DIR"
    JARVIS_DATA_DIR="$JARVIS_DEMO_DIR" uv run uvicorn app.main:app --port 8000

Delete the directory afterwards to clean up.
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import action_service, decision_service, mission_control_service, mission_focus_service, research_service
from app.config import Settings
from app.database import build_engine, build_sessionmaker
from app.domain_summary_service import set_domain_summary
from app.memory_service import create_memory
from app.models import Domain
from app.recall_index_service import rebuild_recall_index
from app.seed import seed_domains, seed_example_skills
from app.structured_record_service import create_structured_record

DEFAULT_REAL_DATA_DIR = Path.home() / "JarvisData"


def _domain_id(session, slug: str) -> str:
    return session.query(Domain).filter(Domain.slug == slug).one().id


def _iso_date(days_from_today: int) -> str:
    return (datetime.now(timezone.utc).date() + timedelta(days=days_from_today)).isoformat()


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def seed(session) -> None:
    print("Seeding domains and example skill templates...")
    seed_domains(session)
    seed_example_skills(session)

    body = _domain_id(session, "body")
    mind = _domain_id(session, "mind")
    people = _domain_id(session, "people")
    path = _domain_id(session, "path")
    build = _domain_id(session, "build")
    life = _domain_id(session, "life")

    print("Domain summaries...")
    set_domain_summary(session, body, "Training 4x/week, knee symptom-free for 3 weeks. Weight trending down slowly.")
    set_domain_summary(session, mind, "Mood steady this week; sleep the main lever when it dips.")
    set_domain_summary(session, people, "Weekly call with family on Sundays; nothing urgent open.")
    set_domain_summary(session, path, "Two applications in flight, one interview scheduled next week.")
    set_domain_summary(session, build, "Jarvis V1 shipped; now reviewing project documentation before the next release.")
    set_domain_summary(session, life, "Rent renewal due soon; a couple of admin tasks outstanding.")

    print("Memories...")
    create_memory(
        session, scope="global", domain_id=None, kind="preference", title="Prefers concise answers",
        content="Keep responses short and direct; skip preamble.",
    )
    create_memory(
        session, scope="domain", domain_id=body, kind="fact", title="Knee history",
        content="Past minor knee strain; cleared for full training as of this month.",
    )
    create_memory(
        session, scope="domain", domain_id=build, kind="goal", title="Finish the local release",
        content="Wrap up the outstanding checklist items before tagging the next local release.",
    )
    create_memory(
        session, scope="domain", domain_id=build, kind="preference", title="Keep changes small",
        content="Prefer small, reviewable diffs over large speculative rewrites.",
    )
    create_memory(
        session, scope="domain", domain_id=path, kind="goal", title="Land next role",
        content="Targeting roles that combine backend systems work with applied AI.",
    )

    print("Structured records...")
    create_structured_record(session, domain_id=body, record_type="body_weight",
                              occurred_at=_utcnow() - timedelta(days=2), payload={"kilograms": 78.4})
    create_structured_record(session, domain_id=body, record_type="body_weight",
                              occurred_at=_utcnow() - timedelta(days=9), payload={"kilograms": 79.1})
    create_structured_record(session, domain_id=body, record_type="body_symptom",
                              occurred_at=_utcnow() - timedelta(days=20),
                              payload={"body_area": "knee", "description": "Mild ache after long run", "severity": 2})
    create_structured_record(session, domain_id=mind, record_type="mind_checkin",
                              occurred_at=_utcnow() - timedelta(days=1), payload={"mood": "steady", "note": "Good focus today."})
    create_structured_record(session, domain_id=people, record_type="people_interaction",
                              occurred_at=_utcnow() - timedelta(days=3),
                              payload={"person": "Family", "note": "Sunday call, all well."})
    create_structured_record(session, domain_id=path, record_type="path_deadline",
                              occurred_at=_utcnow(), payload={"title": "Submit application — Role A", "due_date": _iso_date(-1)})
    path_deadline_upcoming = create_structured_record(
        session, domain_id=path, record_type="path_deadline",
        occurred_at=_utcnow(), payload={"title": "Interview prep — Role B", "due_date": _iso_date(2)})
    build_checkpoint = create_structured_record(
        session, domain_id=build, record_type="build_checkpoint",
        occurred_at=_utcnow() - timedelta(days=1),
        payload={"project": "Jarvis", "summary": "Shipped native macOS packaging.", "decision": "Self-signed cert, local-only."})
    build_checkpoint_2 = create_structured_record(
        session, domain_id=build, record_type="build_checkpoint",
        occurred_at=_utcnow() - timedelta(days=6),
        payload={"project": "Jarvis", "summary": "Finished the guarded-action lifecycle audit trail.", "decision": "Every transition writes an immutable event."})
    life_task_overdue = create_structured_record(
        session, domain_id=life, record_type="life_task",
        occurred_at=_utcnow(), payload={"title": "Renew rental contract", "due_date": _iso_date(-2)})
    life_task_soon = create_structured_record(
        session, domain_id=life, record_type="life_task",
        occurred_at=_utcnow(), payload={"title": "Pay utility bill", "due_date": _iso_date(1)})

    print("Conversations...")
    from app.models import Conversation, Message
    convo = Conversation(domain_id=build, title="Reviewing project documentation")
    session.add(convo)
    session.flush()
    session.add(Message(conversation_id=convo.id, role="user", content="What's left before this release is ready?"))
    session.add(Message(conversation_id=convo.id, role="assistant", content="Just the documentation review and one open checkpoint.", model_used="demo"))
    session.add(Message(conversation_id=convo.id, role="user", content="Good, remind me what the last checkpoint covered."))
    session.add(Message(conversation_id=convo.id, role="assistant", content="The guarded-action lifecycle audit trail — every transition now writes an immutable event.", model_used="demo"))
    session.commit()

    print("Guarded actions (Actions Centre)...")
    proposed = action_service.propose_action(
        session, capability_id="structured_record.create", domain_id=life,
        arguments={"record_type": "life_task", "payload": {"title": "Review monthly budget"}},
        reason="Demo: awaiting approval.",
    )
    to_approve = action_service.propose_action(
        session, capability_id="structured_record.create", domain_id=life,
        arguments={"record_type": "life_task", "payload": {"title": "Schedule dentist appointment"}},
        reason="Demo: approved and executed.",
    )
    approved = action_service.approve_action(session, to_approve.id, payload_digest=to_approve.payload_digest)
    action_service.execute_action(session, approved.id, confirmation_token=approved.confirmation_token)
    to_deny = action_service.propose_action(
        session, capability_id="structured_record.create", domain_id=life,
        arguments={"record_type": "life_task", "payload": {"title": "Buy concert tickets"}},
        reason="Demo: denied for lifecycle variety.",
    )
    action_service.deny_action(session, to_deny.id, reason="Demo: not needed right now.")

    print("Rebuilding Recall index...")
    rebuild_recall_index(session)
    session.commit()

    print("Research workspace...")
    workspace = research_service.create_workspace(session, title="Should Jarvis add a wake word?")
    research_service.add_evidence(session, workspace.id, source_type="structured_record",
                                   source_id=build_checkpoint.id, classification="contextual")
    research_service.add_evidence(session, workspace.id, source_type="structured_record",
                                   source_id=build_checkpoint_2.id, classification="contextual")
    research_service.add_evidence(session, workspace.id, source_type="message",
                                   source_id=session.query(Message).filter(Message.conversation_id == convo.id).first().id,
                                   classification="supporting")
    research_service.generate_deterministic_brief(session, workspace.id)

    print("Decision Room...")
    decision = decision_service.create_decision(
        session, title="Enable automatic weekly backups?",
        description="Comparing manual backups against turning on the weekly automatic schedule.",
        research_workspace_id=workspace.id,
    )
    opt_a = decision_service.add_option(session, decision.id, name="Manual backups only", benefits="No background process")
    opt_b = decision_service.add_option(session, decision.id, name="Enable weekly schedule", benefits="Never forget a backup")
    crit_effort = decision_service.add_criterion(session, decision.id, name="Setup effort", weight=3)
    crit_reliability = decision_service.add_criterion(session, decision.id, name="Reliability", weight=4)
    decision_service.set_assessment(session, decision.id, option_id=opt_a.id, criterion_id=crit_effort.id, score=5)
    decision_service.set_assessment(session, decision.id, option_id=opt_a.id, criterion_id=crit_reliability.id, score=2)
    decision_service.set_assessment(session, decision.id, option_id=opt_b.id, criterion_id=crit_effort.id, score=3)
    decision_service.set_assessment(session, decision.id, option_id=opt_b.id, criterion_id=crit_reliability.id, score=5)
    decision_service.add_evidence(session, decision.id, source_type="structured_record", source_id=build_checkpoint.id)
    decision_service.generate_deterministic_brief(session, decision.id)
    decision_service.decide(session, decision.id, selected_option_id=opt_b.id,
                             rationale="Reliability matters more than the small setup cost.", decision_confidence=4)

    print("Mission Focus pins...")
    mission_focus_service.create_pin(session, source_type="path_deadline", source_id=path_deadline_upcoming.id,
                                      next_action="Finish prep doc tonight")
    mission_focus_service.create_pin(session, source_type="life_task", source_id=life_task_soon.id,
                                      next_action="Pay online after work")

    print("Mission Control session...")
    mission_control_service.start_mission(
        session, title="Documentation review", domain_slug="build", source_type="manual", source_id=None,
        target_duration_minutes=45, now=_utcnow(),
    )

    print("Rebuilding Recall index once more (mission control + decision)...")
    rebuild_recall_index(session)
    session.commit()

    print("\nDone. Overdue PATH/LIFE items are in place so the Home briefing shows NOW/NEXT items too.")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", required=True, help="A separate, disposable JARVIS_DATA_DIR (schema must already exist — run alembic upgrade head against it first).")
    args = parser.parse_args()

    target = Path(args.data_dir).expanduser().resolve()
    if target == DEFAULT_REAL_DATA_DIR.expanduser().resolve():
        print(f"Refusing to seed demo data into the real data directory ({DEFAULT_REAL_DATA_DIR}).", file=sys.stderr)
        print("Pass a separate --data-dir, e.g. ~/JarvisDemoData.", file=sys.stderr)
        return 1
    if not (target / "database" / "jarvis.sqlite").exists():
        print(f"No database found at {target}/database/jarvis.sqlite.", file=sys.stderr)
        print("Run migrations against this data dir first:", file=sys.stderr)
        print(f'  JARVIS_DATA_DIR="{target}" uv run alembic upgrade head', file=sys.stderr)
        return 1

    settings = Settings(jarvis_data_dir=str(target))
    engine = build_engine(settings.database_url)
    session_factory = build_sessionmaker(engine)
    session = session_factory()
    try:
        seed(session)
    finally:
        session.close()

    print(f"\nDemo data written to: {target}")
    print("To browse it:")
    print(f'  JARVIS_DATA_DIR="{target}" uv run uvicorn app.main:app --reload --host 127.0.0.1 --port 8000')
    print("To delete it when you're done:")
    print(f"  rm -rf {target}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

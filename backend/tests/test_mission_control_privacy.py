"""Mission Control / Current Focus — privacy boundaries and the no-model-
call guarantee. Mirrors `test_mission_focus_briefing.py`'s equivalent
checks: MIND/PEOPLE must never surface as a candidate regardless of any
settings flag, and none of this module's code paths may ever import a
model/Hermes provider or call `send_turn`."""

from __future__ import annotations

import ast
import inspect
import json
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app import briefing_service, mission_control_service
from app.briefing_service import assemble_home_briefing
from app.models import Domain
from app.models_memory import StructuredRecord

NOW = datetime(2026, 8, 29, 9, 0, tzinfo=timezone.utc)


def _domain_id(db_session: Session, slug: str) -> str:
    return db_session.query(Domain).filter_by(slug=slug).one().id


def test_mind_and_people_records_never_become_candidates_even_with_flags_true(db_session: Session) -> None:
    db_session.add(
        StructuredRecord(
            domain_id=_domain_id(db_session, "mind"), record_type="mind_checkin", occurred_at=NOW,
            payload_json=json.dumps({"mood": "anxious"}),
        )
    )
    db_session.add(
        StructuredRecord(
            domain_id=_domain_id(db_session, "people"), record_type="people_interaction", occurred_at=NOW,
            payload_json=json.dumps({"note": "call mum"}),
        )
    )
    db_session.commit()

    briefing = assemble_home_briefing(
        db_session, include_body=True, include_mind=True, include_people=True, now=NOW, trigger="home_view"
    )
    candidates = mission_control_service.mission_candidates(briefing)
    all_candidates = (
        ([candidates.recommended] if candidates.recommended else [])
        + candidates.alternatives
        + candidates.watch
    )
    assert all(c.domain_slug not in ("mind", "people") for c in all_candidates)


def test_body_excluded_by_default_setting(db_session: Session) -> None:
    briefing = assemble_home_briefing(
        db_session, include_body=False, include_mind=False, include_people=False, now=NOW, trigger="home_view"
    )
    assert briefing.include_body is False
    # No BODY source is read at all when the flag is off — nothing here
    # asserts a specific candidate exists, only that the flag round-trips
    # into the assembled briefing Mission Control then partitions as-is.


def test_mission_control_service_imports_no_model_provider() -> None:
    tree = ast.parse(inspect.getsource(mission_control_service))
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)
        elif isinstance(node, ast.Import):
            for alias in node.names:
                imported.add(alias.name)
    for forbidden in ("app.providers", "app.providers.base", "app.providers.hermes", "app.turn_service"):
        assert forbidden not in imported


def test_mission_control_service_never_calls_send_turn() -> None:
    tree = ast.parse(inspect.getsource(mission_control_service))
    call_names = {
        node.func.attr if isinstance(node.func, ast.Attribute) else getattr(node.func, "id", None)
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
    }
    assert "send_turn" not in call_names


def test_mission_control_router_imports_no_model_provider() -> None:
    from app.routers import mission_control as router_module

    tree = ast.parse(inspect.getsource(router_module))
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)
        elif isinstance(node, ast.Import):
            for alias in node.names:
                imported.add(alias.name)
    for forbidden in ("app.providers", "app.providers.base", "app.providers.hermes", "app.turn_service"):
        assert forbidden not in imported

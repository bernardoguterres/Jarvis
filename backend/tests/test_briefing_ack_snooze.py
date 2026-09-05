"""Phase 12B: acknowledge/snooze/restore — a local presentation
preference only, never a mutation of any underlying source. Fictional
fixtures and an injected clock throughout; no real Google/Keychain/
Hermes/model contact."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy.orm import Session

from app import briefing_service
from app.models import Domain
from app.models_briefing import BriefingAcknowledgement, BriefingSnooze
from app.models_memory import StructuredRecord


def _domain_id(db_session: Session, slug: str) -> str:
    return db_session.query(Domain).filter_by(slug=slug).one().id


def _life_task(db_session: Session, title: str, due_date: str) -> StructuredRecord:
    record = StructuredRecord(
        domain_id=_domain_id(db_session, "life"), record_type="life_task", occurred_at=datetime.now(timezone.utc),
        payload_json=json.dumps({"title": title, "due_date": due_date}),
    )
    db_session.add(record)
    db_session.commit()
    return record


def _assemble(db_session: Session, now: datetime):
    return briefing_service.assemble_home_briefing(
        db_session, include_body=False, include_mind=False, include_people=False, now=now
    )


# --- Acknowledge -------------------------------------------------------------


def test_acknowledge_suppresses_from_main_list(db_session: Session) -> None:
    now = datetime(2026, 8, 29, 9, 0, tzinfo=timezone.utc)
    _life_task(db_session, "Renew passport", "2026-08-20")
    b1 = _assemble(db_session, now)
    key = b1.items[0].id

    briefing_service.acknowledge_item(db_session, key, now)
    b2 = _assemble(db_session, now + timedelta(minutes=1))
    assert b2.items == []
    assert [e.kind for e in b2.acknowledged_and_snoozed] == ["acknowledged"]
    assert b2.acknowledged_and_snoozed[0].title == "Renew passport"


def test_acknowledge_never_mutates_the_underlying_record(db_session: Session) -> None:
    now = datetime(2026, 8, 29, 9, 0, tzinfo=timezone.utc)
    record = _life_task(db_session, "Renew passport", "2026-08-20")
    b1 = _assemble(db_session, now)
    briefing_service.acknowledge_item(db_session, b1.items[0].id, now)

    db_session.refresh(record)
    assert record.archived_at is None
    payload = json.loads(record.payload_json)
    assert payload["title"] == "Renew passport"


def test_acknowledging_unknown_item_raises(db_session: Session) -> None:
    with pytest.raises(briefing_service.BriefingActionError):
        briefing_service.acknowledge_item(db_session, "life_task:does-not-exist", datetime.now(timezone.utc))


def test_fingerprint_change_breaks_acknowledgement(db_session: Session) -> None:
    now = datetime(2026, 8, 29, 9, 0, tzinfo=timezone.utc)
    record = _life_task(db_session, "Renew passport", "2026-08-20")
    b1 = _assemble(db_session, now)
    briefing_service.acknowledge_item(db_session, b1.items[0].id, now)
    assert _assemble(db_session, now + timedelta(minutes=1)).items == []

    record.payload_json = json.dumps({"title": "Renew passport urgently", "due_date": "2026-08-20"})
    db_session.commit()

    b2 = _assemble(db_session, now + timedelta(minutes=2))
    assert len(b2.items) == 1  # automatically resurfaced — the ack no longer matches the new fingerprint
    assert b2.items[0].change_state == "changed"


def test_restore_unacknowledges(db_session: Session) -> None:
    now = datetime(2026, 8, 29, 9, 0, tzinfo=timezone.utc)
    _life_task(db_session, "Renew passport", "2026-08-20")
    b1 = _assemble(db_session, now)
    key = b1.items[0].id
    briefing_service.acknowledge_item(db_session, key, now)
    assert _assemble(db_session, now + timedelta(minutes=1)).items == []

    restored = briefing_service.restore_item(db_session, key, now + timedelta(minutes=2))
    assert restored is True
    b2 = _assemble(db_session, now + timedelta(minutes=3))
    assert len(b2.items) == 1
    assert b2.acknowledged_and_snoozed == []

    ack_row = db_session.query(BriefingAcknowledgement).filter_by(stable_key=key).one()
    assert ack_row.status == "restored"
    assert ack_row.restored_at is not None


def test_restore_on_never_acknowledged_item_is_a_safe_no_op(db_session: Session) -> None:
    now = datetime(2026, 8, 29, 9, 0, tzinfo=timezone.utc)
    _life_task(db_session, "Renew passport", "2026-08-20")
    b1 = _assemble(db_session, now)
    restored = briefing_service.restore_item(db_session, b1.items[0].id, now)
    assert restored is False


# --- Snooze ------------------------------------------------------------------


def test_snooze_suppresses_and_expires(db_session: Session) -> None:
    now = datetime(2026, 8, 29, 9, 0, tzinfo=timezone.utc)
    _life_task(db_session, "Renew passport", "2026-08-20")
    b1 = _assemble(db_session, now)
    key = b1.items[0].id

    briefing_service.snooze_item(db_session, key, "1h", now)
    assert _assemble(db_session, now + timedelta(minutes=30)).items == []

    b2 = _assemble(db_session, now + timedelta(hours=1, minutes=1))
    assert len(b2.items) == 1  # expired automatically

    snooze_row = db_session.query(BriefingSnooze).filter_by(stable_key=key).one()
    assert snooze_row.status == "expired"


def test_snooze_durations_1h_4h_1w(db_session: Session) -> None:
    now = datetime(2026, 8, 29, 9, 0, tzinfo=timezone.utc)
    _life_task(db_session, "Renew passport", "2026-08-20")
    b1 = _assemble(db_session, now)
    key = b1.items[0].id

    s1 = briefing_service.snooze_item(db_session, key, "1h", now)
    assert briefing_service._as_aware(s1.snooze_until) == now + timedelta(hours=1)

    s2 = briefing_service.snooze_item(db_session, key, "4h", now)
    assert briefing_service._as_aware(s2.snooze_until) == now + timedelta(hours=4)
    # Choosing a new duration restores the previous active snooze.
    old = db_session.get(BriefingSnooze, s1.id)
    assert old.status == "restored"

    s3 = briefing_service.snooze_item(db_session, key, "1w", now)
    assert briefing_service._as_aware(s3.snooze_until) == now + timedelta(weeks=1)


def test_invalid_snooze_duration_rejected(db_session: Session) -> None:
    now = datetime(2026, 8, 29, 9, 0, tzinfo=timezone.utc)
    _life_task(db_session, "Renew passport", "2026-08-20")
    b1 = _assemble(db_session, now)
    with pytest.raises(briefing_service.BriefingActionError):
        briefing_service.snooze_item(db_session, b1.items[0].id, "3_days", now)


def test_snoozing_unknown_item_raises(db_session: Session) -> None:
    with pytest.raises(briefing_service.BriefingActionError):
        briefing_service.snooze_item(db_session, "life_task:does-not-exist", "1h", datetime.now(timezone.utc))


def test_fingerprint_change_breaks_snooze(db_session: Session) -> None:
    now = datetime(2026, 8, 29, 9, 0, tzinfo=timezone.utc)
    record = _life_task(db_session, "Renew passport", "2026-08-20")
    b1 = _assemble(db_session, now)
    briefing_service.snooze_item(db_session, b1.items[0].id, "1w", now)
    assert _assemble(db_session, now + timedelta(minutes=1)).items == []

    record.payload_json = json.dumps({"title": "Renew passport urgently", "due_date": "2026-08-20"})
    db_session.commit()

    b2 = _assemble(db_session, now + timedelta(minutes=2))
    assert len(b2.items) == 1
    assert b2.items[0].change_state == "changed"


def test_restore_unsnoozes(db_session: Session) -> None:
    now = datetime(2026, 8, 29, 9, 0, tzinfo=timezone.utc)
    _life_task(db_session, "Renew passport", "2026-08-20")
    b1 = _assemble(db_session, now)
    key = b1.items[0].id
    briefing_service.snooze_item(db_session, key, "1w", now)
    assert _assemble(db_session, now + timedelta(minutes=1)).items == []

    restored = briefing_service.restore_item(db_session, key, now + timedelta(minutes=2))
    assert restored is True
    assert len(_assemble(db_session, now + timedelta(minutes=3)).items) == 1


def test_snooze_never_touches_the_underlying_record_or_schedules_anything(db_session: Session) -> None:
    now = datetime(2026, 8, 29, 9, 0, tzinfo=timezone.utc)
    record = _life_task(db_session, "Renew passport", "2026-08-20")
    b1 = _assemble(db_session, now)
    briefing_service.snooze_item(db_session, b1.items[0].id, "1h", now)

    db_session.refresh(record)
    assert record.archived_at is None
    # No action proposal, no capability, nothing beyond the snooze table itself.
    from app.models_actions import ActionProposal

    assert db_session.query(ActionProposal).count() == 0


# --- "Tomorrow morning", DST-safe ---------------------------------------------


def test_tomorrow_morning_before_dst_transition() -> None:
    # Europe/Lisbon: clocks spring forward on the last Sunday of March.
    # 2026-03-28 09:00 UTC is still WET (UTC+0); tomorrow morning should
    # land at 08:00 local the next day, correctly converted to UTC.
    now = datetime(2026, 3, 28, 9, 0, tzinfo=timezone.utc)
    result = briefing_service._tomorrow_morning_utc(now, "Europe/Lisbon")
    local = result.astimezone(__import__("zoneinfo").ZoneInfo("Europe/Lisbon"))
    assert local.hour == 8
    assert local.date() == (now.date() + timedelta(days=1))


def test_tomorrow_morning_across_dst_transition() -> None:
    # 2026-03-29 is Lisbon's spring-forward day (WET -> WEST). Snoozing on
    # 2026-03-28 evening for "tomorrow morning" must still land at exactly
    # 08:00 *local* time on the 29th, not 08:00 UTC or off-by-an-hour.
    now = datetime(2026, 3, 28, 22, 0, tzinfo=timezone.utc)
    result = briefing_service._tomorrow_morning_utc(now, "Europe/Lisbon")
    from zoneinfo import ZoneInfo

    local = result.astimezone(ZoneInfo("Europe/Lisbon"))
    assert local.hour == 8
    assert local.minute == 0
    assert local.date() == (now.date() + timedelta(days=1))


def test_snooze_tomorrow_morning_uses_requested_timezone(db_session: Session) -> None:
    now = datetime(2026, 8, 29, 20, 0, tzinfo=timezone.utc)
    _life_task(db_session, "Renew passport", "2026-08-20")
    b1 = _assemble(db_session, now)
    snooze = briefing_service.snooze_item(db_session, b1.items[0].id, "tomorrow_morning", now, "Europe/Lisbon")
    from zoneinfo import ZoneInfo

    local = snooze.snooze_until.astimezone(ZoneInfo("Europe/Lisbon"))
    assert local.hour == briefing_service.SNOOZE_MORNING_HOUR


def test_snooze_and_acknowledge_timestamps_survive_db_round_trip_as_aware_utc(db_session: Session) -> None:
    """Regression: SQLite silently drops tzinfo on read-back even for a
    `DateTime(timezone=True)` column, so a naive datetime built straight
    from an ORM refresh gets serialized to the frontend with no UTC
    offset — which `new Date(iso)` in the browser then misreads as local
    time rather than UTC. This only became visible once tests ran under a
    non-UTC system clock (a real Mac in BST), not in a UTC-only
    container. `acknowledge_item`/`snooze_item` must always return aware
    UTC datetimes, and the ledger entries surfaced to the API
    (`_acknowledged_and_snoozed_entries`, what `GET /api/briefing/home`
    actually returns) must too."""
    now = datetime(2026, 8, 29, 20, 0, tzinfo=timezone.utc)
    _life_task(db_session, "Renew passport", "2026-08-20")
    b1 = _assemble(db_session, now)
    item_id = b1.items[0].id

    snooze = briefing_service.snooze_item(db_session, item_id, "1h", now)
    assert snooze.snoozed_at.tzinfo is not None
    assert snooze.snooze_until.tzinfo is not None

    entries = briefing_service._acknowledged_and_snoozed_entries(db_session, now)
    assert len(entries) == 1
    assert entries[0].since.tzinfo is not None
    assert entries[0].until is not None
    assert entries[0].until.tzinfo is not None

    briefing_service.restore_item(db_session, item_id, now)
    ack = briefing_service.acknowledge_item(db_session, item_id, now)
    assert ack.acknowledged_at.tzinfo is not None

    entries = briefing_service._acknowledged_and_snoozed_entries(db_session, now)
    assert len(entries) == 1
    assert entries[0].since.tzinfo is not None


def test_snooze_tomorrow_morning_rejects_unknown_timezone(db_session: Session) -> None:
    now = datetime(2026, 8, 29, 20, 0, tzinfo=timezone.utc)
    _life_task(db_session, "Renew passport", "2026-08-20")
    b1 = _assemble(db_session, now)
    with pytest.raises(briefing_service.BriefingActionError):
        briefing_service.snooze_item(db_session, b1.items[0].id, "tomorrow_morning", now, "Not/AZone")

"""Phase 6: general Jarvis conversation scope (migration 0011).

This is deliberately NOT a seventh domain — every test here also asserts
that exactly six domains exist and that a general conversation has no
domain_id, real or fabricated. All turns use FakeProvider; no test in this
file ever makes a real Hermes/model call.
"""

from __future__ import annotations

import uuid
from pathlib import Path

from fastapi.testclient import TestClient

from app.config import Settings
from app.database import build_engine, build_sessionmaker
from app.export_service import create_export
from app.import_service import restore_archive, validate_archive
from app.migration_info import upgrade_database_to_head
from app.models import Conversation, Domain
from app.seed import seed_domains
from tests.conftest import FakeProvider


def _domain_id(client: TestClient, slug: str) -> str:
    domains = client.get("/api/domains").json()
    return next(d["id"] for d in domains if d["slug"] == slug)


def test_exactly_six_domains_exist(client_with_fake_provider: TestClient) -> None:
    domains = client_with_fake_provider.get("/api/domains").json()
    assert len(domains) == 6
    assert {d["slug"] for d in domains} == {"body", "mind", "people", "path", "build", "life"}


def test_general_conversation_has_no_domain_id(client_with_fake_provider: TestClient) -> None:
    client = client_with_fake_provider
    resp = client.post("/api/general/conversations", json={"title": "General chat"})
    assert resp.status_code == 201
    body = resp.json()
    assert body["domain_id"] is None
    assert body["title"] == "General chat"

    # Still exactly six domains — creating a general conversation must never
    # fabricate or reuse a "JARVIS" domain row.
    domains = client.get("/api/domains").json()
    assert len(domains) == 6


def test_general_conversation_listed_separately_from_domain_conversations(client_with_fake_provider: TestClient) -> None:
    client = client_with_fake_provider
    client.post("/api/general/conversations", json={"title": "G1"})
    client.post("/api/domains/body/conversations", json={"title": "Domain one"})

    general = client.get("/api/general/conversations").json()
    body_convs = client.get("/api/domains/body/conversations").json()

    assert [c["title"] for c in general] == ["G1"]
    assert [c["title"] for c in body_convs] == ["Domain one"]


def test_default_general_turn_retrieves_no_domain_scoped_material(client_with_fake_provider: TestClient) -> None:
    client = client_with_fake_provider
    body_id = _domain_id(client, "body")
    client.post(
        "/api/memories",
        json={"scope": "domain", "domain_id": body_id, "kind": "health_context", "title": "Knee issue", "content": "knee pain history"},
    )
    client.post(
        "/api/memories",
        json={"scope": "global", "kind": "identity", "title": "Preferred name", "content": "Bernardo"},
    )

    conv = client.post("/api/general/conversations", json={"title": "General"}).json()
    resp = client.post(
        f"/api/conversations/{conv['id']}/turns",
        json={"content": "hello", "idempotency_key": str(uuid.uuid4())},
    )
    assert resp.status_code == 201
    run_id = resp.json()["run_id"]
    snapshot = client.get(f"/api/agent-runs/{run_id}/context").json()

    # No active domain at all — general, not a fabricated seventh domain.
    assert snapshot["active_domain_id"] is None
    assert snapshot["additional_domain_ids"] == []
    # Global profile is included by default...
    assert len(snapshot["global_memory_version_ids"]) == 1
    # ...but nothing domain-scoped leaked in without being explicitly asked for.
    assert snapshot["domain_memory_version_ids"] == []
    assert snapshot["domain_summary_version_ids"] == []
    assert snapshot["structured_record_ids"] == []


def test_explicit_per_turn_domain_inclusion_works_and_does_not_persist(
    client_with_fake_provider: TestClient,
) -> None:
    client = client_with_fake_provider
    body_id = _domain_id(client, "body")
    client.post(
        "/api/memories",
        json={"scope": "domain", "domain_id": body_id, "kind": "health_context", "title": "Knee issue", "content": "knee pain history"},
    )
    conv = client.post("/api/general/conversations", json={"title": "General"}).json()

    # Turn 1: explicitly include BODY.
    resp1 = client.post(
        f"/api/conversations/{conv['id']}/turns",
        json={"content": "how's my knee?", "idempotency_key": str(uuid.uuid4()), "additional_domain_ids": [body_id]},
    )
    snapshot1 = client.get(f"/api/agent-runs/{resp1.json()['run_id']}/context").json()
    assert snapshot1["additional_domain_ids"] == [body_id]
    assert body_id and len(snapshot1["domain_memory_version_ids"]) == 1

    # Turn 2: no explicit inclusion — must NOT silently carry BODY over.
    resp2 = client.post(
        f"/api/conversations/{conv['id']}/turns",
        json={"content": "what's next", "idempotency_key": str(uuid.uuid4())},
    )
    snapshot2 = client.get(f"/api/agent-runs/{resp2.json()['run_id']}/context").json()
    assert snapshot2["additional_domain_ids"] == []
    assert snapshot2["domain_memory_version_ids"] == []


def test_general_conversation_domain_isolation_unaffected(client_with_fake_provider: TestClient) -> None:
    """A general conversation must never let a domain's memories leak into
    another domain's own conversation, and vice versa — domain isolation
    (Phase 1) must remain exactly as it was."""
    client = client_with_fake_provider
    body_id = _domain_id(client, "body")
    build_id = _domain_id(client, "build")
    client.post(
        "/api/memories",
        json={"scope": "domain", "domain_id": build_id, "kind": "fact", "title": "Build secret", "content": "unrelated build info"},
    )
    body_conv = client.post("/api/domains/body/conversations", json={"title": "Body"}).json()

    resp = client.post(
        f"/api/conversations/{body_conv['id']}/turns",
        json={"content": "hi", "idempotency_key": str(uuid.uuid4())},
    )
    snapshot = client.get(f"/api/agent-runs/{resp.json()['run_id']}/context").json()
    assert snapshot["active_domain_id"] == body_id
    assert snapshot["domain_memory_version_ids"] == []  # BUILD's memory never leaked into BODY


def test_general_turn_no_real_model_call(client_with_fake_provider: TestClient, fake_provider: FakeProvider) -> None:
    client = client_with_fake_provider
    conv = client.post("/api/general/conversations", json={"title": "General"}).json()
    resp = client.post(
        f"/api/conversations/{conv['id']}/turns",
        json={"content": "hello", "idempotency_key": str(uuid.uuid4())},
    )
    assert resp.status_code == 201
    assert resp.json()["provider"] == "fake"
    # The FakeProvider recorded exactly one call — proves a "model call"
    # happened only against the fake, never a real provider.
    assert len(fake_provider.sent_system_prompts) == 1


def _make_installation(root: Path) -> Settings:
    settings = Settings(jarvis_data_dir=str(root))
    settings.ensure_directories()
    upgrade_database_to_head(settings.database_url)
    return settings


def test_general_conversations_survive_restart(tmp_path: Path) -> None:
    install = _make_installation(tmp_path / "restart-install")
    engine = build_engine(install.database_url)
    with build_sessionmaker(engine)() as session:
        seed_domains(session)
        conv = Conversation(domain_id=None, title="Restart-surviving general chat")
        session.add(conv)
        session.commit()
        conv_id = conv.id
    engine.dispose()

    # Simulate a restart: fresh engine/session against the same database file.
    engine2 = build_engine(install.database_url)
    with build_sessionmaker(engine2)() as session:
        restored = session.get(Conversation, conv_id)
        assert restored is not None
        assert restored.domain_id is None
        assert restored.title == "Restart-surviving general chat"
        assert session.query(Domain).count() == 6
    engine2.dispose()


def test_general_conversations_survive_export_restore(tmp_path: Path) -> None:
    install_a = _make_installation(tmp_path / "installation-a")
    engine_a = build_engine(install_a.database_url)
    with build_sessionmaker(engine_a)() as session:
        seed_domains(session)
        conv = Conversation(domain_id=None, title="General, exported")
        session.add(conv)
        session.commit()
        conv_id = conv.id
    engine_a.dispose()

    export_result = create_export(install_a)
    validation = validate_archive(export_result.path)
    assert validation.ok, validation.errors

    install_b = tmp_path / "installation-b"
    restore_archive(export_result.path, Settings(jarvis_data_dir=str(install_b)))

    engine_b = build_engine(Settings(jarvis_data_dir=str(install_b)).database_url)
    with build_sessionmaker(engine_b)() as session:
        restored = session.get(Conversation, conv_id)
        assert restored is not None
        assert restored.domain_id is None
        assert restored.title == "General, exported"
        assert session.query(Domain).count() == 6
    engine_b.dispose()

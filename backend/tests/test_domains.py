from __future__ import annotations

from fastapi.testclient import TestClient

from app.models import DOMAIN_SEEDS


def test_exactly_six_domains_seeded(client: TestClient) -> None:
    resp = client.get("/api/domains")
    assert resp.status_code == 200
    domains = resp.json()
    assert len(domains) == 6
    slugs = {d["slug"] for d in domains}
    assert slugs == {"body", "mind", "people", "path", "build", "life"}


def test_domain_uuids_are_stable_constants(client: TestClient) -> None:
    resp = client.get("/api/domains")
    domains = {d["slug"]: d["id"] for d in resp.json()}
    for seed in DOMAIN_SEEDS:
        assert domains[seed["slug"]] == seed["id"]


def test_domain_seeding_is_idempotent(restart_client_factory) -> None:
    client1 = restart_client_factory()
    first = {d["slug"]: d["id"] for d in client1.get("/api/domains").json()}

    # Simulate re-running startup/seeding against the same database.
    client2 = restart_client_factory()
    second = {d["slug"]: d["id"] for d in client2.get("/api/domains").json()}

    assert first == second
    assert len(second) == 6


def test_conversation_for_invalid_domain_returns_404(client: TestClient) -> None:
    resp = client.get("/api/domains/not-a-real-domain/conversations")
    assert resp.status_code == 404

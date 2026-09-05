from __future__ import annotations

from pathlib import Path

from app.config import Settings


def test_default_data_dir_is_home_jarvisdata_and_is_never_touched() -> None:
    """Verifies default resolution without ever creating the real directory."""
    settings = Settings(jarvis_data_dir=str(Path.home() / "JarvisData"))
    assert settings.data_dir == (Path.home() / "JarvisData").resolve()
    # Deliberately do not call settings.ensure_directories() here.


def test_conversation_and_message_survive_simulated_backend_restart(
    restart_client_factory,
) -> None:
    client1 = restart_client_factory()
    conv = client1.post("/api/domains/build/conversations", json={"title": "Alpha checkpoint"})
    conversation_id = conv.json()["id"]

    unique_marker = "persistence-check-c9f1a2"
    client1.post(
        f"/api/conversations/{conversation_id}/messages",
        json={"role": "user", "content": unique_marker},
    )

    # Simulate a backend restart: a brand new app instance / engine / connections,
    # same on-disk SQLite file.
    client2 = restart_client_factory()

    messages = client2.get(f"/api/conversations/{conversation_id}/messages").json()
    assert any(m["content"] == unique_marker for m in messages)

    domains = client2.get("/api/domains").json()
    assert len(domains) == 6


def test_existing_database_is_preserved_not_recreated(restart_client_factory) -> None:
    client1 = restart_client_factory()
    client1.post("/api/domains/life/conversations", json={"title": "Keep me"})

    client2 = restart_client_factory()
    conversations = client2.get("/api/domains/life/conversations").json()
    assert len(conversations) == 1
    assert conversations[0]["title"] == "Keep me"

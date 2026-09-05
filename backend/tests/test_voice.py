from __future__ import annotations

import io
import os

from fastapi.testclient import TestClient


def test_transcribe_returns_transcript(client_with_fake_voice: TestClient, fake_stt) -> None:
    fake_stt.transcript = "What do you remember about my knee?"

    response = client_with_fake_voice.post(
        "/api/voice/transcribe",
        files={"audio": ("recording.webm", io.BytesIO(b"fake-audio-bytes"), "audio/webm")},
    )

    assert response.status_code == 200
    assert response.json() == {"transcript": "What do you remember about my knee?"}


def test_transcribe_deletes_temp_audio_file_after_success(
    client_with_fake_voice: TestClient, fake_stt
) -> None:
    response = client_with_fake_voice.post(
        "/api/voice/transcribe",
        files={"audio": ("recording.webm", io.BytesIO(b"fake-audio-bytes"), "audio/webm")},
    )

    assert response.status_code == 200
    assert len(fake_stt.received_paths) == 1
    # The raw recording must not survive past this request.
    assert not fake_stt.received_paths[0].exists()


def test_transcribe_deletes_temp_audio_file_after_failure(
    client_with_fake_voice: TestClient, fake_stt
) -> None:
    fake_stt.error = RuntimeError("boom")

    response = client_with_fake_voice.post(
        "/api/voice/transcribe",
        files={"audio": ("recording.webm", io.BytesIO(b"fake-audio-bytes"), "audio/webm")},
    )

    assert response.status_code == 502
    assert len(fake_stt.received_paths) == 1
    assert not fake_stt.received_paths[0].exists()


def test_transcribe_rejects_empty_audio(client_with_fake_voice: TestClient) -> None:
    response = client_with_fake_voice.post(
        "/api/voice/transcribe",
        files={"audio": ("recording.webm", io.BytesIO(b""), "audio/webm")},
    )

    assert response.status_code == 400


def test_speak_returns_audio_bytes(client_with_fake_voice: TestClient, fake_tts) -> None:
    fake_tts.audio_bytes = b"synthesized-audio"

    response = client_with_fake_voice.post("/api/voice/speak", json={"text": "Hello there."})

    assert response.status_code == 200
    assert response.headers["content-type"] == "audio/mpeg"
    assert response.content == b"synthesized-audio"
    assert fake_tts.received_texts == ["Hello there."]


def test_speak_rejects_empty_text(client_with_fake_voice: TestClient) -> None:
    response = client_with_fake_voice.post("/api/voice/speak", json={"text": "   "})

    assert response.status_code == 400


def test_speak_surfaces_synthesis_failure(client_with_fake_voice: TestClient, fake_tts) -> None:
    fake_tts.error = RuntimeError("edge tts unavailable")

    response = client_with_fake_voice.post("/api/voice/speak", json={"text": "Hello"})

    assert response.status_code == 502

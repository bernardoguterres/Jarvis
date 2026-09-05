from __future__ import annotations

from pathlib import Path

import pytest

from app.voice.faster_whisper_stt import FasterWhisperSTT


class _FakeSegment:
    def __init__(self, text: str) -> None:
        self.text = text


class _FakeWhisperModel:
    """Records how many times the real (heavy) WhisperModel constructor
    would have been called, without actually loading any model weights —
    these tests are about construction/reuse lifecycle, not transcription
    accuracy or real timing."""

    construction_count = 0

    def __init__(self, model_size: str, device: str, compute_type: str) -> None:
        type(self).construction_count += 1
        self.model_size = model_size
        self.device = device
        self.compute_type = compute_type

    def transcribe(self, path: str):
        return [_FakeSegment("hello world")], object()


@pytest.fixture(autouse=True)
def _fake_whisper_model(monkeypatch: pytest.MonkeyPatch) -> None:
    _FakeWhisperModel.construction_count = 0
    monkeypatch.setattr("faster_whisper.WhisperModel", _FakeWhisperModel)


def test_model_is_constructed_lazily_on_first_transcribe(tmp_path: Path) -> None:
    stt = FasterWhisperSTT(model_size="base", device="cpu", compute_type="int8")
    assert _FakeWhisperModel.construction_count == 0

    stt.transcribe(tmp_path / "a.webm")

    assert _FakeWhisperModel.construction_count == 1


def test_repeated_transcribe_calls_reuse_the_same_model_instead_of_reconstructing(tmp_path: Path) -> None:
    # The lifecycle guarantee this whole module depends on: construction
    # happens once, on first use, never again — see docs/DECISIONS.md D107
    # for why an *eager* startup version of this guarantee was attempted
    # and reverted (it triggered a severe, reproducible runaway process
    # respawn in the real packaged app; this lazy, on-demand path was
    # confirmed safe in the same investigation).
    stt = FasterWhisperSTT(model_size="base", device="cpu", compute_type="int8")

    stt.transcribe(tmp_path / "a.webm")
    stt.transcribe(tmp_path / "b.webm")
    stt.transcribe(tmp_path / "c.webm")

    assert _FakeWhisperModel.construction_count == 1


def test_transcribe_joins_segment_text(tmp_path: Path) -> None:
    stt = FasterWhisperSTT(model_size="base", device="cpu", compute_type="int8")

    result = stt.transcribe(tmp_path / "a.webm")

    assert result == "hello world"

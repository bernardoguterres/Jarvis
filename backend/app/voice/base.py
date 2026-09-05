"""Model-independent speech interfaces (Phase 5).

Mirrors app/providers/base.py's approach for the reasoning model: the rest
of the app depends only on these Protocols, never on faster-whisper or
edge-tts directly, so either could be swapped later without touching the
router or tests.
"""

from __future__ import annotations

from pathlib import Path
from typing import Protocol


class SpeechToText(Protocol):
    """Transcribes a local audio file to text. Implementations must never
    retain the audio file themselves; the caller owns its lifecycle and
    deletes it immediately after this call returns (CLAUDE.md §8: raw
    recordings are not retained after successful transcription)."""

    def transcribe(self, audio_path: Path) -> str: ...


class TextToSpeech(Protocol):
    """Synthesizes spoken audio (MP3 bytes) from text."""

    async def synthesize(self, text: str) -> bytes: ...

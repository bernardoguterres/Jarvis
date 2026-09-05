"""Local speech-to-text via faster-whisper. Fully offline after the model
weights have been downloaded once (cached by huggingface-hub in the normal
HF cache directory, not JARVIS_DATA_DIR — this is model weight cache, not
personal data)."""

from __future__ import annotations

from pathlib import Path


class FasterWhisperSTT:
    def __init__(self, model_size: str, device: str, compute_type: str) -> None:
        self._model_size = model_size
        self._device = device
        self._compute_type = compute_type
        self._model = None  # lazy: only loaded on first real transcription

    def _get_model(self):
        if self._model is None:
            from faster_whisper import WhisperModel

            self._model = WhisperModel(
                self._model_size, device=self._device, compute_type=self._compute_type
            )
        return self._model

    def transcribe(self, audio_path: Path) -> str:
        model = self._get_model()
        segments, _info = model.transcribe(str(audio_path))
        return " ".join(segment.text.strip() for segment in segments).strip()

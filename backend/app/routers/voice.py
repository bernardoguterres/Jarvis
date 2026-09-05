"""Phase 5: push-to-talk transcription and spoken-response synthesis.

Raw audio uploaded for transcription is written to a temporary file outside
JARVIS_DATA_DIR and deleted immediately after transcription completes
(success or failure) — CLAUDE.md §8 requires that raw recordings are not
retained by default. Only the resulting transcript text is ever returned;
nothing about the audio itself is persisted by this router.
"""

from __future__ import annotations

import asyncio
import logging
import os
import tempfile

from fastapi import APIRouter, Depends, HTTPException, Response, UploadFile
from pydantic import BaseModel

from app.deps import get_stt, get_tts
from app.voice.base import SpeechToText, TextToSpeech

logger = logging.getLogger("jarvis")

router = APIRouter(tags=["voice"])


class TranscriptRead(BaseModel):
    transcript: str


class SpeakRequest(BaseModel):
    text: str


@router.post("/api/voice/transcribe", response_model=TranscriptRead)
async def transcribe(
    audio: UploadFile,
    stt: SpeechToText = Depends(get_stt),
) -> TranscriptRead:
    data = await audio.read()
    if not data:
        raise HTTPException(status_code=400, detail="Empty audio upload")

    suffix = os.path.splitext(audio.filename or "")[1] or ".webm"
    fd, tmp_path_str = tempfile.mkstemp(prefix="jarvis-voice-", suffix=suffix)
    try:
        with os.fdopen(fd, "wb") as tmp_file:
            tmp_file.write(data)
        from pathlib import Path

        # stt.transcribe() is synchronous, CPU-bound work (benchmarked at
        # ~0.6-1.0s warm on the target M2 Pro) — running it directly inside
        # this async handler would block the whole event loop for that
        # entire duration, stalling every other concurrent request (health
        # polling, the Phase 10 scheduler runtime's own background task)
        # for no reason. Offloading to a worker thread costs nothing in
        # wall-clock transcription time; it only stops that time from
        # blocking unrelated work.
        transcript = await asyncio.to_thread(stt.transcribe, Path(tmp_path_str))
    except Exception as exc:
        logger.exception("Transcription failed")
        raise HTTPException(status_code=502, detail="Transcription failed") from exc
    finally:
        # Raw audio must never outlive this request, success or failure.
        try:
            os.remove(tmp_path_str)
        except FileNotFoundError:
            pass

    return TranscriptRead(transcript=transcript)


@router.post("/api/voice/speak")
async def speak(
    payload: SpeakRequest,
    tts: TextToSpeech = Depends(get_tts),
) -> Response:
    if not payload.text.strip():
        raise HTTPException(status_code=400, detail="Empty text")

    try:
        audio_bytes = await tts.synthesize(payload.text)
    except Exception as exc:
        logger.exception("Speech synthesis failed")
        raise HTTPException(status_code=502, detail="Speech synthesis failed") from exc

    return Response(content=audio_bytes, media_type="audio/mpeg")

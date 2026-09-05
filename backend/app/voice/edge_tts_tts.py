"""Spoken-response synthesis via Microsoft Edge TTS (free endpoint;
sanctioned in CLAUDE.md as the initial TTS choice, ElevenLabs deferred)."""

from __future__ import annotations


class EdgeTextToSpeech:
    def __init__(self, voice: str) -> None:
        self._voice = voice

    async def synthesize(self, text: str) -> bytes:
        import edge_tts

        communicate = edge_tts.Communicate(text, self._voice)
        chunks = bytearray()
        async for chunk in communicate.stream():
            if chunk["type"] == "audio":
                chunks.extend(chunk["data"])
        return bytes(chunks)

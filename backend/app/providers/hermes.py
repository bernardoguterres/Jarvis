"""Hermes agent provider, using the local Hermes API server's
OpenAI-compatible endpoints: GET /health, GET /v1/models and
POST /v1/chat/completions. The bearer token is never logged or included
in an error.

No model is sent in the request. Hermes treats anything other than its
profile alias as a per-request override, so leaving it out lets the
profile's own configuration decide. `self._model` is only a label for
local display and audit (Message.model_used, agent_runs.model).
"""

from __future__ import annotations

import time

import httpx

from app.providers.base import (
    AgentProvider,
    ModelInfo,
    ProviderError,
    ProviderErrorCode,
    ProviderHealth,
    TurnMessage,
    TurnResult,
    Usage,
)


class HermesProvider(AgentProvider):
    name = "hermes"

    def __init__(self, base_url: str, bearer_token: str, model: str) -> None:
        self._base_url = base_url.rstrip("/")
        self._bearer_token = bearer_token
        self._model = model

    def _auth_headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self._bearer_token}"}

    def health(self, *, timeout: float) -> ProviderHealth:
        try:
            resp = httpx.get(f"{self._base_url}/health", timeout=timeout)
        except httpx.TimeoutException:
            return ProviderHealth(available=False, detail="Hermes health check timed out.")
        except httpx.HTTPError:
            return ProviderHealth(available=False, detail="Hermes is not reachable.")

        if resp.status_code != 200:
            return ProviderHealth(
                available=False, detail=f"Hermes health check returned HTTP {resp.status_code}."
            )
        return ProviderHealth(available=True, detail="ok")

    def model_info(self, *, timeout: float) -> ModelInfo:
        if not self._bearer_token:
            return ModelInfo(configured=False, model=None, provider_name=self.name)

        try:
            resp = httpx.get(
                f"{self._base_url}/v1/models", headers=self._auth_headers(), timeout=timeout
            )
        except httpx.HTTPError:
            return ModelInfo(configured=False, model=None, provider_name=self.name)

        if resp.status_code == 401 or resp.status_code == 403:
            return ModelInfo(configured=False, model=None, provider_name=self.name)
        if resp.status_code != 200:
            return ModelInfo(configured=False, model=None, provider_name=self.name)

        return ModelInfo(configured=True, model=self._model, provider_name=self.name)

    def send_turn(
        self,
        *,
        system_prompt: str,
        messages: list[TurnMessage],
        timeout: float,
    ) -> TurnResult:
        if not self._bearer_token:
            raise ProviderError(
                ProviderErrorCode.AUTH_FAILED,
                "No Hermes API bearer token is configured on the backend.",
            )

        payload_messages = [{"role": "system", "content": system_prompt}] + [
            {"role": m.role, "content": m.content} for m in messages
        ]

        started = time.monotonic()
        try:
            resp = httpx.post(
                f"{self._base_url}/v1/chat/completions",
                headers=self._auth_headers(),
                json={"messages": payload_messages},
                timeout=timeout,
            )
        except httpx.TimeoutException as exc:
            raise ProviderError(ProviderErrorCode.TIMEOUT, "Hermes did not respond in time.") from exc
        except httpx.HTTPError as exc:
            raise ProviderError(ProviderErrorCode.UNAVAILABLE, "Hermes is not reachable.") from exc

        latency_ms = int((time.monotonic() - started) * 1000)

        if resp.status_code in (401, 403):
            raise ProviderError(
                ProviderErrorCode.AUTH_FAILED, "Hermes rejected the backend's credentials."
            )
        if resp.status_code == 429:
            raise ProviderError(ProviderErrorCode.RATE_LIMITED, "Hermes is rate-limiting requests.")
        if resp.status_code != 200:
            raise ProviderError(
                ProviderErrorCode.UNAVAILABLE, f"Hermes returned HTTP {resp.status_code}."
            )

        try:
            data = resp.json()
            content = _message_text(data["choices"][0]["message"].get("content"))
            # data["model"] is Hermes's own virtual per-profile alias (e.g.
            # "jarvis"), not the underlying model, so use our configured label
            # for anything human-facing instead.
            model_name = self._model
            usage_data = data.get("usage") or {}
            usage = Usage(
                input_tokens=usage_data.get("prompt_tokens"),
                output_tokens=usage_data.get("completion_tokens"),
                total_tokens=usage_data.get("total_tokens"),
            )
            external_run_id = data.get("id")
        except (KeyError, IndexError, TypeError, ValueError, AttributeError) as exc:
            raise ProviderError(
                ProviderErrorCode.MALFORMED_RESPONSE,
                "Hermes returned a response that could not be parsed.",
            ) from exc

        if not content.strip():
            # A null or blank reply (for example a tool-call-only turn, or a
            # provider-side filter) is not an answer. Treat it as a failed
            # turn rather than saving an empty assistant message.
            raise ProviderError(ProviderErrorCode.EMPTY_RESPONSE, "Hermes returned an empty reply.")

        return TurnResult(
            content=content,
            model=model_name,
            provider_name=self.name,
            latency_ms=latency_ms,
            usage=usage,
            external_run_id=external_run_id,
        )


def _message_text(content) -> str:
    """OpenAI-compatible servers return message content as a string, null,
    or a list of typed parts. Only text parts count; anything else is
    reported as malformed by the caller."""
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for part in content:
            if not isinstance(part, dict):
                raise TypeError("unexpected content part")
            if part.get("type") == "text" and isinstance(part.get("text"), str):
                parts.append(part["text"])
        return "".join(parts)
    raise TypeError("unexpected content type")

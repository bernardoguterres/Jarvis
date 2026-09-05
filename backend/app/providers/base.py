"""Model-independent agent-provider interface.

Jarvis's memory and conversation storage never depend on which reasoning
model or agent harness is behind this interface (CLAUDE.md §10-11). Hermes
is the first implementation; a different provider could be substituted
behind this same contract without touching the database or API layer.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol


class ProviderErrorCode:
    """Sanitised, stable error codes safe to store and return to clients.

    Never a raw exception message or provider-internal detail — those could
    leak secrets (bearer tokens, internal URLs) or change wording across
    provider versions in a way that breaks stored-error comparisons.
    """

    UNAVAILABLE = "unavailable"
    TIMEOUT = "timeout"
    AUTH_FAILED = "auth_failed"
    MALFORMED_RESPONSE = "malformed_response"
    RATE_LIMITED = "rate_limited"
    UNKNOWN = "unknown"


class ProviderError(Exception):
    """Raised by a provider for any failure. Carries only sanitised info."""

    def __init__(self, code: str, summary: str) -> None:
        super().__init__(summary)
        self.code = code
        self.summary = summary


@dataclass
class ProviderHealth:
    available: bool
    detail: str = ""


@dataclass
class ModelInfo:
    configured: bool
    model: str | None
    provider_name: str


@dataclass
class TurnMessage:
    role: str
    content: str


@dataclass
class Usage:
    input_tokens: int | None = None
    output_tokens: int | None = None
    total_tokens: int | None = None


@dataclass
class TurnResult:
    content: str
    model: str
    provider_name: str
    latency_ms: int
    usage: Usage = field(default_factory=Usage)
    external_run_id: str | None = None


class AgentProvider(Protocol):
    """A conversational agent backend. Implementations must never raise an
    exception other than ProviderError from send_turn/health/model_info."""

    name: str

    def health(self, *, timeout: float) -> ProviderHealth: ...

    def model_info(self, *, timeout: float) -> ModelInfo: ...

    def send_turn(
        self,
        *,
        system_prompt: str,
        messages: list[TurnMessage],
        timeout: float,
    ) -> TurnResult: ...

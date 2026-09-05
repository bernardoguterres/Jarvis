from __future__ import annotations

from types import SimpleNamespace

import httpx
import pytest

from app.providers.base import ProviderError, ProviderErrorCode, TurnMessage
from app.providers.hermes import HermesProvider


def _fake_response(status_code: int, json_data: dict | None = None) -> SimpleNamespace:
    return SimpleNamespace(status_code=status_code, json=lambda: json_data or {})


def _provider(bearer_token: str = "test-token") -> HermesProvider:
    return HermesProvider(
        base_url="http://127.0.0.1:8642", bearer_token=bearer_token, model="openai-codex/gpt-5.6-terra"
    )


def test_health_success(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(httpx, "get", lambda url, timeout: _fake_response(200))
    health = _provider().health(timeout=5.0)
    assert health.available is True


def test_health_failure_on_non_200(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(httpx, "get", lambda url, timeout: _fake_response(503))
    health = _provider().health(timeout=5.0)
    assert health.available is False


def test_health_failure_on_connection_error(monkeypatch: pytest.MonkeyPatch) -> None:
    def _raise(url, timeout):
        raise httpx.ConnectError("refused")

    monkeypatch.setattr(httpx, "get", _raise)
    health = _provider().health(timeout=5.0)
    assert health.available is False


def test_model_info_configured(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(httpx, "get", lambda url, headers, timeout: _fake_response(200))
    info = _provider().model_info(timeout=5.0)
    assert info.configured is True
    assert info.model == "openai-codex/gpt-5.6-terra"


def test_model_info_unconfigured_without_token() -> None:
    info = _provider(bearer_token="").model_info(timeout=5.0)
    assert info.configured is False
    assert info.model is None


def test_model_info_unconfigured_on_auth_rejection(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(httpx, "get", lambda url, headers, timeout: _fake_response(401))
    info = _provider().model_info(timeout=5.0)
    assert info.configured is False


def test_send_turn_success(monkeypatch: pytest.MonkeyPatch) -> None:
    response_json = {
        "id": "chatcmpl-abc123",
        "model": "openai-codex/gpt-5.6-terra",
        "choices": [{"message": {"content": "Hello, Bernardo."}}],
        "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
    }
    monkeypatch.setattr(
        httpx, "post", lambda url, headers, json, timeout: _fake_response(200, response_json)
    )

    result = _provider().send_turn(
        system_prompt="You are Jarvis.",
        messages=[TurnMessage(role="user", content="Hi")],
        timeout=10.0,
    )

    assert result.content == "Hello, Bernardo."
    assert result.model == "openai-codex/gpt-5.6-terra"
    assert result.usage.input_tokens == 10
    assert result.usage.output_tokens == 5
    assert result.usage.total_tokens == 15
    assert result.external_run_id == "chatcmpl-abc123"


def test_send_turn_without_token_raises_auth_failed() -> None:
    with pytest.raises(ProviderError) as exc_info:
        _provider(bearer_token="").send_turn(
            system_prompt="sys", messages=[], timeout=10.0
        )
    assert exc_info.value.code == ProviderErrorCode.AUTH_FAILED


def test_send_turn_auth_rejected_by_hermes(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(httpx, "post", lambda url, headers, json, timeout: _fake_response(401))
    with pytest.raises(ProviderError) as exc_info:
        _provider().send_turn(system_prompt="sys", messages=[], timeout=10.0)
    assert exc_info.value.code == ProviderErrorCode.AUTH_FAILED


def test_send_turn_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    def _raise(url, headers, json, timeout):
        raise httpx.TimeoutException("timed out")

    monkeypatch.setattr(httpx, "post", _raise)
    with pytest.raises(ProviderError) as exc_info:
        _provider().send_turn(system_prompt="sys", messages=[], timeout=10.0)
    assert exc_info.value.code == ProviderErrorCode.TIMEOUT


def test_send_turn_unavailable_on_connection_error(monkeypatch: pytest.MonkeyPatch) -> None:
    def _raise(url, headers, json, timeout):
        raise httpx.ConnectError("refused")

    monkeypatch.setattr(httpx, "post", _raise)
    with pytest.raises(ProviderError) as exc_info:
        _provider().send_turn(system_prompt="sys", messages=[], timeout=10.0)
    assert exc_info.value.code == ProviderErrorCode.UNAVAILABLE


def test_send_turn_rate_limited(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(httpx, "post", lambda url, headers, json, timeout: _fake_response(429))
    with pytest.raises(ProviderError) as exc_info:
        _provider().send_turn(system_prompt="sys", messages=[], timeout=10.0)
    assert exc_info.value.code == ProviderErrorCode.RATE_LIMITED


def test_send_turn_malformed_response(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        httpx, "post", lambda url, headers, json, timeout: _fake_response(200, {"unexpected": True})
    )
    with pytest.raises(ProviderError) as exc_info:
        _provider().send_turn(system_prompt="sys", messages=[], timeout=10.0)
    assert exc_info.value.code == ProviderErrorCode.MALFORMED_RESPONSE


def test_provider_error_never_embeds_bearer_token(monkeypatch: pytest.MonkeyPatch) -> None:
    secret_token = "super-secret-bearer-token-value"
    monkeypatch.setattr(httpx, "post", lambda url, headers, json, timeout: _fake_response(401))
    with pytest.raises(ProviderError) as exc_info:
        _provider(bearer_token=secret_token).send_turn(system_prompt="sys", messages=[], timeout=10.0)
    assert secret_token not in str(exc_info.value)
    assert secret_token not in exc_info.value.summary

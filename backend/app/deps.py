"""Testable dependency-injection helpers for DB sessions and providers."""

from __future__ import annotations

from collections.abc import Generator

from fastapi import Request
from sqlalchemy.orm import Session

from app.credential_store import CredentialStore
from app.oauth_flow import OAuthFlowStore
from app.providers.base import AgentProvider
from app.voice.base import SpeechToText, TextToSpeech


def get_db(request: Request) -> Generator[Session, None, None]:
    session_factory = request.app.state.session_factory
    session = session_factory()
    try:
        yield session
    finally:
        session.close()


def get_provider(request: Request) -> AgentProvider:
    return request.app.state.provider


def get_stt(request: Request) -> SpeechToText:
    return request.app.state.stt


def get_tts(request: Request) -> TextToSpeech:
    return request.app.state.tts


def get_credential_store(request: Request) -> CredentialStore:
    return request.app.state.credential_store


def get_oauth_flow_store(request: Request) -> OAuthFlowStore:
    return request.app.state.oauth_flow_store


def get_http_client(request: Request):
    return request.app.state.integration_http_client


def get_backend_base_url(request: Request) -> str:
    return request.app.state.backend_base_url

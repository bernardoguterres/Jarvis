from __future__ import annotations

import uuid
from collections.abc import Generator, Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.config import Settings, get_settings
from app.migration_info import upgrade_database_to_head


@pytest.fixture(autouse=True)
def _no_real_hermes_cli(monkeypatch: pytest.MonkeyPatch) -> None:
    """Automated tests must never shell out to whatever Hermes installation
    (or lack of one) happens to exist on the machine running them — that
    would make export tests non-deterministic and could leak a real local
    Hermes profile's contents into a test archive. Tests that specifically
    want to exercise Hermes-profile-export behavior override this back with
    a fake script (see test_hermes_profile_export.py)."""
    monkeypatch.setenv("HERMES_CLI_COMMAND", "hermes-cli-unavailable-in-automated-tests")


@pytest.fixture(autouse=True)
def _no_real_browser_open(monkeypatch: pytest.MonkeyPatch) -> None:
    """Automated tests must never actually spawn `open <url>` — `POST
    /api/integrations/{provider}/connect` does this for real (server-side
    system-browser open, see app/routers/integrations.py's
    `_open_in_system_browser`) so every OAuth connect-flow test would
    otherwise pop open a real browser window on whatever machine runs the
    suite. Patches that one dedicated function, never `subprocess.Popen`
    globally — the latter is a shared module object, and patching it
    would also silently break every other real subprocess use elsewhere
    (Hermes profile export, etc.) that happens to run in the same test
    session — confirmed the hard way when an earlier, broader version of
    this same fixture did exactly that."""
    monkeypatch.setattr("app.routers.integrations._open_in_system_browser", lambda url: None)


@pytest.fixture()
def data_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Isolated JARVIS_DATA_DIR for a single test. Never the real ~/JarvisData."""
    isolated = tmp_path / f"jarvis-test-{uuid.uuid4().hex[:8]}"
    monkeypatch.setenv("JARVIS_DATA_DIR", str(isolated))
    return isolated


def _prepare_schema(data_dir: Path) -> Settings:
    """Applies real Alembic migrations (not create_all) so the resulting
    database carries a genuine alembic_version stamp — required for the
    Phase 2 import/export schema-revision checks to have anything to check."""
    settings = get_settings()
    assert settings.data_dir == data_dir.resolve()
    settings.ensure_directories()
    upgrade_database_to_head(settings.database_url)
    return settings


@pytest.fixture()
def client(data_dir: Path) -> Iterator[TestClient]:
    _prepare_schema(data_dir)

    from app.main import create_app

    app = create_app()
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture()
def restart_client_factory(data_dir: Path) -> Generator:
    """Yields a factory that builds a fresh TestClient against the SAME data_dir,
    simulating a backend restart while preserving the on-disk SQLite database."""
    _prepare_schema(data_dir)

    from app.main import create_app

    clients: list[TestClient] = []

    def _make() -> TestClient:
        app = create_app()
        test_client = TestClient(app)
        test_client.__enter__()
        clients.append(test_client)
        return test_client

    yield _make

    for c in clients:
        c.__exit__(None, None, None)


@pytest.fixture()
def populated_settings(data_dir: Path) -> Settings:
    """A fully migrated, seeded data directory with one BODY and one BUILD
    conversation (each with a message) plus one document, one domain
    summary, and one skill file — the fixture used by Phase 2 export/import
    tests that need real content to round-trip."""
    settings = _prepare_schema(data_dir)

    from app.database import build_sessionmaker
    from app.database import build_engine as _build_engine
    from app.models import Conversation, Message
    from app.seed import seed_domains

    engine = _build_engine(settings.database_url)
    session_factory = build_sessionmaker(engine)
    with session_factory() as session:
        seed_domains(session)

        from app.models import Domain

        body = session.query(Domain).filter_by(slug="body").one()
        build = session.query(Domain).filter_by(slug="build").one()

        body_conv = Conversation(domain_id=body.id, title="Knee check-in")
        build_conv = Conversation(domain_id=build.id, title="Alpha checkpoint")
        session.add_all([body_conv, build_conv])
        session.flush()

        session.add_all(
            [
                Message(conversation_id=body_conv.id, role="user", content="Knee felt fine today."),
                Message(conversation_id=build_conv.id, role="user", content="Shipped the tokenizer fix."),
            ]
        )
        session.commit()
    engine.dispose()

    settings.documents_dir.mkdir(parents=True, exist_ok=True)
    (settings.documents_dir / "note.txt").write_text("A test document for round-trip verification.\n")

    settings.domain_summaries_dir.mkdir(parents=True, exist_ok=True)
    (settings.domain_summaries_dir / "body.md").write_text("# BODY summary\nKnee stable this week.\n")

    settings.skills_dir.mkdir(parents=True, exist_ok=True)
    (settings.skills_dir / "log-weight.md").write_text("# log-weight skill\nRecord a weight entry.\n")

    return settings


class FakeProvider:
    """A mocked/fake agent provider — automated tests must never make a real
    (paid) call to Hermes/Claude. Configurable per-test via the mutable
    attributes below."""

    name = "fake"

    def __init__(self) -> None:
        self.available = True
        self.configured = True
        self.model = "openai-codex/gpt-5.6-terra"
        self.response_content = "This is a fake Jarvis response."
        self.usage_input_tokens: int | None = 12
        self.usage_output_tokens: int | None = 8
        self.usage_total_tokens: int | None = 20
        self.external_run_id: str | None = "fake-run-id-123"
        self.error: object | None = None  # set to a ProviderError to force failure
        self.sent_messages: list[list] = []
        self.sent_system_prompts: list[str] = []

    def health(self, *, timeout: float):
        from app.providers.base import ProviderHealth

        return ProviderHealth(available=self.available, detail="fake")

    def model_info(self, *, timeout: float):
        from app.providers.base import ModelInfo

        return ModelInfo(configured=self.configured, model=self.model, provider_name=self.name)

    def send_turn(self, *, system_prompt: str, messages, timeout: float):
        from app.providers.base import TurnResult, Usage

        self.sent_system_prompts.append(system_prompt)
        self.sent_messages.append(list(messages))

        if self.error is not None:
            raise self.error

        return TurnResult(
            content=self.response_content,
            model=self.model,
            provider_name=self.name,
            latency_ms=42,
            usage=Usage(
                input_tokens=self.usage_input_tokens,
                output_tokens=self.usage_output_tokens,
                total_tokens=self.usage_total_tokens,
            ),
            external_run_id=self.external_run_id,
        )


@pytest.fixture()
def fake_provider() -> FakeProvider:
    return FakeProvider()


@pytest.fixture()
def client_with_fake_provider(
    client: TestClient, fake_provider: FakeProvider
) -> Iterator[TestClient]:
    """The standard `client` fixture, but with its Hermes provider replaced
    by a FakeProvider — for tests that exercise agent/turn endpoints without
    ever making a real network call."""
    client.app.state.provider = fake_provider
    yield client


class FakeSTT:
    """Fake speech-to-text — automated tests must never load a real
    faster-whisper model (slow, and downloads weights over the network on
    first use)."""

    def __init__(self) -> None:
        self.transcript = "This is a fake transcript."
        self.received_paths: list[Path] = []
        self.error: Exception | None = None

    def transcribe(self, audio_path: Path) -> str:
        self.received_paths.append(audio_path)
        if self.error is not None:
            raise self.error
        return self.transcript


class FakeTTS:
    """Fake text-to-speech — automated tests must never call the real Edge
    TTS network endpoint."""

    def __init__(self) -> None:
        self.audio_bytes = b"fake-mp3-bytes"
        self.received_texts: list[str] = []
        self.error: Exception | None = None

    async def synthesize(self, text: str) -> bytes:
        self.received_texts.append(text)
        if self.error is not None:
            raise self.error
        return self.audio_bytes


@pytest.fixture()
def fake_stt() -> FakeSTT:
    return FakeSTT()


@pytest.fixture()
def fake_tts() -> FakeTTS:
    return FakeTTS()


@pytest.fixture()
def client_with_fake_voice(
    client: TestClient, fake_stt: FakeSTT, fake_tts: FakeTTS
) -> Iterator[TestClient]:
    """The standard `client` fixture, but with real STT/TTS replaced by
    fakes — for tests that exercise voice endpoints without ever loading a
    real Whisper model or calling the real Edge TTS network endpoint."""
    client.app.state.stt = fake_stt
    client.app.state.tts = fake_tts
    yield client


from app.credential_store import FakeCredentialStore  # noqa: E402


@pytest.fixture()
def fake_credential_store() -> FakeCredentialStore:
    return FakeCredentialStore()


@pytest.fixture()
def client_with_fake_integrations(
    client: TestClient, fake_credential_store: FakeCredentialStore
) -> Iterator[TestClient]:
    """The standard `client` fixture, but with the credential store replaced
    by an in-memory fake — automated tests must never touch the real macOS
    Keychain. HTTP to Google (Calendar and Health) must additionally be mocked per-test via
    `make_mock_http_client` (real network calls are never made in tests)."""
    client.app.state.credential_store = fake_credential_store
    yield client


def make_mock_http_client(handler) -> "httpx.Client":
    import httpx

    return httpx.Client(transport=httpx.MockTransport(handler))


@pytest.fixture()
def memory_settings(data_dir: Path) -> Settings:
    """A fully migrated, seeded (six domains only, no extra conversations)
    data directory for Phase 4 memory/record/context tests."""
    settings = _prepare_schema(data_dir)

    from app.database import build_engine as _build_engine
    from app.database import build_sessionmaker
    from app.seed import seed_domains

    engine = _build_engine(settings.database_url)
    with build_sessionmaker(engine)() as session:
        seed_domains(session)
    engine.dispose()
    return settings


@pytest.fixture()
def db_session(memory_settings: Settings) -> Iterator["Session"]:
    from app.database import build_engine as _build_engine
    from app.database import build_sessionmaker

    engine = _build_engine(memory_settings.database_url)
    session_factory = build_sessionmaker(engine)
    session = session_factory()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()

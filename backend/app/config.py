"""Resolves the Jarvis personal-data directory and derived paths.

Personal data (the SQLite database, documents, etc.) lives outside the Git
repository under JARVIS_DATA_DIR, defaulting to ~/JarvisData. This module is
the single place that resolves that path so the rest of the app never
hardcodes it.
"""

from __future__ import annotations

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="", extra="ignore", env_file=".env", env_file_encoding="utf-8"
    )

    jarvis_data_dir: str = str(Path.home() / "JarvisData")
    cors_origin: str = "http://localhost:5173"

    # Hermes provider configuration. Non-secret fields have safe defaults;
    # the bearer token is the one secret field here and must never be
    # returned by any API response, logged, or included in an export/backup
    # (it lives only in backend/.env, outside JARVIS_DATA_DIR entirely).
    #
    # hermes_model is a human-readable label only (recorded in
    # Message.model_used and agent_runs.model) — it is NEVER sent to Hermes.
    # Hermes's API server only understands its own virtual per-profile model
    # alias, so the actual model/provider is entirely owned by however the
    # 'jarvis' Hermes profile itself is configured (`jarvis config set
    # model` / `jarvis setup model`). Update this label to match whenever
    # that changes; nothing else in this codebase needs to.
    hermes_base_url: str = "http://127.0.0.1:8642"
    hermes_model: str = "openai-codex/gpt-5.6-terra"
    hermes_request_timeout_seconds: float = 30.0
    hermes_max_context_messages: int = 20
    hermes_api_bearer_token: str = ""
    hermes_profile_name: str = "jarvis"
    hermes_cli_command: str = "hermes"

    # Voice (Phase 5): local faster-whisper transcription and Edge TTS
    # synthesis. Both run entirely outside the model-independence boundary
    # above (they are not the reasoning model) but are configured here for
    # the same reason: nothing about the provider should be hardcoded deep
    # in application code.
    whisper_model_size: str = "base"
    whisper_device: str = "cpu"
    whisper_compute_type: str = "int8"
    edge_tts_voice: str = "en-GB-RyanNeural"

    # Phase 9: this backend's own loopback base URL, used to construct
    # OAuth redirect URIs (e.g. http://127.0.0.1:8000/api/integrations/
    # google_calendar/oauth/callback) — must exactly match what's registered
    # in each provider's OAuth client console.
    backend_base_url: str = "http://127.0.0.1:8000"

    @property
    def data_dir(self) -> Path:
        return Path(self.jarvis_data_dir).expanduser().resolve()

    @property
    def database_dir(self) -> Path:
        return self.data_dir / "database"

    @property
    def database_path(self) -> Path:
        return self.database_dir / "jarvis.sqlite"

    @property
    def database_url(self) -> str:
        return f"sqlite:///{self.database_path}"

    @property
    def documents_dir(self) -> Path:
        return self.data_dir / "documents"

    @property
    def domain_summaries_dir(self) -> Path:
        return self.data_dir / "domain-summaries"

    @property
    def skills_dir(self) -> Path:
        return self.data_dir / "skills"

    @property
    def configuration_dir(self) -> Path:
        return self.data_dir / "configuration"

    @property
    def backups_dir(self) -> Path:
        return self.data_dir / "backups"

    @property
    def exports_dir(self) -> Path:
        return self.data_dir / "exports"

    def ensure_directories(self) -> None:
        """Create only the missing directories, personal data included."""
        for path in (
            self.database_dir,
            self.documents_dir,
            self.domain_summaries_dir,
            self.skills_dir,
            self.configuration_dir,
            self.backups_dir,
            self.exports_dir,
        ):
            path.mkdir(parents=True, exist_ok=True)


def get_settings() -> Settings:
    return Settings()

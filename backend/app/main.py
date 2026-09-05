"""Jarvis FastAPI controller entrypoint (Phase 1-2)."""

from __future__ import annotations

import logging
import sys
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path

import httpx
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import text

from app.action_service import expire_interrupted_executions
from app.backup_service import run_due_backups
from app.briefing_service import cleanup_old_briefing_state
from app.config import get_settings
from app.credential_store import KeychainCredentialStore
from app.database import build_engine, build_sessionmaker
from app.export_service import cleanup_stale_export_temp_files
from app.mission_control_service import cleanup_old_focus_sessions
from app.oauth_flow import OAuthFlowStore
from app.providers.hermes import HermesProvider
from app.recall_index_service import rebuild_recall_index
from app.scheduler_runtime import SchedulerRuntime
from app.routers import (
    actions,
    agent,
    briefing,
    conversations,
    data_management,
    decisions,
    documents,
    domains,
    general,
    health,
    integrations,
    memory,
    mission_control,
    mission_focus,
    recall,
    research,
    routines,
    skills,
    voice,
)
from app.seed import seed_domains, seed_example_skills
from app.voice.edge_tts_tts import EdgeTextToSpeech
from app.voice.faster_whisper_stt import FasterWhisperSTT

logger = logging.getLogger("jarvis")

def _resolve_frontend_dist_dir() -> Path:
    """Locate the built frontend, whether running from source or frozen.

    From source, it's repo root / frontend / dist — three levels up from
    this file. Under the PyInstaller onefile native-packaging sidecar
    (Stage 1), ``__file__`` resolves inside a path that no longer exists at
    runtime, and bundled data (added via the spec's ``--add-data``) is
    extracted at startup to ``sys._MEIPASS`` — a fresh temp directory each
    run, never a fixed location relative to the executable itself — so the
    build is located there instead (see
    backend/packaging/jarvis_backend.spec).
    """
    if getattr(sys, "frozen", False):
        meipass = getattr(sys, "_MEIPASS", None)
        base = Path(meipass) if meipass else Path(sys.executable).resolve().parent
        return base / "frontend-dist"
    return Path(__file__).resolve().parents[2] / "frontend" / "dist"


FRONTEND_DIST_DIR = _resolve_frontend_dist_dir()


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    settings.ensure_directories()

    engine = build_engine(settings.database_url)
    session_factory = build_sessionmaker(engine)

    app.state.engine = engine
    app.state.session_factory = session_factory
    app.state.provider = HermesProvider(
        base_url=settings.hermes_base_url,
        bearer_token=settings.hermes_api_bearer_token,
        model=settings.hermes_model,
    )
    app.state.stt = FasterWhisperSTT(
        model_size=settings.whisper_model_size,
        device=settings.whisper_device,
        compute_type=settings.whisper_compute_type,
    )
    app.state.tts = EdgeTextToSpeech(voice=settings.edge_tts_voice)

    # Phase 9: integrations. Credentials/tokens live only in the Keychain —
    # never in this app's own database or config.
    app.state.credential_store = KeychainCredentialStore()
    app.state.oauth_flow_store = OAuthFlowStore()
    app.state.integration_http_client = httpx.Client(timeout=30.0)
    app.state.backend_base_url = settings.backend_base_url

    with session_factory() as session:
        seed_domains(session)
        seed_example_skills(session)

    # Recover any action proposal a prior process left stuck in "executing"
    # (a crash/kill mid-execution) — see action_service.expire_interrupted_executions
    # for why nothing else in this codebase ever resolves that state on an
    # ordinary restart. Must never block or fail startup.
    try:
        with session_factory() as session:
            recovered = expire_interrupted_executions(session)
            if recovered:
                logger.warning(
                    "Recovered %d action proposal(s) left stuck in 'executing' by a prior interrupted process.",
                    recovered,
                )
    except Exception:
        logger.exception("Startup interrupted-execution recovery failed; continuing without it.")

    # Remove any leftover export scratch file (.tmp-*/.dbsnapshot-*) a prior
    # process left behind by being killed mid-export — see
    # export_service.cleanup_stale_export_temp_files. Must never block or
    # fail startup; a real completed export is never matched by this.
    try:
        removed = cleanup_stale_export_temp_files(settings)
        if removed:
            logger.warning("Removed %d stale export scratch file(s) left by a prior interrupted export.", removed)
    except Exception:
        logger.exception("Startup stale-export-temp-file cleanup failed; continuing without it.")

    # Lightweight due-check, not a scheduler (see docs/ARCHITECTURE.md). Must
    # never block or fail startup.
    try:
        run_due_backups(settings)
    except Exception:
        logger.exception("Startup backup due-check failed; continuing without it.")

    # Phase 12B: bounded retention for old resolved briefing-ledger rows
    # and restored/expired acknowledge/snooze rows — never touches an
    # active row of any kind. Must never block or fail startup.
    try:
        with session_factory() as session:
            removed = cleanup_old_briefing_state(session, datetime.now(timezone.utc))
            if removed:
                logger.info("Pruned %d expired/resolved briefing-continuity row(s).", removed)
    except Exception:
        logger.exception("Startup briefing-continuity cleanup failed; continuing without it.")

    # Mission Control: bounded retention for old completed/abandoned focus
    # sessions — never touches the current active/paused session. Must
    # never block or fail startup.
    try:
        with session_factory() as session:
            removed = cleanup_old_focus_sessions(session)
            if removed:
                logger.info("Pruned %d old focus session(s) beyond the retention window.", removed)
    except Exception:
        logger.exception("Startup focus-session cleanup failed; continuing without it.")

    # Phase 12D: backfill the recall index for an installation upgrading
    # from before migration 0016 (a fresh empty recall_fts table has
    # nothing wrong with it — this only ever fires once per installation,
    # the first startup after the migration). Never a periodic resync —
    # every relevant write path calls recall_index_service.sync_recall()
    # directly, this is only the one-time backfill safety net. Must never
    # block or fail startup.
    try:
        with session_factory() as session:
            existing = session.execute(text("SELECT COUNT(*) FROM recall_fts")).scalar_one()
            if existing == 0:
                indexed = rebuild_recall_index(session)
                if indexed:
                    logger.info("Backfilled the recall index with %d row(s).", indexed)
    except Exception:
        logger.exception("Startup recall-index backfill failed; continuing without it.")

    # Phase 10: controller-owned automatic integration resync. A single
    # background asyncio task, started/stopped with this same lifespan —
    # never a Hermes cron job, never a second process. See
    # docs/ARCHITECTURE.md and docs/DECISIONS.md.
    app.state.scheduler_runtime = SchedulerRuntime(
        session_factory, app.state.credential_store, app.state.integration_http_client
    )
    await app.state.scheduler_runtime.start()

    yield

    await app.state.scheduler_runtime.stop()
    app.state.integration_http_client.close()
    engine.dispose()


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(title="Jarvis Controller", version="0.1.0", lifespan=lifespan)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=[settings.cors_origin],
        allow_credentials=False,
        # PUT is required by real, already-shipped endpoints (domain summary,
        # integration schedule, routine schedule) — omitting it only ever
        # broke `npm run dev`'s cross-origin (5173->8000) preflight for
        # those specific calls, never production (Phase 7 serves the
        # frontend same-origin, where no preflight happens at all). Fixed
        # per docs/DECISIONS.md D82 — still an explicit, non-wildcard list,
        # not "*".
        allow_methods=["GET", "POST", "PUT"],
        allow_headers=["Content-Type"],
    )

    app.include_router(health.router)
    app.include_router(domains.router)
    app.include_router(conversations.router)
    app.include_router(general.router)
    app.include_router(data_management.router)
    app.include_router(agent.router)
    app.include_router(memory.router)
    app.include_router(voice.router)
    app.include_router(actions.router)
    app.include_router(skills.router)
    app.include_router(integrations.router)
    app.include_router(documents.router)
    app.include_router(routines.router)
    app.include_router(briefing.router)
    app.include_router(mission_focus.router)
    app.include_router(mission_control.router)
    app.include_router(recall.router)
    app.include_router(research.router)
    app.include_router(decisions.router)

    # A genuine 404 for any unmatched /api/* path, registered before the
    # static mount below — otherwise a client typo'd or nonexistent API path
    # would silently fall through to the static-file app and come back as
    # its own 404/405 instead of this API's, once that mount exists.
    @app.api_route(
        "/api/{full_path:path}",
        methods=["GET", "POST", "PUT", "DELETE"],
        include_in_schema=False,
    )
    async def api_not_found(full_path: str) -> None:
        raise HTTPException(status_code=404, detail="Not Found")

    # Phase 7: serve the production frontend build from this same origin/port
    # when it exists, so ordinary use doesn't depend on Vite's dev server.
    # Registered last so none of it ever shadows the "/api/..." routes
    # above — Starlette tries routes in registration order.
    if FRONTEND_DIST_DIR.is_dir():
        # Vite's hashed JS/CSS bundle lives under /assets — mounted on its
        # own subpath (not "/") so a plain Mount("/") can never swallow the
        # catch-all route below before it gets a chance to run.
        app.mount(
            "/assets",
            StaticFiles(directory=FRONTEND_DIST_DIR / "assets", check_dir=False),
            name="frontend-assets",
        )

        index_path = FRONTEND_DIST_DIR / "index.html"

        # Phase 6 (D75-series diagnostic pass): a genuine SPA fallback.
        # This is a single-URL frontend (no client-side URL routing at
        # all) — the app itself decides what's a known route. Any GET not
        # already matched above (not /api/*, not /assets/*) either names a
        # real file at the build root (favicon, etc.) and is served
        # verbatim, or is the frontend's own "unknown route" case, and
        # gets index.html (200, not a bare framework 404) so the SPA can
        # mount and render its own NotFoundDiagnostic truthfully.
        @app.get("/{full_path:path}", include_in_schema=False)
        async def spa_fallback(full_path: str) -> FileResponse:
            candidate = (FRONTEND_DIST_DIR / full_path).resolve()
            dist_root = FRONTEND_DIST_DIR.resolve()
            if full_path and candidate.is_file() and dist_root in candidate.parents:
                return FileResponse(candidate)
            return FileResponse(index_path)
    else:
        logger.info(
            "No frontend production build found at %s; not serving static "
            "frontend (run `npm run build` in frontend/, or use `npm run dev` "
            "for local development).",
            FRONTEND_DIST_DIR,
        )

    return app


app = create_app()

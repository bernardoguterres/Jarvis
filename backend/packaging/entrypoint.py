"""Entrypoint for the PyInstaller-frozen Jarvis backend sidecar (Stage 1
native macOS packaging).

Mirrors exactly what scripts/jarvisctl.sh already does when starting the
backend from source: run pending Alembic migrations, then serve the app —
so this is a packaging-only wrapper, not a second startup implementation.
Never imported by the running application itself; only ever invoked as the
frozen binary's own process entrypoint.
"""

from __future__ import annotations

import logging
import os
import sys
from pathlib import Path

logger = logging.getLogger("jarvis.packaging.entrypoint")


def _bundled_base_dir() -> Path:
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        return Path(meipass)
    # Running unfrozen (e.g. `uv run python packaging/entrypoint.py` during
    # development of this script itself) — alembic.ini/alembic/ live one
    # level up, at the backend/ project root.
    return Path(__file__).resolve().parent.parent


def _run_migrations() -> None:
    from alembic import command
    from alembic.config import Config

    # Mirrors alembic/env.py: honor an already-set sqlalchemy.url, otherwise
    # fall back to the JARVIS_DATA_DIR-resolved default exactly as normal
    # application startup does.
    from app.config import get_settings

    settings = get_settings()
    settings.ensure_directories()

    base = _bundled_base_dir()
    cfg = Config(str(base / "alembic.ini"))
    cfg.set_main_option("script_location", str(base / "alembic"))
    cfg.set_main_option("sqlalchemy.url", settings.database_url)
    command.upgrade(cfg, "head")


def _detach_stdin() -> None:
    """Redirect stdin to /dev/null.

    The Tauri sidecar host (tauri-plugin-shell) always spawns this process
    with stdin as an open OS pipe it never writes to or closes. Left alone,
    an unread pipe on fd 0 can make part of this process's own startup
    block indefinitely waiting for input that will never arrive. A
    background service has no legitimate use for stdin, so detach it
    unconditionally, the same way any other daemon would.
    """
    try:
        devnull_fd = os.open(os.devnull, os.O_RDONLY)
        os.dup2(devnull_fd, 0)
        os.close(devnull_fd)
    except OSError:
        pass


def main() -> int:
    _detach_stdin()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

    host = "127.0.0.1"
    port = 8000
    for i, arg in enumerate(sys.argv):
        if arg == "--port" and i + 1 < len(sys.argv):
            port = int(sys.argv[i + 1])

    logger.info("Running database migrations…")
    _run_migrations()

    logger.info("Starting Jarvis backend on %s:%s", host, port)
    import uvicorn

    from app.main import app

    uvicorn.run(app, host=host, port=port, log_level="info")
    return 0


if __name__ == "__main__":
    # Required for a frozen (PyInstaller onefile) executable that may use
    # Python's multiprocessing module with the 'spawn' start method (macOS's
    # default since Python 3.8). Spawning a worker re-invokes sys.executable
    # — this same frozen binary — with a bootstrap marker in argv;
    # freeze_support() must run first to intercept that marker and run only
    # the worker bootstrap. Without it, a respawned "worker" instead falls
    # through to this script's own main(), re-running migrations and
    # uvicorn.run() from scratch (see docs/DECISIONS.md D109 for the real
    # incident this caused).
    import multiprocessing

    multiprocessing.freeze_support()

    raise SystemExit(main())

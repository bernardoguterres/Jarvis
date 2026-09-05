# PyInstaller spec for the Jarvis backend sidecar (Stage 1 native macOS
# packaging). Produces a single onefile arm64 executable containing the
# FastAPI app, its Python dependencies, the built frontend (served
# same-origin — see app/main.py's _resolve_frontend_dist_dir), and the
# Alembic migration scripts (run once at startup, mirroring
# scripts/jarvisctl.sh's own sequence).
#
# Build with: uv run pyinstaller backend/packaging/jarvis_backend.spec
# from the backend/ directory. Output naming (Tauri externalBin convention,
# a target-triple suffix) is applied by scripts/build_native_app.sh after
# this spec produces the base onefile binary.
from pathlib import Path

block_cipher = None

BACKEND_DIR = Path.cwd()
REPO_ROOT = BACKEND_DIR.parent
FRONTEND_DIST = REPO_ROOT / "frontend" / "dist"

datas = [
    (str(BACKEND_DIR / "alembic"), "alembic"),
    (str(BACKEND_DIR / "alembic.ini"), "."),
    (str(FRONTEND_DIST), "frontend-dist"),
]

# faster-whisper ships model-loading assets and ctranslate2 native
# libraries that PyInstaller's static import analysis cannot see (loaded
# dynamically) — collect them explicitly rather than guessing which files
# matter.
hiddenimports = [
    "app.routers.actions",
    "app.routers.agent",
    "app.routers.briefing",
    "app.routers.conversations",
    "app.routers.data_management",
    "app.routers.decisions",
    "app.routers.documents",
    "app.routers.domains",
    "app.routers.general",
    "app.routers.health",
    "app.routers.integrations",
    "app.routers.memory",
    "app.routers.mission_control",
    "app.routers.mission_focus",
    "app.routers.recall",
    "app.routers.research",
    "app.routers.routines",
    "app.routers.skills",
    "app.routers.voice",
    "keyring.backends.macOS",
]

a = Analysis(
    ["entrypoint.py"],
    pathex=[str(BACKEND_DIR)],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    cipher=block_cipher,
)
pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="jarvis-backend",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,
    target_arch="arm64",
)

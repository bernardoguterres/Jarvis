"""Shared constants and safety helpers for the export/import/backup system."""

from __future__ import annotations

import platform
import stat
from pathlib import Path
from zipfile import ZipInfo

EXPORT_FORMAT_VERSION = "1.0"
SUPPORTED_EXPORT_FORMAT_VERSIONS = {"1.0"}

APP_VERSION = "0.1.0"

CHECKSUM_ALGORITHM = "sha256"

# Payload directories that may be included in an export, in a fixed order so
# archive contents are deterministic.
PAYLOAD_DIRS = ("documents", "domain-summaries", "skills", "configuration")

# Archive path for an optional, supported Hermes profile export (Phase 3+).
HERMES_PROFILE_ARCHIVE_DIR = "hermes_profile"
HERMES_PROFILE_ARCHIVE_PATH = f"{HERMES_PROFILE_ARCHIVE_DIR}/"

# Basenames that must never appear inside a Hermes profile export payload.
# hermes_agent stores its own credentials in the profile's .env and any
# pooled-auth state in auth.json; both are excluded by `hermes profile
# export` itself, but Jarvis verifies this independently rather than trusting
# that the upstream tool always will.
HERMES_SECRET_BASENAMES = {".env", "auth.json"}

MANIFEST_FILENAME = "manifest.json"
DATABASE_ARCHIVE_PATH = "database/jarvis.sqlite"

# Safety limits enforced on import, independent of what an archive claims
# about itself.
MAX_ARCHIVE_MEMBERS = 5000
MAX_TOTAL_UNCOMPRESSED_BYTES = 2 * 1024 * 1024 * 1024  # 2 GiB

# Names never copied into an export payload, even if present in a source
# directory. Defends against accidental secret/junk inclusion.
EXCLUDED_NAMES = {".DS_Store", "__pycache__", "node_modules", ".git", ".env"}
EXCLUDED_NAME_PREFIXES = (".env.",)


def is_excluded_name(name: str) -> bool:
    if name in EXCLUDED_NAMES:
        return True
    return any(name.startswith(prefix) for prefix in EXCLUDED_NAME_PREFIXES)


def platform_info() -> dict[str, str]:
    """Non-identifying platform info: no hostname, username, or machine ID."""
    return {
        "system": platform.system(),
        "machine": platform.machine(),
        "python_version": platform.python_version(),
    }


def has_parent_traversal(archive_path: str) -> bool:
    parts = Path(archive_path).parts
    return ".." in parts


def is_absolute_archive_path(archive_path: str) -> bool:
    if archive_path.startswith("/") or archive_path.startswith("\\"):
        return True
    # Windows drive letter, e.g. "C:\\..."
    if len(archive_path) >= 2 and archive_path[1] == ":":
        return True
    return False


def zipinfo_is_symlink_or_special(info: ZipInfo) -> bool:
    """True if a ZIP member's stored Unix mode indicates a symlink or
    another non-regular file (device, FIFO, socket).

    Members written via ``ZipFile.writestr`` (as manifest.json is) carry
    permission bits but no file-type bits at all (``external_attr`` has no
    S_IFMT component) — that's a legitimate regular file, not a special one,
    so an absent file type is treated as "unknown, assume regular" rather
    than rejected. A real Unix zip archiver always sets the type bits for
    files it writes, so this doesn't weaken detection of an actually crafted
    malicious symlink entry, which is exactly what has explicit S_IFLNK bits.
    """
    mode = info.external_attr >> 16
    if mode == 0:
        return False
    file_type = stat.S_IFMT(mode)
    if file_type == 0:
        return False
    if stat.S_ISLNK(mode):
        return True
    if not stat.S_ISREG(mode) and not stat.S_ISDIR(mode):
        return True
    return False


def normalized_archive_path(archive_path: str) -> str:
    """Normalizes separators for duplicate-detection, without resolving '..'."""
    return archive_path.replace("\\", "/").rstrip("/")

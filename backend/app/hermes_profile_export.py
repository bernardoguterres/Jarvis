"""Optional Hermes profile export/import support.

Uses Hermes's own supported ``hermes profile export``/``import`` commands
rather than copying undocumented internal files (CLAUDE.md §11). Inclusion
is always optional: if the ``hermes`` command or the named profile isn't
present, the main Jarvis export proceeds without it.

Jarvis independently scans the resulting archive for HERMES_SECRET_BASENAMES
rather than trusting that Hermes's own export always excludes them.
"""

from __future__ import annotations

import shutil
import subprocess
import tarfile
from dataclasses import dataclass
from pathlib import Path

from app.archive_common import HERMES_SECRET_BASENAMES


@dataclass
class HermesExportAttempt:
    path: Path | None
    skipped_reason: str | None


def attempt_hermes_profile_export(
    profile_name: str, hermes_cli_command: str, dest_dir: Path
) -> HermesExportAttempt:
    """Runs `hermes profile export <profile_name>` into dest_dir. Returns the
    resulting tar.gz path, or a reason it was skipped (never raises)."""
    hermes_bin = shutil.which(hermes_cli_command)
    if hermes_bin is None:
        return HermesExportAttempt(path=None, skipped_reason="hermes command not found")

    output_path = dest_dir / f"{profile_name}.tar.gz"
    try:
        result = subprocess.run(
            [hermes_bin, "profile", "export", profile_name, "-o", str(output_path)],
            capture_output=True,
            timeout=60,
            text=True,
        )
    except (subprocess.TimeoutExpired, OSError) as exc:
        return HermesExportAttempt(path=None, skipped_reason=f"hermes profile export failed: {exc}")

    if result.returncode != 0 or not output_path.exists():
        return HermesExportAttempt(
            path=None,
            skipped_reason=f"profile {profile_name!r} not found or export failed",
        )

    secret_members = find_secret_members(output_path)
    if secret_members:
        output_path.unlink(missing_ok=True)
        return HermesExportAttempt(
            path=None,
            skipped_reason=(
                f"excluded: Hermes export unexpectedly contained secret file(s): "
                f"{secret_members}"
            ),
        )

    return HermesExportAttempt(path=output_path, skipped_reason=None)


def find_secret_members(tar_path: Path) -> list[str]:
    """Returns any member names in a Hermes profile tar.gz whose basename is
    a known secret filename (.env, auth.json)."""
    found: list[str] = []
    with tarfile.open(tar_path, "r:gz") as tf:
        for member in tf.getmembers():
            basename = Path(member.name).name
            if basename in HERMES_SECRET_BASENAMES:
                found.append(member.name)
    return found

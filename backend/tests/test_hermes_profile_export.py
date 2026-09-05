"""Tests for optional Hermes profile export/import — using a small fake
`hermes` script so these tests are hermetic and never depend on (or touch)
whatever real Hermes installation exists on the machine running them."""

from __future__ import annotations

import json
import stat
import sys
import tarfile
from pathlib import Path

from app.config import Settings
from app.export_service import create_export
from app.import_service import restore_archive, validate_archive

# Deliberately no "#!/usr/bin/env python3" shebang in these templates — see
# _install_fake_hermes, which prepends a shebang pointing at sys.executable
# (the exact interpreter running this test suite) instead. A bare "python3"
# shebang resolves through the *subprocess's inherited PATH*, not through
# whatever venv pytest itself is running under, which is never guaranteed to
# have a full standard library: this was found to genuinely break here,
# where PATH resolves "python3" to Ubuntu's python3.14-minimal package (its
# stdlib deliberately excludes tarfile, among other modules) rather than the
# project's own uv-managed venv — a real, reproducible environment gap, not
# a flaky test. Pinning to sys.executable makes the fake CLI hermetic
# against that gap the same way the rest of this file is already hermetic
# against a real Hermes installation.
FAKE_HERMES_CLEAN = """import sys, tarfile, io

assert sys.argv[1:3] == ["profile", "export"]
profile_name = sys.argv[3]
output = sys.argv[sys.argv.index("-o") + 1]

with tarfile.open(output, "w:gz") as tf:
    def add(name, content):
        data = content.encode()
        info = tarfile.TarInfo(name=f"{profile_name}/{name}")
        info.size = len(data)
        tf.addfile(info, io.BytesIO(data))
    add("SOUL.md", "You are Jarvis.")
    add("config.yaml", "model: openai-codex/gpt-5.6-terra\\n")
sys.exit(0)
"""

FAKE_HERMES_WITH_SECRETS = FAKE_HERMES_CLEAN.replace(
    'add("config.yaml"', 'add(".env", "API_SERVER_KEY=leaked-secret")\n    add("config.yaml"'
)

FAKE_HERMES_MISSING_PROFILE = """import sys
sys.stderr.write("profile not found\\n")
sys.exit(1)
"""


def _install_fake_hermes(tmp_path: Path, script_contents: str) -> str:
    script_path = tmp_path / "fake-hermes"
    # sys.executable, not a bare "#!/usr/bin/env python3" — see the module
    # docstring comment above FAKE_HERMES_CLEAN for why.
    script_path.write_text(f"#!{sys.executable}\n{script_contents}")
    script_path.chmod(script_path.stat().st_mode | stat.S_IEXEC)
    return str(script_path)


def test_hermes_profile_included_when_export_succeeds(
    populated_settings: Settings, tmp_path: Path
) -> None:
    populated_settings.hermes_cli_command = _install_fake_hermes(tmp_path, FAKE_HERMES_CLEAN)

    result = create_export(populated_settings)

    assert "hermes_profile" in result.manifest["included_components"]
    assert result.manifest["hermes_profile_export"]["included"] is True
    assert result.manifest["hermes_profile_export"]["archive_path"] == "hermes_profile/jarvis.tar.gz"

    validation = validate_archive(result.path)
    assert validation.ok, validation.errors


def test_hermes_profile_optional_when_command_missing(
    populated_settings: Settings,
) -> None:
    populated_settings.hermes_cli_command = "definitely-not-a-real-command-xyz"

    result = create_export(populated_settings)

    assert "hermes_profile" not in result.manifest["included_components"]
    assert result.manifest["hermes_profile_export"]["included"] is False


def test_hermes_profile_optional_when_profile_missing(
    populated_settings: Settings, tmp_path: Path
) -> None:
    populated_settings.hermes_cli_command = _install_fake_hermes(
        tmp_path, FAKE_HERMES_MISSING_PROFILE
    )

    result = create_export(populated_settings)

    assert result.manifest["hermes_profile_export"]["included"] is False


def test_hermes_secret_files_excluded_from_export(
    populated_settings: Settings, tmp_path: Path
) -> None:
    populated_settings.hermes_cli_command = _install_fake_hermes(
        tmp_path, FAKE_HERMES_WITH_SECRETS
    )

    result = create_export(populated_settings)

    # The export must NOT include the tainted Hermes payload at all.
    assert result.manifest["hermes_profile_export"]["included"] is False
    assert "secret" in result.manifest["hermes_profile_export"]["reason"].lower()

    import zipfile

    with zipfile.ZipFile(result.path) as zf:
        names = zf.namelist()
    assert not any("hermes_profile" in n for n in names)


def test_validate_rejects_archive_with_secrets_in_hermes_payload(
    populated_settings: Settings, tmp_path: Path
) -> None:
    """Simulates a hand-crafted (tampered) archive that claims a clean Hermes
    export but actually embeds one containing secrets, to prove the
    independent Jarvis-side scan — not just trust in the export step."""
    populated_settings.hermes_cli_command = _install_fake_hermes(tmp_path, FAKE_HERMES_CLEAN)
    result = create_export(populated_settings)

    tainted_hermes_tar = tmp_path / "tainted.tar.gz"
    with tarfile.open(tainted_hermes_tar, "w:gz") as tf:
        data = b"API_SERVER_KEY=leaked"
        info = tarfile.TarInfo(name="jarvis/.env")
        info.size = len(data)
        import io

        tf.addfile(info, io.BytesIO(data))

    import hashlib
    import shutil
    import zipfile

    tainted_bytes = tainted_hermes_tar.read_bytes()
    tainted_sha256 = hashlib.sha256(tainted_bytes).hexdigest()

    tmp_zip = tmp_path / "tampered.zip"
    with zipfile.ZipFile(result.path) as src, zipfile.ZipFile(tmp_zip, "w", zipfile.ZIP_DEFLATED) as dst:
        manifest = json.loads(src.read("manifest.json"))
        for entry in manifest["files"]:
            if entry["path"] == "hermes_profile/jarvis.tar.gz":
                entry["sha256"] = tainted_sha256
                entry["size"] = len(tainted_bytes)
        for info in src.infolist():
            if info.filename == "hermes_profile/jarvis.tar.gz":
                dst.writestr(info, tainted_bytes)
            elif info.filename == "manifest.json":
                dst.writestr(info, json.dumps(manifest).encode())
            else:
                dst.writestr(info, src.read(info.filename))
    shutil.move(str(tmp_zip), str(result.path))

    validation = validate_archive(result.path)
    assert not validation.ok
    assert any("secret" in e.lower() for e in validation.errors)


def test_hermes_profile_not_auto_imported_on_restore(
    populated_settings: Settings, tmp_path: Path
) -> None:
    populated_settings.hermes_cli_command = _install_fake_hermes(tmp_path, FAKE_HERMES_CLEAN)
    result = create_export(populated_settings)

    target = Settings(jarvis_data_dir=str(tmp_path / "install-b"))
    report = restore_archive(result.path, target)

    assert report.hermes_profile_export_path is not None
    assert report.hermes_profile_export_path.exists()
    # It must live OUTSIDE the restored JARVIS_DATA_DIR.
    assert not str(report.hermes_profile_export_path).startswith(str(target.data_dir))
    assert report.hermes_profile_import_command is not None
    assert "hermes profile import" in report.hermes_profile_import_command
    assert "jarvis" in report.hermes_profile_import_command

    # And restoring must never itself create a Hermes profile directory.
    with tarfile.open(report.hermes_profile_export_path, "r:gz") as tf:
        names = tf.getnames()
    assert any(n.endswith("SOUL.md") for n in names)


def test_older_phase2_style_archive_still_validates(
    populated_settings: Settings,
) -> None:
    """An export produced with no Hermes profile available (the Phase 2
    shape: hermes_profile_export.included == False) must still validate and
    restore fine — Phase 3 must not break Phase 2 archives."""
    populated_settings.hermes_cli_command = "definitely-not-a-real-command-xyz"
    result = create_export(populated_settings)

    assert result.manifest["hermes_profile_export"]["included"] is False
    validation = validate_archive(result.path)
    assert validation.ok, validation.errors

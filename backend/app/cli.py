"""Jarvis command-line entry point for export, restore, backup, and validation.

Run via: `uv run jarvis-cli <command> ...` (see pyproject.toml [project.scripts]).
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import getpass

from app.backup_service import BackupError, create_backup, get_latest_backup_info
from app.config import Settings, get_settings
from app.credential_store import KeychainCredentialStore
from app.export_service import ExportError, create_export
from app.import_service import RestoreError, ValidationError, restore_archive, validate_archive
from app.integration_service import store_client_credentials


def _settings_for_target(target: str | None) -> Settings:
    if target:
        return Settings(jarvis_data_dir=target)
    return get_settings()


def cmd_export(args: argparse.Namespace) -> int:
    settings = _settings_for_target(args.data_dir)
    try:
        result = create_export(settings)
    except ExportError as exc:
        print(f"Export failed: {exc}", file=sys.stderr)
        return 1

    print(f"Export created: {result.path}")
    print(f"  filename:   {result.filename}")
    print(f"  size:       {result.size_bytes} bytes")
    print(f"  created_at: {result.created_at_utc}")
    return 0


def cmd_validate(args: argparse.Namespace) -> int:
    result = validate_archive(Path(args.archive))
    if result.extracted_dir:
        import shutil

        shutil.rmtree(result.extracted_dir, ignore_errors=True)

    if result.ok:
        print(f"Archive is valid: {args.archive}")
        if result.manifest:
            print(f"  export_format_version: {result.manifest['export_format_version']}")
            print(f"  schema_revision:       {result.manifest['schema_revision']}")
            print(f"  included_components:   {result.manifest['included_components']}")
        return 0

    print(f"Archive is INVALID: {args.archive}", file=sys.stderr)
    for error in result.errors:
        print(f"  - {error}", file=sys.stderr)
    return 1


def cmd_restore(args: argparse.Namespace) -> int:
    target_settings = _settings_for_target(args.target)

    try:
        report = restore_archive(
            Path(args.archive), target_settings, confirm_overwrite=args.confirm
        )
    except (ValidationError, RestoreError) as exc:
        print(f"Restore failed: {exc}", file=sys.stderr)
        return 1

    print(f"Restore complete into: {report.target_dir}")
    print(f"  domains restored:          {report.domains_restored}")
    print(f"  conversations restored:    {report.conversations_restored}")
    print(f"  messages restored:         {report.messages_restored}")
    print(f"  documents restored:        {report.documents_restored}")
    print(f"  domain summaries restored: {report.domain_summaries_restored}")
    print(f"  skills restored:           {report.skills_restored}")
    print(f"  schema revision before:    {report.schema_revision_before}")
    print(f"  schema revision after:     {report.schema_revision_after}")
    if report.rollback_dir:
        print(f"  previous installation preserved at: {report.rollback_dir}")
    if report.hermes_profile_export_path:
        print(f"  Hermes profile export saved at: {report.hermes_profile_export_path}")
        print(
            "  This was NOT imported automatically. To import it (only if you "
            "want to replace/create that profile on this machine), run:"
        )
        print(f"    {report.hermes_profile_import_command}")
        print(
            "  No model credential (API key or OAuth token) is included — run "
            "'jarvis setup model' afterward to re-establish it."
        )
    return 0


def cmd_backup(args: argparse.Namespace) -> int:
    settings = _settings_for_target(args.data_dir)
    try:
        result = create_backup(settings, category=args.category)
    except BackupError as exc:
        print(f"Backup failed: {exc}", file=sys.stderr)
        return 1

    print(f"Backup created: {result.path}")
    print(f"  category:   {result.category}")
    print(f"  size:       {result.size_bytes} bytes")
    print(f"  sha256:     {result.sha256}")
    return 0


def cmd_list_backups(args: argparse.Namespace) -> int:
    settings = _settings_for_target(args.data_dir)
    info = get_latest_backup_info(settings)
    print("Latest backup overall:", info["latest"])
    for category, details in info["by_category"].items():
        print(f"  {category}: {details}")
    return 0


def cmd_configure_integration(args: argparse.Namespace) -> int:
    """Enters an OAuth client id/secret directly into the macOS Keychain —
    run this yourself, in your own terminal. Nothing here is ever printed,
    logged, or sent anywhere by Jarvis; it is stored only via `keyring`."""
    client_id = input(f"{args.provider} OAuth client ID: ").strip()
    if not client_id:
        print("Client ID is required.", file=sys.stderr)
        return 1
    client_secret = getpass.getpass(f"{args.provider} OAuth client secret (input hidden): ").strip()
    if not client_secret:
        print("Client secret is required.", file=sys.stderr)
        return 1

    store_client_credentials(KeychainCredentialStore(), args.provider, client_id=client_id, client_secret=client_secret)
    print(f"Stored {args.provider} OAuth client credentials in the macOS Keychain.")
    print("Nothing was printed, logged, or written to any file by this command.")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="jarvis-cli", description="Jarvis data management CLI")
    subparsers = parser.add_subparsers(dest="command", required=True)

    export_parser = subparsers.add_parser("export", help="Create a portable export archive")
    export_parser.add_argument("--data-dir", help="Override JARVIS_DATA_DIR for this command")
    export_parser.set_defaults(func=cmd_export)

    validate_parser = subparsers.add_parser("validate", help="Validate an export archive without restoring it")
    validate_parser.add_argument("archive", help="Path to the .zip export archive")
    validate_parser.set_defaults(func=cmd_validate)

    restore_parser = subparsers.add_parser("restore", help="Restore an export archive into a data directory")
    restore_parser.add_argument("archive", help="Path to the .zip export archive")
    restore_parser.add_argument("--target", help="Target JARVIS_DATA_DIR (defaults to the current one)")
    restore_parser.add_argument(
        "--confirm",
        action="store_true",
        help="Required to overwrite a target directory that already has a database",
    )
    restore_parser.set_defaults(func=cmd_restore)

    backup_parser = subparsers.add_parser("backup", help="Create a manual backup")
    backup_parser.add_argument("--data-dir", help="Override JARVIS_DATA_DIR for this command")
    backup_parser.add_argument(
        "--category", choices=["daily", "weekly", "monthly"], default="daily"
    )
    backup_parser.set_defaults(func=cmd_backup)

    list_backups_parser = subparsers.add_parser("list-backups", help="Show latest backup metadata")
    list_backups_parser.add_argument("--data-dir", help="Override JARVIS_DATA_DIR for this command")
    list_backups_parser.set_defaults(func=cmd_list_backups)

    configure_integration_parser = subparsers.add_parser(
        "configure-integration",
        help="Enter an OAuth client id/secret into the macOS Keychain (run this yourself)",
    )
    configure_integration_parser.add_argument("provider", choices=["google_calendar", "google_health"])
    configure_integration_parser.set_defaults(func=cmd_configure_integration)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())

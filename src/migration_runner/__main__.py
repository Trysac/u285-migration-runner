"""Command-line interface for migration_runner."""

from __future__ import annotations

import argparse
import os
import socket
import sqlite3
import sys
from pathlib import Path

from .migrations import MigrationError, Migrator, load_migrations


def _make_owner() -> str:
    return f"{socket.gethostname()}-{os.getpid()}"


def _build_parser() -> argparse.ArgumentParser:
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--db", required=True, help="Path to SQLite database file.")
    common.add_argument(
        "--dir",
        required=True,
        help="Directory containing V<n>__<name>.sql migration files.",
    )
    common.add_argument("--target", type=int, default=None, help="Target version.")
    common.add_argument(
        "--owner",
        default=_make_owner(),
        help="Lock owner identifier (default hostname-pid).",
    )

    parser = argparse.ArgumentParser(
        prog="migration_runner",
        description="Run versioned SQL migrations against SQLite.",
    )
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("migrate", parents=[common], help="Apply pending migrations")
    sub.add_parser("status", parents=[common], help="Show migration status")
    sub.add_parser("plan", parents=[common], help="Show migrations that would be applied")
    return parser


def main(argv: list[str] | None = None) -> int:
    """Run the migration CLI.

    Exit codes: 0 success, 1 migration/checksum/lock error, 2 usage or IO error.
    """
    try:
        args = _build_parser().parse_args(argv)
    except SystemExit as exc:
        return exc.code if isinstance(exc.code, int) else 2

    try:
        migrations = load_migrations(Path(args.dir))
    except MigrationError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    except OSError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    try:
        conn = sqlite3.connect(args.db, isolation_level=None)
    except sqlite3.Error as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    try:
        migrator = Migrator(
            conn,
            migrations,
            owner=args.owner,
        )
        if args.command == "migrate":
            applied = migrator.migrate(target=args.target)
            migration_map = {m.version: m for m in migrations}
            for version in applied:
                migration = migration_map[version]
                print(f"applied {version} {migration.name}")
        elif args.command == "status":
            for status in migrator.status():
                print(f"{status.state} {status.version} {status.name}")
        elif args.command == "plan":
            for migration in migrator.plan(target=args.target):
                print(f"pending {migration.version} {migration.name}")
        return 0
    except MigrationError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    except (OSError, sqlite3.Error) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main())

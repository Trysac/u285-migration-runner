"""Core migration engine."""

from __future__ import annotations

import hashlib
import logging
import re
import sqlite3
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

logger = logging.getLogger(__name__)
logger.addHandler(logging.NullHandler())

_FILE_NAME_RE = re.compile(r"^V(\d{1,9})__([a-z0-9_]{1,100})\.sql$")


@dataclass(frozen=True)
class Migration:
    """A single migration read from a ``.sql`` file."""

    version: int
    name: str
    sql: str
    checksum: str


@dataclass(frozen=True)
class MigrationStatus:
    """State of one migration in the database."""

    version: int
    name: str
    state: Literal["applied", "pending", "missing_file"]


class MigrationError(Exception):
    """Base error for the migration runner."""

    def __init__(
        self,
        code: str,
        version: int | None = None,
        message: str | None = None,
    ) -> None:
        super().__init__(message or code)
        self.code = code
        self.version = version
        self.message = message or code

    def __str__(self) -> str:
        if self.version is not None:
            return f"{self.code} (version {self.version})"
        return self.message


class LockError(MigrationError):
    """Raised when the migration lock cannot be acquired."""

    def __init__(self, owner: str | None = None) -> None:
        message = f"lock held by {owner}" if owner else "lock held"
        super().__init__("lock_held", message=message)


def load_migrations(
    directory: Path,
    *,
    max_file_bytes: int = 1_000_000,
    max_files: int = 10_000,
) -> list[Migration]:
    r"""Load ``V<version>__<name>.sql`` files from *directory*.

    File names must match ``^V(\d{1,9})__([a-z0-9_]{1,100})\.sql$``.  Non-
    ``.sql`` files are ignored.  Migrations are returned sorted by version
    in ascending order.

    Args:
        directory: Directory containing migration files.
        max_file_bytes: Maximum size in bytes for a single migration file.
        max_files: Maximum number of ``.sql`` files to consider.

    Returns:
        List of :class:`Migration` objects.

    Raises:
        MigrationError: If a ``.sql`` file has an invalid name, exceeds
            ``max_file_bytes``, or if there are too many files or duplicate
            versions.
        OSError: If *directory* does not exist or is not a directory.
    """
    if not directory.exists():
        raise FileNotFoundError(f"directory does not exist: {directory}")
    if not directory.is_dir():
        raise NotADirectoryError(f"not a directory: {directory}")

    migrations: list[Migration] = []
    sql_files: list[Path] = []
    for entry in directory.iterdir():
        if not entry.is_file():
            continue
        if entry.suffix != ".sql":
            continue
        sql_files.append(entry)

    if len(sql_files) > max_files:
        raise MigrationError("too_many_files")

    for path in sql_files:
        match = _FILE_NAME_RE.match(path.name)
        if not match:
            raise MigrationError("invalid_name")
        version = int(match.group(1))
        name = match.group(2)

        try:
            size = path.stat().st_size
        except OSError:
            # File vanished between iterdir and stat; treat as missing and
            # re-raise with a clear error.
            raise
        if size > max_file_bytes:
            raise MigrationError("file_too_large", version=version)

        try:
            raw = path.read_text(encoding="utf-8")
        except OSError:
            raise
        normalized = raw.replace("\r\n", "\n").replace("\r", "\n")
        checksum = hashlib.sha256(normalized.encode("utf-8")).hexdigest()
        migrations.append(Migration(version, name, normalized, checksum))

    migrations.sort(key=lambda m: m.version)
    seen_versions: set[int] = set()
    for m in migrations:
        if m.version in seen_versions:
            raise MigrationError("duplicate_version", version=m.version)
        seen_versions.add(m.version)

    return migrations


_WORD_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_$]*")
_TRANSACTION_KEYWORDS = frozenset({"BEGIN", "COMMIT", "END", "ROLLBACK", "SAVEPOINT"})
_QUOTE_CLOSERS = {"'": "'", '"': '"', "`": "`", "[": "]"}


def _skip_quoted(sql: str, start: int) -> int:
    """Return the index just past the quoted section beginning at *start*."""
    closing = _QUOTE_CLOSERS[sql[start]]
    length = len(sql)
    i = start + 1
    while i < length:
        char = sql[i]
        if char == closing:
            if closing != "]" and i + 1 < length and sql[i + 1] == closing:
                i += 2
                continue
            return i + 1
        i += 1
    return length


def _has_transaction_control(sql: str) -> bool:
    """Return ``True`` if a top-level statement starts with transaction control.

    The script is scanned once so that quoted strings, quoted identifiers and
    comments are ignored, and the ``BEGIN ... END`` body of a ``CREATE
    TRIGGER`` statement is not mistaken for transaction control.
    """
    length = len(sql)
    i = 0
    statement_start = True
    in_trigger = False
    is_trigger_statement = False

    while i < length:
        char = sql[i]

        if char.isspace():
            i += 1
            continue
        if char == "-" and sql.startswith("--", i):
            newline = sql.find("\n", i)
            i = length if newline == -1 else newline + 1
            continue
        if char == "/" and sql.startswith("/*", i):
            end = sql.find("*/", i + 2)
            i = length if end == -1 else end + 2
            continue
        if char in _QUOTE_CLOSERS:
            i = _skip_quoted(sql, i)
            statement_start = False
            continue
        if char == ";":
            i += 1
            if not in_trigger:
                statement_start = True
                is_trigger_statement = False
            continue

        match = _WORD_RE.match(sql, i)
        if match is None:
            i += 1
            statement_start = False
            continue

        word = match.group(0).upper()
        i = match.end()
        if statement_start:
            if not in_trigger and word in _TRANSACTION_KEYWORDS:
                return True
            statement_start = False
            continue

        if word == "TRIGGER":
            is_trigger_statement = True
        elif word == "BEGIN" and is_trigger_statement and not in_trigger:
            in_trigger = True
        elif word == "END" and in_trigger:
            in_trigger = False

    return False


class Migrator:
    """Applies migrations to a SQLite connection.

    The connection must be created with ``isolation_level=None`` so that the
    runner can manage transactions explicitly.
    """

    def __init__(
        self,
        conn: sqlite3.Connection,
        migrations: Sequence[Migration],
        *,
        owner: str,
        clock: Callable[[], float] = time.time,
        lock_ttl_s: float = 600.0,
        allow_out_of_order: bool = False,
        on_event: Callable[[dict[str, object]], None] | None = None,
    ) -> None:
        self._conn = conn
        self._migrations = list(migrations)
        self._owner = owner
        self._clock = clock
        self._lock_ttl_s = lock_ttl_s
        self._allow_out_of_order = allow_out_of_order
        self._on_event = on_event
        self._migration_by_version = {m.version: m for m in self._migrations}

    def _ensure_schema(self) -> None:
        self._conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS schema_migrations (
                version INTEGER PRIMARY KEY,
                name TEXT NOT NULL,
                checksum TEXT NOT NULL,
                applied_at REAL NOT NULL
            );
            CREATE TABLE IF NOT EXISTS schema_migrations_lock (
                id INTEGER PRIMARY KEY CHECK (id = 1),
                owner TEXT NOT NULL,
                expires_at REAL NOT NULL
            );
            """
        )

    def _acquire_lock(self) -> None:
        now = self._clock()
        expires = now + self._lock_ttl_s
        try:
            self._conn.execute(
                "INSERT INTO schema_migrations_lock (id, owner, expires_at) VALUES (1, ?, ?)",
                (self._owner, expires),
            )
        except sqlite3.IntegrityError:
            previous_row = self._conn.execute(
                "SELECT owner FROM schema_migrations_lock WHERE id = 1"
            ).fetchone()
            if previous_row is None:
                # Should never happen; the insert failed but no row exists.
                raise
            previous_owner = previous_row[0]
            cursor = self._conn.execute(
                "UPDATE schema_migrations_lock "
                "SET owner = ?, expires_at = ? "
                "WHERE id = 1 AND expires_at < ?",
                (self._owner, expires, now),
            )
            if cursor.rowcount == 1:
                if self._on_event:
                    self._on_event({"event": "lock_stolen", "previous_owner": previous_owner})
            else:
                raise LockError(previous_owner) from None
        else:
            if self._on_event:
                self._on_event({"event": "lock_acquired"})

    def _release_lock(self) -> None:
        self._conn.execute("DELETE FROM schema_migrations_lock WHERE owner = ?", (self._owner,))
        if self._on_event:
            self._on_event({"event": "lock_released"})

    def _verify_checksums(self) -> None:
        rows = self._conn.execute(
            "SELECT version, checksum FROM schema_migrations ORDER BY version"
        ).fetchall()
        for version, stored_checksum in rows:
            migration = self._migration_by_version.get(version)
            if migration is not None and migration.checksum != stored_checksum:
                raise MigrationError("checksum_mismatch", version=version)

    def _compute_pending(self, target: int | None) -> list[Migration]:
        applied_versions = {
            row[0] for row in self._conn.execute("SELECT version FROM schema_migrations").fetchall()
        }
        max_applied = max(applied_versions) if applied_versions else 0
        pending_all = [m for m in self._migrations if m.version not in applied_versions]

        if not self._allow_out_of_order:
            for m in pending_all:
                if m.version < max_applied:
                    raise MigrationError("out_of_order", version=m.version)

        if target is not None:
            pending = [m for m in pending_all if m.version <= target]
        else:
            pending = pending_all

        return sorted(pending, key=lambda m: m.version)

    def plan(self, target: int | None = None) -> list[Migration]:
        """Return the migrations that would be applied without running them.

        Performs checksum verification and out-of-order detection, but does
        not acquire the lock or modify the database.

        Args:
            target: If given, only migrations with version <= *target* are
                returned.

        Returns:
            List of :class:`Migration` objects that ``migrate`` would apply.

        Raises:
            MigrationError: If checksum mismatch or out-of-order condition
                is detected.
        """
        self._ensure_schema()
        self._verify_checksums()
        return self._compute_pending(target)

    def migrate(self, target: int | None = None) -> list[int]:
        """Apply all pending migrations up to *target*.

        Migrations are applied in ascending version order.  Each migration
        runs inside a transaction via ``executescript`` with an explicit
        ``BEGIN``, followed by an ``INSERT`` into ``schema_migrations`` and a
        ``COMMIT``.  On any SQLite error the transaction is rolled back and
        a :class:`MigrationError` with code ``migration_failed`` is raised.

        A cross-process lock is acquired before validation and released in a
        ``finally`` block.  The lock is a row in ``schema_migrations_lock``
        with an expiry timestamp; expired locks may be stolen (an
        ``lock_stolen`` event is emitted).

        Args:
            target: If given, only apply migrations with version <= *target*.

        Returns:
            List of version numbers that were newly applied.

        Raises:
            LockError: If the lock is held by another owner and not expired.
            MigrationError: For all other error conditions (checksum mismatch,
                out-of-order, invalid script, failure during apply, etc.).
        """
        self._ensure_schema()
        lock_acquired = False
        try:
            self._acquire_lock()
            lock_acquired = True
            self._verify_checksums()
            pending = self._compute_pending(target)
            applied_versions: list[int] = []

            for migration in pending:
                if _has_transaction_control(migration.sql):
                    raise MigrationError("transaction_in_script", version=migration.version)

                start = self._clock()
                try:
                    script = "BEGIN;\n" + migration.sql + "\n;"
                    self._conn.executescript(script)
                    self._conn.execute(
                        "INSERT INTO schema_migrations "
                        "(version, name, checksum, applied_at) VALUES (?, ?, ?, ?)",
                        (migration.version, migration.name, migration.checksum, self._clock()),
                    )
                    self._conn.execute("COMMIT")
                except sqlite3.Error as exc:
                    if self._conn.in_transaction:
                        self._conn.execute("ROLLBACK")
                    raise MigrationError("migration_failed", version=migration.version) from exc

                duration_ms = int((self._clock() - start) * 1000)
                if self._on_event:
                    self._on_event(
                        {
                            "event": "applied",
                            "version": migration.version,
                            "name": migration.name,
                            "duration_ms": duration_ms,
                        }
                    )
                applied_versions.append(migration.version)

            return applied_versions
        finally:
            if lock_acquired:
                self._release_lock()

    def status(self) -> list[MigrationStatus]:
        """Return the current state of all known migrations.

        Applied migrations whose files are no longer present are reported as
        ``missing_file``.  Migrations present in the files but not applied are
        ``pending``.

        Returns:
            List of :class:`MigrationStatus` sorted by version.
        """
        self._ensure_schema()
        applied_rows = self._conn.execute(
            "SELECT version, name FROM schema_migrations ORDER BY version"
        ).fetchall()
        applied_map = {version: name for version, name in applied_rows}

        statuses: list[MigrationStatus] = []
        for version in sorted(applied_map):
            applied_name = applied_map[version]
            migration = self._migration_by_version.get(version)
            if migration is not None:
                statuses.append(MigrationStatus(version, migration.name, "applied"))
            else:
                statuses.append(MigrationStatus(version, applied_name, "missing_file"))

        for migration in self._migrations:
            if migration.version not in applied_map:
                statuses.append(MigrationStatus(migration.version, migration.name, "pending"))

        statuses.sort(key=lambda s: s.version)
        return statuses

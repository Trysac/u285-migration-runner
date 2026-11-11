"""Versioned SQL migrations for SQLite.

Run ordered ``.sql`` files against a SQLite database with a cross-process lock
table, checksums of applied files, transactional apply and rollback, and a
dry-run plan.
"""

from __future__ import annotations

from .migrations import (
    LockError,
    Migration,
    MigrationError,
    MigrationStatus,
    Migrator,
    load_migrations,
)

__all__ = [
    "LockError",
    "Migration",
    "MigrationError",
    "MigrationStatus",
    "Migrator",
    "__version__",
    "load_migrations",
]

__version__ = "0.1.0"

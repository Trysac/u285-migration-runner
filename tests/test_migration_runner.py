"""Behavior tests for the public API of migration_runner."""

from __future__ import annotations

import dataclasses

import pytest

import migration_runner


def test_version_is_semver() -> None:
    parts = migration_runner.__version__.split(".")
    assert len(parts) == 3
    assert all(part.isdigit() for part in parts)


def test_public_api_is_exported() -> None:
    expected = {
        "LockError",
        "Migration",
        "MigrationError",
        "MigrationStatus",
        "Migrator",
        "load_migrations",
    }
    assert expected <= set(migration_runner.__all__)


def test_migration_dataclass_is_frozen() -> None:
    migration = migration_runner.Migration(1, "init", "SELECT 1;", "abc")
    assert migration.version == 1
    with pytest.raises(dataclasses.FrozenInstanceError):
        migration.version = 2


def test_lock_error_reports_owner_and_code() -> None:
    error = migration_runner.LockError("other")
    assert error.code == "lock_held"
    assert "other" in str(error)

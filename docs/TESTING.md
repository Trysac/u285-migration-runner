# Testing

## Running

```sh
python -m pytest
```

## Policy

Tests are `pytest` functions in `tests/`. They import the public API from `migration_runner` and use temporary directories and in-memory SQLite connections where needed. The repository currently contains one pytest tier; there are no marked conformance tests or external-tool downloads in the files present.

## Tiers

All tests in the repository run with `pytest` as a single local tier. No separate CI conformance tier is present in the test files.

## Layout

- `tests/test_migration_runner.py`: `test_version_is_semver` checks `__version__`; `test_public_api_is_exported` checks the names in `__all__`; `test_migration_dataclass_is_frozen` checks that `Migration` is frozen; `test_lock_error_reports_owner_and_code` checks `LockError` message and code.
- `tests/test_migrations.py`: defines `FakeClock`, `write_migration`, and `make_conn`; `test_load_migrations_basic` covers ordering and ignoring `notes.txt`; `test_load_migrations_invalid_name` covers `invalid_name`; `test_load_migrations_duplicate_version` covers `duplicate_version`.

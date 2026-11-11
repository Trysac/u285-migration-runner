# trysac-migration-runner

Run versioned SQL migrations against SQLite with a cross-process lock table, checksums of applied files, transactional apply and rollback, and a dry-run plan.

## Installation

```bash
pip install trysac-migration-runner
```

The package has no runtime dependencies outside the Python standard library and requires Python >= 3.10.

## Quick start

```python
from pathlib import Path
import sqlite3
from migration_runner import load_migrations, Migrator

conn = sqlite3.connect("app.db", isolation_level=None)
migrations = load_migrations(Path("migrations"))
Migrator(conn, migrations, owner="worker-1").migrate()
conn.close()
```

Migration files are named `V<version>__<name>.sql` and must match `^V(\d{1,9})__([a-z0-9_]{1,100})\.sql$`.

## CLI

```bash
python -m migration_runner migrate --db app.db --dir migrations
python -m migration_runner status --db app.db --dir migrations
python -m migration_runner plan --db app.db --dir migrations --target 10
```

`--owner` defaults to `hostname-pid`. Exit codes: `0` success, `1` migration/checksum/lock error, `2` usage or IO error.

## API

- `load_migrations(directory, *, max_file_bytes=1_000_000, max_files=10_000) -> list[Migration]` reads `V<version>__<name>.sql` files, ignores non-`.sql` files, normalizes line endings, computes SHA-256 checksums, and returns migrations sorted by version. It raises `OSError` if the directory is missing or not a directory, and `MigrationError` with codes `invalid_name`, `duplicate_version`, `file_too_large`, or `too_many_files`.
- `Migrator(conn, migrations, *, owner, clock=time.time, lock_ttl_s=600.0, allow_out_of_order=False, on_event=None)` applies migrations on a `sqlite3.Connection` created with `isolation_level=None`.
  - `migrate(target=None) -> list[int]` acquires the lock, verifies checksums, computes pending migrations, rejects out-of-order pending versions unless `allow_out_of_order=True`, applies each migration in a transaction with its `schema_migrations` row, and returns newly applied versions.
  - `plan(target=None) -> list[Migration]` ensures the bookkeeping tables, verifies checksums and out-of-order conditions, and returns what `migrate` would apply without acquiring the lock or applying migrations.
  - `status() -> list[MigrationStatus]` returns every known version as `applied`, `pending`, or `missing_file`.
- `Migration(version, name, sql, checksum)` and `MigrationStatus(version, name, state)` are frozen dataclasses.
- `MigrationError(code, version=None, message=None)` carries a code and optional version. Codes include `invalid_name`, `duplicate_version`, `file_too_large`, `too_many_files`, `transaction_in_script`, `checksum_mismatch`, `out_of_order`, and `migration_failed`. `LockError` is a subclass with code `lock_held` and names the current owner when known.
- `on_event` receives dictionaries for `applied`, `lock_acquired`, `lock_stolen`, and `lock_released`; event payloads do not contain SQL text.

Limits: `lock_ttl_s` defaults to 600 seconds and must exceed the longest migration because the lock has no heartbeat. A script whose top-level statement starts with `BEGIN`, `COMMIT`, `END`, `ROLLBACK`, or `SAVEPOINT` raises `transaction_in_script` before execution.

## Why not Alembic or Flyway

This is a dependency-free runner for embedded SQLite databases: it uses plain SQL files, a lock row with expiry, a checksum guard, and forward-only migrations. It is not a full migration framework and does not provide down migrations, PostgreSQL or other engines, Python migrations, repeatable migrations, or baselining.

## Security

See [docs/SECURITY.md](docs/SECURITY.md) for the threat model and defensive measures.

## License

MIT

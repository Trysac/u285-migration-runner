# Security

This document describes the threat model of `migration_runner`.

## Defended

- File names: only files matching `^V(\d{1,9})__([a-z0-9_]{1,100})\.sql$` are accepted. Other `.sql` names raise `invalid_name`; non-`.sql` files are ignored.
- Size limits: `load_migrations` defaults to `max_file_bytes=1_000_000` and `max_files=10_000`. A larger file raises `file_too_large`; too many `.sql` files raise `too_many_files`.
- Checksums: each file is read as UTF-8 with CRLF and CR normalized to LF, then hashed with SHA-256. An applied version whose file changed raises `checksum_mismatch` before pending migrations run. A line-ending-only change is normalized away.
- Lock protocol: `migrate` inserts a row in `schema_migrations_lock` with `owner` and `expires_at = clock() + lock_ttl_s`. If the row exists and is expired (`expires_at < clock()`), the runner updates it to the new owner and emits `lock_stolen`; otherwise it raises `LockError` with code `lock_held`. Release deletes the row for the owner in a `finally` block. `lock_ttl_s` defaults to 600 seconds and has no heartbeat, so it must exceed the longest migration.
- Transaction control: a top-level statement starting with `BEGIN`, `COMMIT`, `END`, `ROLLBACK`, or `SAVEPOINT` raises `transaction_in_script` before execution. The scanner ignores quoted strings, quoted identifiers, `--` comments, `/* */` comments, and the `BEGIN ... END` body of `CREATE TRIGGER`.
- Transactional apply: with `isolation_level=None`, each migration runs as `executescript("BEGIN;\n" + sql + "\n;")`, then inserts its `schema_migrations` row, then `COMMIT`. On `sqlite3.Error` the runner issues `ROLLBACK` when `conn.in_transaction` and raises `MigrationError` with code `migration_failed`, chained to the cause. SQLite DDL is transactional, so a failed `CREATE TABLE` is rolled back.
- Events and logging: `on_event` payloads for `applied`, `lock_acquired`, `lock_stolen`, and `lock_released` do not include SQL text. The module logger uses a `NullHandler`.

## Not defended

- SQL execution is not sandboxed. A migration file can run any SQL the provided SQLite connection is permitted to run; the library only scans for transaction control and enforces file, checksum, and lock rules.
- The lock is advisory inside the database file. It does not protect against processes that write outside this protocol or against filesystem-level access to the database or migration directory.
- Lock expiry relies on the injected `clock`. A `lock_ttl_s` shorter than a migration's runtime allows another process to steal the lock; there is no heartbeat or automatic extension.
- The library does not authenticate owners; `owner` is an identifier string supplied by the caller.
- The library does not protect secrets. Do not store credentials in migration files.

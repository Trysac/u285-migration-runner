# Use a lock table with expiry and SQL transaction per migration

Status: accepted (generated, pending human review)

## Context

SQLite databases embedded in applications can be migrated by multiple processes simultaneously. Naive migration runners may apply the same migration twice or interleave partially applied scripts.

## Decision

Implement a dedicated `schema_migrations_lock` table with a single row (id=1), owner, and expiry timestamp. Migrator acquires the lock by inserting the row; if it already exists and is not expired, it raises LockError. If expired, the lock is stolen. Each migration runs inside a BEGIN/COMMIT transaction via `executescript` with the history INSERT in the same transaction.

## Consequences

Positive: guarantees exclusive migration execution across processes, prevents partial application, supports lock TTL for crash recovery. Negative: requires all processes to use the same lock table and owner identifiers; TTL must exceed longest migration duration (no heartbeat).

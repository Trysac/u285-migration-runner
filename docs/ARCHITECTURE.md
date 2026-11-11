# Architecture

## Purpose

`migration_runner` is a standard-library Python package that loads ordered SQL files and applies them to a SQLite connection with a lock table, checksum history, transactional apply, and a dry-run plan.

## Shape

```text
caller code --> migration_runner.__init__ (exports)
                    |
                    +-- migrations.py: Migration, MigrationStatus, errors, load_migrations, Migrator
                    +-- __main__.py: argparse CLI (migrate, status, plan)
```

- **Public API**: the names in `__all__` of `src/migration_runner/__init__.py`: `LockError`, `Migration`, `MigrationError`, `MigrationStatus`, `Migrator`, `load_migrations`, and `__version__`.
- **I/O**: `load_migrations` reads a directory and files; `Migrator` executes SQL on the caller-provided `sqlite3.Connection`. The library API does not open database connections itself; the CLI opens one from `--db`.
- **Errors**: invalid files, checksums, ordering, scripts, and apply failures raise `MigrationError` or `LockError`; missing directories raise `OSError`.

## Quality contract

Tests are in `tests/test_migration_runner.py` and `tests/test_migrations.py` and run with `pytest`. The package ships `py.typed`.

## Decisions

No architecture decision records are present in the provided repository; behavior is defined by the code and specification.

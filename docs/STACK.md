# Stack

## Used

| Tool | Why |
|---|---|
| Python >= 3.10 | Required by modern typing syntax such as `list[str] | None` in the code. |
| `sqlite3` (stdlib) | Database access, transactions, and the lock and history tables. |
| `hashlib` (stdlib) | SHA-256 checksums of migration files. |
| `argparse` (stdlib) | CLI parsing in `src/migration_runner/__main__.py`. |
| `pytest` | Tests in `tests/`. |

Runtime code uses only the Python standard library.

## Discarded

| Tool | Why not |
|---|---|
| Alembic / Flyway | Not used; this package is a dependency-free forward-only runner for embedded SQLite with an explicit lock row and checksum guard. |
| ORM migration tools | Out of scope; migrations are plain SQL files, not Python migrations. |
